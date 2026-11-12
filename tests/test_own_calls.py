"""Own-call takeover and observed connected duration; no telephone requests."""
import unittest
import test_badge_notifications as integration
import test_notifications as fixtures

class OwnCallTests(unittest.TestCase):
    def setup_call(self,state='dialing',direction='outbound',identity='out-1'):
        support=integration.BadgeNotificationTests()
        module,monitor,hardware=support.monitor()
        call={'id':identity,'state':state,'direction':direction,'peer_name':'Alex Example',
              'peer_number':'245','kind':'internal','priority':False}
        value=support.source(monitor,[],alert=None)
        value['own'].update(state='busy',calls=[call])
        monitor.controller.accept(value,monitor.clock_ms)
        return support,module,monitor,call

    def test_outgoing_call_automatically_takes_over_then_counts_connected_time(self):
        support,module,monitor,call=self.setup_call()
        self.assertFalse(monitor.controller.own_view)
        self.assertIn('Alex Example',support.texts(monitor))
        self.assertIn('CALLING',support.texts(monitor))
        self.assertNotIn('00:00',support.texts(monitor))
        support.advance(module,monitor,10000)
        call['state']='connected'
        value=support.source(monitor,alert=None)
        value['own']['calls']=[call]
        monitor.controller.accept(value,monitor.clock_ms)
        self.assertIn('00:00',support.texts(monitor))
        support.advance(module,monitor,65000)
        words=support.texts(monitor)
        self.assertIn('01:05',words)
        self.assertIn('OUTGOING / INTERNAL',words)
        self.assertIn('ON CALL',words)
        self.assertNotIn('245',words)

    def test_incoming_connected_hold_transfer_new_call_and_stale_cleanup(self):
        support,module,monitor,call=self.setup_call('connected','inbound')
        support.advance(module,monitor,5000)
        self.assertIn('00:05',support.texts(monitor))
        value=support.source(monitor)
        value['own']['calls'][0]['state']='held'
        monitor.controller.accept(value,monitor.clock_ms)
        support.advance(module,monitor,3000)
        self.assertIn('ON HOLD',support.texts(monitor))
        self.assertIn('00:08',support.texts(monitor))
        value=support.source(monitor)
        value['own']['calls'][0].update(id='new-call',state='connected')
        monitor.controller.accept(value,monitor.clock_ms)
        self.assertIn('00:00',support.texts(monitor))
        support.advance(module,monitor,6000,refresh=False)
        self.assertIn('OFFLINE',support.texts(monitor))
        self.assertIsNone(monitor.controller.own_call(monitor.clock_ms))

    def test_waiting_incoming_call_preempts_connected_and_urgent_rules_remain(self):
        support,module,monitor,call=self.setup_call('connected')
        waiting=dict(call,id='waiting',peer_name='New Caller',state='ringing',direction='inbound')
        value=support.source(monitor,alert=waiting)
        value['own']['calls'].append(waiting)
        monitor.controller.accept(value,monitor.clock_ms)
        self.assertIn('New Caller',support.texts(monitor))
        self.assertNotIn('Alex Example',support.texts(monitor))
        support.source(monitor,[fixtures.item(priority=5)])
        self.assertIn('URGENT',support.texts(monitor))
        waiting['priority']=True
        value=support.source(monitor,alert=waiting)
        value['own']['calls']=[call,waiting]
        monitor.controller.accept(value,monitor.clock_ms)
        self.assertNotIn('Backup completed',support.texts(monitor))

    def test_call_removed_resets_timer_and_hour_format(self):
        support,module,monitor,call=self.setup_call('connected')
        support.advance(module,monitor,3661000)
        self.assertIn('1:01:01',support.texts(monitor))
        value=support.source(monitor)
        value['own'].update(state='idle',calls=[])
        monitor.controller.accept(value,monitor.clock_ms)
        self.assertFalse(monitor.controller._connected_since)
        self.assertIsNone(monitor.controller.own_call(monitor.clock_ms))
