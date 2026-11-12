import unittest
import test_matrix as fixture
from test_matrix_native_simulator import liteloop

class ConnectedMatrixTests(unittest.TestCase):
    def display(self,name='TB',number='223'):
        backend=fixture.Backend();backend.bus=liteloop.MatrixSink()
        display=fixture.matrix.MatrixDisplay({'matrix':{'call_brightness':.1}},backend)
        value=fixture.payload(calls=[{'id':'call-1','state':'connected','direction':'outbound',
             'peer_name':name,'peer_number':number,'elapsed_seconds':65}])
        return display,backend,value

    def drain(self,display):
        import asyncio
        async def run():
            for unused in range(12):
                if not display.pending:return
                await display.flush()
            self.fail('Pending matrix goal did not commit')
        asyncio.run(run())

    def test_connected_name_timer_name_cycle_full_brightness_and_compact_timer(self):
        display,backend,value=self.display()
        display.update(value,True,0,partner=True);self.drain(display)
        self.assertEqual(display.displayed_mode,'call_name')
        self.assertEqual(backend.bus.registers[0x51:0x54],b'TB\0')
        self.assertEqual(max(backend.bus.image(fixture.matrix.GRID)),255)
        display.update(value,True,5000,partner=True);self.drain(display)
        self.assertEqual(display.displayed_mode,'call_timer')
        self.assertEqual(display._text_identity,('call-1','0105','timer'))
        self.assertEqual(backend.bus.registers[0x50],2)
        self.assertEqual(max(backend.bus.image(fixture.matrix.GRID)),255)
        before=bytes(backend.bus.registers[0x51:0x65])
        value['own']['calls'][0]['elapsed_seconds']=66
        display.update(value,True,6000);self.drain(display)
        after=bytes(backend.bus.registers[0x51:0x65])
        self.assertNotEqual(before,after)
        self.assertLessEqual(sum(a!=b for a,b in zip(before,after)),5)
        display.update(value,True,10000);self.drain(display)
        self.assertEqual(display.displayed_mode,'call_name')
        self.assertEqual(backend.bus.registers[0x50],0)
        self.assertEqual(backend.bus.registers[0x51:0x54],b'TB\0')

    def test_unknown_names_show_number_and_new_call_restarts_name_phase(self):
        display,backend,value=self.display('Unknown caller','+441632960123')
        display.update(value,True,0);self.drain(display)
        self.assertEqual(display._text_identity[1],'+441632960123')
        value['own']['calls'][0].update(id='new-call',peer_name='PD',peer_number='268')
        display.update(value,True,15000);self.drain(display)
        self.assertEqual(display.displayed_mode,'call_name')
        self.assertEqual(display._text_identity[:2],('new-call','PD'))

    def test_call_waiting_and_offline_preempt_timer_then_idle_restores_brightness(self):
        display,backend,value=self.display()
        display.update(value,True,0);self.drain(display)
        display.update(value,True,5000);self.drain(display)
        value['own']['calls'].append({'id':'waiting','state':'ringing','direction':'inbound','peer_name':'New caller'})
        display.update(value,True,5100);self.drain(display)
        self.assertEqual(display.displayed_mode,'caller')
        display.update(value,False,5200);self.drain(display)
        self.assertEqual(display.displayed_mode,'unknown')
        display.update(fixture.payload(),True,5300);self.drain(display)
        self.assertLessEqual(max(backend.bus.image(fixture.matrix.GRID)),38)

    def test_timer_has_readable_colon_and_hour_fallback(self):
        digits,bits=fixture.matrix.timer_bits(5999,fixture.matrix.GRID)
        self.assertEqual(digits,'9959')
        self.assertEqual(len(bits),20)
        for y in (3,5):
            index=fixture.matrix.GRID[y*18+8]
            self.assertTrue(bits[index//8]&(128>>(index%8)))
        self.assertEqual(fixture.matrix.timer_bits(6000,fixture.matrix.GRID)[0],'0140')
