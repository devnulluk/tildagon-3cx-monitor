"""Bundled clock pixels are bounded, verified and never required for time."""
import importlib
import shutil
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("clock_assets_test_package")
package.__path__ = [str(ROOT / "badge")]
sys.modules[package.__name__] = package
assets = importlib.import_module(package.__name__ + ".clock_assets")


class Canvas:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
    def image(self, path, x, y, width, height):
        self.calls.append((path, x, y, width, height))
        if self.fail:
            raise OSError("No image decoder")


class ClockAssetTests(unittest.TestCase):
    def test_bundled_asset_matches_exact_public_metadata_and_draws_native_image(self):
        store = assets.ClockAssetStore(ROOT / "badge")
        self.assertTrue(store.available)
        canvas = Canvas()
        self.assertTrue(store.draw(canvas))
        self.assertEqual(len(canvas.calls), 1)
        self.assertEqual(canvas.calls[0][1:], (-120, -120, 240, 240))
        self.assertLess(assets.asset_entries()[0]["bytes"], 128 * 1024)

    def test_metadata_copies_do_not_change_the_accepted_path_or_digest(self):
        first = assets.asset_entries()
        first[0].update(file="../../config.json", sha256="0" * 64)
        second = assets.asset_entries()[0]
        self.assertEqual(second["file"], "clocks/atelier-dial.png")
        self.assertNotEqual(second["sha256"], "0" * 64)

    def test_missing_or_corrupt_same_length_pixels_are_not_decoded(self):
        with tempfile.TemporaryDirectory() as folder:
            store = assets.ClockAssetStore(folder)
            self.assertFalse(store.draw(Canvas()))
            target = Path(folder) / "assets/clocks/atelier-dial.png"
            target.parent.mkdir(parents=True)
            source = ROOT / "badge/assets/clocks/atelier-dial.png"
            value = bytearray(source.read_bytes())
            value[-20] ^= 1
            target.write_bytes(value)
            canvas = Canvas()
            self.assertFalse(assets.ClockAssetStore(folder).draw(canvas))
            self.assertEqual(canvas.calls, [])

    def test_deleted_after_verification_and_decoder_failure_are_bounded_fallbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "assets/clocks/atelier-dial.png"
            target.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "badge/assets/clocks/atelier-dial.png", target)
            store = assets.ClockAssetStore(folder)
            self.assertTrue(store.available)
            target.unlink()
            self.assertFalse(store.draw(Canvas()))
            self.assertFalse(store.available)
        store = assets.ClockAssetStore(ROOT / "badge")
        canvas = Canvas(fail=True)
        self.assertFalse(store.draw(canvas))
        self.assertFalse(store.draw(canvas))
        self.assertEqual(len(canvas.calls), 1)


if __name__ == "__main__":
    unittest.main()
