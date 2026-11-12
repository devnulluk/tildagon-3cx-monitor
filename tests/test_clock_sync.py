import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('clock_sync_fixture', Path(__file__).resolve().parents[1] / 'badge/clock_sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class ClockSyncTests(unittest.TestCase):
    def test_connect_retry_cooldown_success_and_reconnect(self):
        state = sync.ClockSync()
        with patch.object(sync, 'clock_valid', return_value=True):
            self.assertTrue(state.due(0))
            state.attempted(0, False)
            self.assertFalse(state.due(59999))
            self.assertTrue(state.due(60000))
            state.attempted(60000, True)
            self.assertFalse(state.due(120000))
            state.disconnected()
            self.assertTrue(state.due(120001))

    def test_lost_clock_is_repaired_after_prior_success(self):
        state = sync.ClockSync()
        state.due(0)
        state.attempted(0, True)
        with patch.object(sync, 'clock_valid', return_value=False):
            self.assertFalse(state.due(10))
            self.assertTrue(state.due(60000))

    def test_ntp_failure_is_reported_without_exception(self):
        ntp = types.SimpleNamespace(settime=lambda: (_ for _ in ()).throw(OSError()))
        with patch.dict(sys.modules, {'ntptime': ntp}):
            self.assertFalse(sync.sync_clock())

    def test_ntp_success_requires_a_valid_resulting_clock(self):
        calls = []
        with patch.dict(sys.modules, {'ntptime': types.SimpleNamespace(settime=lambda: calls.append(True))}):
            for valid in (True, False):
                with patch.object(sync, 'clock_valid', return_value=valid):
                    self.assertEqual(sync.sync_clock(), valid)
        self.assertEqual(len(calls), 2)

    def test_invalid_dates_are_rejected(self):
        for year, valid in ((2000, False), (2026, True), (2100, False)):
            with patch.object(sync.time, 'gmtime', return_value=(year,)):
                self.assertEqual(sync.clock_valid(), valid)
