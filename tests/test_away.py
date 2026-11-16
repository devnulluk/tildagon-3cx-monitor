import unittest,importlib.util
from pathlib import Path
from unittest.mock import patch
import test_badge as support
spec=importlib.util.spec_from_file_location("away_fixture",Path(__file__).resolve().parents[1]/"badge/away.py")
away=importlib.util.module_from_spec(spec);spec.loader.exec_module(away)
class AwayTests(unittest.TestCase):
 def test_unconfigured_does_not_lock(self):self.assertFalse(away.AwayState().away(20000))
 def test_missing_and_stale_lock_but_fresh_nearby_unlocks(self):
  a=away.AwayState(True);self.assertTrue(a.away(0));self.assertTrue(a.accept(dict(version=1,enabled=True,enrolled=True,nearby=True),100));self.assertFalse(a.away(101));self.assertTrue(a.away(15101))
 def test_away_and_unpaired_lock_even_when_latest(self):
  a=away.AwayState(True)
  for enrolled,nearby in [(True,False),(False,True),(False,False)]:
   a.accept(dict(version=1,enabled=True,enrolled=enrolled,nearby=nearby),100);self.assertTrue(a.away(101))
 def test_invalid_status_cannot_unlock(self):
  a=away.AwayState(True)
  self.assertFalse(a.accept(dict(version=1,enabled=True,enrolled=True,nearby="true"),0));self.assertTrue(a.away(0))
 def test_disabled_detection_restores_normal_display(self):
  a=away.AwayState(True);a.accept(dict(version=1,enabled=False,enrolled=True,nearby=False),0);self.assertFalse(a.away(1))
 def test_away_caps_leds_even_during_priority_and_blanks_matrix(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True)
  m.away.configured=True;m.away.accept(dict(version=1,enabled=True,enrolled=True,nearby=False),0)
  with patch.object(m.controller,"led_frame",side_effect=AssertionError("live LEDs must not override away")),patch.object(m.matrix,"away_snake") as blank,patch.object(m.expansions,"write_own_status") as eeh:
   m._write_leds();blank.assert_called_once();self.assertLessEqual(max(max(c) for c in m._last_leds),13);self.assertGreater(len(set(m._last_leds)),1);self.assertEqual(eeh.call_args.args[0],(0,0,0))

 def test_lock_screen_contains_no_call_details(self):
  from test_clocks import Canvas
  class Screen(Canvas):ARITIES=dict(Canvas.ARITIES,rectangle=4)
  module,m,hw=support.BadgeAppTests.live_monitor(True);m.away.configured=True
  m.away.accept(dict(version=1,enabled=True,enrolled=True,nearby=False),0)
  c=Screen();m.draw(c)
  self.assertEqual({word[0] for word in c.words},{"AWAY","PHONE AWAY"});self.assertEqual(c.saved,0)
 def test_buttons_do_not_queue_calls_behind_lock(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True);m.away.configured=True
  m.away.accept(dict(version=1,enabled=True,enrolled=True,nearby=False),0)
  m.update(0);support.BadgeAppTests.press(module,m,"F");self.assertIsNone(m.controls.pending)
 def test_matrix_blank_overwrites_native_mode_and_cached_zeroes(self):
  from test_matrix import MatrixTests,payload
  fixture=MatrixTests();fixture.setUp();display=fixture.display(slot=2)
  display.update(payload(),True,0);fixture.drain(display)
  fixture.backend.bus.registers[0x51:0x51+156]=bytes([255])*156
  display._known[:]=bytes([1])*156;display._actual[:]=bytes(156)
  display._native_active=True;display._text_writes=[(0x50,6)]
  self.assertTrue(display.blank(1000));fixture.drain(display)
  self.assertEqual(fixture.image(),bytes(156));self.assertEqual(display.displayed_mode,"away")
  display.update(payload(),True,2000);fixture.drain(display);self.assertNotEqual(fixture.image(),bytes(156))

 def test_rainbow_is_slow_bounded_and_keeps_zero_brightness_off(self):
  frame=away.rainbow(0);later=away.rainbow(100)
  self.assertEqual(away.rainbow(0,brightness=0),[(0,0,0)]*12)
  self.assertLessEqual(max(abs(a-b) for x,y in zip(frame,later) for a,b in zip(x,y)),1)
  self.assertTrue(all(0<=v<=13 for c in frame for v in c))

 def test_matrix_snake_moves_gently_at_half_previous_peak(self):
  from test_matrix import MatrixTests,payload
  fixture=MatrixTests();fixture.setUp();display=fixture.display(slot=2)
  self.assertTrue(display.away_snake(1000));fixture.drain(display)
  self.assertEqual(display.displayed_mode,"away_snake");self.assertIsNone(display._text_writes)
  image=fixture.image();self.assertEqual(max(image),90)
  display.away_snake(1400);fixture.drain(display);self.assertEqual(fixture.image(),image)
  display.away_snake(1450);fixture.drain(display);self.assertNotEqual(fixture.image(),image)
  self.assertTrue(all(v<=90 for v in fixture.image()))
  display.update(payload(),True,21000);fixture.drain(display);self.assertEqual(display.displayed_mode,"available")

 def test_welcome_only_on_return_not_boot_and_not_each_poll(self):
  a=away.AwayState(True);near=dict(version=1,enabled=True,enrolled=True,nearby=True)
  a.accept(near,100);self.assertFalse(a.welcoming(101))
  a.accept(dict(near,nearby=False),200);self.assertFalse(a.welcoming(201))
  a.accept(near,300);self.assertTrue(a.welcoming(301));end=a.welcome_until
  a.accept(near,800);self.assertEqual(a.welcome_until,end);self.assertFalse(a.welcoming(end))
 def test_welcome_cancels_when_away_again(self):
  a=away.AwayState(True);near=dict(version=1,enabled=True,enrolled=True,nearby=True)
  a.accept(dict(near,nearby=False),0);a.accept(near,100);self.assertTrue(a.welcoming(101));a.accept(dict(near,nearby=False),200);self.assertFalse(a.welcoming(201))
 def test_welcome_draws_once_and_calls_preempt_it(self):
  from test_clocks import Canvas
  class Screen(Canvas):ARITIES=dict(Canvas.ARITIES,rectangle=4)
  module,m,hw=support.BadgeAppTests.live_monitor(True);m.away.configured=True
  m.away.accept(dict(version=1,enabled=True,enrolled=True,nearby=False),0)
  m.away.accept(dict(version=1,enabled=True,enrolled=True,nearby=True),1)
  m._now=lambda:2
  c=Screen();m.draw(c);self.assertIn("WELCOME BACK",[x[0] for x in c.words]);self.assertEqual(c.saved,0)
  with patch.object(m.controller,"own_call",return_value={"state":"connected"}),patch.object(module,"draw_welcome") as welcome,patch.object(m,"_draw_call"):
   m.draw(Screen());welcome.assert_not_called();self.assertEqual(m.away.welcome_until,0)

 def test_snake_autoplay_eats_grows_and_avoids_walls_and_itself(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('snake_fixture',Path(__file__).resolve().parents[1]/'badge/snake.py')
  game=importlib.util.module_from_spec(spec);spec.loader.exec_module(game)
  for seed in (0,1,37,999):
   snake=game.Snake(seed)
   for i in range(3000):
    previous=snake.points()[0];snake.step();points=snake.points();head=points[0]
    self.assertEqual(abs(head[0]-previous[0])+abs(head[1]-previous[1]),1)
    self.assertEqual(len(set(points)),len(points));self.assertNotIn(snake.apple(),points)
    self.assertTrue(all(1<=x<=16 and 2<=y<=7 for x,y in points))
   self.assertGreater(snake.score,20);self.assertEqual(len(snake.body),18)
 def test_welcome_themes_render_without_bunny_callback(self):
  from test_clocks import Canvas
  class Screen(Canvas):ARITIES=dict(Canvas.ARITIES,rectangle=4)
  for theme in ('original','christmas','easter','anniversary','birthday_self','birthday_partner','cyberpunk','lcars','kitty','noir','ocean','retro','photo'):
   c=Screen();away.draw_welcome(c,1000,{'id':theme},'haute_celestial')
   self.assertIn('WELCOME BACK',[word[0] for word in c.words]);self.assertEqual(c.saved,0)
