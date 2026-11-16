#include <cassert>
#include "presence_policy.h"
using namespace spaceport;
int main(){
 PresencePolicy p;
 assert(p.allows(0));p.enabled=true;assert(!p.allows(0));
 p.observe(-40,100);assert(!p.allows(101));
 p.enrolled=true;p.seen=false;p.observe(-90,200);assert(!p.allows(201));
 p.observe(-60,300);assert(p.allows(301));
 p.observe(-79,500);assert(p.allows(600));
 assert(!p.allows(60500));
 p.observe(-79,60600);assert(!p.allows(60601));
 p.observe(-60,61000);assert(p.allows(61001));
 p.enrolled=false;assert(!p.allows(61002));
 p.enrolled=true;p.observe(-60,0xfffffff0);assert(p.allows(10));
 assert(!p.allows(70000));
}
