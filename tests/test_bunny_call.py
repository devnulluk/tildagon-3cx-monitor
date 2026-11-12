import math
import unittest
import test_theme_integration as fixtures
from test_clocks import Canvas


class BunnyCanvas(Canvas):
    ARITIES = dict(Canvas.ARITIES, scale=2)


class BunnyCallTests(unittest.TestCase):
    def test_partner_name_surname_replace_initials_and_number(self):
        fixture = fixtures.ThemeIntegrationTests()
        module, monitor, _, _ = fixture.monitor(config={'partner_name': 'Partner', 'partner_surname': 'Example'})
        fixture.incoming(monitor)
        records = fixture.draw(monitor)
        words = [item['text'] for item in records]
        self.assertIn('Partner', words)
        self.assertIn('Example', words)
        self.assertNotIn('KZ', words)
        self.assertNotIn('MB', words)
        self.assertFalse(any('7700' in word for word in words))

    def test_known_caller_uses_full_name_and_unknown_caller_keeps_number(self):
        fixture = fixtures.ThemeIntegrationTests()
        for name, known in (('Alex Example', True), ('Unknown caller', False), ('', False)):
            module, monitor, _, _ = fixture.monitor()
            fixture.incoming(monitor, number='+441632960123', name=name)
            words = [item['text'] for item in fixture.draw(monitor)]
            self.assertEqual(name in words, known if name else False)
            digits = ''.join(word for word in words if word and all(c in '+0123456789' for c in word))
            self.assertEqual(digits, '' if known else '+441632960123')
            self.assertNotIn('MB', words)

    def test_waving_bunny_moves_blinks_and_restores_native_canvas(self):
        fixture = fixtures.ThemeIntegrationTests()
        module, _, _, _ = fixture.monitor()
        canvases = []
        for tick in (0, 300, 3500):
            canvas = BunnyCanvas()
            module.draw_bunny(canvas, tick)
            self.assertEqual(canvas.saved, 0)
            self.assertLess(sum(name in ('fill', 'stroke', 'text') for name, args in canvas.operations), 60)
            for name, args in canvas.operations:
                self.assertTrue(all(not isinstance(value, (int, float)) or math.isfinite(value) for value in args))
            canvases.append(canvas.operations)
        self.assertNotEqual(canvases[0], canvases[1])
        self.assertNotEqual(canvases[0], canvases[2])
