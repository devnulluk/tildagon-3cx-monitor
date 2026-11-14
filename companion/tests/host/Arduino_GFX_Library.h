// Host-only raster sink for the production ui.h; never linked into the firmware.
#pragma once
#include <stdint.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <vector>
#define PROGMEM
struct GFXglyph {uint16_t bitmapOffset;uint8_t width,height,xAdvance;int8_t xOffset,yOffset;};
struct GFXfont {uint8_t* bitmap;GFXglyph* glyph;uint16_t first,last;uint8_t yAdvance;};
class Arduino_GFX {
 std::vector<uint16_t> pixels=std::vector<uint16_t>(360*360);
 const GFXfont* font=nullptr;int cx=0,cy=0;uint16_t colour=0xffff;
 public:
 void pixel(int x,int y,uint16_t c){if(x>=0&&y>=0&&x<360&&y<360&&(x-180)*(x-180)+(y-180)*(y-180)<=180*180)pixels[y*360+x]=c;}
 void fillScreen(uint16_t c){std::fill(pixels.begin(),pixels.end(),c);}
 void fillCircle(int x,int y,int r,uint16_t c){for(int yy=-r;yy<=r;yy++)for(int xx=-r;xx<=r;xx++)if(xx*xx+yy*yy<=r*r)pixel(x+xx,y+yy,c);}
 void fillEllipse(int x,int y,int rx,int ry,uint16_t c){for(int yy=-ry;yy<=ry;yy++)for(int xx=-rx;xx<=rx;xx++)if(float(xx*xx)/(rx*rx)+float(yy*yy)/(ry*ry)<=1)pixel(x+xx,y+yy,c);}
 void drawLine(int x,int y,int a,int b,uint16_t c){int dx=abs(a-x),sx=x<a?1:-1,dy=-abs(b-y),sy=y<b?1:-1,err=dx+dy;for(;;){pixel(x,y,c);if(x==a&&y==b)break;int e=2*err;if(e>=dy){err+=dy;x+=sx;}if(e<=dx){err+=dx;y+=sy;}}}
 void drawCircle(int x,int y,int r,uint16_t c){for(float a=0;a<6.284f;a+=.004f)pixel(x+int(cosf(a)*r),y+int(sinf(a)*r),c);}
 void fillTriangle(int x1,int y1,int x2,int y2,int x3,int y3,uint16_t c){for(int y=std::min({y1,y2,y3});y<=std::max({y1,y2,y3});y++)for(int x=std::min({x1,x2,x3});x<=std::max({x1,x2,x3});x++){int a=(x-x2)*(y1-y2)-(x1-x2)*(y-y2),b=(x-x3)*(y2-y3)-(x2-x3)*(y-y3),d=(x-x1)*(y3-y1)-(x3-x1)*(y-y1);if((a>=0&&b>=0&&d>=0)||(a<=0&&b<=0&&d<=0))pixel(x,y,c);}}
 void drawRoundRect(int x,int y,int w,int h,int r,uint16_t c){drawLine(x+r,y,x+w-r,y,c);drawLine(x+r,y+h,x+w-r,y+h,c);drawLine(x,y+r,x,y+h-r,c);drawLine(x+w,y+r,x+w,y+h-r,c);for(float a=0;a<1.571f;a+=.02f){int xx=cosf(a)*r,yy=sinf(a)*r;pixel(x+r-xx,y+r-yy,c);pixel(x+w-r+xx,y+r-yy,c);pixel(x+r-xx,y+h-r+yy,c);pixel(x+w-r+xx,y+h-r+yy,c);}}
 void fillRoundRect(int x,int y,int w,int h,int r,uint16_t c){for(int yy=0;yy<h;yy++)for(int xx=0;xx<w;xx++)pixel(x+xx,y+yy,c);}
 void setFont(const GFXfont* f){font=f;}void setTextSize(int){}void setTextColor(uint16_t c){colour=c;}void setCursor(int x,int y){cx=x;cy=y;}
 void getTextBounds(const char* s,int x,int y,int16_t* x1,int16_t* y1,uint16_t* w,uint16_t* h){int l=x,rr=x,top=y,bot=y,cur=x;for(;*s;s++){unsigned char c=*s;if(c<font->first||c>font->last)continue;auto g=font->glyph[c-font->first];l=std::min(l,cur+g.xOffset);rr=std::max(rr,cur+g.xOffset+g.width);top=std::min(top,y+g.yOffset);bot=std::max(bot,y+g.yOffset+g.height);cur+=g.xAdvance;}*x1=l;*y1=top;*w=rr-l;*h=bot-top;}
 void print(const char* s){for(;*s;s++){unsigned char c=*s;if(c<font->first||c>font->last)continue;auto g=font->glyph[c-font->first];int bit=0;for(int y=0;y<g.height;y++)for(int x=0;x<g.width;x++,bit++)if(font->bitmap[g.bitmapOffset+bit/8]&(0x80>>(bit%8)))pixel(cx+g.xOffset+x,cy+g.yOffset+y,colour);cx+=g.xAdvance;}}
 void save(const char* path){FILE* f=fopen(path,"wb");fprintf(f,"P6\n360 360\n255\n");for(auto v:pixels){unsigned char rgb[]={uint8_t(((v>>11)&31)*255/31),uint8_t(((v>>5)&63)*255/63),uint8_t((v&31)*255/31)};fwrite(rgb,1,3,f);}fclose(f);}
};
