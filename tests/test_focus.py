import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import test_badge as support

spec=importlib.util.spec_from_file_location('focus_test',Path(__file__).resolve().parents[1]/'badge/focus.py')
focus=importlib.util.module_from_spec(spec);spec.loader.exec_module(focus)

class FocusTests(unittest.TestCase):
 def test_app_page_and_call_preemption(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True)
  for member in [m.controller.payload['own']]+m.controller.payload['team']:member.update(state='idle',calls=[])
  m._open_menu();m.menu_selected=5;m._menu_key('ENTER');self.assertTrue(m.focus_open)
  m._focus_key('C');self.assertTrue(m.focus.active);self.assertIsNone(m.controls.pending)
  m._focus_key('A');self.assertFalse(m.focus_open);self.assertTrue(m.focus.active)
  m.controller.payload['own']['calls']=[{'state':'connected'}]
  self.assertFalse(focus.quiet(m.controller.payload,True))
  self.assertFalse(focus.quiet(m.controller.payload,False))
 def test_driver_uses_physical_grid_and_returns_to_call_text(self):
  from test_matrix import MatrixTests,payload
  fixture=MatrixTests();fixture.setUp();display=fixture.display(slot=2)
  display.focus_rain(.5,1000);fixture.drain(display)
  self.assertEqual(display.last_mode,'focus_rain')
  self.assertEqual(display._packet[0],3)
  display.update(payload(calls=[{'state':'ringing','peer_name':'Example Caller','peer_number':'223','kind':'internal'}]),True,1400)
  self.assertNotEqual(display.last_mode,'focus_rain')
 def test_pause_resume_break_and_long_break(self):
  f=focus.FocusTimer();f.toggle(1000)
  f.toggle(61000);self.assertEqual(f.remaining(90000),24*60)
  f.toggle(121000);self.assertEqual(f.remaining(121000),24*60)
  f.tick(1561000);self.assertEqual(f.phase,'break');self.assertEqual(f.completed,1)
  f.tick(1900000);self.assertEqual(f.phase,'done');self.assertEqual(f.remaining(1900000),0)
  f.completed=3;f.toggle(2000000);f.tick(3500000)
  self.assertEqual(f.duration,15*60000)
 def test_matrix_fill_is_monotonic_bounded_and_paused_static(self):
  before=focus.rain_frame(.25,1000,60,True);after=focus.rain_frame(.5,1000,60,True)
  self.assertEqual(len(after),162);self.assertEqual(sum(bool(x) for x in before),40)
  self.assertEqual(sum(bool(x) for x in after),81)
  self.assertTrue(all(a>=b for a,b in zip(after,before)))
  self.assertLessEqual(max(focus.rain_frame(.5,2000,60)),60)
  self.assertEqual(focus.rain_frame(.5,1000,60,True),focus.rain_frame(.5,2000,60,True))
 def test_clock_independent_duration_and_brightness(self):
  f=focus.FocusTimer();f.adjust(1);self.assertEqual(f.remaining(0),1800)
  f.toggle(0);self.assertEqual(f.remaining(900000),900)
  self.assertLessEqual(max(max(c) for c in f.led_frame(900000,.1)),25)
  f.reset();self.assertFalse(f.active)
 def test_every_active_peer_preempts_focus_animation(self):
  payload={'own':{'state':'idle','calls':[]},'team':[]}
  self.assertTrue(focus.quiet(payload,True));self.assertFalse(focus.quiet(payload,False))
  for state in ('ringing','dialing','busy','connected','hold'):
   payload['team']=[{'state':state,'calls':[]}]
   self.assertFalse(focus.quiet(payload,True))
 def test_app_focus_controls_never_place_a_call(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True)
  m._open_menu();m.menu_selected=5;m._menu_key('ENTER')
  self.assertTrue(m.focus_open)
  m._focus_key('C');self.assertTrue(m.focus.active);self.assertIsNone(m.controls.pending)
  m._focus_key('C');self.assertIsNotNone(m.focus.paused_at)
  m._focus_key('D');self.assertFalse(m.focus.active);self.assertIsNone(m.controls.pending)
  m._focus_key('A');self.assertFalse(m.focus_open)
 def test_focus_draws_native_canvas(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True)
  for member in [m.controller.payload['own']]+m.controller.payload['team']:member.update(state='idle',calls=[])
  m.focus_open=True;m.focus.toggle(m.clock_ms)
  canvas=support.RecordingCanvas();m.draw(canvas)
  self.assertIn('FOCUS ORBIT',[r['text'] for r in canvas.records])
