#include "protocol.h"
#include <cassert>
#include <iostream>
using namespace spaceport;
int main(){
 JsonDocument j;deserializeJson(j,R"({"version":1,"connected":true,"age_seconds":0.2,"own":{"calls":[{"id":"42","state":"ringing","direction":"inbound","peer_number":"07700900123","kind":"ring_group","queue_name":"","ring_group_name":"Operations Office"}]},"team":[{"name":"TB","state":"busy","calls":[{"kind":"internal","peer_first_name":"Example"}]}],"weather":{"available":true,"stale":false,"current":{"temperature_c":14,"condition":"Cloudy"},"rain_next_hour":{"status":"rain_likely"}},"notifications":[{"id":"a","title":"Backup","priority":5,"age_seconds":2,"ttl_seconds":60}]})");
 auto s=parseState(j,100,"+447700900123","Partner","Example");
 assert(s.live&&s.sourceAgeMs==200&&s.calls.size()==1&&s.calls[0].partner);
 assert(s.calls[0].name=="Partner"&&s.calls[0].route=="Example");
 s=parseState(j,100);assert(s.calls[0].route=="Operations Office"&&!s.calls[0].partner);
 assert(s.team[0].peer=="Example"&&s.weather&&s.rain=="Rain in next hour");
 assert(s.notices[0].remainingMs==58000&&s.notices[0].priority==5);
 j["weather"]["rain_next_hour"]["status"]="dry_likely";assert(parseState(j,100).rain=="Dry next hour");
 j["weather"]["stale"]=true;assert(!parseState(j,100).weather);
 j["demo"]=true;assert(!parseState(j,100).live);j["demo"]=false;
 j["age_seconds"]=5;assert(!parseState(j,100).live);j["age_seconds"]=-1;assert(!parseState(j,100).live);
 j["age_seconds"]=0;j["notifications"][0]["age_seconds"]=60;assert(parseState(j,100).notices.empty());
 j["version"]=2;assert(!parseState(j,100).live);
 JsonDocument missing;assert(!parseState(missing,100).live);
 std::cout<<"Protocol: route fallback, partner matching, weather, expiry and stale/demo rejection checks passed\n";
}
