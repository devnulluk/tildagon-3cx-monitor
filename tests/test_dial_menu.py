import copy
import unittest
from unittest.mock import patch
import test_badge as support
import test_on_demand as demand
import test_badge_notifications as notices
import test_notifications as notice_items

class DialMenuTests(unittest.TestCase):
    def test_five_equal_tiles_include_wife_name_corner_crown_and_button_labels(self):
        module,monitor,hardware=demand.OnDemandAppTests().monitor()
        monitor.expansions.keys=['SPACE'];monitor.update(0)
        canvas=support.RecordingCanvas()
        with patch.object(module,'speed_card',wraps=module.speed_card) as card:
            monitor.draw(canvas)
        self.assertEqual(card.call_count,5)
        self.assertTrue(card.call_args_list[-1].kwargs['crowned'])
        words={item['text'] for item in canvas.records}
        self.assertTrue({'F','TB','B','PD','E','JH','C','SM','D','Keziah','A MENU'}<=words)
        wife=next(item for item in canvas.records if item['text']=='Keziah')
        self.assertLessEqual(wife['size'],26)

    def test_every_badge_mapping_with_and_without_keyboard_and_a_is_menu(self):
        for keyboard in (False,True):
            for key,target in (('F','tb'),('B','pd'),('E','jh'),('C','sm'),('D','kz')):
                with self.subTest(key=key,keyboard=keyboard):
                    module,monitor,unused=support.BadgeAppTests.live_monitor(keyboard)
                    with patch.object(module,'send_control') as send:
                        support.BadgeAppTests.press(module,monitor,key)
                        self.assertEqual(monitor.controls.pending['target'],target)
                        send.assert_not_called()
            module,monitor,unused=support.BadgeAppTests.live_monitor(keyboard)
            support.BadgeAppTests.press(module,monitor,'A')
            self.assertTrue(monitor.menu_open)
            self.assertIsNone(monitor.controls.pending)

    def test_space_opens_then_closes_even_during_team_call_until_new_activity(self):
        module,monitor,unused=demand.OnDemandAppTests().monitor()
        for expected in (False,True):
            monitor.expansions.keys=['SPACE'];monitor.update(0)
            self.assertEqual(monitor.idle_pages.active(monitor.clock_ms),expected)
            self.assertFalse(monitor.controller.own_view)
        value=copy.deepcopy(monitor.controller.payload)
        value['team'][0].update(state='busy',calls=[{'id':'t1','state':'connected'}])
        monitor.controller.accept(value,monitor.clock_ms);monitor.update(0)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        monitor.expansions.keys=['SPACE'];monitor.update(0)
        self.assertTrue(monitor.idle_pages.active(monitor.clock_ms))
        monitor.controller.accept(copy.deepcopy(value),monitor.clock_ms);monitor.update(0)
        self.assertTrue(monitor.idle_pages.active(monitor.clock_ms))
        value['team'][0]['calls'][0]['id']='t2'
        monitor.controller.accept(value,monitor.clock_ms);monitor.update(0)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))

    def test_menu_dnd_selection_is_explicit_and_never_queues_speed_dial(self):
        module,monitor,unused=demand.OnDemandAppTests().monitor()
        monitor.expansions.keys=['A'];monitor.update(0)
        self.assertTrue(monitor.menu_open)
        for key in ('DOWN','ENTER'):
            monitor.expansions.keys=[key];monitor.update(0)
        self.assertFalse(monitor.menu_open)
        self.assertEqual(monitor.controls.pending['action'],'dnd')
        self.assertNotIn('target',monitor.controls.pending)

    def test_menu_settings_and_priority_call_precedence(self):
        module,monitor,unused=demand.OnDemandAppTests().monitor()
        monitor.expansions.keys=['A'];monitor.update(0)
        for key in ('DOWN','DOWN','DOWN','ENTER'):
            monitor.expansions.keys=[key];monitor.update(0)
        self.assertTrue(monitor.settings_open)
        self.assertIsNone(monitor.controls.pending)
        monitor.settings_open=False;monitor._open_menu()
        incoming={'id':'incoming','state':'ringing','direction':'inbound','priority':True,
                  'peer_name':'Priority caller','peer_number':'245','kind':'internal'}
        value=copy.deepcopy(monitor.controller.payload)
        value.update(alert=incoming);value['own'].update(state='ringing',calls=[incoming])
        monitor.controller.accept(value,monitor.clock_ms)
        canvas=support.RecordingCanvas();monitor.draw(canvas)
        self.assertIn('Priority caller',[item['text'] for item in canvas.records])
        self.assertNotIn('MENU',[item['text'] for item in canvas.records])
        monitor._menu_key('ENTER')
        self.assertIsNone(monitor.controls.pending)

    def test_menu_close_consumes_frame_and_sensor_confirm_cannot_change_dnd(self):
        module,monitor,unused=demand.OnDemandAppTests().monitor()
        monitor._open_menu();monitor.menu_selected=1
        monitor.expansions.keys=['A','ENTER'];monitor.update(0)
        self.assertFalse(monitor.menu_open)
        self.assertIsNone(monitor.controls.pending)
        monitor._open_menu();monitor.menu_selected=1
        with patch.object(monitor.space_inputs,'pop',return_value=[{'kind':'joystick','action':'confirm'}]):
            monitor.update(0)
        self.assertTrue(monitor.menu_open)
        self.assertIsNone(monitor.controls.pending)
        monitor.expansions.keys=['ENTER'];monitor.update(0)
        self.assertEqual(monitor.controls.pending['action'],'dnd')

    def test_notification_matrix_priority_matches_calls_and_does_not_mutate_snapshot(self):
        fixture=notices.BadgeNotificationTests()
        module,monitor,unused=fixture.monitor()
        fixture.source(monitor,[notice_items.item()])
        monitor.update(0)
        with patch.object(monitor.matrix,'update') as update:
            monitor._write_leds()
            self.assertEqual(update.call_args.args[0]['_matrix_notification']['id'],'fixture-1')
            self.assertNotIn('_matrix_notification',monitor.controller.payload)
            call={'id':'own','state':'connected','direction':'outbound','peer_name':'Alex','priority':False}
            value=fixture.source(monitor)
            value['own'].update(state='busy',calls=[call]);monitor.controller.accept(value,monitor.clock_ms)
            monitor._write_leds()
            self.assertNotIn('_matrix_notification',update.call_args.args[0])
            fixture.source(monitor,[notice_items.item(priority=5)])
            monitor._write_leds()
            self.assertIn('_matrix_notification',update.call_args.args[0])
            monitor.controller.payload['own']['calls'][0]['priority']=True
            monitor._write_leds()
            self.assertNotIn('_matrix_notification',update.call_args.args[0])
