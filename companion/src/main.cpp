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
#include "presence.h"
#include "welcome_call.h"
#if __has_include("welcome_audio.private.h")
#include "welcome_audio.private.h"
#define PRIVATE_WELCOME_PCM 1
static constexpr uint32_t WELCOME_DURATION_MS=(WELCOME_SAMPLES*1000u+22049u)/22050u;
#else
static constexpr uint32_t WELCOME_DURATION_MS=1900;
#endif

using namespace spaceport;
static constexpr char VERSION[]="0.10.1";
Preferences prefs;
PhonePresence presence;
volatile bool presenceAudioAllowed=true;
Engine engine,dashboard;
SemaphoreHandle_t stateLock;
Snapshot latest;
std::string reportedCommand,reportedCommandStatus;
uint32_t renderCounter=0;
WebServer web(80);
String ssid,password,origin,token,ca,webKey,partnerNumber,partnerName,partnerSurname;
bool configured=false, demo=false, demoAudio=false, permanentMute=false;
uint32_t demoSince=0,lastRender=0,buttonSince=0,manualPageAt=0;
bool manualPage=false;
int page=0,volume=20,priorityVolume=35,brightness=50;
String serialLine;
String presenceReadKey;
Arduino_ESP32QSPI bus(21,40,46,45,42,41);
class WavesharePanel : public Arduino_ST77916 {
 public: WavesharePanel(Arduino_DataBus* b):Arduino_ST77916(b,GFX_NOT_DEFINED,0,true,360,360){}
 protected: void tftInit() override {_bus->sendCommand(ST77916_SWRESET);delay(120);_bus->batchOperation(panel_init,sizeof(panel_init));_bus->beginWrite();_bus->writeC8D8(ST77916_COLMOD,0x55);_bus->endWrite();invertDisplay(false);}
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
bool audioReady=false,displayReady=false,audioFsReady=false;
DailyWelcomeCall dailyWelcomeCall;
volatile uint32_t pipeUntil=0,pipeStarted=0;
volatile uint32_t toneUntil=0;volatile int toneHz=440,toneChannel=0;
volatile uint32_t audioBytesWritten=0,audioShortWrites=0;
volatile uint32_t audioNonzeroSamples=0;volatile int audioWriteStatus=0;

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
  if(deserializeJson(j,line)){Serial.println("SETUP_INVALID");return;}
  if(j["command"]=="presence_pair"){presence.pair();Serial.println("PRESENCE_PAIRING");return;}
  if(j["command"]=="presence_enable"){presence.enable(true);Serial.println("PRESENCE_ENABLED");return;}
  if(j["command"]=="status") {
    JsonDocument result;result["version"]=VERSION;result["wifi_connected"]=WiFi.status()==WL_CONNECTED;result["ip"]=WiFi.localIP().toString();result["display_ready"]=displayReady;result["audio_ready"]=audioReady;result["audio_filesystem"]=audioFsReady;result["audio_nonzero_samples"]=audioNonzeroSamples;result["audio_write_status"]=audioWriteStatus;result["audio_bytes_written"]=audioBytesWritten;result["audio_short_writes"]=audioShortWrites;result["test_tone_active"]=toneUntil&&int32_t(toneUntil-millis())>0;result["clock_ready"]=time(nullptr)>1700000000;
    xSemaphoreTake(stateLock,portMAX_DELAY);result["feed_live"]=dashboard.fresh(millis());result["phone_live"]=engine.fresh(millis());xSemaphoreGive(stateLock);
    auto ps=presence.status();result["presence_enabled"]=ps.enabled;result["phone_enrolled"]=ps.enrolled;result["phone_nearby"]=ps.nearby(millis());result["pairing"]=presence.pairing();
    Serial.print("SPACEPORT_STATUS ");serializeJson(result,Serial);Serial.println();return;
  }
  if(!j["ssid"].is<const char*>()||!j["password"].is<const char*>()||!j["origin"].is<const char*>()||!j["token"].is<const char*>()||!j["ca"].is<const char*>()||!j["web_key"].is<const char*>()) {Serial.println("SETUP_INVALID");return;}
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
  uint32_t lastReport=0,reportSeq=0;String reportBoot=String(esp_random(),HEX)+String(esp_random(),HEX);
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
            Snapshot s=parseState(j,millis(),partnerNumber.c_str(),partnerName.c_str(),partnerSurname.c_str());xSemaphoreTake(stateLock,portMAX_DELAY);latest=s;engine.accept(s);dashboard.accept(dashboardSnapshot(s));xSemaphoreGive(stateLock);
          }
        }
        http.end();
        if(millis()-lastReport>=10000){
          lastReport=millis();JsonDocument report;report["device"]="waveshare";report["boot"]=reportBoot;report["seq"]=++reportSeq;report["version"]=VERSION;
          xSemaphoreTake(stateLock,portMAX_DELAY);
          auto settings=report["settings"].to<JsonObject>();settings["volume"]=volume;settings["priority_volume"]=priorityVolume;settings["brightness"]=brightness;settings["muted"]=permanentMute;settings["demo"]=demo;settings["page"]=page;settings["frame_counter"]=renderCounter;settings["presence_enabled"]=presence.status().enabled;settings["phone_nearby"]=presence.allows();
          if(!reportedCommand.empty()){report["ack"]["id"]=reportedCommand;report["ack"]["status"]=reportedCommandStatus;}
          xSemaphoreGive(stateLock);String json;serializeJson(report,json);
          if(http.begin(tls,origin+"/v1/state")){http.addHeader("Authorization","Bearer "+token);http.addHeader("Content-Type","application/json");http.POST(json);http.end();}
        }
      }
    }
    vTaskDelay(pdMS_TO_TICKS(750));
  }
}

static void audioTask(void*) {
  i2s_config_t conf={};conf.mode=i2s_mode_t(I2S_MODE_MASTER|I2S_MODE_TX);conf.sample_rate=44100;
  // Match the vendor audio library legacy-I2S transfer configuration.
  conf.bits_per_sample=I2S_BITS_PER_SAMPLE_16BIT;conf.channel_format=I2S_CHANNEL_FMT_RIGHT_LEFT;
  conf.communication_format=I2S_COMM_FORMAT_STAND_I2S;conf.intr_alloc_flags=ESP_INTR_FLAG_LEVEL1;
  conf.dma_buf_count=16;conf.dma_buf_len=512;conf.fixed_mclk=1;conf.mclk_multiple=I2S_MCLK_MULTIPLE_128;conf.use_apll=false;conf.tx_desc_auto_clear=true;
  i2s_pin_config_t pins={};pins.mck_io_num=I2S_PIN_NO_CHANGE;pins.bck_io_num=48;pins.ws_io_num=38;pins.data_out_num=47;pins.data_in_num=I2S_PIN_NO_CHANGE;
  audioReady=i2s_driver_install(I2S_NUM_0,&conf,0,nullptr)==ESP_OK&&i2s_set_pin(I2S_NUM_0,&pins)==ESP_OK;
  if(audioReady){i2s_zero_dma_buffer(I2S_NUM_0);audioReady=i2s_set_sample_rates(I2S_NUM_0,44100)==ESP_OK;i2s_start(I2S_NUM_0);}
  bool fsReady=LittleFS.begin(false,"/littlefs",10,"littlefs"); // Never format an existing filesystem on failure.
  audioFsReady=fsReady;
  File wav;bool wavReady=false;
  static int16_t samples[1024];uint8_t pcm[512];uint32_t position=0,previousStart=0,lastPipeStart=0,pipePosition=0;
  for(;;) {
    if(toneUntil&&int32_t(toneUntil-millis())<=0)toneUntil=0;
    if(pipeUntil&&int32_t(pipeUntil-millis())<=0)pipeUntil=0;
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
    uint32_t nonzero=0;
    uint32_t blockNow=millis();bool pipeActive=pipeUntil&&int32_t(pipeUntil-blockNow)>0&&cue==Cue::Silent&&!permanentMute&&presenceAudioAllowed;
    if(pipeStarted!=lastPipeStart){lastPipeStart=pipeStarted;pipePosition=0;}
    float pipeTime=pipePosition/22050.f;
    for(int i=0;i<256;i++,position++) {
      float value=0,t=position/22050.0f;
      if(toneUntil&&int32_t(toneUntil-millis())>0&&!permanentMute)value=sinf(t*6.2831853f*toneHz);
      else if(pipeActive){
#ifdef PRIVATE_WELCOME_PCM
        uint32_t at=(pipePosition+i)*2;
        if(at+1<sizeof(WELCOME_PCM))value=int16_t(uint16_t(WELCOME_PCM[at])|(uint16_t(WELCOME_PCM[at+1])<<8))/32768.f;
#else
        value=welcomePipe(pipeTime+i/22050.f);
#endif
      }
      else if(cue!=Cue::Silent&&wavReady) {
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
      if(!presenceAudioAllowed)value=0;
      int16_t v=int16_t(value*12000.f*audioVolume/100.f);if(v)nonzero++;// Duplicate each 22.05kHz source sample into two 44.1kHz frames.
      int16_t left=v,right=v;
      if(toneUntil){if(toneChannel==1)right=0;else if(toneChannel==2)left=0;else if(toneChannel==3)right=-right;}
      for(int repeat=0;repeat<2;repeat++){samples[i*4+repeat*2]=left;samples[i*4+repeat*2+1]=right;}
    }
    if(pipeActive)pipePosition+=256;
    audioNonzeroSamples+=nonzero;size_t written=0;if(audioReady){audioWriteStatus=i2s_write(I2S_NUM_0,samples,sizeof(samples),&written,pdMS_TO_TICKS(50));audioBytesWritten+=written;if(written<sizeof(samples))audioShortWrites++;}else vTaskDelay(pdMS_TO_TICKS(12));
  }
}

static void setSound(const Presentation& p) {
  if(p.view==View::Ringing)toneUntil=0;
  if(p.view==View::Ringing||p.view==View::Call||p.view==View::Notice)pipeUntil=0;
  static std::string lastId;static Cue last=Cue::Silent;
  if(!presence.allows()||permanentMute||(demo&&!demoAudio&&!p.priority)) {pipeUntil=0;audioCue=Cue::Silent;last=Cue::Silent;lastId=p.id;return;}
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
static const char WEB_PAGE[] PROGMEM=R"HTML(<!doctype html><meta name="viewport" content="width=device-width"><title>Spaceport</title><style>body{background:#060b18;color:#c8ecff;font:18px system-ui;max-width:650px;margin:35px auto;padding:20px}button,input{font:inherit;padding:12px;margin:5px;background:#142840;color:#d4faff;border:1px solid #367b99;border-radius:12px}h1{color:#49e5f5}small{color:#8fa8b4}</style><h1>SPACEPORT</h1><p>Audio and display companion to Spaceagon</p><p id="state">Connecting...</p><button onclick="act('mute')">Mute</button><button onclick="act('unmute')">Unmute</button><button onclick="act('silence')">Silence this alert</button><button onclick="act('dismiss')">Clear local notice</button><button onclick="act('page')">Next idle screen</button><h2>iPhone presence</h2><p id="presence"></p><button onclick="act('presence_on')">Only ring nearby</button><button onclick="act('presence_off')">Disable presence gate</button><button onclick="act('presence_pair')">Pair iPhone (2 minutes)</button><button onclick="if(confirm('Forget paired phone?'))act('presence_forget')">Forget phone</button><p>Nearby threshold (dBm)<input type="number" min="-95" max="-35" value="-72" onchange="act('presence_threshold',this.value)"></p><p>Away timeout (seconds)<input type="number" min="15" max="300" value="60" onchange="act('presence_timeout',this.value)"></p><p>Ring volume <input id="vol" type="range" min="0" max="75" value="20" onchange="act('volume',this.value)"></p><p>Priority volume <input type="range" min="0" max="75" value="35" onchange="act('priority_volume',this.value)"></p><p>Display brightness <input type="range" min="5" max="100" value="50" onchange="act('brightness',this.value)"></p><button onclick="act('test')">Test sound</button><button onclick="act('welcome_sound_test')">Test boatswain call</button><button onclick="act('test_tone',440)">Steady tone (60s)</button><button onclick="act('stop_tone')">Stop tone</button><button onclick="act('demo')">Visual demo</button><button onclick="act('live')">Return to live</button><p><small>Local acknowledgement affects Spaceport only. Calls and DND remain on Spaceagon. Demo sound is off; Test sound plays one short chime.</small></p><script>async function act(action,value){await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json','X-Spaceport':'1'},body:JSON.stringify({action,value:Number(value)})});poll()}async function poll(){let s=await(await fetch('/status')).json();document.querySelector('#state').textContent=`${s.live?'LIVE':'OFFLINE'} / ${s.muted?'MUTED':'SOUND ON'} / ${s.demo?'DEMO':'LIVE DATA'} / v${s.version}`;document.querySelector('#vol').value=s.volume;document.querySelector('#presence').textContent=`${s.presence_enabled?'ENABLED':'DISABLED'} / ${s.pairing?'PAIR NOW':!s.phone_enrolled?'NOT PAIRED':s.phone_nearby?'PHONE NEARBY':'QUIET - PHONE AWAY'} / RSSI ${s.presence_rssi} dBm`}setInterval(poll,3000);poll()</script>)HTML";
static void webSetup() {
  const char* headers[]={"X-Spaceport","Authorization"};web.collectHeaders(headers,2);
  web.on("/presence-link",HTTP_GET,[]{if(!authenticate())return;JsonDocument j;j["url"]="http://"+WiFi.localIP().toString()+"/v1/presence";j["token"]=presenceReadKey;String out;serializeJson(j,out);web.sendHeader("Cache-Control","no-store");web.send(200,"application/json",out);});
  web.on("/v1/presence",HTTP_GET,[]{
    String expected="Bearer "+presenceReadKey,actual=web.header("Authorization");unsigned difference=actual.length()^expected.length();
    for(size_t i=0;i<expected.length();i++)difference|=uint8_t(expected[i])^uint8_t(i<actual.length()?actual[i]:0);
    if(difference){web.send(401,"application/json","{}");return;}
    auto ps=presence.status();JsonDocument j;j["version"]=1;j["enabled"]=ps.enabled;j["enrolled"]=ps.enrolled;j["nearby"]=ps.nearby(millis());j["timeout_seconds"]=ps.grace/1000;j["rssi"]=ps.rssi;
    String out;serializeJson(j,out);web.sendHeader("Cache-Control","no-store");web.send(200,"application/json",out);
  });
  web.on("/",HTTP_GET,[]{if(authenticate())web.send(200,"text/html",FPSTR(WEB_PAGE));});
  web.on("/status",HTTP_GET,[]{if(!authenticate())return;JsonDocument j;xSemaphoreTake(stateLock,portMAX_DELAY);j["live"]=dashboard.fresh(millis());j["phone_live"]=engine.fresh(millis());xSemaphoreGive(stateLock);j["version"]=VERSION;j["muted"]=permanentMute;j["demo"]=demo;j["volume"]=volume;j["brightness"]=brightness;j["audio_ready"]=audioReady;j["welcome_call_day"]=dailyWelcomeCall.lastDay;j["welcome_call_active"]=pipeUntil&&int32_t(pipeUntil-millis())>0;j["audio_nonzero_samples"]=audioNonzeroSamples;j["free_heap"]=ESP.getFreeHeap();j["minimum_heap"]=ESP.getMinFreeHeap();auto ps=presence.status();j["presence_enabled"]=ps.enabled;j["phone_enrolled"]=ps.enrolled;j["phone_nearby"]=ps.nearby(millis());j["presence_rssi"]=ps.rssi;j["presence_threshold"]=ps.threshold;j["presence_timeout"]=ps.grace/1000;j["pairing"]=presence.pairing();String out;serializeJson(j,out);web.sendHeader("Cache-Control","no-store");web.send(200,"application/json",out);});
  web.on("/action",HTTP_POST,[]{
    if(!authenticate())return;
    if(web.header("X-Spaceport")!="1"||web.arg("plain").length()>256){web.send(400);return;}
    JsonDocument j;if(deserializeJson(j,web.arg("plain"))){web.send(400);return;}
    String a=j["action"]|"";
    xSemaphoreTake(stateLock,portMAX_DELAY);Presentation phone=engine.present(millis());Presentation shown=dashboard.present(millis());Presentation p=phone.view==View::Ringing?phone:shown;
    if(a=="welcome_sound_test"){
      if(!presence.allows()||permanentMute||phone.view==View::Ringing||phone.view==View::Call||shown.view==View::Notice){xSemaphoreGive(stateLock);web.send(409,"application/json","{\"ok\":false}");return;}
      toneUntil=0;audioCue=Cue::Silent;audioVolume=volume;pipeStarted=millis();pipeUntil=pipeStarted+WELCOME_DURATION_MS;
    }
    else if(a=="presence_on")presence.enable(true);
    else if(a=="presence_off")presence.enable(false);
    else if(a=="presence_pair")presence.pair();
    else if(a=="presence_forget")presence.forget();
    else if(a=="presence_threshold")presence.threshold(j["value"]|-72);
    else if(a=="presence_timeout")presence.timeout(j["value"]|60);
    else if(a=="mute"){toneUntil=0;pipeUntil=0;permanentMute=true;engine.muted=true;dashboard.muted=true;audioCue=Cue::Silent;}
    else if(a=="unmute"){permanentMute=false;engine.muted=false;dashboard.muted=false;}
    else if(a=="silence"){toneUntil=0;pipeUntil=0;engine.silence(p);dashboard.silence(p);audioCue=Cue::Silent;}
    else if(a=="dismiss"){dashboard.acknowledge(shown);audioCue=Cue::Silent;}
    else if(a=="page"){page=(page+1)%dashboardPages(time(nullptr),latest.calendarEnabled);manualPage=true;manualPageAt=millis();}
    else if(a=="volume")volume=constrain(j["value"]|20,0,75);
    else if(a=="priority_volume")priorityVolume=constrain(j["value"]|35,0,75);
    else if(a=="brightness"){brightness=constrain(j["value"]|50,5,100);ledcWrite(0,brightness*255/100);}
    else if(a=="demo"){demo=true;demoAudio=false;demoSince=millis();audioCue=Cue::Silent;}
    else if(a=="live"){demo=false;audioCue=Cue::Silent;}
    else if(a=="test_tone"){pipeUntil=0;audioCue=Cue::Silent;audioStarted=millis();audioVolume=35;toneHz=constrain(j["value"]|440,100,2000);toneChannel=constrain(j["channel"]|0,0,3);toneUntil=millis()+60000;}
    else if(a=="stop_tone"){toneUntil=0;pipeUntil=0;audioCue=Cue::Silent;}
    else if(a=="test"){toneUntil=0;pipeUntil=0;audioStarted=millis();audioRepeat=false;audioVolume=volume;audioCue=Cue::Info;}
    else {xSemaphoreGive(stateLock);web.send(400);return;}
    xSemaphoreGive(stateLock);
    prefs.begin("spaceport",false);prefs.putInt("brightness",brightness);prefs.putInt("volume",volume);prefs.putInt("priority",priorityVolume);prefs.putBool("muted",permanentMute);prefs.end();web.send(200,"application/json","{\"ok\":true}");
  });web.begin();
}

static Presentation demoPresentation(uint32_t now) {
  Presentation p;int step=((now-demoSince)/6000)%(2+dashboardPages(time(nullptr),latest.calendarEnabled));
  if(step<2){p.view=View::Notice;p.priority=step==1;p.id="demo";p.title=step==1?"Storage needs attention":"Backup complete";p.body=step==1?"An example urgent alert. Hold BOOT to clear.":"All files copied successfully.";p.kind=step==1?"failure":"success";p.progress=step==0?73:-1;}
  else p.view=View::Idle;
  return p;
}

void setup() {
  Serial.setRxBufferSize(8192);Serial.begin(115200);pinMode(0,INPUT_PULLUP);pinMode(5,OUTPUT);digitalWrite(5,LOW);
  prefs.begin("spaceport",true);ssid=prefs.getString("ssid");password=prefs.getString("password");origin=prefs.getString("origin");token=prefs.getString("token");ca=prefs.getString("ca");webKey=prefs.getString("web_key");partnerNumber=prefs.getString("partner");partnerName=prefs.getString("partner_name","Partner");partnerSurname=prefs.getString("partner_surname");brightness=constrain(prefs.getInt("brightness",50),5,100);volume=prefs.getInt("volume",20);priorityVolume=prefs.getInt("priority",35);permanentMute=prefs.getBool("muted",false);dailyWelcomeCall.lastDay=prefs.getUInt("whistle_day",0);prefs.end();
  configured=validOrigin(origin)&&token.length()>=16&&webKey.length()>=16;engine.muted=permanentMute;dashboard.muted=permanentMute;
  stateLock=xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(audioTask,"audio",8192,nullptr,2,nullptr,0);
  uint32_t audioWait=millis();while(!audioReady&&millis()-audioWait<3000)delay(1);
  expanderReset();displayReady=screen.begin(40000000);ledcSetup(0,5000,8);ledcAttachPin(5,0);ledcWrite(0,brightness*255/100);
  if(!displayReady)Serial.println("DISPLAY_INIT_FAILED");
  WiFi.mode(WIFI_STA);WiFi.setHostname("spaceport");if(configured)WiFi.begin(ssid.c_str(),password.c_str());
  configTzTime("GMT0BST,M3.5.0/1,M10.5.0","pool.ntp.org","time.cloudflare.com");
  xTaskCreatePinnedToCore(networkTask,"network",16384,nullptr,1,nullptr,0);
  presence.begin();
  prefs.begin("presence",false);presenceReadKey=prefs.getString("read_key");
  if(presenceReadKey.length()!=64){char key[65];for(int i=0;i<8;i++)snprintf(key+i*8,9,"%08lx",(unsigned long)esp_random());presenceReadKey=key;prefs.putString("read_key",presenceReadKey);}prefs.end();
  webSetup();Serial.println("SPACEPORT_READY 0.7.0");
}
void loop() {
  presence.tick();presenceAudioAllowed=presence.allows();web.handleClient();
  static std::string lastRemoteCommand;
  xSemaphoreTake(stateLock,portMAX_DELAY);
  if(latest.commandExpires>time(nullptr)&&!latest.commandId.empty()&&latest.commandId!=lastRemoteCommand){
    lastRemoteCommand=latest.commandId;const auto& a=latest.commandAction;int value=latest.commandValue;
    auto p=dashboard.present(millis());
    if(a=="volume")volume=constrain(value,0,75);
    else if(a=="priority_volume")priorityVolume=constrain(value,0,75);
    else if(a=="brightness")brightness=constrain(value,5,100);
    else if(a=="mute"){permanentMute=true;engine.muted=true;dashboard.muted=true;toneUntil=0;pipeUntil=0;audioCue=Cue::Silent;}
    else if(a=="unmute"){permanentMute=false;engine.muted=false;dashboard.muted=false;}
    else if(a=="silence"){engine.silence(engine.present(millis()));dashboard.silence(p);toneUntil=0;pipeUntil=0;audioCue=Cue::Silent;}
    else if(a=="dismiss")dashboard.acknowledge(p);
    else if(a=="page"){page=(page+1)%dashboardPages(time(nullptr),latest.calendarEnabled);manualPage=true;manualPageAt=millis();}
    else if(a=="demo"){demo=true;demoAudio=false;demoSince=millis();}
    else if(a=="live")demo=false;
    else if(a=="test"){toneUntil=0;pipeUntil=0;audioStarted=millis();audioRepeat=false;audioVolume=volume;audioCue=Cue::Info;}
    prefs.begin("spaceport",false);prefs.putInt("brightness",brightness);prefs.putInt("volume",volume);prefs.putInt("priority",priorityVolume);prefs.putBool("muted",permanentMute);prefs.end();
    reportedCommand=lastRemoteCommand;reportedCommandStatus="applied";
  }
  xSemaphoreGive(stateLock);
  while(Serial.available()) {char c=Serial.read();if(c=='\n'){provision(serialLine);serialLine="";}else if(c!='\r'){if(serialLine.length()<8192)serialLine+=c;else serialLine="";}}
  uint32_t now=millis();bool down=digitalRead(0)==LOW;
  if(down&&!buttonSince)buttonSince=now;
  if(!down&&buttonSince) {
    uint32_t held=now-buttonSince;buttonSince=0;
    if(held>=40){xSemaphoreTake(stateLock,portMAX_DELAY);auto phone=engine.present(now);auto shown=dashboard.present(now);auto p=phone.view==View::Ringing?phone:shown;
      if(held>1500&&shown.view==View::Notice)dashboard.acknowledge(shown);
      else if(p.view==View::Ringing||p.view==View::Notice){engine.silence(p);dashboard.silence(p);}
      else if(held>1500){demo=!demo;demoAudio=false;demoSince=now;}
      else {page=(page+1)%dashboardPages(time(nullptr),latest.calendarEnabled);manualPage=true;manualPageAt=now;}
      toneUntil=0;pipeUntil=0;audioCue=Cue::Silent;xSemaphoreGive(stateLock);}
  }
  if(demo&&now-demoSince>120000)demo=false;
  if(now-lastRender>=100) {
    lastRender=now;xSemaphoreTake(stateLock,portMAX_DELAY);Presentation phone=engine.present(now);Presentation p=dashboard.present(now);Snapshot s=latest;xSemaphoreGive(stateLock);
    renderCounter++;
    // Urgent notifications interrupt the visual tour; phone priority controls audio only.
    if(demo&&!p.priority)p=demoPresentation(now);
    if(phone.view==View::Call||phone.view==View::Ringing)pipeUntil=0;
    setSound(audioPresentation(phone,p));
    int idlePage=manualPage&&uint32_t(now-manualPageAt)<(page==4?30000u:20000u)?page:dashboardPageAt(time(nullptr),now,s.calendarEnabled);
    if(demo&&p.view==View::Idle)idlePage=std::max(0,int(((now-demoSince)/6000)%(2+dashboardPages(time(nullptr),latest.calendarEnabled)))-2);
    bool away=presence.status().enabled&&!presence.allows();
    static uint32_t awaySince=0,welcomeUntil=0;bool welcomeStarted=false;
    if(away&&!awaySince)awaySince=now;
    if(!away&&awaySince){if(now-awaySince>5000){welcomeUntil=now+2300;welcomeStarted=true;}awaySince=0;}
    if(phone.view==View::Ringing||phone.view==View::Call||p.view!=View::Idle||(welcomeUntil&&int32_t(now-welcomeUntil)>=0))welcomeUntil=0;
    if(welcomeStarted&&welcomeUntil&&!demo&&time(nullptr)>1700000000){
      time_t epoch=time(nullptr);tm local={};localtime_r(&epoch,&local);
      uint32_t day=(local.tm_year+1900)*10000+(local.tm_mon+1)*100+local.tm_mday;
      if(dailyWelcomeCall.claim(day)){
        prefs.begin("spaceport",false);prefs.putUInt("whistle_day",day);prefs.end();
        if(!permanentMute&&volume>0&&presence.allows()){toneUntil=0;audioCue=Cue::Silent;audioVolume=volume;pipeStarted=now;pipeUntil=now+WELCOME_DURATION_MS;}
      }
    }
    ledcWrite(0,(away?std::min(brightness,15):brightness)*255/100);
    if(displayReady&&away){screen.fillScreen(0);screen.drawRoundRect(157,130,46,37,7,SP_CYAN);screen.drawCircle(180,127,15,SP_CYAN);screen.fillRect(154,131,52,12,0);screen.drawRoundRect(157,137,46,37,7,SP_CYAN);label(screen,"AWAY",213,3,SP_WHITE);label(screen,"PHONE NOT NEARBY",250,1,SP_CYAN);screen.flush();}
    else if(displayReady&&welcomeUntil&&int32_t(welcomeUntil-now)>0){renderWelcome(screen,now);screen.flush();}
    else if(displayReady){render(screen,p,s,now,idlePage,configured,(presence.status().enabled?String(""):WiFi.localIP().toString()).c_str(),permanentMute,demo);screen.flush();}
  }
  delay(2);
}

