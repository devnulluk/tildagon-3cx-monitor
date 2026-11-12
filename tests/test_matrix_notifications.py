import unittest
import test_matrix as fixture

class MatrixNotificationTests(unittest.TestCase):
    setUp=fixture.MatrixTests.setUp
    display=fixture.MatrixTests.display
    drain=fixture.MatrixTests.drain

    def test_notification_loads_title_body_then_scrolls_without_reloading(self):
        display=self.display()
        value=fixture.payload()
        value['_matrix_notification']={'id':'notice','title':'Build complete','body':'Everything saved','priority':3}
        display.update(value,True,0);self.drain(display)
        self.assertEqual(display.displayed_mode,'notification')
        self.assertEqual(display._text_identity[1],'Build complete - Everything saved')
        self.assertEqual(self.backend.bus.registers[0x50],0)
        count=len(self.backend.bus.frames)
        display.update(value,True,790);self.drain(display)
        self.assertEqual([row[1] for row in self.backend.bus.frames[count:]],[0x39])
        value.pop('_matrix_notification')
        display.update(value,True,1000);self.drain(display)
        self.assertEqual(display.displayed_mode,'available')

    def test_long_notification_is_bounded_to_real_ascii_register_buffer(self):
        display=self.display()
        value=fixture.payload()
        item={'id':'long','title':'Urgént','body':'x'*10000,'priority':5,'progress':75}
        value['_matrix_notification']=item
        display.update(value,True,0);self.drain(display)
        self.assertEqual(len(display._text_identity[1]),155)
        self.assertTrue(display._text_identity[1].startswith('URGENT: Urgent'))
        self.assertEqual(self.backend.bus.registers[0xEC],0)
        self.assertLessEqual(max(row[1] for row in self.backend.bus.frames),0xEC)
