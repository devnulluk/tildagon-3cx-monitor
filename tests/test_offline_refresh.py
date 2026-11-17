import unittest
from unittest.mock import patch
import test_badge as support
class RefreshTests(unittest.TestCase):
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
