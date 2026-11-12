"""Bounded local photo assets; no SD enumeration, downloads or retained pixels."""
import binascii
import hashlib
import json
import os

MAX_ASSET = 128 * 1024
MAX_CATALOG = 16384
MAX_ENTRIES = 16
SD_ROOTS = ("/sd/threecx-themes", "/sdcard/threecx-themes", "/sdcard_1/threecx-themes", "/mnt/sd/threecx-themes")
_CRC_TABLE = None


def _crc(data, value=0):
    global _CRC_TABLE
    if hasattr(binascii, "crc32"):
        return binascii.crc32(data, value) & 0xffffffff
    if _CRC_TABLE is None:
        table = []
        for value0 in range(256):
            for unused in range(8):
                value0 = (value0 >> 1) ^ (0xedb88320 if value0 & 1 else 0)
            table.append(value0)
        _CRC_TABLE = tuple(table)
    value ^= 0xffffffff
    for byte in data:
        value = _CRC_TABLE[(value ^ byte) & 255] ^ (value >> 8)
    return value ^ 0xffffffff


def _u32(value):
    return (value[0] << 24) | (value[1] << 16) | (value[2] << 8) | value[3]


def _safe_id(value):
    return (isinstance(value, str) and 1 <= len(value) <= 32 and value[0] in "abcdefghijklmnopqrstuvwxyz"
            and all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in value))


def safe_relative(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 120 or not value.endswith(".png"):
        return False
    parts = value.split("/")
    if len(parts) > 4:
        return False
    reserved = ("con", "prn", "aux", "nul") + tuple("com" + str(i) for i in range(1, 10)) + tuple("lpt" + str(i) for i in range(1, 10))
    return all(part and not part.startswith(".") and not part.endswith(".")
               and part.split(".", 1)[0].lower() not in reserved
               and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in part)
               for part in parts)


def parse_catalog(value):
    """Accept public photo metadata only; callers handle asset availability."""
    if (not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1
            or not isinstance(value.get("themes"), list) or len(value["themes"]) > MAX_ENTRIES):
        raise ValueError("Invalid theme catalog")
    result, ids, paths = [], set(), set()
    for item in value["themes"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid theme entry")
        ident, name, path, digest = (item.get(key) for key in ("id", "name", "file", "sha256"))
        size, width, height = (item.get(key) for key in ("bytes", "width", "height"))
        if (not _safe_id(ident) or ident in ids or item.get("renderer") != "photo"
                or not isinstance(name, str) or not 1 <= len(name) <= 40
                or any(c < " " or c == "\x7f" for c in name) or not safe_relative(path) or path.lower() in paths
                or not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                or type(size) is not int or not 1 <= size <= MAX_ASSET
                or type(width) is not int or type(height) is not int or not 1 <= width <= 240 or not 1 <= height <= 240):
            raise ValueError("Invalid theme entry")
        result.append({"id": ident, "name": name, "renderer": "photo", "file": path,
                       "bytes": size, "sha256": digest, "width": width, "height": height})
        ids.add(ident)
        paths.add(path.lower())
    return result


def verify_png(path, entry):
    """Stream signature, size, dimensions, chunk CRCs and complete SHA256."""
    try:
        entry = parse_catalog({"schema": 1, "themes": [entry]})[0]
        digest, total = hashlib.sha256(), 0
        with open(path, "rb") as handle:
            def take(count):
                nonlocal total
                value = handle.read(count)
                if len(value) != count or total + count > entry["bytes"]:
                    raise ValueError("Invalid PNG length")
                total += count
                digest.update(value)
                return value
            if take(8) != b"\x89PNG\r\n\x1a\n":
                return False
            seen_header = seen_data = seen_end = seen_palette = data_closed = False
            colour, data_bytes = None, 0
            for unused in range(128):
                length, kind = _u32(take(4)), take(4)
                if length > entry["bytes"] - total - 4 or any(not (65 <= c <= 90 or 97 <= c <= 122) for c in kind):
                    return False
                if not seen_header and kind != b"IHDR":
                    return False
                if kind in (b"acTL", b"fcTL", b"fdAT") or (65 <= kind[0] <= 90 and kind not in (b"IHDR", b"PLTE", b"IDAT", b"IEND")):
                    return False
                crc = _crc(kind)
                if kind == b"IHDR":
                    if seen_header or length != 13:
                        return False
                    data = take(13)
                    crc = _crc(data, crc)
                    if (_u32(data[:4]) != entry["width"] or _u32(data[4:8]) != entry["height"]
                            or data[8] != 8 or data[9] not in (0, 2, 3, 4, 6) or data[10:] != b"\x00\x00\x00"):
                        return False
                    seen_header = True
                    colour = data[9]
                else:
                    if kind == b"PLTE":
                        if seen_palette or seen_data or not 3 <= length <= 768 or length % 3:
                            return False
                        seen_palette = True
                    if kind == b"IDAT":
                        if data_closed or (colour == 3 and not seen_palette):
                            return False
                        data_bytes += length
                    elif seen_data:
                        data_closed = True
                    remaining = length
                    while remaining:
                        value = take(min(1024, remaining))
                        crc = _crc(value, crc)
                        remaining -= len(value)
                if _u32(take(4)) != crc:
                    return False
                if kind == b"IDAT":
                    seen_data = True
                if kind == b"IEND":
                    seen_end = length == 0
                    break
            if not seen_header or not seen_data or not data_bytes or not seen_end or total != entry["bytes"] or handle.read(1):
                return False
        return binascii.hexlify(digest.digest()).decode() == entry["sha256"]
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return False


def _no_symlinks(root, relative=""):
    if not hasattr(os, "lstat"):
        # Native FAT VFS has no symlink support.
        return True
    try:
        current = root
        for part in [""] + (relative.split("/") if relative else []):
            if part:
                current += "/" + part
            if os.lstat(current)[0] & 0xf000 == 0xa000:
                return False
        return True
    except OSError:
        return False


class ThemeAssetStore:
    def __init__(self, config=None, app_root=None, mount_roots=None):
        config = config if isinstance(config, dict) else {}
        if app_root is None:
            app_root = __file__.replace("\\", "/").rsplit("/", 1)[0]
        roots = [str(app_root).replace("\\", "/").rstrip("/") + "/assets"]
        extra = config.get("theme_asset_roots")
        if isinstance(extra, (list, tuple)):
            roots += [value for value in extra[:4] if isinstance(value, str) and value.startswith("/")
                      and "\\" not in value and all(part not in (".", "..") for part in value.split("/"))]
        roots += list(SD_ROOTS if mount_roots is None else mount_roots)[:4]
        self._assets = {}
        for root in roots:
            if len(self._assets) >= MAX_ENTRIES:
                break
            if not isinstance(root, str) or not root or not _no_symlinks(root, "catalog.json"):
                continue
            root = root.rstrip("/")
            try:
                with open(root + "/catalog.json", "rb") as handle:
                    raw = handle.read(MAX_CATALOG + 1)
                if len(raw) > MAX_CATALOG:
                    continue
                entries = parse_catalog(json.loads(raw))
            except (OSError, ValueError, TypeError):
                continue
            for entry in entries:
                if len(self._assets) >= MAX_ENTRIES:
                    break
                if entry["id"] in self._assets or not _no_symlinks(root, entry["file"]):
                    continue
                path = root + "/" + entry["file"]
                if verify_png(path, entry):
                    self._assets[entry["id"]] = (path, entry)

    def photo_available(self, theme_id="photo"):
        return isinstance(theme_id, str) and theme_id in self._assets

    def catalog_entries(self):
        return [{"id": key, "name": value[1]["name"], "renderer": "photo", "available": True}
                for key, value in self._assets.items() if key != "photo"]

    def draw_photo(self, ctx, now_ms=0, theme_id="photo"):
        if not self.photo_available(theme_id):
            return False
        path, entry = self._assets[theme_id]
        try:
            if os.stat(path)[6] != entry["bytes"]:
                raise ValueError("Asset changed")
            ctx.image(path, -120, -120, 240, 240)
            return True
        except (OSError, ValueError, AttributeError, TypeError, MemoryError):
            self._assets.pop(theme_id, None)
            return False
