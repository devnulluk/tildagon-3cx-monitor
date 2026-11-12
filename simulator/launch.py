"""Official Tildagon SDL/ctx simulator with isolated synthetic fixtures."""
import argparse
from datetime import date as calendar_date
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import types
import time as host_time

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("TILDAGON_SIM_ROOT", ROOT / ".simulator")).expanduser().resolve()
RUN = CACHE / "run"
SIM = CACHE / "firmware/sim"
CLOCK_STYLES = (("original", "Original"), ("celestial", "Celestial"),
                ("tokyoflash", "Coded lights"), ("radar", "Radar"),
                ("flip", "Flip"), ("analogue", "Analogue"),
                ("corpus", "Corpus Time Eater"),
                ("haute_celestial", "Celestial Atelier"),
                ("neon_orrery", "Neon Orrery"),
                ("mondaine", "Mondaine"),
                ("great_british_railways", "Great British Railways"))
parser = argparse.ArgumentParser()
parser.add_argument("--screenshot", action="store_true")
parser.add_argument("--record", "--video", type=Path, help="Record actual DEMO renderer frames to an MP4, GIF preview and contact sheet")
parser.add_argument("--seconds", type=float, default=24, help="Bounded recording duration (1..60 real seconds)")
parser.add_argument("--video-fps", type=int, default=15, help="Maximum capture sampling rate (5..30), not device FPS")
parser.add_argument("--record-view", choices=["lcd", "window"], default="lcd")
parser.add_argument("--showcase", choices=["idle", "tour", "calls", "themes", "clocks", "atelier", "rail", "sky", "notifications", "feature-demo"], default="tour")
parser.add_argument("--feature-demo", action="store_true",
                    help="Start the app's production showcase; recordings explicitly abbreviate it with manual feature jumps")
parser.add_argument("--feature-stage", type=int,
                    help="Begin a standalone production showcase at one zero-based catalogue position")
parser.add_argument("--notification", choices=["info", "success", "warning", "failure", "progress"],
                    help="Show a synthetic rich notification through the production badge UI")
parser.add_argument("--scene", default="team")
parser.add_argument("--keyboard", action="store_true", default=os.environ.get("TILDAGON_DEMO_KEYBOARD", "0") == "1")
parser.add_argument("--settings", action="store_true", help="Open settings through a synthetic S key on a demo keyboard")
parser.add_argument("--detail", action="store_true", help="Start a synthetic team fixture in its selected-member detail view")
parser.add_argument("--idle-page", choices=["weather", "rain", "clock", "moon", "meteors", "advent"], help="Fast-forward to a clearly labelled synthetic idle page")
parser.add_argument("--theme", choices=["original", "christmas", "easter", "anniversary", "birthday_self", "birthday_partner", "cyberpunk", "lcars", "kitty", "photo", "noir", "ocean", "retro"], default="original")
parser.add_argument("--clock-style", choices=[key for key, name in CLOCK_STYLES], default="original")
parser.add_argument("--demo-date", help="Synthetic YYYY-MM-DD calendar date; never reads personal dates")
parser.add_argument("--demo-time", help="Synthetic HH:MM or HH:MM:SS local time; never sets a badge clock")
parser.add_argument("--component-theme", action="store_true", help="DEMO-only direct component review before app theme dispatch is integrated")
parser.add_argument("--partner-demo", action="store_true", help="Synthetic KZ priority caller using a reserved example number")
parser.add_argument("--matrix-demo", action="store_true", help="Show the real Liteloop adapter output through a simulated I2C sink and labelled diagram")
parser.add_argument("--gallery-stills", action="store_true", help="Export actual midpoint frames as matching native LCD and full-window gallery stills")
parser.add_argument("--weather-kind", choices=["clear", "day", "night", "rain", "rain-night", "heavy", "snow", "storm", "fog", "stale"], default="clear",
                    help="Synthetic weather condition; never requests live weather")
parser.add_argument("--output", type=Path, help="Copy a completed DEMO screenshot and its status JSON to this path")
parser.add_argument("--action", choices=list("ABCDEFSN") + ["ENTER", "SPACE", "UP", "DOWN", "LEFT", "RIGHT", "SHIFT+D"], help="Inject one synthetic badge/keyboard press in DEMO")
parser.add_argument("--capture-frames", type=int, default=None)
parser.add_argument("--action-frame", type=int, default=12)
parser.add_argument("--action-hold-frames", type=int, default=3, help="Duration of a synthetic held key in DEMO")
parser.add_argument("--diagnose", action="store_true")
options = parser.parse_args()
from notification_fixture import notification as demo_notification
if options.showcase == "feature-demo" or options.feature_stage is not None:
    options.feature_demo = True
if options.feature_demo:
    if options.notification or options.settings or options.component_theme or options.partner_demo:
        parser.error("Production feature demo cannot be combined with simulator-only notification, settings, component or partner fixtures")
    options.showcase = "feature-demo"
    options.keyboard = True
    options.idle_page = None
    options.scene = "team"
if options.showcase == "atelier":
    options.demo_date = options.demo_date or "2026-12-12"
    options.demo_time = options.demo_time or "10:08:30"
if options.showcase == "rail":
    options.demo_date = options.demo_date or "2026-12-12"
    options.demo_time = options.demo_time or "10:08:52"
if options.notification:
    options.keyboard = True
    options.idle_page = options.idle_page or "weather"
if options.idle_page == "advent":
    options.theme = "christmas"
    options.demo_date = options.demo_date or "2026-12-12"
if options.idle_page == "meteors":
    options.demo_date = options.demo_date or "2026-12-12"
if options.demo_date:
    try:
        calendar_date.fromisoformat(options.demo_date)
    except (ValueError, TypeError):
        parser.error("--demo-date must be a valid synthetic calendar date")
demo_hms = None
if options.demo_time:
    fields = options.demo_time.split(":")
    if (len(fields) not in (2, 3) or any(len(value) != 2 or not value.isdigit() for value in fields)
            or not 0 <= int(fields[0]) < 24 or not 0 <= int(fields[1]) < 60
            or (len(fields) == 3 and not 0 <= int(fields[2]) < 60)):
        parser.error("--demo-time must be a valid synthetic HH:MM or HH:MM:SS local time")
    demo_hms = tuple(int(value) for value in fields) + ((0,) if len(fields) == 2 else ())
if options.record and options.screenshot:
    parser.error("Choose either --record or --screenshot")
if options.feature_stage is not None and (options.record or not 0 <= options.feature_stage < 4096):
    parser.error("--feature-stage is for standalone previews and must be0..4095")
if options.record and (options.record.suffix.lower() != ".mp4" or not 1 <= options.seconds <= 60 or not 5 <= options.video_fps <= 30):
    parser.error("Recording needs an MP4 path, duration 1..60 seconds and sampling 5..30 FPS")
if options.output and not options.screenshot:
    parser.error("--output requires --screenshot")
if options.gallery_stills and not options.record:
    parser.error("--gallery-stills requires --record")
if options.capture_frames is not None and not 1 <= options.capture_frames <= 600:
    parser.error("--capture-frames must be between 1 and 600")
if not (SIM / "run.py").is_file() or not (SIM / "wasm/ctx.wasm").is_file():
    raise SystemExit("Official simulator is not prepared. Run Python3.10 tools/prepare_simulator.py first; see simulator/README.md.")
RUN.mkdir(parents=True, exist_ok=True)
capture_output = options.output.resolve() if options.output else None
if capture_output:
    capture_output.parent.mkdir(parents=True, exist_ok=True)
film_recorder = None
film_plan = []
film_event_index = 0
film_label = "Synthetic DEMO"
fixture_clock_started = host_time.monotonic()
if options.record:
    from film_capture import FrameRecorder
    film_recorder = FrameRecorder(CACHE, options.record, options.seconds, options.video_fps,
                                  options.record_view, options.showcase)
    options.keyboard = True
    if not options.feature_demo:
        options.idle_page = options.idle_page or ("clock" if options.showcase == "calls" else "weather")
    if options.feature_demo:
        scenes = [dict(production_showcase=True, label="Production showcase / continuous")]
    elif options.showcase == "notifications":
        scenes = [dict(notification="info", label="Notification / information"),
                  dict(notification="success", label="Notification / success"),
                  dict(notification="warning", label="Notification / warning"),
                  dict(notification="failure", label="Notification / failure"),
                  dict(notification="progress", progress=25, label="Progress /25 percent"),
                  dict(notification="progress", progress=75, label="Progress / same job updated"),
                  dict(notification="warning", notification_id="demo-call-preemption", scene="priority",
                       label="Incoming call / notification held"),
                  dict(notification="warning", notification_id="demo-call-preemption",
                       label="Notification / resumes after call")]
    elif options.showcase == "sky":
        scenes = [dict(page="moon", kind="night", date="2026-12-12", label="Moon / calendar demonstration"),
                  dict(page="meteors", kind="night", date="2026-12-12", label="Meteors / Geminids season"),
                  dict(page="moon", kind="night", date="2026-12-20", label="Moon / later calendar date")]
    elif options.showcase in ("clocks", "atelier", "rail"):
        scenes = [dict(page="clock", clock=key, kind="night", label="Clock / " + label)
                  for key, label in CLOCK_STYLES
                  if options.showcase == "clocks"
                  or options.showcase == "atelier" and key in ("haute_celestial", "neon_orrery")
                  or options.showcase == "rail" and key in ("mondaine", "great_british_railways")]
        if options.showcase == "rail":
            scenes[0].update(synthetic_time=options.demo_time)
            scenes[1].update(synthetic_time="10:09:22", label="GBR / DEMO time cut")
    elif options.showcase == "themes":
        scenes = [dict(theme=key, page="weather", kind="clear", label="Theme / " + label)
                  for key, label in (("original", "Original"), ("christmas", "Christmas"), ("easter", "Easter"),
                                     ("anniversary", "Anniversary"), ("birthday_self", "Birthday celebration"),
                                     ("birthday_partner", "Gift celebration"), ("cyberpunk", "Cyberpunk"),
                                     ("lcars", "LCARS"), ("kitty", "Pink Purr"), ("photo", "Photo"),
                                     ("noir", "Noir"), ("ocean", "Ocean"), ("retro", "Retro"))]
        scenes.insert(2, dict(theme="christmas", page="advent", kind="snow", date="2026-12-12", label="Christmas / Advent DEMO date"))
    elif options.showcase == "tour":
        scenes = [dict(page="weather", kind="clear", label="Weather / clear sky"),
                  dict(page="weather", kind="night", label="Weather / after dark"),
                  dict(page="weather", kind="rain-night", label="Weather / night rain"),
                  dict(page="rain", kind="rain", label="Rain / next 60 minutes"),
                  dict(page="clock", kind="night", label="Clock / London time"),
                  dict(view="team", label="Team / BLF overview"),
                  dict(view="settings", label="Settings / brightness"),
                  dict(scene="ddi", label="Incoming / direct line"),
                  dict(scene="priority", label="Priority / full brightness"),
                  dict(page="weather", kind="snow", label="Weather / snow")]
    elif options.showcase == "calls":
        scenes = [dict(page="clock", kind="night", label="Clock / quiet period"),
                  dict(scene="ddi", label="Incoming / direct line"),
                  dict(scene="queue", label="Incoming / queue"),
                  dict(scene="priority", label="Priority / full brightness")]
    else:
        scenes = [dict(page=options.idle_page, kind=options.weather_kind, label="DEMO / " + options.idle_page)]
    film_plan = [dict(scene, at=index * options.seconds / len(scenes)) for index, scene in enumerate(scenes)]
    film_label = film_plan[0]["label"]
    options.idle_page = film_plan[0].get("page", options.idle_page)
    options.demo_date = film_plan[0].get("date", options.demo_date)
    options.weather_kind = film_plan[0].get("kind", options.weather_kind)
    options.theme = film_plan[0].get("theme", options.theme)
    options.clock_style = film_plan[0].get("clock", options.clock_style)
    options.notification = film_plan[0].get("notification", options.notification)
if options.settings:
    options.keyboard = True
if options.idle_page and not options.feature_demo:
    options.scene = "idle"

# A detached GUI must own its log file handles. PowerShell's Start-Process
# -RedirectStandardOutput uses a parent-managed pipe which can stop draining
# when that short-lived shell exits, eventually blocking the simulator's prints.
if not options.screenshot and not options.record:
    sys.stdout = open(RUN / "live-stdout.log", "w", buffering=1, encoding="utf-8")
    sys.stderr = open(RUN / "live-stderr.log", "w", buffering=1, encoding="utf-8")
if options.diagnose:
    import faulthandler
    trace_file = open(RUN / "thread-stacks.log", "w", buffering=1, encoding="utf-8")
    faulthandler.enable(file=trace_file)
    faulthandler.dump_traceback_later(30, repeat=True, file=trace_file)

# Code/public manifests only: private config, tokens and CA are never copied.
target = SIM / "apps/threecx_monitor"
target.mkdir(parents=True, exist_ok=True)
for source in (ROOT / "badge").glob("*.py"):
    shutil.copyfile(source, target / source.name)
for name in ("metadata.json", "tildagon.toml"):
    shutil.copyfile(ROOT / "badge" / name, target / name)
asset_hashes = {}
target_assets = target / "assets"
target_assets.mkdir(parents=True, exist_ok=True)
verified_assets = []
source_assets = ROOT / "badge/assets"
if source_assets.is_dir() and not source_assets.is_symlink():
    assets_spec = importlib.util.spec_from_file_location("simulator_public_theme_assets", target / "theme_assets.py")
    assets_module = importlib.util.module_from_spec(assets_spec)
    assets_spec.loader.exec_module(assets_module)
    try:
        raw_catalog = (source_assets / "catalog.json").read_bytes()
        entries = assets_module.parse_catalog(json.loads(raw_catalog)) if len(raw_catalog) <= assets_module.MAX_CATALOG else []
        for entry in entries:
            source_asset = source_assets / entry["file"]
            if (source_asset.resolve().is_relative_to(source_assets.resolve())
                    and assets_module._no_symlinks(str(source_assets), entry["file"])
                    and assets_module.verify_png(str(source_asset), entry)):
                destination = target_assets / entry["file"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_asset, destination)
                verified_assets.append(entry)
                asset_hashes["assets/" + entry["file"]] = entry["sha256"]
    except (OSError, ValueError, TypeError):
        verified_assets = []
    # Clock artwork is a separately approved asset, never a selectable weather
    # theme. Its fixed metadata uses the same path/PNG/hash verifier as photos.
    if (target / "clock_assets.py").is_file():
        clock_spec = importlib.util.spec_from_file_location("simulator_public_clock_assets",
                                                          target / "clock_assets.py",
                                                          submodule_search_locations=[str(target)])
        clock_assets = importlib.util.module_from_spec(clock_spec)
        sys.modules[clock_spec.name] = clock_assets
        clock_spec.loader.exec_module(clock_assets)
        entries = assets_module.parse_catalog({"schema": 1, "themes": list(clock_assets.asset_entries())})
        for entry in entries:
            if entry["id"] != "atelier_dial" or entry["file"] != "clocks/atelier-dial.png":
                raise ValueError("Clock asset is outside the explicitly approved simulator fixture")
            source_asset = source_assets / entry["file"]
            if (source_asset.resolve().is_relative_to(source_assets.resolve())
                    and assets_module._no_symlinks(str(source_assets), entry["file"])
                    and assets_module.verify_png(str(source_asset), entry)):
                destination = target_assets / entry["file"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_asset, destination)
                asset_hashes["assets/" + entry["file"]] = entry["sha256"]
(target_assets / "catalog.json").write_text(json.dumps({"schema": 1, "themes": verified_assets}), encoding="utf-8")
if film_recorder:
    film_recorder.source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in target.glob("*.py")}
    film_recorder.source_hashes.update(asset_hashes)
(target / "config.json").write_text(json.dumps({
    "demo": True, "demo_keyboard": options.keyboard, "eeh_brightness": 0.03,
    "ring_brightness": 0.15,
    "idle_seconds": 60,
    "theme": options.theme, "theme_auto": False, "personal_dates": {}, "clock_style": options.clock_style,
    "bridge_url": "", "token": "", "control_token": "",
    "partner_name": "Partner", "partner_surname": "Example",
    "demo_notifications": [],
    "eeh": {"slot": 6, "type": "EEH Logo"},
    "matrix": {"slot": 2, "type": "Liteloop", "brightness": 0.35} if options.matrix_demo else False,
}), encoding="utf-8")
os.chdir(SIM)
sys.path.insert(0, str(SIM))
import run
# Preserve normal firmware import order to avoid upstream's CPython circular import.
import system.scheduler
import pygame
import _sim
from events.input import ButtonDownEvent, ButtonUpEvent
from events.keyboard import KEYBOARD_BUTTONS
from system.eventbus import eventbus
from threecx_monitor import ThreeCXMonitor
from threecx_monitor import expansions
import threecx_monitor.app as monitor_app
pygame.display.set_caption("3CX Monitor - Official Tildagon Simulator (DEMO)")

# These fixtures change supplied data only. Production drawing and call
# processing remain the exact badge source used by the official renderer.
fixture_scenes = ("idle", "long-number", "named-e164", "numeric-caller", "team-long-number", "team-internal", "team-external")

def demo_weather():
    """Synthetic values for labelled DEMO captures; no weather API request."""
    today = host_time.localtime(host_time.time())
    year, month, day = (int(value) for value in options.demo_date.split("-")) if options.demo_date else (today.tm_year, today.tm_mon, today.tm_mday)
    night = options.weather_kind in ("night", "rain-night")
    hour, minute, second = demo_hms or (21 if night else 12, 7, 0)
    now = int(host_time.mktime((year, month, day, hour, minute, second,
                               0, 0, -1))) + int(host_time.monotonic() - fixture_clock_started)
    local = host_time.localtime(now)
    kind = options.weather_kind
    current = {"temperature_c": 18.4, "apparent_temperature_c": 17.0, "condition": "Clear",
               "weather_code": 0, "is_day": not night, "wind_kmh": 8.2, "forecast_at": now}
    rain = {"status": "dry_likely", "precipitation_mm": 0.0, "onset_minutes": None,
            "window_start": now, "window_end": now + 3600, "resolution_minutes": 15,
            "interpolated": True, "basis": "model_forecast",
            "peak_overlapping_hourly_probability_percent": 5}
    if night:
        current.update(temperature_c=8.1, apparent_temperature_c=5.5)
    if kind in ("rain", "rain-night", "heavy"):
        heavy = kind == "heavy"
        current.update(temperature_c=7.3 if heavy else 10.4, apparent_temperature_c=3.8 if heavy else 8.5,
                       weather_code=65 if heavy else 63 if night else 61,
                       condition="Heavy rain" if heavy else "Rain" if night else "Light rain",
                       wind_kmh=28.8 if heavy else 14.8 if night else 12.0)
        rain.update(status="rain_likely", precipitation_mm=5.2 if heavy else 1.4 if night else 0.8,
                    onset_minutes=[0, 15] if heavy or night else [15, 30],
                    peak_overlapping_hourly_probability_percent=90 if heavy else 60)
    elif kind == "snow":
        current.update(temperature_c=-1.4, apparent_temperature_c=-4.2, weather_code=73,
                       condition="Snow", wind_kmh=16.0)
        rain.update(status="rain_likely", precipitation_mm=0.6, onset_minutes=[0, 15],
                    peak_overlapping_hourly_probability_percent=80)
    elif kind == "storm":
        current.update(temperature_c=13.0, apparent_temperature_c=10.0, weather_code=95,
                       condition="Thunderstorm", wind_kmh=38.0)
        rain.update(status="rain_likely", precipitation_mm=3.1, onset_minutes=[0, 15],
                    peak_overlapping_hourly_probability_percent=95)
    elif kind == "fog":
        current.update(temperature_c=5.0, apparent_temperature_c=2.0, weather_code=45,
                       condition="Fog", wind_kmh=4.0)
    value = {
        "status": "live", "live": True, "available": True, "stale": False, "demo": True,
        "source": "DEMO", "attribution": "Synthetic demonstration data", "location": "Westmoor",
        "now_unix": now, "local_clock": host_time.strftime("%H:%M", local),
        "local_date": host_time.strftime("%a %d %b", local),
        "local_date_iso": host_time.strftime("%Y-%m-%d", local),
        "utc_offset_seconds": -host_time.altzone if local.tm_isdst > 0 else -host_time.timezone,
        "fetched_at": now, "age_seconds": 0,
        "current": current, "rain_next_hour": rain,
    }
    if kind == "stale":
        value.update(status="stale", live=False, available=False, stale=True,
                     fetched_at=now - 2400, age_seconds=2400, current=None)
        rain.update(status="unknown", precipitation_mm=None, onset_minutes=None,
                    peak_overlapping_hourly_probability_percent=None)
    return value

if options.scene in fixture_scenes and not options.feature_demo:
    original_call_snapshot = monitor_app.snapshot
    def fixture_call_snapshot(scene):
        value = original_call_snapshot("team" if options.scene in ("idle", "team-long-number", "team-internal", "team-external") else "ddi")
        if options.scene == "idle" and options.idle_page and scene != "team":
            # Enter still generates the normal synthetic incoming-call scenes,
            # allowing the real production idle-page override to be checked.
            value = original_call_snapshot(scene)
            if scene != "internal" and value.get("alert"):
                # Reserved example number for the incoming override fixture;
                # canonical production DEMO remains unchanged.
                value["alert"]["peer_number"] = "+441632960123"
        elif options.scene == "idle":
            for member in value["team"]:
                member["state"] = "idle"
                member["calls"] = []
            value["own"]["calls"] = []
            value["alert"] = None
        elif options.scene == "team-long-number":
            call = value["team"][1]["calls"][0]
            call.update(peer_name="Example customer", peer_number="+999123456789012")
        elif options.scene in ("team-internal", "team-external"):
            for member in value["team"]:
                member["state"], member["calls"] = "idle", []
            internal = options.scene == "team-internal"
            value["team"][0].update(state="busy", calls=[{
                "id": "demo-team-status", "state": "busy", "direction": "outbound",
                "kind": "internal" if internal else "external", "priority": False,
                "peer_number": "271" if internal else "+441632960123",
                "peer_extension": "271" if internal else "",
                "peer_name": "Alex Example" if internal else "Example customer",
                "peer_first_name": "Alex" if internal else "Example",
            }])
        else:
            call = value["alert"]
            number = "+44 1632 960 123" if options.scene == "long-number" else "+999123456789012"
            call.update(peer_name="Example caller" if options.scene in ("long-number", "named-e164") else number,
                        peer_number=number)
        if options.idle_page:
            value["weather"] = demo_weather()
        return value
    monitor_app.snapshot = fixture_call_snapshot

if options.partner_demo and not options.feature_demo:
    ordinary_snapshot = monitor_app.snapshot
    def partner_snapshot(scene):
        value = ordinary_snapshot(scene)
        call = value.get("alert")
        if scene == "priority" and isinstance(call, dict):
            call.update(peer_initials="KZ", peer_name="Partner DEMO", peer_number="+441632960123")
        return value
    monitor_app.snapshot = partner_snapshot

# Official NeoPixel fake shares one ring for every chain. This independent demo
# backend passes actual adapter writes to a schematic 14-pixel extension panel.
eeh_values = [(0, 0, 0)] * 14
eeh_writes = 0
class EEHPixels:
    n = 14
    def fill(self, colour):
        self.colour = tuple(colour)
    def write(self):
        global eeh_values, eeh_writes
        eeh_values = [self.colour] * 14
        eeh_writes += 1
original_snapshot = expansions.FirmwareBackend.snapshot
original_pixels = expansions.FirmwareBackend.pixels
original_headers = expansions.FirmwareBackend.headers
original_matrix_i2c = expansions.FirmwareBackend.matrix_i2c
matrix_header = types.SimpleNamespace(vid=0xCAFE, pid=0x54E1, friendly_name="Liteloop")
class MatrixSink:
    """In-memory simulation only; never opens a physical adapter or serial port."""
    def writeto_mem(self, address, register, payload):
        return len(payload)
matrix_sink = MatrixSink()
def demo_snapshot(backend):
    drivers, attached, running = original_snapshot(backend)
    attached.add(6)
    if options.matrix_demo:
        attached.add(2)
    if options.keyboard:
        drivers[1] = types.SimpleNamespace(hexpansion_config=types.SimpleNamespace(port=1), ADDR=0x34, handle_keyboard_key=lambda key, pressed: None)
        attached.add(1)
    return drivers, attached, running
def demo_pixels(backend, slot, count):
    return EEHPixels() if slot == 6 and count == 14 else original_pixels(backend, slot, count)
def demo_headers(backend):
    headers = dict(original_headers(backend))
    if options.matrix_demo:
        headers[2] = matrix_header
    return headers
def demo_matrix_i2c(backend, slot):
    return matrix_sink if options.matrix_demo and slot == 2 else original_matrix_i2c(backend, slot)
expansions.FirmwareBackend.snapshot = demo_snapshot
expansions.FirmwareBackend.pixels = demo_pixels
expansions.FirmwareBackend.headers = demo_headers
expansions.FirmwareBackend.matrix_i2c = demo_matrix_i2c

# Computer A-F represent physical badge buttons. Other keyboard keys become
# genuine Keyboard-group events; arrows never double as held badge buttons.
original_events = _sim._sim.process_events
key_names = {pygame.K_UP:"UP", pygame.K_DOWN:"DOWN", pygame.K_LEFT:"LEFT", pygame.K_RIGHT:"RIGHT", pygame.K_ESCAPE:"ESCAPE", pygame.K_RETURN:"ENTER", pygame.K_SPACE:"SPACE", pygame.K_BACKSPACE:"BACKSPACE"}
badge_keys = [getattr(pygame, "K_" + letter) for letter in "abcdef"]
enter_events = 0
keyboard_d_down = False
def process_events():
    global enter_events, keyboard_d_down
    for event in pygame.event.get():
        if (options.keyboard and event.type in (pygame.KEYDOWN, pygame.KEYUP) and event.key == pygame.K_d
                and ((event.type == pygame.KEYDOWN and getattr(event, "mod", pygame.key.get_mods()) & pygame.KMOD_SHIFT)
                     or keyboard_d_down)):
            # PC A–F keep representing the six physical buttons. Shift+D is
            # the separate expansion-keyboard D key, including its matching Up.
            keyboard_d_down = event.type == pygame.KEYDOWN
            eventbus.emit((ButtonDownEvent if keyboard_d_down else ButtonUpEvent)(KEYBOARD_BUTTONS["D"]))
            continue
        if options.keyboard and event.type in (pygame.KEYDOWN, pygame.KEYUP) and event.key not in badge_keys:
            name = key_names.get(event.key)
            if name is None and 32 <= event.key < 127:
                name = chr(event.key).upper()
            button = KEYBOARD_BUTTONS.get(name)
            if button is not None:
                if name == "ENTER" and event.type == pygame.KEYDOWN:
                    enter_events += 1
                eventbus.emit((ButtonDownEvent if event.type == pygame.KEYDOWN else ButtonUpEvent)(button))
            continue
        pygame.event.post(event)
    original_events()
_sim._sim.process_events = process_events

preview_app = None


def feature_film_plan(app):
    """Select real production stages without modifying playback or fixtures."""
    engine = app.showcase
    if engine is None or not 1 <= engine.count <= 4096:
        raise RuntimeError("Production showcase catalogue is unavailable")
    stages = [engine.stage(index) for index in range(engine.count)]
    highlights = (
        ("Original theme", {"theme": "original", "feature": "intro"}),
        ("Weather / Original", {"theme": "original", "feature": "weather", "weather_kind": "day"}),
        ("Next-hour rain", {"theme": "original", "feature": "rain", "weather_kind": "rain"}),
        ("Celestial Atelier", {"theme": "original", "feature": "clock", "clock": "haute_celestial"}),
        ("Neon Orrery", {"theme": "original", "feature": "clock", "clock": "neon_orrery"}),
        ("Team BLF", {"theme": "original", "feature": "team"}),
        ("Team call detail", {"theme": "original", "feature": "team_detail", "detail": "internal"}),
        ("Direct call", {"theme": "original", "feature": "call", "scene": "ddi"}),
        ("Internal call", {"theme": "original", "feature": "call", "scene": "internal"}),
        ("Queue call", {"theme": "original", "feature": "call", "scene": "queue"}),
        ("Partner / priority", {"theme": "original", "feature": "call", "scene": "partner"}),
        ("Progress alert", {"theme": "original", "feature": "notification", "notification": "progress75"}),
        ("Own status / DND", {"theme": "original", "feature": "presence", "presence": "dnd"}),
        ("Christmas theme", {"theme": "christmas", "feature": "intro"}),
        ("Weather / Christmas", {"theme": "christmas", "feature": "weather", "weather_kind": "day"}),
        ("Christmas Advent", {"theme": "christmas", "feature": "advent"}),
    )
    plan = []
    for label, selector in highlights:
        stage = next((item for item in stages if all(item.get(key) == value for key, value in selector.items())), None)
        if stage is None:
            raise RuntimeError("Missing production showcase highlight: " + label)
        plan.append({"at": len(plan) * options.seconds / len(highlights), "label": "CUT / " + label,
                     "stage_index": stage["index"], "manual_feature_jump": True,
                     "production_showcase": True, **selector})
    return plan


def feature_stage_metadata():
    stage = getattr(preview_app, "_showcase_stage", None)
    if not isinstance(stage, dict):
        return None
    return {key: stage.get(key) for key in ("index", "theme", "theme_name", "feature", "clock", "scene", "date", "weather_kind",
                                           "notification", "presence", "theme_index", "theme_count",
                                           "step_index", "step_count", "paused", "loop")}


def apply_film_event(event):
    """Change synthetic inputs, then let the production app draw each view."""
    global film_label, fixture_clock_started, demo_hms
    app = preview_app
    if app is None:
        return
    if options.feature_demo:
        app._showcase_seek(event["stage_index"])
        stage = feature_stage_metadata()
        if not stage or stage["index"] != event["stage_index"]:
            raise RuntimeError("Production showcase jump was not applied")
        film_label = event["label"]
        film_recorder.events.append(dict(event, at=round(film_recorder.elapsed(), 6)))
        return
    if options.showcase == "rail" and event.get("synthetic_time"):
        # Each explicitly labelled synthetic time cut then runs at real speed.
        options.demo_time = event["synthetic_time"]
        demo_hms = tuple(int(part) for part in options.demo_time.split(":"))
        fixture_clock_started = host_time.monotonic()
    app.settings_open = False
    app.controller.detail_view = False
    app.controller.own_view = False
    app._brightness_notice_until = 0
    app.controls.message_until = 0
    if "kind" in event:
        options.weather_kind = event["kind"]
    if "theme" in event:
        options.theme = event["theme"]
        app.config.update(theme=options.theme, theme_auto=False)
        app.themes.select(options.theme)
    if "clock" in event:
        options.clock_style = event["clock"]
        app.config["clock_style"] = options.clock_style
        app.clock_style = options.clock_style
    if "date" in event:
        options.demo_date = event["date"]
    if "notification" in event:
        options.notification = event["notification"]
        app.config["demo_notifications"] = [demo_notification(options.notification, event.get("notification_id"),
                                                               event.get("progress"))]
    options.scene = "team-internal" if event.get("view") in ("team", "settings") else "idle"
    from threecx_monitor.demo import SCENARIOS
    app.demo_scene = SCENARIOS.index(event.get("scene", "team"))
    app._accept_demo()
    now = app._now()
    idle = app.idle_pages
    app._observe_idle(now)
    if "page" in event:
        # Skip only the quiet waiting period in this labelled demonstration.
        # The actual production face-arrival and call rendering remain intact.
        idle._quiet_since = now - idle.idle_after_ms - 1
        idle._rotation_at = now
        idle._rotation_index = idle.pages.index(event["page"])
    else:
        idle.touch(now)
    if event.get("view") == "settings":
        app._open_settings()
    film_label = event["label"]
    film_recorder.events.append(dict(event, at=round(film_recorder.elapsed(), 6)))
class PreviewMonitor(ThreeCXMonitor):
    def __init__(self):
        global preview_app
        super().__init__()
        preview_app = self
        if options.feature_demo:
            # The genuine showcase starts once this app is foregrounded after
            # boot. None of the legacy simulator fixtures modifies its state.
            return
        if options.detail:
            self.controller.detail_view = True
        if options.scene not in ("team",) + fixture_scenes:
            from threecx_monitor.demo import SCENARIOS
            self.demo_scene = SCENARIOS.index(options.scene)
            self.controller.accept(monitor_app.snapshot(options.scene), self._now())
        if options.idle_page:
            idle = getattr(self, "idle_pages", None)
            if idle is None:
                raise RuntimeError("The badge idle-page UI is not available yet")
            if options.record and options.showcase in ("atelier", "rail"):
                # These selective two-face films extend only DEMO rotation
                # dwell, leaving animation timing and production drawing intact.
                idle.rotate_ms = max(idle.rotate_ms, int(options.seconds * 1000) + 1000)
            requested_page = options.idle_page
            if options.component_theme and requested_page == "advent" and requested_page not in idle.pages:
                idle.pages.append("advent")
            now = self._now()
            self._observe_idle(now)
            self.clock_ms += idle.idle_after_ms + idle.pages.index(requested_page) * idle.rotate_ms + 50
            # Keep source age fresh across the simulated elapsed quiet period.
            self._accept_demo()
            now = self._now()
            idle.observe(self.controller.payload, self.controller.live(now), now)
            # Dynamic seasonal/sky pages may reset their rotation origin while
            # the fixture advances past the quiet wait. Select the requested
            # page explicitly, then let normal production rotation continue.
            idle._quiet_since = now - idle.idle_after_ms - 1
            idle._rotation_at = now
            idle._rotation_index = idle.pages.index(requested_page)
        if options.notification:
            # Deliver the synthetic event after the fixture skips its quiet
            # wait, so the production10-second toast does not elapse offscreen.
            self.config["demo_notifications"] = [demo_notification(options.notification)]
            self._accept_demo()

    def _draw_idle(self, ctx, now):
        if options.component_theme:
            from threecx_monitor.theme_art import draw_theme_face
            from threecx_monitor.themes import ThemeManager
            from threecx_monitor.controls import own_colour
            weather, fresh, elapsed = self._weather(now)
            local = self._local_weather_time(weather, elapsed)
            context = ThemeManager(self.config).resolve(local)
            if draw_theme_face(ctx, self.idle_pages.page(now), options.theme, weather, fresh, local,
                               elapsed, now, own_colour(self._status_payload(), self.controller.live(now), now, 1.0),
                               demo=True, context=context):
                return
        return super()._draw_idle(ctx, now)
preview_module = types.ModuleType("simulator_preview")
preview_module.PreviewMonitor = PreviewMonitor
sys.modules["simulator_preview"] = preview_module
_sim.screen = pygame.display.set_mode((1040, 733))
original_render = _sim._sim.render_gui_now
frames = 0
native_screenshot = None
latest_render_status = None
gallery_stills_saved = set()
notification_fixture_opened = False
feature_started_frame = None
rail_started_frame = None
def side_text(text, y, size=20, colour=(220,230,240)):
    font = pygame.font.Font(None, size)
    _sim.screen.blit(font.render(text, True, colour), (755,y))
def report_render():
    global frames, film_event_index, native_screenshot, latest_render_status, notification_fixture_opened
    global feature_started_frame, rail_started_frame, film_plan
    if options.screenshot:
        native_screenshot = pygame.Surface((240, 240))
        native_screenshot.fill((0, 0, 0))
        native_screenshot.blit(_sim._sim._oled_surface, (0, 0))
    original_render()
    frames += 1
    scheduler = system.scheduler.scheduler
    boot_overlay = any(item.__class__.__name__ == "BoopSpinner" for item in scheduler.on_top_stack)
    app_ready = preview_app is not None and scheduler.app_is_foregrounded(preview_app) and not boot_overlay
    if options.screenshot and not app_ready:
        _sim.SCREENSHOT_DELAY = max(2, _sim.SCREENSHOT_DELAY)
    if options.showcase == "rail" and film_recorder and app_ready and rail_started_frame is None:
        apply_film_event(film_plan[0])
        film_event_index = 1
        rail_started_frame = frames
    if options.feature_demo and app_ready and feature_started_frame is None:
        if getattr(preview_app, "showcase", None) is None and not preview_app._start_showcase():
            raise RuntimeError("The production showcase did not start")
        feature_started_frame = frames
        if options.feature_stage is not None:
            if options.feature_stage >= preview_app.showcase.count:
                raise RuntimeError("The requested production showcase stage does not exist")
            preview_app._showcase_seek(options.feature_stage)
        if film_recorder:
            film_plan = feature_film_plan(preview_app)
            apply_film_event(film_plan[0])
            film_event_index = 1
        if options.screenshot:
            _sim.SCREENSHOT_DELAY = max(3, _sim.SCREENSHOT_DELAY)
    showcase_active = bool(getattr(preview_app, "showcase", None))
    feature_stage = feature_stage_metadata()
    if options.notification and app_ready and not notification_fixture_opened:
        # Equivalent to opening the production inbox with N. Do this after
        # the upstream boot overlay, which may outlast an automatic toast.
        preview_app._open_notifications()
        notification_fixture_opened = True
        if options.screenshot:
            _sim.SCREENSHOT_DELAY = max(2, _sim.SCREENSHOT_DELAY)
    pygame.draw.rect(_sim.screen, (16,22,31), (733,0,307,733))
    side_text("EEH LOGO", 38, 32)
    side_text("SIMULATED HEXPANSIONS" if options.matrix_demo else "SIMULATED HEXPANSION", 76, 17, (140,160,180))
    side_text("Slot 6 / 14 LEDs / own status", 102, 20)
    if showcase_active:
        side_text("PRODUCTION SHOWCASE / DEMO", 126, 17, (240,205,100))
    elif options.idle_page:
        side_text("WEATHER = SYNTHETIC DEMO", 126, 17, (240,205,100))
    for index, colour in enumerate(eeh_values):
        # Schematic fixture view; no claim about the PCB's LED placement.
        rgb = tuple(max(0,min(255,int(channel))) for channel in colour)
        if options.matrix_demo:
            x,y = 780+(index%7)*35,160+(index//7)*33
            pygame.draw.circle(_sim.screen, (35,45,58), (x,y), 12)
            pygame.draw.circle(_sim.screen, rgb, (x,y), 9)
        else:
            x,y = 800+(index%2)*100,160+(index//2)*48
            pygame.draw.circle(_sim.screen, (35,45,58), (x,y), 18)
            pygame.draw.circle(_sim.screen, rgb, (x,y), 13)
    if options.matrix_demo and preview_app is not None:
        from threecx_monitor.matrix import GRID
        matrix = preview_app.matrix
        side_text("LITELOOP / GLYPH DIAGRAM", 224, 21)
        side_text("Simulated156-LED monochrome output", 252, 16, (140,160,180))
        for cell, address in enumerate(GRID):
            if address < 0:
                continue
            level = matrix._actual[address] if matrix._known[address] else 0
            shade = 27 if not level else min(255, 55 + level * 200 // 90)
            pygame.draw.circle(_sim.screen, (shade, shade, shade),
                               (777 + cell % 18 * 13, 282 + cell // 18 * 14), 4)
        side_text("Mode: " + str(matrix.displayed_mode or matrix.last_mode or "initializing"), 420, 20, (180,200,220))
        side_text("Diagram only / no physical LED footage", 448, 16, (240,205,100))
    eeh_level = getattr(getattr(preview_app, "controller", None), "eeh_brightness", 0.03)
    ring_level = getattr(getattr(preview_app, "controller", None), "ring_brightness", 0.15)
    side_text("Ring %d%% / EEH %d%%" % (round(ring_level * 100), round(eeh_level * 100)), 489, 21, (140,160,180))
    side_text("Priority 100%; EEH RGB " + "/".join(str(c) for c in eeh_values[0]), 512, 17, (140,160,180))
    side_text("Keyboard: " + ("attached" if options.keyboard else "unplugged"), 535, 23)
    settings_open = bool(getattr(preview_app, "settings_open", False))
    idle = getattr(preview_app, "idle_pages", None)
    idle_page = idle.page(preview_app._now()) if idle is not None else None
    if showcase_active:
        side_text("Shift+D / Esc = stop demo", 570, 20)
        side_text("Enter / Space = pause", 594, 20)
        side_text("Left / Right = feature", 618, 20)
        side_text("Up / Down = theme", 642, 20)
        side_text("Continuous on the badge", 666, 20)
        side_text("Film uses labelled feature cuts" if options.record else "All features, then next theme", 690, 18)
    elif settings_open:
        side_text("Up / Down = select setting", 570, 20)
        side_text("Left / Right = adjust 1%", 594, 20)
        side_text("Enter / C = start demo" if preview_app.settings_selected == 4 else "Enter / Space = done", 618, 20)
        side_text("A / D = select", 642, 20)
        side_text("B / E = adjust", 666, 20)
        side_text("C / F = done", 690, 20)
    elif options.keyboard and idle_page:
        side_text("Left / Right = idle pages", 570, 20)
        side_text("Enter = demo incoming call", 594, 20)
        side_text("Space = team overview", 618, 20)
        side_text("S = brightness settings", 642, 20)
        side_text("A-F = badge buttons", 666, 20)
        side_text("Esc = exit", 690, 20)
    elif options.keyboard:
        side_text("A-F = badge buttons", 570, 20)
        side_text("Enter = next call scene", 594, 20)
        side_text("Space = own / team", 618, 20)
        side_text("Left / Right = select team", 642, 20)
        side_text("S = brightness settings", 666, 20)
        side_text("Esc = exit", 690, 20)
    else:
        side_text("A-F = badge buttons", 570, 20)
        side_text("Hold C = brightness settings", 594, 20)
    side_text("Offline demo / no real calls", 710, 19, (90,210,170))
    pygame.display.flip()
    if options.settings and frames in (6, 9):
        kind = pygame.KEYDOWN if frames == 6 else pygame.KEYUP
        pygame.event.post(pygame.event.Event(kind, key=pygame.K_s))
    if options.action and frames in (options.action_frame,options.action_frame + max(1, options.action_hold_frames)):
        kind = pygame.KEYDOWN if frames == options.action_frame else pygame.KEYUP
        if options.action == "SHIFT+D":
            pygame.event.post(pygame.event.Event(kind, key=pygame.K_d,
                                               mod=pygame.KMOD_SHIFT if kind == pygame.KEYDOWN else 0))
        else:
            action_key = {"ENTER":pygame.K_RETURN, "SPACE":pygame.K_SPACE, "UP":pygame.K_UP,
                          "DOWN":pygame.K_DOWN, "LEFT":pygame.K_LEFT, "RIGHT":pygame.K_RIGHT}.get(options.action)
            if action_key is None:
                action_key = getattr(pygame,"K_"+options.action.lower())
            pygame.event.post(pygame.event.Event(kind, key=action_key))
    alerting = preview_app is not None and preview_app.controller.alert(preview_app._now()) is not None
    visible_notification = preview_app._visible_notification(preview_app._now()) if preview_app else None
    if options.screenshot and alerting and not any(any(c>0 for c in led) for led in _sim._sim.led_state[1:13]):
        _sim.SCREENSHOT_DELAY = max(2,_sim.SCREENSHOT_DELAY)
    if options.screenshot and alerting and options.partner_demo and max(eeh_values[0]) < 128:
        # Pick a real bright heartbeat frame for the still; recordings keep
        # every observed pulse phase and retain their actual capture timing.
        _sim.SCREENSHOT_DELAY = max(2, _sim.SCREENSHOT_DELAY)
    latest_render_status = {
        "pid": os.getpid(), "driver": pygame.display.get_driver(), "active": pygame.display.get_active(),
        "initialized": pygame.display.get_init(), "size": pygame.display.get_surface().get_size(),
        "caption": pygame.display.get_caption()[0], "frames": frames, "demo_keyboard": options.keyboard,
        "eeh_writes": eeh_writes, "eeh_rgb": eeh_values[0], "eeh_default_brightness": 0.03,
        "eeh_brightness": eeh_level, "ring_brightness": ring_level, "idle_page": idle_page,
        "weather_kind": feature_stage["weather_kind"] if feature_stage else options.weather_kind, "weather_is_synthetic": True,
        "theme": feature_stage["theme"] if feature_stage else options.theme,
        "clock_style": feature_stage["clock"] if feature_stage else options.clock_style,
        "demo_date": feature_stage["date"] if feature_stage else options.demo_date,
        "demo_time": options.demo_time,
        "component_preview": options.component_theme, "partner_demo": options.partner_demo,
        "matrix_diagram": options.matrix_demo, "alerting": alerting, "heartbeat": host_time.time(),
        "notification_fixture": options.notification,
        "notification_visible": bool(visible_notification),
        "demo_scene": getattr(preview_app, "demo_scene", None), "enter_events": enter_events,
        "production_showcase": options.feature_demo,
        "showcase_active": showcase_active, "showcase_stage": feature_stage,
    }
    if options.matrix_demo and preview_app is not None:
        latest_render_status["matrix_mode"] = preview_app.matrix.displayed_mode
    if frames in (1,5) or frames % 20 == 0:
        name = "status-record.json" if options.record else "status-capture.json" if options.screenshot else "status.json"
        with open(str(RUN / name),"w") as handle:
            json.dump(latest_render_status, handle)
    if (film_recorder is not None and app_ready and frames >= 8
            and (not options.feature_demo or (feature_started_frame is not None and frames >= feature_started_frame + 2))
            and (options.showcase != "rail" or (rail_started_frame is not None and frames >= rail_started_frame + 2))):
        if options.record_view == "lcd":
            recorded = pygame.Surface((240, 240))
            recorded.fill((0, 0, 0))
            recorded.blit(_sim._sim._oled_surface, (0, 0))
        else:
            recorded = _sim.screen.copy()
        alert = preview_app.controller.alert(preview_app._now())
        metadata = {"label": film_label, "page": idle_page, "weather_kind": options.weather_kind,
                    "alerting": bool(alert), "priority": bool(alert and alert.get("priority")),
                    "ring_rgb": list(_sim._sim.led_state[1:13]), "eeh_rgb": list(eeh_values[0]),
                    "settings": settings_open, "theme": options.theme, "clock_style": options.clock_style}
        metadata.update(notification_fixture=options.notification, notification_visible=bool(visible_notification),
                        notification_progress=visible_notification.get("progress") if visible_notification else None)
        if options.showcase == "rail":
            supplied_weather, supplied_fresh, supplied_elapsed = preview_app._weather(preview_app._now())
            supplied_local = preview_app._local_weather_time(supplied_weather, supplied_elapsed)
            metadata["synthetic_local_time"] = ("%02d:%02d:%02d" % tuple(supplied_local[3:6])
                                                 if supplied_local else None)
            metadata["clock_elapsed_ms"] = supplied_elapsed
        if options.feature_demo:
            metadata.update(production_showcase=True, abbreviated_showcase=True, manual_feature_jumps=True,
                            showcase_stage=feature_stage, theme=feature_stage["theme"],
                            clock_style=feature_stage["clock"], weather_kind=feature_stage["weather_kind"])
        if options.matrix_demo:
            metadata.update(matrix_diagram=True, matrix_mode=preview_app.matrix.displayed_mode,
                            matrix_simulated_frames=preview_app.matrix.frames_written)
        if film_recorder.capture(pygame, recorded, metadata):
            sys.exit(0)
        elapsed = film_recorder.elapsed()
        if options.gallery_stills:
            for index, event in enumerate(film_plan):
                end = film_plan[index + 1]["at"] if index + 1 < len(film_plan) else options.seconds
                target_time = event["at"] if options.feature_demo and event.get("scene") == "partner" else (event["at"] + end) / 2
                if elapsed < target_time:
                    continue
                if options.feature_demo and (not feature_stage or feature_stage["index"] != event["stage_index"]):
                    continue
                stem = None
                if options.feature_demo:
                    stem = "showcase-%02d-%s" % (index + 1, event["feature"])
                elif options.showcase == "themes":
                    stem = "theme-advent" if event.get("page") == "advent" else "theme-" + event["theme"]
                elif options.showcase == "atelier":
                    stem = "clocks-atelier-" + event["clock"]
                elif options.showcase == "rail":
                    stem = "clock-" + event["clock"]
                elif options.showcase == "clocks":
                    stem = "clock-" + event["clock"]
                elif options.showcase == "sky":
                    stem = "sky-" + event["page"]
                elif options.showcase == "notifications":
                    if event.get("scene"):
                        stem = "notification-call-preemption"
                    elif event.get("notification_id") == "demo-call-preemption":
                        stem = "notification-resumed"
                    elif event.get("progress") == 75:
                        stem = "notification-progress-update"
                    else:
                        stem = "notification-" + event["notification"]
                elif options.showcase == "calls" and options.partner_demo and event.get("scene") == "priority":
                    stem = "partner-call"
                elif options.showcase == "idle" and options.clock_style == "corpus":
                    stem = "clock-corpus"
                if stem is None or stem in gallery_stills_saved:
                    continue
                if stem == "partner-call" and max(eeh_values[0]) < 128:
                    continue
                if (options.feature_demo and event.get("scene") == "partner"
                        and ((eeh_level > 0 and eeh_values[0][0] == 0)
                             or (options.matrix_demo and preview_app.matrix.displayed_mode != "heart"))):
                    # Choose an actual red heartbeat still; the film keeps
                    # all observed phases and its original elapsed timing.
                    continue
                destination = film_recorder.output.parent
                pygame.image.save(_sim.screen, str(destination / (stem + ".png")))
                native = pygame.Surface((240, 240))
                native.fill((0, 0, 0))
                native.blit(_sim._sim._oled_surface, (0, 0))
                pygame.image.save(native, str(destination / (stem + "-lcd.png")))
                with open(str(destination / (stem + "-capture.json")), "w") as handle:
                    json.dump(latest_render_status, handle)
                film_recorder.stills.append({"file": stem + ".png", "native_file": stem + "-lcd.png",
                                             "at": round(elapsed, 6), "label": event["label"]})
                gallery_stills_saved.add(stem)
        while film_event_index < len(film_plan) and elapsed >= film_plan[film_event_index]["at"]:
            apply_film_event(film_plan[film_event_index])
            film_event_index += 1
_sim._sim.render_gui_now = report_render
_sim.SCREENSHOT_DELAY = options.capture_frames or (max(options.action_frame + max(1, options.action_hold_frames) + 25, 40) if options.action or options.settings else 8)
sys.argv = [str(SIM/"run.py")] + (["--screenshot"] if options.screenshot else []) + ["simulator_preview.PreviewMonitor"]
try:
    run.sim_main()
except SystemExit as stopped:
    if options.record and stopped.code in (None, 0) and film_recorder.finished:
        encoder_log = str(film_recorder.directory / "encode.log")
        with open(encoder_log, "w", encoding="utf-8") as log:
            completed = subprocess.run([sys.executable, str(HERE / "film_encode.py"),
                                        str(film_recorder.directory)], stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if completed.returncode:
            print("DEMO video encoding failed; see", encoder_log)
            raise SystemExit(completed.returncode)
        print("Official simulator DEMO video exported:", str(film_recorder.output))
    if options.screenshot and capture_output and stopped.code in (None, 0):
        # Firmware mocks every inode/device as0. shutil.copyfile's same-file
        # check therefore rejects different paths when replacing an old capture.
        capture_input = SIM / "flow3r.png"
        if capture_output != capture_input:
            with open(str(capture_input), "rb") as source, open(str(capture_output), "wb") as destination:
                shutil.copyfileobj(source, destination)
        if native_screenshot is not None:
            pygame.image.save(native_screenshot, str(capture_output.with_name(capture_output.stem + "-lcd.png")))
        if latest_render_status is not None:
            with open(str(capture_output.with_name(capture_output.stem + "-capture.json")), "w") as destination:
                json.dump(latest_render_status, destination)
        print("DEMO capture exported:", str(capture_output))
    raise
