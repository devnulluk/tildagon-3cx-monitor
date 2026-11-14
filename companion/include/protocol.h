#pragma once
#include <ArduinoJson.h>
#include "engine.h"
namespace spaceport {
inline Snapshot parseState(JsonDocument& j,uint32_t now,const std::string& partnerNumber="",const std::string& partnerName="Partner",const std::string& partnerSurname="") {
  Snapshot s;s.received=now;
  const double age=j["age_seconds"]|99999.0;
  s.feedLive=j["own"].is<JsonObject>()&&j["team"].is<JsonArray>()&&j["version"]==1&&!j["demo"].as<bool>();
  s.live=s.feedLive&&j["connected"]==true&&std::isfinite(age)&&age>=0&&age<5;
  s.sourceAgeMs=uint32_t(std::min(99999.0,std::max(0.0,age))*1000);
  for(JsonObject c:j["own"]["calls"].as<JsonArray>()) {
    if(s.calls.size()>=8)break;
    Call v;v.id=ascii(c["id"]|"",64);if(v.id.empty())continue;
    v.state=ascii(c["state"]|"",16);v.name=ascii(c["peer_name"]|"",80);v.number=ascii(c["peer_number"]|"",40);
    v.kind=ascii(c["kind"]|"",20);v.priority=c["priority"]==true;v.incoming=c["direction"]=="inbound";
    // Empty queue fields are common: select the first nonempty route explicitly.
    for(const char *field:{"queue_name","queue_number","ring_group_name","ring_group_number","ddi_name","ddi"}) {
      std::string route=ascii(c[field]|"",60);if(!route.empty()){v.route=route;break;}
    }
    v.partner=!partnerNumber.empty()&&normalize(v.number)==normalize(partnerNumber.c_str());
    if(v.partner){v.name=partnerName.c_str();if(!partnerSurname.empty())v.route=partnerSurname.c_str();}
    s.calls.push_back(v);
  }
  for(JsonObject n:j["notifications"].as<JsonArray>()) {
    if(s.notices.size()>=16)break;
    double ageN=n["age_seconds"]|99999.0;int ttl=n["ttl_seconds"]|0;
    if(!std::isfinite(ageN)||ageN<0||ttl<1||ttl>86400||ageN>=ttl)continue;
    Notice v;v.id=ascii(n["id"]|"",64);if(v.id.empty())continue;
    v.title=ascii(n["title"]|"Notification",80);v.body=ascii(n["body"]|"",320);v.type=ascii(n["type"]|"info",12);
    v.priority=std::max(1,std::min(5,n["priority"]|3));v.progress=n["progress"].is<int>()?std::max(0,std::min(100,n["progress"].as<int>())):-1;
    v.remainingMs=uint32_t((ttl-ageN)*1000);s.notices.push_back(v);
  }
  for(JsonObject m:j["team"].as<JsonArray>()) {
    if(s.team.size()>=4)break;
    Team t;t.initials=ascii(m["name"]|"?",4);t.state=ascii(m["state"]|"unknown",12);
    for(JsonObject c:m["calls"].as<JsonArray>()){t.peer=c["kind"]=="internal"?ascii(c["peer_first_name"]|"",20):"External";break;}
    s.team.push_back(t);
  }
  JsonObject w=j["weather"].as<JsonObject>();
  s.weather=w["available"]==true && !w["stale"].as<bool>();
  s.temperature=w["current"]["temperature_c"]|0.0f;s.condition=ascii(w["current"]["condition"]|"Weather unavailable",35);
  JsonObject rain=w["rain_next_hour"].as<JsonObject>();
  std::string status=rain["status"]|"unknown";
  s.rain=status=="dry_likely"?"Dry next hour":status=="rain_likely"?"Rain in next hour":"Rain forecast uncertain";
  return s;
}

}
