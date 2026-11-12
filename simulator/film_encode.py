"""Encode captured official-simulator frames as labelled phone-friendly media.

Runs in a fresh interpreter, outside the firmware's mocked filesystem. Frames
retain their actual capture timing. No generated UI frames or motion tweening.
"""
import argparse
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont


def run_encoder(arguments):
    return subprocess.run(arguments, check=True, timeout=180,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def font(size):
    for filename in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                     "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if Path(filename).is_file():
            return ImageFont.truetype(filename, size)
    return ImageFont.load_default(size=size)


def centered(draw, xy, value, size, colour):
    draw.text(xy, value, font=font(size), fill=colour, anchor="mm")


def framed(source, label, view):
    if view == "lcd":
        canvas = Image.new("RGB", (720, 900), "#080d18")
        canvas.paste(source.resize((720, 720), Image.Resampling.NEAREST), (0, 90))
        draw = ImageDraw.Draw(canvas)
        centered(draw, (360, 30), "SPACEAGON / 3CX", 27, "#f0f6ff")
        centered(draw, (360, 64), label, 22, "#88bdd9")
        centered(draw, (360, 839), "OFFICIAL SIMULATOR - SYNTHETIC DEMO", 22, "#ffd06c")
        centered(draw, (360, 873), "Real ctx-rendered pixels / no camera footage", 18, "#a0aec0")
    else:
        canvas = Image.new("RGB", (1040, 816), "#080d18")
        canvas.paste(source.convert("RGB"), (0, 48))
        draw = ImageDraw.Draw(canvas)
        centered(draw, (520, 24), "SPACEAGON / 3CX - " + label, 24, "#f0f6ff")
        centered(draw, (520, 798), "OFFICIAL SDL/ctx SIMULATOR / SYNTHETIC DEMO / NOT CAMERA FOOTAGE", 18, "#ffd06c")
    return canvas


def concat_file(path, entries):
    def quote(value):
        return str(value).replace("\\", "/").replace("'", "'\\''")
    lines = ["ffconcat version 1.0"]
    for file, duration in entries:
        lines.extend(["file '" + quote(file) + "'", "duration %.6f" % max(0.001, duration)])
    lines.append("file '" + quote(entries[-1][0]) + "'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def encode(directory):
    directory = Path(directory).resolve()
    capture = json.loads((directory / "capture.json").read_text(encoding="utf-8"))
    frames = capture["frames"]
    if not capture.get("synthetic") or not 1 <= len(frames) <= 1802:
        raise ValueError("Invalid bounded simulator recording")
    output = Path(capture["output"])
    view, fps, duration = capture["source_view"], capture["requested_sample_fps"], capture["duration_seconds"]
    canvases = directory / "framed"
    canvases.mkdir(exist_ok=True)
    images, entries = [], []
    for index, frame in enumerate(frames):
        source = (directory / frame["file"]).resolve()
        if not source.is_relative_to(directory) or source.suffix != ".png":
            raise ValueError("Invalid captured frame path")
        with Image.open(source) as native:
            image = framed(native.convert("RGB"), frame.get("label", "DEMO"), view)
        canvas = canvases / ("canvas-%05d.png" % index)
        image.save(canvas)
        next_time = frames[index + 1]["elapsed"] if index + 1 < len(frames) else duration
        entries.append((canvas, max(0.001, next_time - frame["elapsed"])))
        images.append(canvas)
    manifest = directory / "frames.ffconcat"
    concat_file(manifest, entries)
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    base = [exe, "-hide_banner", "-loglevel", "error", "-y"]
    run_encoder(base + ["-f", "concat", "-safe", "0", "-i", str(manifest), "-t", str(duration),
                          "-vf", "fps=" + str(fps), "-c:v", "libx264", "-profile:v", "baseline",
                          "-level:v", "3.1", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                          "-movflags", "+faststart", "-an", str(output)])
    gif = output.with_suffix(".gif")
    gif_limit = 32 if capture.get("showcase") == "atelier" else 42 if capture.get("showcase") in ("themes", "notifications") else 18
    gif_duration = min(duration, gif_limit)
    gif_width = 480 if view == "lcd" else 780
    filters = ("fps=10,scale=%d:-1:flags=lanczos,split[s0][s1];" % gif_width
               + "[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4")
    run_encoder(base + ["-i", str(output), "-t", str(gif_duration), "-filter_complex", filters,
                       "-loop", "0", str(gif)])
    # One real frame near each scene's midpoint, plus a native-pixel contact sheet.
    events = capture.get("events") or [{"at": 0, "label": "DEMO"}]
    selected = []
    for index, event in enumerate(events):
        if event["at"] >= duration:
            continue
        end = events[index + 1]["at"] if index + 1 < len(events) else duration
        target = (event["at"] + min(end, duration)) / 2
        frame = min(frames, key=lambda item: abs(item["elapsed"] - target))
        selected.append((event.get("label", "DEMO"), frame))
    for index, (label, frame) in enumerate(selected):
        with Image.open(directory / frame["file"]) as native:
            poster = framed(native.convert("RGB"), label, view)
            poster.save(output.with_name(output.stem + "-scene-%02d.png" % (index + 1)))
    # LCD crops are native240px; window contact cells are fit within320px.
    cells = selected[:16]
    cell_width = 240 if view == "lcd" else 320
    cell_height = 280 if view == "lcd" else 270
    columns = 4 if len(cells) > 9 else 3 if len(cells) >= 3 else len(cells)
    rows = (len(cells) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, 70 + rows * cell_height), "#080d18")
    draw = ImageDraw.Draw(sheet)
    centered(draw, (sheet.width / 2, 25), "SPACEAGON / OFFICIAL SIMULATOR / DEMO", 18, "#ffd06c")
    centered(draw, (sheet.width / 2, 49), "Actual rendered frames - synthetic demonstration data", 13, "#a0aec0")
    for index, (label, frame) in enumerate(cells):
        x, y = index % columns * cell_width, 70 + index // columns * cell_height
        with Image.open(directory / frame["file"]) as source:
            source = source.convert("RGB")
            if view == "window":
                source.thumbnail((320, 235), Image.Resampling.LANCZOS)
            sheet.paste(source, (x + (cell_width - source.width) // 2, y))
        centered(draw, (x + cell_width / 2, y + cell_height - 19), label, 16, "#f0f6ff")
    sheet_path = output.with_name(output.stem + "-contact-sheet.png")
    sheet.save(sheet_path)
    poster_path = output.with_name(output.stem + "-poster.png")
    with Image.open(images[min(len(images) - 1, int(fps))]) as image:
        image.save(poster_path)
    # Decode the exported H.264 fully once; fail if the phone-facing file is corrupt.
    run_encoder(base[:4] + ["-i", str(output), "-f", "null", "-"])
    result = {key: value for key, value in capture.items() if key != "frames"}
    result["output"] = output.name
    result.update({"mp4": output.name, "gif": gif.name, "poster": poster_path.name,
                   "contact_sheet": sheet_path.name, "codec": "H.264 baseline / yuv420p / faststart",
                   "output_fps": fps, "gif_preview_seconds": gif_duration,
                   "ffmpeg_version": imageio_ffmpeg.get_ffmpeg_version(),
                   "verified_decode": True})
    output.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_directory")
    encode(parser.parse_args().capture_directory)
