"""Native text protocol produces changing glyphs in the simulator I2C sink."""
import importlib.util
from pathlib import Path
import unittest
import test_matrix as fixture

spec=importlib.util.spec_from_file_location('liteloop_sim',Path(__file__).resolve().parents[1]/'simulator/liteloop.py')
liteloop=importlib.util.module_from_spec(spec);spec.loader.exec_module(liteloop)

class NativeSimulatorTests(unittest.TestCase):
    def test_real_adapter_ascii_and_offsets_render_changing_names(self):
        backend=fixture.Backend();backend.bus=liteloop.MatrixSink()
        display=fixture.matrix.MatrixDisplay({'matrix':{}},backend)
        value=fixture.payload(calls=[{'id':'native','state':'ringing','direction':'inbound','peer_name':'Alex Example'}])
        signatures=[]
        async def drain():
            for unused in range(10):
                if not display.pending:break
                await display.flush()
        import asyncio
        for now in (0,790,880,970,1060,1150):
            display.update(value,True,now);asyncio.run(drain())
            image=backend.bus.image(fixture.matrix.GRID)
            self.assertEqual(len(image),156)
            self.assertEqual(max(image),255)
            signatures.append(bytes(image))
        self.assertEqual(len(set(signatures)),6)
