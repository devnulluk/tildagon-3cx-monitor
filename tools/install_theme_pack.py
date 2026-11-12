"""Install verified photo packs to an explicit badge/SD cache directory.

Only this project's public GitHub repository is contacted. Existing managed
packs are renamed to a reversible backup; unrelated directories are refused.
No badge, PBX or credentials are required. Uses only Python's standard library.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import ssl
import tempfile
import urllib.request
import uuid
import zlib

_SOURCE = Path(__file__).resolve().parents[1] / "badge" / "theme_assets.py"
_SPEC = importlib.util.spec_from_file_location("theme_pack_validation", _SOURCE)
assets = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(assets)
REPOSITORY = "https://raw.githubusercontent.com/devnulluk/tildagon-3cx-monitor/"
MARKER = ".threecx-theme-pack"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _download(url, limit):
    if not url.startswith(REPOSITORY) or "?" in url or "#" in url:
        raise ValueError("Unapproved asset source")
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request(url, headers={"User-Agent": "TildagonThemeInstaller/1", "Accept-Encoding": "identity"})
    try:
        with opener.open(request, timeout=20) as response:
            if response.status != 200 or response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Asset download rejected")
            chunks, total = [], 0
            while True:
                value = response.read(min(8192, limit + 1 - total))
                if not value:
                    return b"".join(chunks)
                chunks.append(value)
                total += len(value)
                if total > limit:
                    raise ValueError("Asset download is too large")
    except Exception:
        raise ValueError("Asset download failed") from None


def _deflate_valid(path, entry):
    """Bound PNG expansion before its first native STB decode on the badge."""
    raw, compressed, colour = path.read_bytes(), [], None
    position = 8
    while position + 12 <= len(raw):
        length = int.from_bytes(raw[position:position + 4], "big")
        kind = raw[position + 4:position + 8]
        data = raw[position + 8:position + 8 + length]
        if kind == b"IHDR":
            colour = data[9]
        elif kind == b"IDAT":
            compressed.append(data)
        position += length + 12
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour)
    if channels is None:
        return False
    stride = entry["width"] * channels + 1
    expected = stride * entry["height"]
    try:
        decoder = zlib.decompressobj()
        value = decoder.decompress(b"".join(compressed), expected + 1)
        return (len(value) == expected and decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data
                and all(value[index] <= 4 for index in range(0, expected, stride)))
    except zlib.error:
        return False


def install(target, ref="main", theme=None, fetch=None):
    if (not isinstance(ref, str) or not 1 <= len(ref) <= 64 or ref in (".", "..")
            or not all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in ref)):
        raise ValueError("Invalid GitHub ref")
    original = Path(target).expanduser().absolute()
    if original.is_symlink() or original.parent == original:
        raise ValueError("Target must be a dedicated pack directory")
    target = original.resolve()
    if target.exists() and (not target.is_dir() or (any(target.iterdir()) and not (target / MARKER).is_file())):
        raise ValueError("Refusing to replace an unrelated directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    base = REPOSITORY + ref + "/badge/assets/"
    fetch = fetch or _download
    raw = fetch(base + "catalog.json", assets.MAX_CATALOG)
    if not isinstance(raw, bytes) or len(raw) > assets.MAX_CATALOG:
        raise ValueError("Invalid catalog download")
    try:
        entries = assets.parse_catalog(json.loads(raw))
    except (ValueError, UnicodeError):
        raise ValueError("Invalid theme catalog") from None
    if theme is not None:
        entries = [entry for entry in entries if entry["id"] == theme]
        if not entries:
            raise ValueError("Requested theme is unavailable")
    if not entries:
        raise ValueError("Theme pack is empty")
    stage = Path(tempfile.mkdtemp(prefix=target.name + ".staging-", dir=target.parent))
    backup = None
    try:
        for entry in entries:
            destination = stage.joinpath(*entry["file"].split("/"))
            if stage.resolve() not in destination.resolve().parents:
                raise ValueError("Invalid staged asset path")
            value = fetch(base + entry["file"], entry["bytes"])
            if not isinstance(value, bytes) or len(value) != entry["bytes"]:
                raise ValueError("Asset size mismatch")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(value)
            if not assets.verify_png(str(destination), entry) or not _deflate_valid(destination, entry):
                raise ValueError("Asset verification failed")
        (stage / "catalog.json").write_text(json.dumps({"schema": 1, "themes": entries}, indent=2) + "\n", encoding="utf-8")
        (stage / MARKER).write_text(json.dumps({"schema": 1, "ref": ref, "catalog_sha256": hashlib.sha256(raw).hexdigest()}) + "\n", encoding="utf-8")
        if target.exists():
            backup = target.parent / (target.name + ".backup-" + uuid.uuid4().hex[:12])
            os.replace(target, backup)
        try:
            os.replace(stage, target)
        except BaseException:
            if backup is not None and not target.exists():
                os.replace(backup, target)
                backup = None
            raise
        return {"target": str(target), "themes": [entry["id"] for entry in entries],
                "backup": str(backup) if backup is not None else None}
    finally:
        if stage.exists():
            # Delete only the exact temporary directory created above, after
            # checking its resolved parent remains the explicit target parent.
            if stage.resolve().parent != target.parent or not stage.name.startswith(target.name + ".staging-") or stage.is_symlink():
                raise ValueError("Refusing unsafe staging cleanup")
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Dedicated threecx-themes directory on SD or local disk")
    parser.add_argument("--ref", default="main", help="Public repository branch, tag or commit")
    parser.add_argument("--theme", help="Install one catalog theme instead of all")
    args = parser.parse_args(argv)
    try:
        result = install(args.target, args.ref, args.theme)
    except (ValueError, OSError):
        parser.exit(1, "Theme pack installation failed; existing files were preserved.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
