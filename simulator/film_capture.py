"""Capture actual pygame/ctx frames; no weather, contacts or PBX requests."""
import builtins
import json
import math
from pathlib import Path
import tempfile
import time

_open = builtins.open  # Preserve native file IO before firmware mocks /flash.


class FrameRecorder:
    def __init__(self, workspace, output, seconds=24, fps=15, view="lcd", showcase="tour"):
        if not 1 <= seconds <= 60 or not 5 <= fps <= 30 or view not in ("lcd", "window"):
            raise ValueError("Invalid bounded recording settings")
        self.output = Path(output).resolve()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix="film-", dir=str(Path(workspace) / "run")))
        self.seconds, self.fps, self.view, self.showcase = float(seconds), int(fps), view, showcase
        self.start = None
        self.next_due = 0.0
        self.frames = []
        self.events = []
        self.stills = []
        self.source_hashes = {}
        self.callbacks = 0
        self.finished = False

    def elapsed(self):
        return 0.0 if self.start is None else max(0.0, time.perf_counter() - self.start)

    def capture(self, pygame, surface, metadata):
        if self.finished:
            return True
        if self.start is None:
            self.start = time.perf_counter()
        self.callbacks += 1
        elapsed = self.elapsed()
        if elapsed >= self.next_due and len(self.frames) < math.ceil(self.seconds * self.fps) + 2:
            filename = "frame-%05d.png" % len(self.frames)
            pygame.image.save(surface, str(self.directory / filename))
            self.frames.append({"file": filename, "elapsed": round(elapsed, 6), **metadata})
            self.next_due = (math.floor(elapsed * self.fps) + 1) / self.fps
        if elapsed >= self.seconds:
            self.finished = True
            self._manifest(elapsed)
            return True
        return False

    def _manifest(self, elapsed):
        value = {"source": "Official Tildagon SDL/ctx simulator", "synthetic": True,
                 "physical_camera_footage": False, "timebase": "actual monotonic elapsed time",
                 "source_view": self.view, "showcase": self.showcase,
                 "duration_seconds": round(elapsed, 6), "requested_sample_fps": self.fps,
                 "captured_frames": len(self.frames), "renderer_callbacks": self.callbacks,
                 "observed_capture_fps": round((len(self.frames) - 1) / elapsed, 3) if elapsed else None,
                 "motion_interpolation": False, "output": str(self.output),
                 "native_source_resolution": [240, 240] if self.view == "lcd" else [1040, 733],
                 "synthetic_inputs_sequenced": True, "idle_waits_skipped": True,
                 "events": self.events, "badge_source_sha256": self.source_hashes,
                 "stills": self.stills,
                 "frames": self.frames}
        with _open(str(self.directory / "capture.json"), "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
