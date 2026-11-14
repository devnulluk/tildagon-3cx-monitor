#include <Arduino.h>
#include <Arduino_GFX_Library.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <Preferences.h>
#include <Wire.h>
#include <LittleFS.h>
#include <driver/i2s.h>
#include <esp_heap_caps.h>
#include <time.h>
#include "engine.h"
#include "panel_init.h"
#include "ui.h"
#include "protocol.h"

using namespace spaceport;
static constexpr char VERSION[]="0.1.0";
Preferences prefs;
Engine engine;
SemaphoreHandle_t stateLock;
Snapshot latest;
WebServer web(80);
String ssid,password,origin,token,ca,webKey,partnerNumber,partnerName,partnerSurname;
bool configured=false, demo=false, demoAudio=false, permanentMute=false;
uint32_t demoSince=0,lastRender=0,buttonSince=0,manualPageAt=0;
bool manualPage=false;
int page=0,volume=20,priorityVolume=35,brightness=50;
String serialLine;
Arduino_ESP32QSPI bus(21,40,46,45,42,41);
class WavesharePanel : public Arduino_ST77916 {
 public: WavesharePanel(Arduino_DataBus* b):Arduino_ST77916(b,GFX_NOT_DEFINED,0,true,360,360){}
 protected: void tftInit() override {_bus->sendCommand(ST77916_SWRESET);delay(120);_bus->batchOperation(panel_init,sizeof(panel_init));invertDisplay(false);}
};
WavesharePanel panel(&bus);
class SpaceportCanvas : public Arduino_Canvas {
 public: SpaceportCanvas():Arduino_Canvas(360,360,&panel){}
 bool begin(int32_t speed=GFX_NOT_DEFINED) override {
   if(!psramFound()){Serial.println("PSRAM_REQUIRED");return false;}
   if(!_framebuffer)_framebuffer=(uint16_t*)heap_caps_aligned_alloc(16,360*360*2,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
   return _framebuffer&&Arduino_Canvas::begin(speed);
 }
};
SpaceportCanvas screen;
volatile Cue audioCue=Cue::Silent;
volatile uint32_t audioStarted=0;
volatile bool audioRepeat=false;
volatile int audioVolume=20;
bool audioReady=false,displayReady=false;

static void expanderReset() {
  // TCA9554: read-modify-write only P1 (vendor EXIO2), preserve other outputs.
  Wire.begin(11,10,400000);
  auto readReg=[](uint8_t reg)->int {Wire.beginTransmission(0x20);Wire.write(reg);if(Wire.endTransmission(false))return -1; if(Wire.requestFrom(0x20,1)!=1)return -1;return Wire.read();};
  auto writeReg=[](uint8_t reg,uint8_t value){Wire.beginTransmission(0x20);Wire.write(reg);Wire.write(value);return Wire.endTransmission()==0;};
  int dir=readReg(3),out=readReg(1);
  if(dir<0||out<0){Serial.println("DISPLAY_EXPANDER_NOT_FOUND");return;}
  writeReg(3,dir&~2);writeReg(1,out&~2);delay(20);writeReg(1,out|2);delay(120);
}

static bool validOrigin(const String& value) {
  if(!value.startsWith("https://")||value.length()>200)return false;
  String host=value.substring(8);
  if(!host.length()||host.indexOf('/')>=0||host.indexOf('@')>=0||host.indexOf('?')>=0||host.indexOf('#')>=0||host.indexOf('\\')>=0)return false;
  for(char c:host)if(c<=32||c>=127)return false;
  return true;
}
static void provision(const String& line) {
  JsonDocument j;
  if(deserializeJson(j,line)||!j["ssid"].is<const char*>()||!j["password"].is<const char*>()||!j["origin"].is<const char*>()||!j["token"].is<const char*>()||!j["ca"].is<const char*>()||!j["web_key"].is<const char*>()) {Serial.println("SETUP_INVALID");return;}
  String o=j["origin"].as<String>(),cert=j["ca"].as<String>(),k=j["web_key"].as<String>(),t=j["token"].as<String>();
  if(!validOrigin(o)||cert.indexOf("-----BEGIN CERTIFICATE-----")<0||k.length()<16||k.length()>64||t.length()<16||t.length()>512||j["ssid"].as<String>().length()>32||j["password"].as<String>().length()>64){Serial.println("SETUP_INVALID");return;}
  for(char c:t)if(c<=32||c>126){Serial.println("SETUP_INVALID");return;}
  prefs.begin("spaceport",false);
  prefs.putString("ssid",j["ssid"].as<String>());prefs.putString("password",j["password"].as<String>());
  prefs.putString("origin",o);prefs.putString("token",t);prefs.putString("ca",cert);prefs.putString("web_key",k);
  prefs.putString("partner",j["partner_number"]|"");prefs.end();
  prefs.begin("spaceport",false);prefs.putString("partner_name",j["partner_name"]|"Partner");prefs.putString("partner_surname",j["partner_surname"]|"");prefs.end();
  Serial.println("SETUP_SAVED");delay(100);ESP.restart();
}


static void networkTask(void*) {
  uint32_t lastConnect=0;
  for(;;) {
    if(configured&&WiFi.status()!=WL_CONNECTED&&millis()-lastConnect>15000){lastConnect=millis();WiFi.begin(ssid.c_str(),password.c_str());}
    if(configured&&WiFi.status()==WL_CONNECTED&&time(nullptr)>1700000000) {
      WiFiClientSecure tls;tls.setCACert(ca.c_str());tls.setHandshakeTimeout(4);
      HTTPClient http;http.useHTTP10(true);http.setTimeout(2500);http.setConnectTimeout(2000);http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
      if(http.begin(tls,origin+"/v1/state")) {
        http.addHeader("Authorization","Bearer "+token);http.addHeader("Accept","application/json");
        int code=http.GET();
        if(code==200&&http.getSize()>=0&&http.getSize()<=65536) {
          // Bound even a chunked/missing-length response before parsing.
          String body;body.reserve(16384);auto stream=http.getStreamPtr();uint32_t start=millis();
          while((http.connected()||stream->available())&&millis()-start<2500&&body.length()<=65536) {
            while(stream->available()&&body.length()<=65536)body+=char(stream->read());
            if(http.getSize()>=0&&body.length()>=size_t(http.getSize()))break;
            vTaskDelay(1);
          }
          JsonDocument j;
          if(body.length()<=65536&&!deserializeJson(j,body)&&j["version"]==1&&j["own"].is<JsonObject>()&&j["team"].is<JsonArray>()) {
            Snapshot s=parseState(j,millis(),partnerNumber.c_str(),partnerName.c_str(),partnerSurname.c_str());xSemaphoreTake(stateLock,portMAX_DELAY);latest=s;engine.accept(s);xSemaphoreGive(stateLock);
          }
        }
        http.end();
      }
    }
    vTaskDelay(pdMS_TO_TICKS(750));
  }
}

static void audioTask(void*) {
  i2s_config_t conf={};conf.mode=i2s_mode_t(I2S_MODE_MASTER|I2S_MODE_TX);conf.sample_rate=22050;
  conf.bits_per_sample=I2S_BITS_PER_SAMPLE_16BIT;conf.channel_format=I2S_CHANNEL_FMT_RIGHT_LEFT;
  conf.communication_format=I2S_COMM_FORMAT_STAND_I2S;conf.intr_alloc_flags=ESP_INTR_FLAG_LEVEL1;
  conf.dma_buf_count=6;conf.dma_buf_len=256;conf.use_apll=false;conf.tx_desc_auto_clear=true;
  i2s_pin_config_t pins={};pins.mck_io_num=I2S_PIN_NO_CHANGE;pins.bck_io_num=48;pins.ws_io_num=38;pins.data_out_num=47;pins.data_in_num=I2S_PIN_NO_CHANGE;
  audioReady=i2s_driver_install(I2S_NUM_0,&conf,0,nullptr)==ESP_OK&&i2s_set_pin(I2S_NUM_0,&pins)==ESP_OK;
  bool fsReady=LittleFS.begin(false,"/littlefs",10,"littlefs"); // Never format an existing filesystem on failure.
  File wav;bool wavReady=false;
  int16_t samples[512];uint8_t pcm[512];uint32_t position=0,previousStart=0;
  for(;;) {
    Cue cue=audioCue;uint32_t start=audioStarted;
    if(start!=previousStart){position=0;previousStart=start;wav.close();wavReady=false;
      static const char* names[]={"","direct","internal","queue","group","priority","partner","info","urgent"};
      if(fsReady&&cue!=Cue::Silent){wav=LittleFS.open(String("/sounds/")+names[int(cue)]+".wav","r");
        uint8_t h[44];if(wav&&wav.read(h,44)==44&&memcmp(h,"RIFF",4)==0&&memcmp(h+8,"WAVEfmt ",8)==0&&h[16]==16&&h[20]==1&&h[22]==1&&h[24]==0x22&&h[25]==0x56&&h[34]==16&&memcmp(h+36,"data",4)==0)wavReady=true;
      }
    }
    size_t pcmBytes=0;
    if(cue!=Cue::Silent&&wavReady) {
      while(pcmBytes<sizeof(pcm)) {
        size_t got=wav.read(pcm+pcmBytes,sizeof(pcm)-pcmBytes);pcmBytes+=got;
        if(pcmBytes==sizeof(pcm)||!audioRepeat)break;
        if(!got&&wav.size()<=44)break;
        if(!wav.seek(44))break;
      }
    }
    for(int i=0;i<256;i++,position++) {
      float value=0,t=position/22050.0f;
      if(cue!=Cue::Silent&&wavReady) {
        if(size_t(i*2+1)<pcmBytes)value=int16_t(uint16_t(pcm[i*2])|(uint16_t(pcm[i*2+1])<<8))/12000.f;
      } else if(cue!=Cue::Silent&&(audioRepeat||t<.9f)) {
        static const float tunes[9][4]={{0,0,0,0},{523,659,784,659},{440,660,440,660},{587,740,880,740},{440,554,659,554},{880,1109,1320,1109},{659,784,988,1175},{784,1047,0,0},{440,554,440,554}};
        int row=int(cue);int note=int(t/.18f)%4;
        float within=fmodf(t,.18f),phrase=fmodf(t,2.8f);
        float f=tunes[row][note];
        if(f>0&&within<.15f&&(phrase<1.3f||!audioRepeat)) {
          float envelope=fminf(1.f,within/.012f)*fminf(1.f,(.15f-within)/.04f);
          value=(sinf(t*6.2831853f*f)+.18f*sinf(t*6.2831853f*f*2))*envelope;
        }
      }
      int16_t v=int16_t(value*12000.f*audioVolume/100.f);samples[i*2]=v;samples[i*2+1]=v;
    }
    size_t written=0;if(audioReady)i2s_write(I2S_NUM_0,samples,sizeof(samples),&written,pdMS_TO_TICKS(50));else vTaskDelay(pdMS_TO_TICKS(12));
  }
}

static void setSound(const Presentation& p) {
  static std::string lastId;static Cue last=Cue::Silent;
  if(permanentMute||(demo&&!demoAudio&&!p.priority)) {audioCue=Cue::Silent;last=Cue::Silent;lastId=p.id;return;}
  if(p.view==View::Notice&&p.id==lastId&&p.cue==Cue::Silent) {
    if(millis()-audioStarted>900)audioCue=Cue::Silent;
    return;
  }
  if(p.cue!=last||p.id!=lastId) {audioCue=Cue::Silent;audioStarted=millis();audioRepeat=p.view==View::Ringing;
    audioVolume=p.priority?priorityVolume:volume;audioCue=p.cue;last=p.cue;lastId=p.id;}
}

static bool authenticate() {
  if(!configured||webKey.length()<16||!web.authenticate("spaceport",webKey.c_str())) {web.requestAuthentication();return false;}return true;
}
static const char WEB_PAGE[] PROGMEM=R"HTML(<!doctype html><meta name="viewport" content="width=device-width"><title>Spaceport</title><style>body{background:#060b18;color:#c8ecff;font:18px system-ui;max-width:650px;margin:35px auto;padding:20px}button,input{font:inherit;padding:12px;margin:5px;background:#142840;color:#d4faff;border:1px solid #367b99;border-radius:12px}h1{color:#49e5f5}small{color:#8fa8b4}</style><h1>SPACEPORT</h1><p>Audio and display companion to Spaceagon</p><p id="state">Connecting...</p><button onclick="act('mute')">Mute</button><button onclick="act('unmute')">Unmute</button><button onclick="act('silence')">Silence this alert</button><button onclick="act('dismiss')">Clear local notice</button><button onclick="act('page')">Next idle screen</button><p>Ring volume <input id="vol" type="range" min="0" max="75" value="20" onchange="act('volume',this.value)"></p><p>Priority volume <input type="range" min="0" max="75" value="35" onchange="act('priority_volume',this.value)"></p><p>Display brightness <input type="range" min="5" max="100" value="50" onchange="act('brightness',this.value)"></p><button onclick="act('test')">Test sound</button><button onclick="act('demo')">Visual demo</button><button onclick="act('live')">Return to live</button><p><small>Local acknowledgement affects Spaceport only. Calls and DND remain on Spaceagon. Demo sound is off; Test sound plays one short chime.</small></p><script>async function act(action,value){await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json','X-Spaceport':'1'},body:JSON.stringify({action,value:Number(value)})});poll()}async function poll(){let s=await(await fetch('/status')).json();document.querySelector('#state').textContent=`${s.live?'LIVE':'OFFLINE'} / ${s.muted?'MUTED':'SOUND ON'} / ${s.demo?'DEMO':'LIVE DATA'} / v${s.version}`;document.querySelector('#vol').value=s.volume}setInterval(poll,3000);poll()</script>)HTML";
static void webSetup() {
  const char* headers[]={"X-Spaceport"};web.collectHeaders(headers,1);
  web.on("/",HTTP_GET,[]{if(authenticate())web.send(200,"text/html",FPSTR(WEB_PAGE));});
  web.on("/status",HTTP_GET,[]{if(!authenticate())return;JsonDocument j;xSemaphoreTake(stateLock,portMAX_DELAY);j["live"]=engine.fresh(millis());xSemaphoreGive(stateLock);j["version"]=VERSION;j["muted"]=permanentMute;j["demo"]=demo;j["volume"]=volume;j["brightness"]=brightness;j["audio_ready"]=audioReady;String out;serializeJson(j,out);web.sendHeader("Cache-Control","no-store");web.send(200,"application/json",out);});
  web.on("/action",HTTP_POST,[]{
    if(!authenticate())return;
    if(web.header("X-Spaceport")!="1"||web.arg("plain").length()>256){web.send(400);return;}
    JsonDocument j;if(deserializeJson(j,web.arg("plain"))){web.send(400);return;}
    String a=j["action"]|"";
    xSemaphoreTake(stateLock,portMAX_DELAY);Presentation p=engine.present(millis());
    if(a=="mute"){permanentMute=true;engine.muted=true;audioCue=Cue::Silent;}
    else if(a=="unmute"){permanentMute=false;engine.muted=false;}
    else if(a=="silence"){engine.silence(p);audioCue=Cue::Silent;}
    else if(a=="dismiss"){engine.acknowledge(p);audioCue=Cue::Silent;}
    else if(a=="page"){page=(page+1)%3;manualPage=true;manualPageAt=millis();}
    else if(a=="volume")volume=constrain(j["value"]|20,0,75);
    else if(a=="priority_volume")priorityVolume=constrain(j["value"]|35,0,75);
    else if(a=="brightness"){brightness=constrain(j["value"]|50,5,100);ledcWrite(0,brightness*255/100);}
    else if(a=="demo"){demo=true;demoAudio=false;demoSince=millis();audioCue=Cue::Silent;}
    else if(a=="live"){demo=false;audioCue=Cue::Silent;}
    else if(a=="test"){audioStarted=millis();audioRepeat=false;audioVolume=volume;audioCue=Cue::Info;}
    else {xSemaphoreGive(stateLock);web.send(400);return;}
    xSemaphoreGive(stateLock);
    prefs.begin("spaceport",false);prefs.putInt("brightness",brightness);prefs.putInt("volume",volume);prefs.putInt("priority",priorityVolume);prefs.putBool("muted",permanentMute);prefs.end();web.send(200,"application/json","{\"ok\":true}");
  });web.begin();
}

static Presentation demoPresentation(uint32_t now) {
  Presentation p;int step=((now-demoSince)/6000)%9;
  p.id="demo";p.title="Example Caller";p.subtitle="IT";p.kind="queue";p.body="INCOMING";
  if(step<4){p.view=View::Ringing;p.kind=step==0?"queue":step==1?"ring_group":"internal";p.subtitle=step==0?"IT":step==1?"Operations Office":"Internal";p.partner=step==3;if(p.partner){p.title=partnerName.length()?partnerName.c_str():"Partner";p.subtitle=partnerSurname.c_str();}}
  else if(step==4){p.view=View::Call;p.seconds=83;p.body="CONNECTED";}
  else if(step<7){p.view=View::Notice;p.priority=step==6;p.title=step==6?"Storage needs attention":"Backup complete";p.body=step==6?"An example urgent notification. Hold BOOT to clear.":"All files copied successfully.";p.kind=step==6?"failure":"success";p.progress=step==5?73:-1;}
  else p.view=View::Idle;
  return p;
}

void setup() {
  Serial.begin(115200);pinMode(0,INPUT_PULLUP);pinMode(5,OUTPUT);digitalWrite(5,LOW);
  prefs.begin("spaceport",true);ssid=prefs.getString("ssid");password=prefs.getString("password");origin=prefs.getString("origin");token=prefs.getString("token");ca=prefs.getString("ca");webKey=prefs.getString("web_key");partnerNumber=prefs.getString("partner");partnerName=prefs.getString("partner_name","Partner");partnerSurname=prefs.getString("partner_surname");brightness=constrain(prefs.getInt("brightness",50),5,100);volume=prefs.getInt("volume",20);priorityVolume=prefs.getInt("priority",35);permanentMute=prefs.getBool("muted",false);prefs.end();
  configured=validOrigin(origin)&&token.length()>=16&&webKey.length()>=16;engine.muted=permanentMute;
  stateLock=xSemaphoreCreateMutex();
  expanderReset();displayReady=screen.begin(40000000);ledcSetup(0,5000,8);ledcAttachPin(5,0);ledcWrite(0,brightness*255/100);
  if(!displayReady)Serial.println("DISPLAY_INIT_FAILED");
  WiFi.mode(WIFI_STA);WiFi.setHostname("spaceport");if(configured)WiFi.begin(ssid.c_str(),password.c_str());
  configTzTime("GMT0BST,M3.5.0/1,M10.5.0","pool.ntp.org","time.cloudflare.com");
  xTaskCreatePinnedToCore(networkTask,"network",16384,nullptr,1,nullptr,0);
  xTaskCreatePinnedToCore(audioTask,"audio",4096,nullptr,2,nullptr,0);
  webSetup();Serial.println("SPACEPORT_READY 0.1.0");
}
void loop() {
  web.handleClient();
  while(Serial.available()) {char c=Serial.read();if(c=='\n'){provision(serialLine);serialLine="";}else if(c!='\r'){if(serialLine.length()<8192)serialLine+=c;else serialLine="";}}
  uint32_t now=millis();bool down=digitalRead(0)==LOW;
  if(down&&!buttonSince)buttonSince=now;
  if(!down&&buttonSince) {
    uint32_t held=now-buttonSince;buttonSince=0;
    if(held>=40){xSemaphoreTake(stateLock,portMAX_DELAY);auto p=engine.present(now);
      if(held>1500&&p.view==View::Notice)engine.acknowledge(p);
      else if(p.view==View::Ringing||p.view==View::Notice)engine.silence(p);
      else if(held>1500){demo=!demo;demoAudio=false;demoSince=now;}
      else {page=(page+1)%3;manualPage=true;manualPageAt=now;}
      audioCue=Cue::Silent;xSemaphoreGive(stateLock);}
  }
  if(demo&&now-demoSince>120000)demo=false;
  if(now-lastRender>=100) {
    lastRender=now;xSemaphoreTake(stateLock,portMAX_DELAY);Presentation p=engine.present(now);Snapshot s=latest;xSemaphoreGive(stateLock);
    // Real priority calls and real urgent notices always interrupt the visual tour.
    if(demo&&!p.priority)p=demoPresentation(now);
    setSound(p);
    int idlePage=manualPage&&uint32_t(now-manualPageAt)<20000?page:(now/15000)%3;
    if(displayReady){render(screen,p,s,now,idlePage,configured,WiFi.localIP().toString().c_str(),permanentMute,demo);screen.flush();}
  }
  delay(2);
}
