#pragma once
#include <stdint.h>
namespace spaceport {
struct PresencePolicy {
 bool enabled=false,enrolled=false,seen=false; int threshold=-72,rssi=-127; uint32_t last=0,grace=60000;
 void observe(int strength,uint32_t now) { rssi=strength; if(strength>=threshold-(nearby(now)?8:0)){seen=true;last=now;} }
 bool nearby(uint32_t now) const {return enrolled&&seen&&uint32_t(now-last)<grace;}
 bool allows(uint32_t now) const {return !enabled||nearby(now);}
};
}
