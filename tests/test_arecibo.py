import hashlib
import importlib.util
import re
import unittest
from pathlib import Path
from unittest.mock import patch
import test_badge as support

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('arecibo_test',ROOT/'badge/arecibo.py')
arecibo=importlib.util.module_from_spec(spec);spec.loader.exec_module(arecibo)

class AreciboTests(unittest.TestCase):
 def test_original_bits_and_both_implementations_agree(self):
  rows=(ROOT/'assets/arecibo.txt').read_text().splitlines()
  self.assertEqual(len(rows),73);self.assertTrue(all(len(r)==23 for r in rows))
  self.assertEqual(hashlib.sha256(''.join(rows).encode()).hexdigest(),'24babf56f872fc2c38c940b4a438811be454f04a041fe56b3c239662f261dd66')
  self.assertEqual(tuple(rows),arecibo.ROWS)
  cpp=[int(v,16) for v in re.findall(r'0x([0-9a-f]+)u',(ROOT/'companion/include/arecibo.h').read_text())]
  self.assertEqual(cpp,[int(r,2) for r in rows])
 def test_landscape_pan_visits_every_bit_without_downsampling(self):
  seen=set()
  for ms in range(0,56700,100):
   frame=arecibo.matrix_frame(ms,90)
   self.assertEqual(len(frame),162);self.assertEqual(max(frame[:18]),0)
   self.assertLessEqual(max(frame),90)
   head=(ms//700)%81-8;pan=(ms//500)%10;left=pan if pan<=5 else 10-pan
   for y in range(1,9):
    source=head+y-1
    if 0<=source<73:
     for x in range(18):
      self.assertEqual(bool(frame[y*18+x]),arecibo.ROWS[source][x+left]=='1')
      seen.add((x+left,source))
  self.assertEqual(len(seen),1679)
 def test_driver_uses_pwm_and_calls_preempt_it(self):
  from test_matrix import MatrixTests,payload
  fixture=MatrixTests();fixture.setUp();display=fixture.display(slot=2)
  display.arecibo(21000);fixture.drain(display)
  self.assertEqual(display.last_mode,'arecibo');self.assertEqual(display._packet[0],3)
  display.update(payload(calls=[{'id':'call','state':'ringing','kind':'internal','peer_name':'Example','peer_number':'223'}]),True,21500)
  self.assertNotEqual(display.last_mode,'arecibo')
 def test_idle_only_and_focus_call_and_away_preemption(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True)
  for member in [m.controller.payload['own']]+m.controller.payload['team']:member.update(state='idle',calls=[])
  m._observe_idle(m.clock_ms);m.idle_pages.preview(m.clock_ms)
  with patch.object(m.matrix,'arecibo') as animate,patch.object(m.matrix,'update') as normal:
   m._write_leds();animate.assert_called_once()
   m.controller.payload['own']['calls']=[{'id':'call','state':'connected'}]
   m._write_leds();self.assertEqual(animate.call_count,1);normal.assert_called()
   m.controller.payload['own']['calls']=[];m.focus.toggle(m.clock_ms)
   with patch.object(m.matrix,'focus_rain') as sand:
    m._write_leds();sand.assert_called_once();self.assertEqual(animate.call_count,1)
   with patch.object(m.away,'away',return_value=True),patch.object(m.matrix,'away_snake') as snake:
    m._write_leds();snake.assert_called_once();self.assertEqual(animate.call_count,1)
