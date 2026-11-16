"""Button-driven notification tests use a distinct sender token and never call PBX routes."""
import asyncio,sys,types,unittest
from unittest.mock import patch
import test_badge as support

class NotificationButtonTests(unittest.TestCase):
    def monitor(self):
        module,monitor,hw=support.BadgeAppTests.live_monitor(True)
        monitor.config.update(device_role='phone_clock',notify_token='n'*32)
        return module,monitor,hw
    def test_menu_select_queues_one_test_without_phone_action(self):
        module,m,unused=self.monitor();m._open_menu();m.menu_selected=2;m._menu_key('C')
        self.assertFalse(m.menu_open);self.assertEqual(m.controls.pending['action'],'notify')
        self.assertNotIn('target',m.controls.pending);self.assertNotIn('enabled',m.controls.pending)
        self.assertFalse(m.notifications_open)
    def test_held_menu_select_never_becomes_a_speed_dial(self):
        module,m,unused=self.monitor();m._open_menu();m.menu_selected=2;m.update(0)
        support.BadgeAppTests.press(module,m,'C')
        self.assertEqual(m.controls.take()['action'],'notify');m.controls.finish({'status':'accepted'},m.clock_ms)
        for unused in range(5):
            module.time.now+=400;m.update(400)
        self.assertIsNone(m.controls.pending)
    def test_keyboard_n_queues_the_same_test(self):
        module,m,unused=self.monitor();m.expansions.keys=['N'];m.update(0)
        self.assertEqual(m.controls.pending['action'],'notify')
    def test_test_requires_separate_token_and_is_off_in_demo(self):
        for token,demo in [('',False),('bad',False),('n'*32,True)]:
            module,m,unused=self.monitor();m.config['notify_token']=token;m.demo_mode=demo;m._open_notifications()
            self.assertIsNone(m.controls.pending)
    def test_sender_selects_only_fixed_notification_route_and_static_body(self):
        module,m,unused=self.monitor();m._open_notifications();intent=m.controls.take()
        with patch.object(module,'post_json',return_value={'status':'accepted'}) as post:
            module.send_notification_test('https://bridge/','notify-only',intent,'ca.der')
        args,kw=post.call_args;self.assertEqual(args[:2],('https://bridge/v1/notify','notify-only'))
        self.assertEqual(args[2]['ttl_seconds'],30);self.assertEqual(args[2]['priority'],3)
        self.assertNotIn('target',args[2]);self.assertEqual(kw['ca_file'],'ca.der')
    def test_no_auto_retry_cooldown_and_new_press_gets_new_id(self):
        module,m,unused=self.monitor();m._open_notifications();first=m.controls.take();m.controls.fail_unknown(m.clock_ms)
        self.assertIsNone(m.controls.take());m._open_notifications();self.assertIsNone(m.controls.pending)
        m.clock_ms+=5001;m._open_notifications();self.assertNotEqual(m.controls.pending['id'],first['id'])

class NotificationButtonWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_uses_notify_token_once_and_never_phone_sender(self):
        module,m,unused=NotificationButtonTests().monitor();m._open_notifications();value=m.controller.payload
        wifi=types.SimpleNamespace(status=lambda:True)
        async def unblock(fn,periodic,*args):return fn(*args)
        async def no_sleep(delay):return None
        def snapshot(*args):m._stopping=True;return value
        with patch.dict(sys.modules,{'wifi':wifi,'async_helpers':types.SimpleNamespace(unblock=unblock)}), \
             patch.object(module,'asyncio',types.SimpleNamespace(sleep=no_sleep,create_task=asyncio.create_task,CancelledError=asyncio.CancelledError)), \
             patch.object(module,'send_notification_test',return_value={'status':'accepted'}) as send, \
             patch.object(module,'send_control') as phone,patch.object(module,'fetch_snapshot',side_effect=snapshot):
            await m.background_task()
        self.assertEqual(send.call_count,1);self.assertEqual(send.call_args.args[1],'n'*32);phone.assert_not_called()
        self.assertFalse(m.controls.is_busy);self.assertEqual(m.controls.message,'')
