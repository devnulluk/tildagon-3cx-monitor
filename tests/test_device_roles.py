"""Split-device behaviour through the actual badge app with fake hardware."""
import unittest
from unittest.mock import patch
import test_badge_notifications as support
import test_notifications as fixtures

class DeviceRolesTests(unittest.TestCase):
    monitor=support.BadgeNotificationTests.monitor
    source=support.BadgeNotificationTests.source
    texts=support.BadgeNotificationTests.texts
    advance=support.BadgeNotificationTests.advance
    # Inherit fixture helpers without repeating the legacy test cases.
    def test_role_keeps_clock_visible_while_urgent_drives_leds(self):
        module,monitor,hardware=self.monitor()
        monitor.config['device_role']='phone_clock'
        self.source(monitor,[fixtures.item(priority=5)])
        monitor.update(0)
        self.assertIsNone(monitor._visible_notification(monitor.clock_ms))
        self.assertEqual(monitor.idle_pages.pages,['clock'])
        self.assertNotIn('Backup completed',self.texts(monitor))
        with patch.object(monitor.expansions,'write_own_status') as write:
            monitor._write_leds()
            self.assertEqual(hardware.leds[1:13],[(255,0,0)]*12)
            self.assertFalse(write.call_args.kwargs['heartbeat'])
        monitor._open_notifications()
        self.assertFalse(monitor.notifications_open)

    def test_priority_phone_call_overrides_notification_lighting(self):
        module,monitor,hardware=self.monitor()
        monitor.config['device_role']='phone_clock'
        call={'state':'ringing','direction':'inbound','kind':'internal','priority':True,'peer_name':'Priority caller','peer_number':'245'}
        value=self.source(monitor,[fixtures.item(priority=5)],alert=call)
        value['own'].update(state='ringing',calls=[call])
        monitor.update(0);monitor._write_leds()
        self.assertEqual(hardware.leds[1:13],monitor.controller.led_frame(monitor.clock_ms))
        self.assertNotIn('Backup completed',self.texts(monitor))

    def test_normal_notification_lights_do_not_open_or_pause_clock(self):
        module,monitor,hardware=self.monitor()
        monitor.config['device_role']='phone_clock'
        self.source(monitor,[fixtures.item()]);monitor.update(0)
        monitor._write_leds()
        self.assertNotEqual(hardware.leds[1:13],monitor.controller.led_frame(monitor.clock_ms))
        self.assertIsNone(monitor._visible_notification(monitor.clock_ms))
        self.assertFalse(monitor.notifications_open)
        self.assertEqual(monitor.idle_pages.pages,['clock'])
