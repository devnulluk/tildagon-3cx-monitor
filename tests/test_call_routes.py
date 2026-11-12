"""Route names must come from matching routing metadata, never queue membership."""
import unittest
from test_model import settings,leg,dn
from bridge.model import build_state
class RouteTests(unittest.TestCase):
 def state(self,participants,extra=()):
  return build_state(settings(queues={'222':'IT'},ring_groups={'826':'Operations Office'}),[dn('200',participants),*extra],True,0)
 def test_ring_group_routing_fields(self):
  for field in ('referred_by_dn','on_behalf_of_dn','originated_by_dn'):
   with self.subTest(field=field):
    call=self.state([leg(**{field:'826'})])['alert']
    self.assertEqual(call['kind'],'ring_group')
    self.assertEqual(call['ring_group_name'],'Operations Office')
 def test_it_queue_and_direct_extension_are_distinct(self):
  call=self.state([leg(referred_by_dn='222')])['alert']
  self.assertEqual((call['kind'],call['queue_name']),('queue','IT'))
  self.assertEqual(self.state([leg()])['alert']['kind'],'external')
 def test_correlated_group_legs_only(self):
  for other,expected in ((99,'ring_group'),(100,'external'),(0,'external')):
   call=self.state([leg(callid=99)],[dn('826',[leg(callid=other)],kind='Wringgroup')])['alert']
   self.assertEqual(call['kind'],expected)
 def test_queue_precedes_group_without_discarding_evidence(self):
  call=self.state([leg(referred_by_dn='826',on_behalf_of_dn='222')])['alert']
  self.assertEqual(call['kind'],'queue')
  self.assertEqual(call['ring_group_name'],'Operations Office')
 def test_priority_preserves_route(self):
  call=self.state([leg(referred_by_dn='826',party_dn='223',party_caller_id='223',party_dn_type='Wextension')])['alert']
  self.assertTrue(call['priority'])
  self.assertEqual(call['ring_group_name'],'Operations Office')

class RouteDisplayTests(unittest.TestCase):
 def test_named_routes_visible_ringing_and_connected_including_priority(self):
  import test_badge as support
  for kind,field,name in [('queue','queue_name','IT'),('ring_group','ring_group_name','Operations Office')]:
   for incoming in (True,False):
    for priority in (True,False):
     module,monitor,unused=support.BadgeAppTests.live_monitor(True)
     canvas=support.RecordingCanvas()
     monitor._draw_call(canvas,{'id':'route','state':'ringing' if incoming else 'connected','direction':'inbound','peer_name':'Example Caller','peer_number':'WITHHELD','kind':kind,field:name,'priority':priority},incoming=incoming)
     self.assertTrue(any(name in x['text'] for x in canvas.records))
