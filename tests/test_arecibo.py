import hashlib
import importlib.util
import re
import unittest
from pathlib import Path
from unittest.mock import patch
import test_badge as support

ROOT=Path(__file__).resolve().parents[1]
class AreciboTests(unittest.TestCase):
 def test_original_bits_and_both_implementations_agree(self):
  rows=(ROOT/'assets/arecibo.txt').read_text().splitlines()
  self.assertEqual(len(rows),73);self.assertTrue(all(len(r)==23 for r in rows))
  self.assertEqual(hashlib.sha256(''.join(rows).encode()).hexdigest(),'24babf56f872fc2c38c940b4a438811be454f04a041fe56b3c239662f261dd66')
  cpp=[int(v,16) for v in re.findall(r'0x([0-9a-f]+)u',(ROOT/'companion/include/arecibo.h').read_text())]
  self.assertEqual(cpp,[int(r,2) for r in rows])
 def test_matrix_idle_uses_normal_scene(self):
  module,m,hw=support.BadgeAppTests.live_monitor(True)
  for member in [m.controller.payload['own']]+m.controller.payload['team']:member.update(state='idle',calls=[])
  m._observe_idle(m.clock_ms);m.idle_pages.preview(m.clock_ms)
  with patch.object(m.matrix,'update') as normal:
   m._write_leds();normal.assert_called_once()
  self.assertFalse(hasattr(m.matrix,'arecibo'))
