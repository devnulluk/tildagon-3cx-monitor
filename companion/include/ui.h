#pragma once
#include <Arduino_GFX_Library.h>
#include <Fonts/FreeSansBold24pt7b.h>
#include <Fonts/FreeSansBold12pt7b.h>
#include <Fonts/FreeSans9pt7b.h>
#include <time.h>
#include "engine.h"

namespace spaceport {
constexpr uint16_t SP_NAVY=0x0043, SP_CYAN=0x37df, SP_PINK=0xfb76, SP_GOLD=0xfe4a, SP_WHITE=0xefbf, SP_DIM=0x7452;
inline void label(Arduino_GFX& g,const std::string& text,int y,int size=1,uint16_t colour=SP_WHITE,int width=280) {
  const GFXfont* f=size==3?&FreeSansBold24pt7b:size==2?&FreeSansBold12pt7b:&FreeSans9pt7b;
  std::string value=ascii(text,100);int16_t x1,y1;uint16_t w,h;
  g.setFont(f);g.setTextSize(1);g.getTextBounds(value.c_str(),0,y,&x1,&y1,&w,&h);
  if(w>width&&size>1){label(g,value,y,size-1,colour,width);return;}
  bool cut=false;
  while(w>width&&value.size()>3){value.pop_back();cut=true;g.getTextBounds((value+"...").c_str(),0,y,&x1,&y1,&w,&h);}
  if(cut)value+="...";
  g.getTextBounds(value.c_str(),0,y,&x1,&y1,&w,&h);
  g.setTextColor(colour);g.setCursor(180-int(w)/2-x1,y);g.print(value.c_str());
}
inline void arc(Arduino_GFX& g,int radius,float start,float end,uint16_t c,int thick=2) {
  for(float a=start;a<end;a+=.018f) {
    int x=180+cosf(a)*radius,y=180+sinf(a)*radius;g.fillCircle(x,y,thick,c);
  }
}
inline void backdrop(Arduino_GFX& g,uint32_t now,uint16_t accent) {
  g.fillScreen(SP_NAVY);
  for(int i=0;i<58;i++) {
    int x=(i*83+31)%360,y=(i*137+17)%360;
    if((x-180)*(x-180)+(y-180)*(y-180)<28500)g.fillCircle(x,y,i%11==0?1:0,i%3?0x212a:0x4a52);
  }
  g.drawCircle(180,180,174,0x194b);g.drawCircle(180,180,169,0x1129);
  arc(g,174,-1.7f,-.1f,accent,1);arc(g,174,1.45f,2.9f,accent,1);
  for(int i=0;i<60;i++) {
    float a=i*6.2831853f/60;int r=i%5?165:160;
    g.drawLine(180+cosf(a)*r,180+sinf(a)*r,180+cosf(a)*167,180+sinf(a)*167,i%5?0x212a:SP_DIM);
  }
  float a=now/18000.f;g.fillCircle(180+cosf(a)*174,180+sinf(a)*174,3,accent);
}
inline void heart(Arduino_GFX& g,int x,int y,uint16_t c,int r=14) {
  g.fillCircle(x-r/2,y,r,c);g.fillCircle(x+r/2,y,r,c);
  g.fillTriangle(x-r*3/2,y,x+r*3/2,y,x,y+r*2,c);
}
inline void bunny(Arduino_GFX& g,uint32_t now) {
  g.fillEllipse(170,137,10,36,SP_WHITE);g.fillEllipse(197,132,10,38,SP_WHITE);
  g.fillEllipse(170,137,4,25,SP_PINK);g.fillEllipse(197,132,4,26,SP_PINK);
  g.fillEllipse(183,205,44,46,SP_WHITE);g.fillEllipse(183,173,39,33,SP_WHITE);
  g.fillCircle(169,170,3,SP_NAVY);g.fillCircle(197,170,3,SP_NAVY);
  g.fillTriangle(180,178,187,178,184,183,SP_PINK);
  g.fillCircle(157,181,5,0xfcb9);g.fillCircle(208,181,5,0xfcb9);
  int wave=int(8*sinf(now/240.f));g.drawLine(215,208,241+wave,178,SP_PINK);g.fillCircle(241+wave,178,8,SP_WHITE);
  g.fillEllipse(163,245,17,7,SP_PINK);g.fillEllipse(204,245,17,7,SP_PINK);
}
inline void paragraph(Arduino_GFX& g,const std::string& text,int y,uint16_t c=SP_WHITE) {
  std::string word,line;int row=0;
  for(size_t i=0;i<=text.size();i++) {
    char ch=i==text.size()?' ':text[i];
    if(ch==' '||ch=='\n') {
      if(line.size()+word.size()>29){label(g,line,y+row*24,1,c,270);line="";if(++row>=4)return;}
      if(!line.empty())line+=' ';line+=word;word="";
      if(ch=='\n'){label(g,line,y+row*24,1,c,270);line="";if(++row>=4)return;}
    }else word+=ch;
  }
  if(!line.empty())label(g,line,y+row*24,1,c,270);
}
inline void render(Arduino_GFX& g,const Presentation& p,const Snapshot& s,uint32_t now,int page,bool configured,const std::string& ip,bool muted,bool demo) {
  uint16_t accent=p.partner?SP_PINK:p.priority?0xf986:p.kind=="ring_group"?0xab7f:p.kind=="internal"?SP_GOLD:SP_CYAN;
  backdrop(g,now,accent);
  if(p.view==View::Ringing||p.view==View::Call) {
    label(g,p.partner&&p.view==View::Ringing?"INCOMING TRANSMISSION":p.body,61,1,accent,240);
    if(p.partner) {
      label(g,p.title,101,3,SP_PINK);bunny(g,now);label(g,p.subtitle,282,2,SP_WHITE);
      if(p.view==View::Call){char b[24];snprintf(b,sizeof b,"%02lu:%02lu",(unsigned long)p.seconds/60,(unsigned long)p.seconds%60);label(g,b,314,2,SP_PINK);}
      heart(g,103,205,SP_PINK,8);heart(g,265,134,SP_PINK,7);
    }else {
      // Orbiting signal rings leave room for large caller text inside the circle.
      arc(g,140,-.8f+now/1500.f,.3f+now/1500.f,accent,2);
      label(g,p.title,154,3,SP_WHITE,280);label(g,p.subtitle,206,2,accent,290);
      if(p.view==View::Call){char b[30];snprintf(b,sizeof b,"%02lu:%02lu",(unsigned long)p.seconds/60,(unsigned long)p.seconds%60);label(g,b,270,3,SP_WHITE);}
      else {g.drawRoundRect(78,243,204,40,15,accent);label(g,"BOOT TO SILENCE",270,1,accent,190);}
    }
    if(!(p.partner&&p.view==View::Call))label(g,p.priority?"PRIORITY":p.kind=="queue"?"QUEUE":p.kind=="ring_group"?"RING GROUP":p.view==View::Call?"SPACEAGON LINK":"INCOMING CALL",316,1,accent,200);
  }else if(p.view==View::Notice) {
    label(g,p.priority?"PRIORITY SIGNAL":"INCOMING SIGNAL",64,1,accent,240);
    g.drawCircle(180,100,18,accent);label(g,p.priority?"!":"i",108,2,accent,40);
    label(g,p.title,153,2,SP_WHITE,280);paragraph(g,p.body,190);
    if(p.progress>=0){g.drawRoundRect(67,284,226,12,5,SP_DIM);g.fillRoundRect(69,286,222*p.progress/100,8,3,accent);}
    label(g,p.priority?"HOLD BOOT TO CLEAR":"BOOT TO SILENCE",322,1,accent,220);
  }else if(p.view==View::Offline) {
    label(g,"SPACEPORT",84,2,SP_CYAN);g.drawCircle(180,156,29,SP_DIM);g.drawLine(158,177,202,135,SP_GOLD);
    label(g,configured?(time(nullptr)<1700000000?"SYNCING TIME":"LINK LOST"):"USB SETUP",227,2,SP_WHITE);
    label(g,configured?"Checking Wi-Fi / server":"Run provision.py on your PC",258,1,SP_DIM);
    label(g,"AUDIO FAIL-SAFE ACTIVE",300,1,SP_GOLD,240);
  }else {
    int pane=page;
    if(pane==0) {
      label(g,"ORBITAL CHRONOMETER",65,1,SP_CYAN,245);
      time_t epoch=time(nullptr);struct tm tm={};localtime_r(&epoch,&tm);char b[40];
      if(epoch<1700000000)snprintf(b,sizeof b,"--:--");else strftime(b,sizeof b,"%H:%M",&tm);
      label(g,b,174,3,SP_WHITE);strftime(b,sizeof b,"%a %d %b",&tm);label(g,epoch<1700000000?"SYNCING CLOCK":b,210,2,SP_DIM);
      float moon=fmod((epoch/86400.0-10963.26)/29.530588853,1.0);if(moon<0)moon+=1;
      g.fillCircle(180,258,23,0x8c72);g.fillCircle(180+int(cosf(moon*6.2831853f)*20),258,21,SP_NAVY);
      label(g,"MOON / APPROXIMATE",308,1,SP_DIM,230);
    }else if(pane==1) {
      label(g,"PLANETARY WEATHER",65,1,SP_CYAN,245);
      if(s.weather){g.fillCircle(180,116,23,SP_GOLD);for(int i=0;i<8;i++){float a=i*.785398f;g.drawLine(180+cosf(a)*30,116+sinf(a)*30,180+cosf(a)*40,116+sinf(a)*40,SP_GOLD);}
        char b[20];snprintf(b,sizeof b,"%.0f C",s.temperature);label(g,b,208,3,SP_WHITE);label(g,s.condition,242,2,SP_DIM);label(g,s.rain,289,1,SP_CYAN,280);
      }else {label(g,"Weather unavailable",201,2,SP_DIM);label(g,"No forecast is guessed",242,1,SP_DIM);}
    }else {
      label(g,"CREW TELEMETRY",65,1,SP_CYAN,230);
      for(size_t i=0;i<s.team.size();i++) {
        int x=i%2?245:115,y=i<2?123:224;auto& t=s.team[i];uint16_t c=t.state=="idle"?0x3fe9:t.state=="busy"?0xf986:t.state=="ringing"?SP_GOLD:SP_DIM;
        g.drawCircle(x,y,45,c);g.setFont(&FreeSansBold12pt7b);g.setTextColor(c);g.setCursor(x-19,y+7);g.print(t.initials.c_str());
      }
      label(g,"LIVE FROM THE SAME BRIDGE",310,1,SP_DIM,260);
    }
  }
  if(demo)label(g,"DEMO",343,1,SP_GOLD,90);
  else if(muted)label(g,"MUTED",343,1,SP_GOLD,90);
  else if(p.view==View::Idle)label(g,ip,343,1,SP_DIM,155);
}
}
