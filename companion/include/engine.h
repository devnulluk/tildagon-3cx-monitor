#pragma once
#include <stdint.h>
#include <string>
#include <vector>
#include <algorithm>
#include <cmath>

namespace spaceport {
enum class View { Offline, Idle, Ringing, Call, Notice };
enum class Cue { Silent, Direct, Internal, Queue, Group, Priority, Partner, Info, Urgent };
struct Call {
  std::string id, state, name, number, route, kind;
  bool priority=false, partner=false, incoming=false;
};
struct Notice {
  std::string id,title,body,type;
  int priority=3, progress=-1;
  uint32_t remainingMs=0;
};
struct Team {std::string initials, state, peer;};
struct Snapshot {
  bool live=false;
  uint32_t received=0, sourceAgeMs=0;
  std::vector<Call> calls;
  std::vector<Notice> notices;
  std::vector<Team> team;
  bool weather=false;
  float temperature=0;
  std::string condition,rain;
};
struct Presentation {
  View view=View::Offline; Cue cue=Cue::Silent;
  std::string id,title,subtitle,body,kind;
  uint32_t seconds=0; int progress=-1;
  bool priority=false,partner=false;
};
inline bool active(const Call& c) {
  return c.state=="ringing"||c.state=="dialing"||c.state=="connected"||c.state=="busy"||c.state=="hold"||c.state=="held";
}
class Engine {
  Snapshot state;
  std::string silenced, connectedId;
  uint32_t connectedAt=0;
  std::vector<std::string> heard;
  std::vector<std::string> dismissed;
 public:
  bool muted=false;
  void accept(const Snapshot& value) {state=value;}
  const Snapshot& snapshot() const {return state;}
  bool fresh(uint32_t now) const {
    return state.live && uint32_t(now-state.received)<5000 &&
      uint64_t(state.sourceAgeMs)+uint32_t(now-state.received)<5000;
  }
  void silence(const Presentation& p) {silenced=p.id;}
  Presentation present(uint32_t now) {
    Presentation p;
    const bool live=fresh(now);
    const Call *own=nullptr;
    if(live)for(const auto& c:state.calls)if(active(c)) {
      const int rank=(c.priority?100:0)+(c.incoming&&c.state=="ringing"?20:0)+(c.state=="connected"?10:0);
      const int prior=own?((own->priority?100:0)+(own->incoming&&own->state=="ringing"?20:0)+(own->state=="connected"?10:0)):-1;
      if(rank>prior)own=&c;
    }
    const Notice *notice=nullptr;
    for(const auto& n:state.notices)if(std::find(dismissed.begin(),dismissed.end(),n.id)==dismissed.end() && uint32_t(now-state.received)<n.remainingMs &&
      (!notice||n.priority>notice->priority))notice=&n;
    if(notice && (!own || (notice->priority==5&&!own->priority))) {
      p.view=View::Notice;p.id="notice:"+notice->id;p.title=notice->title;p.body=notice->body;
      p.kind=notice->type;p.priority=notice->priority==5;p.progress=notice->progress;
      p.subtitle=p.priority?"URGENT / HOLD BOOT TO CLEAR":"NOTIFICATION";
      if(std::find(heard.begin(),heard.end(),p.id)==heard.end()) {
        p.cue=p.priority?Cue::Urgent:Cue::Info;
        // Only mark audible notices as heard; muted devices do not accumulate a backlog.
        heard.push_back(p.id);if(heard.size()>64)heard.erase(heard.begin());
      }
      if(muted||silenced==p.id)p.cue=Cue::Silent;
      return p;
    }
    if(own) {
      p.id="call:"+own->id;p.title=own->name.empty()?own->number:own->name;
      p.subtitle=own->route;p.kind=own->kind;p.priority=own->priority;p.partner=own->partner;
      const bool ringing=own->incoming&&own->state=="ringing";
      p.view=ringing?View::Ringing:View::Call;
      p.body=ringing?"INCOMING":own->state=="dialing"?"CALLING":own->state=="hold"||own->state=="held"?"ON HOLD":"CONNECTED";
      if(!ringing&&own->state!="dialing") {
        if(connectedId!=own->id){connectedId=own->id;connectedAt=now;}
        p.seconds=uint32_t(now-connectedAt)/1000;
      }
      if(ringing&&!muted&&silenced!=p.id) p.cue=own->partner?Cue::Partner:own->priority?Cue::Priority:
        own->kind=="queue"?Cue::Queue:own->kind=="ring_group"?Cue::Group:own->kind=="internal"?Cue::Internal:Cue::Direct;
      return p;
    }
    if(!own)connectedId.clear();
    p.view=live?View::Idle:View::Offline;
    return p;
  }
  void acknowledge(const Presentation& p) {
    silence(p);if(p.view==View::Notice){dismissed.push_back(p.id.substr(7));if(dismissed.size()>64)dismissed.erase(dismissed.begin());}
  }
};
inline std::string ascii(const std::string& s,size_t limit=100) {
  std::string out;for(unsigned char c:s){if(c>=32&&c<127)out+=char(c);if(out.size()>=limit)break;}return out;
}
inline std::string normalize(std::string s) {
  std::string out;for(char c:s)if(c>='0'&&c<='9')out+=c;
  if(out.rfind("0044",0)==0)out=out.substr(2);
  if(out.size()>8&&out[0]=='0')out="44"+out.substr(1);return out;
}
}
