#include <time.h>
#ifdef _WIN32
inline tm* localtime_r(const time_t* t,tm* out){localtime_s(out,t);return out;}
#endif
#include "ui.h"
#include <string>
using namespace spaceport;
int main(int argc,char** argv){
 if(argc<3)return 2;std::string scene=argv[1];int ms=argc>3?atoi(argv[3]):1800;
 Presentation p;Snapshot s;s.live=true;s.weather=true;s.temperature=14;s.condition="Partly cloudy";s.rain="Dry next hour";
 s.team={{"TB","busy","Marion"},{"PD","idle",""},{"JH","idle",""},{"SM","ringing","External"}};
 p.view=View::Idle;int page=0;
 if(scene=="rain")page=1;else if(scene=="moon")page=2;else if(scene=="meteors")page=3;else if(scene=="advent")page=4;
 else if(scene=="queue"||scene=="group"||scene=="partner"||scene=="connected"){
 p.view=scene=="connected"?View::Call:View::Ringing;p.title="Example Caller";p.kind=scene=="group"?"ring_group":"queue";p.subtitle=scene=="group"?"Operations Office":"IT";p.body=scene=="connected"?"CONNECTED":"INCOMING";p.seconds=83;
 if(scene=="partner"){p.partner=true;p.priority=true;p.title="Keziah";p.subtitle="Partner";}
 }else if(scene=="urgent"||scene=="notification"){
 p.view=View::Notice;p.priority=scene=="urgent";p.kind=p.priority?"failure":"success";p.title=p.priority?"Storage warning":"Backup complete";p.body=p.priority?"Check the server. This alert stays until acknowledged.":"All files copied successfully.";p.progress=p.priority?-1:100;
 }else if(scene=="offline")p.view=View::Offline;
 Arduino_GFX g;render(g,p,s,ms,page,true,"192.0.2.20",false,false);g.save(argv[2]);
}
