import copy
import unittest
from unittest.mock import patch
import test_idle as scheduling
import test_badge as support
import test_badge_idle as idle_support

class OnDemandScheduleTests(unittest.TestCase):
    def test_quiet_boot_immediate_and_every_team_call_stays_visible_until_ended(self):
        idle=scheduling.idle.IdlePages(overview_on_demand=True)
        value=scheduling.snapshot()
        self.assertTrue(idle.observe(value,True,0))
        for state in ('ringing','dialing','connected','held','busy'):
            value['team'][0].update(state=state,calls=[{'id':'team','state':state}])
            self.assertFalse(idle.observe(value,True,100))
            self.assertFalse(idle.observe(value,True,1000000))
        value['team'][0].update(state='idle',calls=[])
        self.assertTrue(idle.observe(value,True,1000001))

    def test_manual_wake_expires_but_presence_and_auto_touches_do_not_wake(self):
        idle=scheduling.idle.IdlePages(overview_on_demand=True)
        value=scheduling.snapshot();idle.observe(value,True,0)
        value['own']['presence'].update(state='dnd',profile='DND')
        self.assertTrue(idle.observe(value,True,100))
        idle.touch(200)
        self.assertTrue(idle.active(200))
        idle.touch(300,manual=True)
        self.assertFalse(idle.active(60299))
        self.assertTrue(idle.active(60300))
        idle.touch(60301,manual=True)
        self.assertTrue(idle.preview(60302))
        self.assertTrue(idle.active(60302))

class OnDemandAppTests(unittest.TestCase):
    def monitor(self):
        module,monitor,hardware=support.BadgeAppTests.live_monitor(True,True)
        self.assertTrue(module.DEFAULT_CONFIG['overview_on_demand'])
        value=copy.deepcopy(monitor.controller.payload)
        for member in value['team']:member.update(state='idle',calls=[])
        value['own'].update(state='idle',calls=[])
        value.update(alert=None,notifications=[])
        monitor.config['partner_name']='Keziah'
        monitor.controller.accept(value,monitor.clock_ms)
        monitor.update(0)
        return module,monitor,hardware

    def test_default_is_idle_first_key_only_wakes_then_d_queues_partner(self):
        module,monitor,hardware=self.monitor()
        self.assertTrue(monitor.idle_pages.active(monitor.clock_ms))
        with patch.object(module,'send_control') as send:
            monitor.expansions.keys=['D'];monitor.update(0)
            self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
            self.assertIsNone(monitor.controls.pending)
            canvas=support.RecordingCanvas();monitor.draw(canvas)
            self.assertIn('Keziah',[r['text'] for r in canvas.records])
            monitor.expansions.keys=['D'];monitor.update(0)
            self.assertEqual(monitor.controls.pending['target'],'kz')
            send.assert_not_called()

    def test_first_badge_speed_dial_key_wakes_without_call_and_timeout_returns_idle(self):
        module,monitor,hardware=self.monitor()
        support.BadgeAppTests.press(module,monitor,'E')
        self.assertIsNone(monitor.controls.pending)
        self.assertFalse(monitor.controller.own_view)
        support.BadgeAppTests.release(module,monitor)
        idle_support.BadgeIdleTests.advance(module,monitor,60000)
        self.assertTrue(monitor.idle_pages.active(monitor.clock_ms))

    def test_team_connection_prevents_idle_and_finishing_restores_it_without_key(self):
        module,monitor,hardware=self.monitor()
        value=copy.deepcopy(monitor.controller.payload)
        value['team'][0].update(state='busy',calls=[{'id':'team','state':'connected','kind':'internal','peer_number':'245'}])
        monitor.controller.accept(value,monitor.clock_ms)
        monitor.update(0)
        idle_support.BadgeIdleTests.advance(module,monitor,120000)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        value=copy.deepcopy(monitor.controller.payload)
        value['team'][0].update(state='idle',calls=[])
        monitor.controller.accept(value,monitor.clock_ms)
        monitor.update(0)
        self.assertTrue(monitor.idle_pages.active(monitor.clock_ms))
