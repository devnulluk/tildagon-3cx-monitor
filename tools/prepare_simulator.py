"""Prepare a pinned official Tildagon simulator in a project-local cache.

Requires Git and CPython3.10. No firmware submodules, global package installs,
system package manager, USB connection, live credentials or PBX are used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_URL = "https://github.com/emfcamp/badge-2024-software.git"
FIRMWARE_REVISION = "f10ecb8b18631b0cd328c765b4a3d9f39dbe1ede"
CTX_SHA256 = "abe7fa17f0a00bde1bbc880287f16d44035dedc29f1927345e20c0c9ad66e142"
PACKAGES = {"pygame": "2.6.1", "requests": "2.32.3", "wasmtime": "39.0.0",
            "Pillow": "12.3.0", "imageio-ffmpeg": "0.8.1"}


def run(arguments, cwd=None, capture=False):
    return subprocess.run([str(value) for value in arguments], cwd=cwd, check=True,
                          text=True, capture_output=capture)


def python_version(executable):
    output = run([executable, "-c", "import json,sys;print(json.dumps(list(sys.version_info[:2])))"], capture=True)
    return json.loads(output.stdout)


def verify_runtime(executable):
    if python_version(executable) != [3, 10]:
        raise RuntimeError("The pinned official simulator requires CPython3.10. Pass --python /path/to/python3.10.")
    code = "import importlib.metadata as m,json;print(json.dumps({n:m.version(n) for n in " + repr(list(PACKAGES)) + "}))"
    versions = json.loads(run([executable, "-c", code], capture=True).stdout)
    if versions != PACKAGES:
        raise RuntimeError("Simulator dependencies differ from simulator/requirements.txt: " + json.dumps(versions))
    return versions


def verify_firmware(folder):
    head = run(["git", "rev-parse", "HEAD"], cwd=folder, capture=True).stdout.strip()
    if head != FIRMWARE_REVISION:
        raise RuntimeError("Existing simulator checkout has another revision; choose a fresh --sim-root. It was not reset.")
    wasm = folder / "sim/wasm/ctx.wasm"
    if not wasm.is_file() or hashlib.sha256(wasm.read_bytes()).hexdigest() != CTX_SHA256:
        raise RuntimeError("The pinned ctx.wasm is missing or modified. Restore it from the pinned official commit.")
    for name in ("sim/run.py", "sim/fakes/ctx.py", "modules/main.py"):
        if not (folder / name).is_file():
            raise RuntimeError("Incomplete official simulator checkout: " + name)


def prepare(options):
    cache = options.sim_root.expanduser().resolve()
    firmware = cache / "firmware"
    manifest = cache / "runtime.json"
    runtime = Path(options.reuse_runtime).expanduser().resolve() if options.reuse_runtime else (
        cache / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    if not shutil.which("git"):
        raise RuntimeError("Git is required; install Git, then rerun this setup command.")
    if options.check:
        if manifest.is_file() and not options.reuse_runtime:
            runtime = Path(json.loads(manifest.read_text(encoding="utf-8"))["python"])
        verify_firmware(firmware)
        versions = verify_runtime(runtime)
        return {"ready": True, "check_only": True, "python": str(runtime), "cache": str(cache),
                "firmware_revision": FIRMWARE_REVISION, "packages": versions}
    cache.mkdir(parents=True, exist_ok=True)
    if not firmware.exists():
        run(["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout", "--sparse", FIRMWARE_URL, firmware])
        run(["git", "fetch", "--depth", "1", "origin", FIRMWARE_REVISION], cwd=firmware)
        run(["git", "sparse-checkout", "set", "sim", "modules"], cwd=firmware)
        run(["git", "checkout", "--detach", FIRMWARE_REVISION], cwd=firmware)
    verify_firmware(firmware)
    if options.reuse_runtime:
        # Explicit opt-in: validate an existing environment without installing
        # or changing anything in it. Useful for a previously prepared runtime.
        versions = verify_runtime(runtime)
    else:
        base_python = Path(options.python).expanduser().resolve() if options.python else Path(sys.executable)
        if python_version(base_python) != [3, 10]:
            raise RuntimeError("Use CPython3.10 for setup, or pass --python /path/to/python3.10. No system Python was changed.")
        if not runtime.is_file():
            run([base_python, "-m", "venv", cache / "venv"])
        if python_version(runtime) != [3, 10]:
            raise RuntimeError("Cached environment is not CPython3.10; choose a fresh --sim-root.")
        run([runtime, "-m", "pip", "install", "--requirement", ROOT / "simulator/requirements.txt"])
        versions = verify_runtime(runtime)
    (cache / "run").mkdir(exist_ok=True)
    result = {"ready": True, "python": str(runtime), "cache": str(cache),
              "firmware_revision": FIRMWARE_REVISION, "packages": versions,
              "ctx_sha256": CTX_SHA256}
    manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim-root", type=Path, default=Path(os.environ.get("TILDAGON_SIM_ROOT", ROOT / ".simulator")),
                        help="Local cache directory; defaults to .simulator in this checkout")
    parser.add_argument("--python", help="CPython3.10 executable used only to create the local virtual environment")
    parser.add_argument("--reuse-runtime", help="Use an explicitly selected existing compatible runtime without installing into it")
    parser.add_argument("--check", action="store_true", help="Read-only verification of an existing prepared cache")
    try:
        print(json.dumps(prepare(parser.parse_args()), indent=2))
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, "Simulator setup failed: " + str(error) + "\n")
