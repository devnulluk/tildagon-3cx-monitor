#pragma once
#include <cmath>
#include <stdint.h>
namespace spaceport {
struct DailyWelcomeCall {
    uint32_t lastDay=0;
    bool claim(uint32_t day){
        // Only advance the local calendar, including after an NTP correction.
        if(day<20200101||day>21001231||day<=lastDay)return false;
        lastDay=day;return true;
    }
};
// Original two-part pipe, not a sampled film/TV recording. Mono 22.05kHz source.
inline float welcomePipe(float t){
    float u,duration,start,slope;
    if(t>=0&&t<.72f){u=t;duration=.72f;start=1850;slope=700;}
    else if(t>=.9f&&t<1.85f){u=t-.9f;duration=.95f;start=2280;slope=-850;}
    else return 0;
    float attack=fminf(1,u/.035f),release=fminf(1,(duration-u)/.11f);
    float envelope=sinf(attack*1.5707963f)*sinf(release*1.5707963f);
    float phase=6.2831853f*(start*u+.5f*slope*u*u)+.025f*sinf(u*31.415926f);
    return .72f*envelope*(sinf(phase)+.06f*sinf(2*phase));
}
}
