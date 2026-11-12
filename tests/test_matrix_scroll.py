import unittest
import test_matrix as fixture
payload, matrix = fixture.payload, fixture.matrix


class ScrollTests(unittest.TestCase):
    setUp = fixture.MatrixTests.setUp
    display = fixture.MatrixTests.display
    drain = fixture.MatrixTests.drain
    image = fixture.MatrixTests.image
    def call(self, name='Alex Example', identity='a'):
        return payload(calls=[{'id':identity,'peer_name':name,'state':'ringing','direction':'inbound'}])

    def test_name_scrolls_after_initial_hold_within_brightness(self):
        display=self.display(brightness=.03,call_brightness=.03)
        value=self.call()
        display.update(value,True,0)
        self.drain(display)
        first=self.image()
        display.update(value,True,999)
        self.assertEqual(display._scroll_position,0)
        display.update(value,True,1000)
        self.drain(display)
        self.assertEqual(display._scroll_position,1)
        self.assertNotEqual(first,self.image())
        self.assertLessEqual(max(self.image()),7)

    def test_slow_transfer_retains_every_column_and_new_caller_preempts(self):
        display=self.display()
        display.update(self.call(),True,0)
        import asyncio
        asyncio.run(display.flush())
        for now in (1000,2000,3000):
            display.update(self.call(),True,now)
            self.assertEqual(display._scroll_position,0)
        display.update(self.call('Jo Example','b'),True,3001)
        self.assertEqual(display._scroll_position,0)
        self.assertEqual(display._scroll_key,('b','JO EXAMPLE'))
        self.drain(display)
        display.update(self.call('Jo Example','b'),True,4000)
        self.assertEqual(display._scroll_position,0)
        display.update(self.call('Jo Example','b'),True,4001)
        self.assertEqual(display._scroll_position,1)

    def test_partner_heart_and_stale_answered_cancel_text(self):
        display=self.display()
        value=self.call()
        for live,partner,expected in ((True,False,'caller'),(True,True,'heart'),(False,True,'unknown')):
            display.update(value,live,0,partner=partner)
            self.drain(display)
            self.assertEqual(display.displayed_mode,expected)
        value['own']['calls'][0]['state']='connected'
        display.update(value,True,2000)
        self.drain(display)
        self.assertEqual(display.displayed_mode,'busy')
        self.assertIsNone(display._scroll_key)

    def test_text_is_bounded_normalized_and_unknown_never_scrolls_numbers(self):
        self.assertEqual(matrix.caller_text('José O’Neill'),'JOSE O\'NEILL')
        self.assertEqual(matrix.caller_text('+441632960123'),'INCOMING CALL')
        self.assertEqual(matrix.caller_text('Unknown caller'),'INCOMING CALL')
        self.assertLessEqual(len(matrix.caller_text('A'*10000)),48)
        self.assertLessEqual(len(matrix.columns('A'*10000)),306)
        self.assertTrue(all(0 <= value <128 for value in matrix.columns('AB')))

    def test_another_ringing_caller_preempts_a_connected_partner_heart(self):
        import copy
        from unittest.mock import patch
        from test_theme_integration import ThemeIntegrationTests
        fixture=ThemeIntegrationTests()
        module, monitor, _, _=fixture.monitor()
        fixture.incoming(monitor)
        value=copy.deepcopy(monitor.controller.payload)
        partner=value['own']['calls'][0]
        partner['state']='connected'
        caller=dict(partner,id='new',peer_name='Alex Example',peer_number='+441632960123',state='ringing')
        value['own']['calls']=[partner,caller]
        value['alert']=caller
        monitor.controller.accept(value,monitor.clock_ms)
        with patch.object(monitor.matrix,'update') as update:
            monitor._write_leds()
        self.assertFalse(update.call_args.kwargs['partner'])

    def test_call_brightness_defaults_full_and_returns_to_idle_level(self):
        display=self.display(brightness=.03)
        display.update(self.call(),True,0)
        self.drain(display)
        self.assertEqual(max(self.image()),255)
        display.update(payload(),True,2000)
        self.drain(display)
        self.assertLessEqual(max(self.image()),7)
        display.call_brightness=0
        display.update(self.call(),True,3000)
        self.drain(display)
        self.assertEqual(max(self.image()),0)

    def test_matrix_call_setting_saves_and_restores_without_phone_actions(self):
        import sys
        from unittest.mock import patch
        from test_theme_integration import ThemeIntegrationTests
        fixture=ThemeIntegrationTests()
        module, monitor, _, settings=fixture.monitor(saved={'threecx_monitor.matrix_call_brightness':.6})
        self.assertEqual(monitor.matrix.call_brightness,.6)
        monitor._open_settings()
        monitor.settings_selected=4
        with patch.dict(sys.modules,{'settings':settings}), patch.object(module,'post_json') as post:
            monitor._settings_key('RIGHT')
            self.assertEqual(monitor.matrix.call_brightness,.65)
            words=[item['text'] for item in fixture.draw(monitor)]
            self.assertIn('MATRIX CALL',words)
            self.assertIn('65%',words)
            monitor._settings_key('ENTER')
            self.assertEqual(settings.values['threecx_monitor.matrix_call_brightness'],.65)
            post.assert_not_called()
