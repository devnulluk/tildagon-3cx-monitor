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

    def test_native_name_loads_ascii_then_only_updates_scroll_offset(self):
        display=self.display()
        value=self.call()
        display.update(value,True,0)
        self.drain(display)
        registers=self.backend.bus.registers
        self.assertEqual(registers[0x50],0)
        self.assertEqual(registers[0x37:0x3B],bytes([3,0,18,1]))
        self.assertEqual(registers[0x51:0x5E],b'ALEX EXAMPLE\0')
        first=len(self.backend.bus.frames)
        display.update(value,True,700)
        self.assertEqual(display._scroll_position,18)
        display.update(value,True,790)
        self.drain(display)
        self.assertEqual(display._scroll_position,19)
        self.assertEqual(self.backend.bus.frames[first:],[(0x20,0x39,b'\x13')])

    def test_internal_initials_are_centred_static_and_caller_changes_preempt(self):
        display=self.display(call_brightness=.25)
        value=self.call('Alex Example')
        value['own']['calls'][0]['kind']='internal'
        display.update(value,True,0)
        self.drain(display)
        first=self.image()
        self.assertEqual(display._scroll_key,('a','AE','initials'))
        self.assertEqual(len(display._scroll_columns),18)
        letters=matrix.columns('AE')[:11]
        self.assertEqual(display._scroll_columns,(0,)*3+letters+(0,)*4)
        frames=display.frames_written
        for now in (1000,2000,10000,60000):
            display.update(value,True,now)
            self.drain(display)
            self.assertEqual(display._scroll_position,0)
            self.assertEqual(self.image(),first)
        self.assertEqual(display.frames_written,frames)
        value['own']['calls'][0].update(id='b',peer_name='Jo Example')
        display.update(value,True,60001)
        self.drain(display)
        self.assertNotEqual(self.image(),first)
        self.assertEqual(max(self.image()),63)

    def test_internal_three_letter_name_or_extension_fits_without_scrolling(self):
        for name,number,expected in (('Alex Example Smith','245','AES'),('', '245','245'),('TB','223','TB')):
            display=self.display(call_brightness=.25)
            value=self.call(name)
            value['own']['calls'][0].update(kind='internal',peer_extension=number)
            display.update(value,True,0)
            self.drain(display)
            self.assertEqual(display._scroll_key[1],expected)
            self.assertEqual(len(display._scroll_columns),18)

    def test_slow_text_load_is_blank_until_complete_and_new_caller_preempts(self):
        display=self.display()
        value=self.call('Alex Example '*4)
        display.update(value,True,0)
        import asyncio
        asyncio.run(display.flush())
        for now in (1000,2000,3000):
            display.update(value,True,now)
            self.assertEqual(display._scroll_position,18)
            self.assertEqual(self.backend.bus.registers[0x51],0)
        display.update(self.call('Jo Example','b'),True,3001)
        self.assertEqual(display._scroll_position,18)
        self.assertEqual(display._scroll_key,('b','JO EXAMPLE','native'))
        self.drain(display)
        self.assertEqual(self.backend.bus.registers[0x51:0x5C],b'JO EXAMPLE\0')
        display.update(self.call('Jo Example','b'),True,3701)
        self.assertEqual(display._scroll_position,18)
        display.update(self.call('Jo Example','b'),True,3791)
        self.assertEqual(display._scroll_position,19)

    def test_native_text_handoff_to_dim_heart_and_offline_restores_pwm(self):
        display=self.display()
        value=self.call()
        for scene in ('dim','heart','offline'):
            display.call_brightness=1.0
            display.update(value,True,0)
            self.drain(display)
            self.assertEqual(self.backend.bus.registers[0x50],0)
            display.call_brightness=.25 if scene=='dim' else 1.0
            display.update(value,scene!='offline',1000,partner=scene=='heart')
            self.drain(display)
            self.assertEqual(self.backend.bus.registers[0x50],3)
            self.assertIsNone(display._text_identity)
            if scene=='dim':self.assertLessEqual(max(self.image()),63)

    def test_native_offset_is_big_endian_and_ascii_is_bounded(self):
        display=self.display()
        value=self.call('Long '*10000)
        display.update(value,True,0)
        self.drain(display)
        self.assertLessEqual(len(display._text_identity[1]),48)
        count=len(self.backend.bus.frames)
        display.update(value,True,700+240*90)
        self.drain(display)
        self.assertEqual(self.backend.bus.registers[0x38:0x3A],b'\x01\x02')
        self.assertEqual([f[1] for f in self.backend.bus.frames[count:]],[0x38,0x39])

    def test_native_name_that_fits_stays_centred_without_offset_traffic(self):
        display=self.display()
        value=self.call('TB')
        display.update(value,True,0)
        self.drain(display)
        self.assertEqual(self.backend.bus.registers[0x39],15)
        count=len(self.backend.bus.frames)
        for now in (1000,2000,10000):
            display.update(value,True,now)
            self.drain(display)
        self.assertEqual(len(self.backend.bus.frames),count)

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
        self.assertEqual(display.displayed_mode,'call_name')

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
        self.assertEqual(display.call_brightness,1.0)
        self.assertEqual(self.backend.bus.registers[0x50],0)
        self.assertEqual(self.backend.bus.registers[0x37],3)
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
