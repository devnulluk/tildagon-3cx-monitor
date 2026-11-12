"""Synthetic PNG/catalog/install fixtures; no downloads or attached storage."""
import binascii
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import types
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assets = load("theme_assets_test", ROOT / "badge/theme_assets.py")
installer = load("theme_installer_test", ROOT / "tools/install_theme_pack.py")


def chunk(kind, value):
    return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", binascii.crc32(kind + value) & 0xffffffff)


def png(width=2, height=2, compressed=None):
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    image = zlib.compress((b"\0" + b"\x11\x33\x55" * width) * height) if compressed is None else compressed
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", image) + chunk(b"IEND", b"")


def entry(value, ident="photo", filename="photo/test.png", width=2, height=2):
    return {"id": ident, "name": "Test photo", "renderer": "photo", "file": filename,
            "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest(), "width": width, "height": height}


def write_pack(root, value=None, metadata=None):
    value = png() if value is None else value
    metadata = entry(value) if metadata is None else metadata
    root.mkdir(parents=True, exist_ok=True)
    destination = root.joinpath(*metadata["file"].split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(value)
    (root / "catalog.json").write_text(json.dumps({"schema": 1, "themes": [metadata]}), encoding="utf-8")
    return destination, metadata


class AssetTests(unittest.TestCase):
    def test_actual_bundled_photo_passes_validation(self):
        store = assets.ThemeAssetStore(app_root=str(ROOT / "badge"), mount_roots=[])
        self.assertTrue(store.photo_available())

    def test_valid_photo_is_streamed_once_and_draw_uses_only_native_image_path(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            path, unused = write_pack(app / "assets")
            store = assets.ThemeAssetStore(app_root=str(app), mount_roots=[])
            self.assertTrue(store.photo_available())
            seen = []
            ctx = types.SimpleNamespace(image=lambda *args: seen.append(args))
            with patch.object(assets, "verify_png", side_effect=AssertionError("revalidated per frame")):
                self.assertTrue(store.draw_photo(ctx))
                self.assertTrue(store.draw_photo(ctx, now_ms=100))
            self.assertEqual(seen, [(str(path).replace("\\", "/"), -120, -120, 240, 240)] * 2)
            self.assertTrue(all(not isinstance(value, bytes) for value in store.__dict__.values()))

    def test_corrupt_crc_truncation_wrong_hash_dimensions_and_extra_data_are_rejected(self):
        good = png()
        corrupt = bytearray(good)
        corrupt[-1] ^= 1
        for value, metadata in ((bytes(corrupt), entry(bytes(corrupt))), (good[:-1], entry(good[:-1])),
                                 (good, dict(entry(good), sha256="0" * 64)),
                                 (good, dict(entry(good), width=3)), (good + b"extra", entry(good + b"extra"))):
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "file.png"
                path.write_bytes(value)
                self.assertFalse(assets.verify_png(str(path), metadata))

    def test_catalog_rejects_traversal_reserved_paths_unknown_renderer_duplicates_and_limits(self):
        good = entry(png())
        for change in ({"file": "../escape.png"}, {"file": "/escape.png"}, {"file": "photo\\escape.png"},
                       {"file": "photo/%2e%2e.png"}, {"file": "photo/CON.png"}, {"renderer": "python"},
                       {"width": 241}, {"height": True}, {"bytes": assets.MAX_ASSET + 1}, {"id": "../bad"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                assets.parse_catalog({"schema": 1, "themes": [dict(good, **change)]})
        with self.assertRaises(ValueError):
            assets.parse_catalog({"schema": 1, "themes": [good, good]})
        with self.assertRaises(ValueError):
            assets.parse_catalog({"schema": True, "themes": []})

    def test_no_recursive_scan_and_external_entries_require_verified_files(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder) / "app"
            sd = Path(folder) / "sd"
            write_pack(sd / "unrelated" / "deep", metadata=entry(png(), ident="garden"))
            store = assets.ThemeAssetStore(app_root=str(app), mount_roots=[str(sd)])
            self.assertFalse(store.photo_available("garden"))
            write_pack(sd, metadata=entry(png(), ident="garden"))
            store = assets.ThemeAssetStore(app_root=str(app), mount_roots=[str(sd)])
            self.assertTrue(store.photo_available("garden"))
            self.assertEqual(store.catalog_entries(), [{"id": "garden", "name": "Test photo", "renderer": "photo", "available": True}])

    def test_removed_asset_or_decoder_failure_disables_photo_without_throwing(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            path, unused = write_pack(app / "assets")
            store = assets.ThemeAssetStore(app_root=str(app), mount_roots=[])
            path.unlink()
            self.assertFalse(store.draw_photo(types.SimpleNamespace(image=lambda *args: None)))
            self.assertFalse(store.photo_available())
            write_pack(app / "assets")
            store = assets.ThemeAssetStore(app_root=str(app), mount_roots=[])
            def fail(*args):
                raise MemoryError()
            self.assertFalse(store.draw_photo(types.SimpleNamespace(image=fail)))

    def test_crc_fallback_matches_native_crc_without_holding_image_bytes(self):
        data = b"123456789"
        fallback = types.SimpleNamespace(hexlify=binascii.hexlify)
        with patch.object(assets, "binascii", fallback):
            self.assertEqual(assets._crc(data), 0xcbf43926)
            self.assertEqual(assets._crc(data[4:], assets._crc(data[:4])), 0xcbf43926)


class InstallerTests(unittest.TestCase):
    @staticmethod
    def fetch_for(value=None, metadata=None):
        value = png() if value is None else value
        metadata = entry(value) if metadata is None else metadata
        catalog = json.dumps({"schema": 1, "themes": [metadata]}).encode()
        seen = []
        def fetch(url, limit):
            seen.append(url)
            return catalog if url.endswith("catalog.json") else value
        return fetch, seen

    def test_staged_install_uses_only_fixed_repo_and_preserves_old_pack_as_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "threecx-themes"
            fetch, seen = self.fetch_for()
            first = installer.install(target, ref="v0.8.0", fetch=fetch)
            self.assertIsNone(first["backup"])
            self.assertTrue((target / installer.MARKER).is_file())
            (target / "personal-note.txt").write_text("preserve me")
            second = installer.install(target, fetch=fetch)
            backup = Path(second["backup"])
            self.assertEqual((backup / "personal-note.txt").read_text(), "preserve me")
            self.assertTrue(all(url.startswith(installer.REPOSITORY) for url in seen))
            self.assertTrue(installer.assets.ThemeAssetStore(app_root=str(Path(folder) / "none"), mount_roots=[str(target)]).photo_available())

    def test_corrupt_asset_and_unbounded_inflate_never_replace_existing_pack(self):
        for bad, metadata in ((png(), dict(entry(png()), sha256="0" * 64)),
                              (png(compressed=zlib.compress(b"x" * 1000000)), None)):
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "threecx-themes"
                fetch, unused = self.fetch_for()
                installer.install(target, fetch=fetch)
                before = (target / "catalog.json").read_bytes()
                bad_fetch, unused = self.fetch_for(bad, metadata)
                with self.assertRaises(ValueError):
                    installer.install(target, fetch=bad_fetch)
                self.assertEqual((target / "catalog.json").read_bytes(), before)
                self.assertFalse(list(Path(folder).glob("*.staging-*")))

    def test_unrelated_target_and_invalid_ref_are_refused_before_download(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "photos"
            target.mkdir()
            (target / "keep.txt").write_text("user data")
            with self.assertRaises(ValueError):
                installer.install(target, fetch=lambda *args: self.fail("downloaded before target validation"))
            self.assertEqual((target / "keep.txt").read_text(), "user data")
            for ref in ("../other", "branch/path", "main?token=x"):
                with self.assertRaises(ValueError):
                    installer.install(Path(folder) / "new", ref=ref, fetch=lambda *args: self.fail("unsafe ref downloaded"))

    def test_failed_final_rename_rolls_back_without_deleting_previous_pack(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "threecx-themes"
            fetch, unused = self.fetch_for()
            installer.install(target, fetch=fetch)
            (target / "note.txt").write_text("retained")
            original = installer.os.replace
            def replace(source, destination):
                if ".staging-" in str(source):
                    raise OSError("simulated SD rename failure")
                return original(source, destination)
            with patch.object(installer.os, "replace", side_effect=replace), self.assertRaises(OSError):
                installer.install(target, fetch=fetch)
            self.assertEqual((target / "note.txt").read_text(), "retained")


if __name__ == "__main__":
    unittest.main()
