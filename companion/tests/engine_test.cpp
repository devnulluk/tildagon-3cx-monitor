#include "engine.h"
#include <cassert>
#include <iostream>
using namespace spaceport;
int main() {
  Engine e;Snapshot s;s.live=true;s.received=100;s.sourceAgeMs=0;
  Call c;c.id="one";c.state="ringing";c.incoming=true;c.kind="queue";c.route="IT";c.name="Example";s.calls={c};
  e.accept(s);auto p=e.present(200);assert(p.view==View::Ringing&&p.cue==Cue::Queue&&p.subtitle=="IT");
  e.silence(p);assert(e.present(300).cue==Cue::Silent);
  s.calls[0].id="two";e.accept(s);assert(e.present(300).cue==Cue::Queue);
  s.calls[0].state="connected";e.accept(s);p=e.present(400);assert(p.view==View::Call&&p.cue==Cue::Silent);
  assert(e.present(2400).seconds==2);
  assert(e.present(5100).view==View::Offline&&e.present(5100).cue==Cue::Silent);
  s.received=6000;s.sourceAgeMs=4900;s.calls[0].state="ringing";e.accept(s);assert(!e.fresh(6100));
  s.received=7000;s.sourceAgeMs=0;
  Notice n;n.id="notice";n.title="Backup";n.priority=5;n.remainingMs=10000;s.notices={n};
  e.accept(s);p=e.present(7100);assert(p.view==View::Notice&&p.cue==Cue::Urgent);
  assert(e.present(7200).cue==Cue::Silent); // No repeated chime on repeated snapshots.
  e.accept(s);assert(e.present(7300).cue==Cue::Silent);
  s.calls[0].priority=true;e.accept(s);assert(e.present(7400).view==View::Ringing);
  s.calls[0].partner=true;e.accept(s);assert(e.present(7400).cue==Cue::Partner);
  s.calls[0].priority=false;s.calls[0].partner=false;e.accept(s);p=e.present(7500);e.acknowledge(p);assert(e.present(7600).view==View::Ringing);
  n.id="second";s.notices.push_back(n);e.accept(s);p=e.present(7700);e.acknowledge(p);assert(e.present(7800).view==View::Ringing);
  assert(normalize("+44 7700 900123")==normalize("07700900123"));
  assert(normalize("07700900124")!=normalize("07700900123"));
  s.calls.clear();s.notices.clear();s.received=0xfffffff0;s.sourceAgeMs=0;e.accept(s);assert(e.fresh(0x20));
  e.muted=true;s.received=8000;s.calls={c};e.accept(s);assert(e.present(8100).cue==Cue::Silent);
  Engine phone,dashboard;Snapshot split;split.live=true;split.received=100;
  c.priority=true;c.partner=false;split.calls={c};n.id="split";n.priority=5;n.remainingMs=10000;split.notices={n};
  phone.accept(split);dashboard.accept(dashboardSnapshot(split));
  auto ph=phone.present(200),screen=dashboard.present(200);
  assert(ph.view==View::Ringing&&screen.view==View::Notice);
  assert(audioPresentation(ph,screen).cue==Cue::Priority);
  split.calls[0].state="connected";phone.accept(split);
  assert(audioPresentation(phone.present(300),screen).view==View::Notice);
  dashboard.acknowledge(screen);assert(dashboard.present(300).view==View::Idle);
  assert(dashboard.snapshot().calls.empty()&&dashboard.snapshot().team.empty());
  std::cout<<"Engine: call priority, mute, expiry, reconnect, timer and rollover checks passed\n";
}
