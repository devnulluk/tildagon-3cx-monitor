#include <cassert>
#include <cmath>
#include "welcome_call.h"
using namespace spaceport;
int main(){
 DailyWelcomeCall day;assert(!day.claim(0));assert(day.claim(20261116));assert(!day.claim(20261116));
 DailyWelcomeCall reboot;reboot.lastDay=day.lastDay;assert(!reboot.claim(20261116));assert(!reboot.claim(20261115));assert(reboot.claim(20261117));assert(reboot.claim(20261201));assert(reboot.claim(20270101));
 float first=0,second=0;
 for(int i=0;i<44100;i++){
  float t=i/22050.f,v=welcomePipe(t);assert(std::isfinite(v)&&std::abs(v)<.8f);
  if(t>.1f&&t<.6f)first+=v*v;
  if(t>1.f&&t<1.7f)second+=v*v;
  if(t>.73f&&t<.89f)assert(v==0);
 }
 assert(first>100&&second>100);assert(welcomePipe(0)==0);assert(welcomePipe(2)==0);
}
