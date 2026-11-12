"""One bundled, bounded clock dial; independent of selectable photo themes."""
import os
from .theme_assets import verify_png, _no_symlinks

_DIAL = {"id": "atelier_dial", "name": "Celestial Atelier dial", "renderer": "photo",
         "file": "clocks/atelier-dial.png", "bytes": 63973, "width": 240, "height": 240,
         "sha256": "87a8c335dc60b0fd7eea5ee375168fac5535707e9760711ff1f90ddae22b54ae"}


def asset_entries():
    return [dict(_DIAL)]


class ClockAssetStore:
    def __init__(self, app_root=None):
        if app_root is None:
            app_root = __file__.replace("\\", "/").rsplit("/", 1)[0]
        root = str(app_root).replace("\\", "/").rstrip("/") + "/assets"
        self.path = root + "/" + _DIAL["file"]
        self.available = bool(_no_symlinks(root, _DIAL["file"]) and verify_png(self.path, _DIAL))

    def draw(self, ctx):
        if not self.available:
            return False
        try:
            if os.stat(self.path)[6] != _DIAL["bytes"]:
                raise ValueError("Clock artwork changed")
            ctx.image(self.path, -120, -120, 240, 240)
            return True
        except (OSError, ValueError, TypeError, AttributeError, MemoryError):
            self.available = False
            return False
