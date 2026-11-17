import unittest
from unittest.mock import patch
import test_badge as support
class RefreshTests(unittest.TestCase):
 def test_round_preserves_presence_when_bridge_fails(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True)
  peer=dict(version=1,enabled=True,enrolled=True,nearby=True);error=OSError('transport unavailable')
  with patch.object(module,'fetch_snapshot',side_effect=error) as get_state,patch.object(module,'get_json',return_value=peer) as get_peer:
   value,failed,presence,stamp=module.poll_round('https://example.test','read','ca.der',m.state_client,'http://192.0.2.2/v1/presence','peer')
  self.assertIsNone(value);self.assertIs(failed,error);self.assertEqual(presence,peer);get_state.assert_called_once();self.assertEqual(get_peer.call_args.kwargs['timeout'],.6)
 def test_presence_failure_does_not_discard_good_call_data(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True);value=dict(m.controller.payload)
  with patch.object(module,'fetch_snapshot',return_value=value),patch.object(module,'get_json',side_effect=OSError('peer unavailable')):
   result,error,presence,stamp=module.poll_round('https://example.test','read','ca.der',m.state_client,'http://192.0.2.2/v1/presence','peer')
  self.assertIs(result,value);self.assertIsNone(error);self.assertIsNone(presence)
 def test_phone_clock_survives_brief_staleness_but_calls_are_not_live(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True);m.config['device_role']='phone_clock';m._now=lambda:7000;m.clock_ms=7000
  m.controller.received_ms=1000;m.controller.source_age_ms=0
  c=support.RecordingCanvas()
  with patch.object(module,'clock_valid',return_value=True),patch.object(m,'_draw_idle') as dial:m.draw(c)
  dial.assert_called_once();self.assertFalse(m.controller.live(7000));self.assertIsNone(m.controller.alert(7000));self.assertIsNone(m.controller.own_call(7000))
  self.assertNotIn('OFFLINE',[x["text"] for x in c.records])
 def test_sustained_staleness_marks_clock_without_reviving_calls(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True);m.config['device_role']='phone_clock';m._now=lambda:20000;m.clock_ms=20000;m.controller.received_ms=1000
  c=support.RecordingCanvas()
  with patch.object(module,'clock_valid',return_value=True),patch.object(m,'_draw_idle'):m.draw(c)
  self.assertIn('CALL DATA OFFLINE',[x["text"] for x in c.records]);self.assertFalse(m.controller.live(20000))
