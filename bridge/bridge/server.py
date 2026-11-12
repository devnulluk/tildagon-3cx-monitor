"""Small authenticated badge-facing HTTP service and command-line entry point."""

import argparse
import asyncio
import hmac
import json
import logging
import math
import os
import re
import time
from pathlib import Path

from aiohttp import web

from .config import load_config, validate_config, validate_weather_config
from .model import build_state, normalize_number
from .transport import ThreeCXTransport


def _stale(config, source):
    age = source.age_seconds
    return (not math.isfinite(age)
            or age > float(config.get("stale_after_seconds", 5)))


def create_app(config, source, token=None, demo=False, control_token=None, actions=None, presence_provider=None, phonebook=None, weather=None):
    if not demo and (not isinstance(token, str) or len(token) < 24):
        raise ValueError("BRIDGE_TOKEN must contain at least 24 characters")
    if token is not None and (not isinstance(token, str) or not token.isascii()
                              or any(c.isspace() for c in token)):
        raise ValueError("BRIDGE_TOKEN must be ASCII without whitespace")
    if control_token is not None:
        if (not isinstance(control_token, str) or len(control_token) < 24
                or not control_token.isascii() or any(c.isspace() for c in control_token)):
            raise ValueError("BRIDGE_CONTROL_TOKEN must be at least 24 ASCII characters without whitespace")
        if token and hmac.compare_digest(control_token, token):
            raise ValueError("Read and control tokens must be different")
    if actions is None and control_token:
        from .actions import ActionController
        actions = ActionController(source, config, demo=demo, presence_provider=presence_provider)
    if phonebook is None and presence_provider is not None and config.get("phonebook_lookup") is True and not demo:
        from .contacts import PhonebookResolver
        phonebook = PhonebookResolver(presence_provider, country_code=config.get("country_code", "44"))
    weather_config = validate_weather_config(config.get("weather", {"enabled": False}))
    if demo:
        weather = None
    elif weather is None and weather_config["enabled"]:
        from .weather import WeatherService
        weather = WeatherService(weather_config["latitude"], weather_config["longitude"],
                                 location=weather_config["location"], timezone=weather_config["timezone"],
                                 api_key=os.environ.get("WEATHER_API_KEY") or None)

    def authorized(request, expected_token):
        value = request.headers.get("Authorization", "")
        return bool(expected_token and value.isascii()
                    and hmac.compare_digest(value, "Bearer " + expected_token))

    @web.middleware
    async def no_store(request, handler):
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            exc.headers["Cache-Control"] = "no-store"
            exc.headers["X-Content-Type-Options"] = "nosniff"
            raise
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def state(request):
        if token:
            expected = "Bearer " + token
            supplied = request.headers.get("Authorization", "")
            if not supplied.isascii() or not hmac.compare_digest(supplied, expected):
                return web.json_response({"error": "unauthorized"}, status=401,
                                         headers={"WWW-Authenticate": "Bearer"})
        state_config = dict(config)
        if phonebook is not None:
            state_config["phonebook_contacts"] = phonebook.cached_contacts()
            state_config["directory_names"] = phonebook.cached_extensions()
        body = build_state(state_config, source.snapshot, connected=source.connected,
                           age_seconds=source.age_seconds, demo=demo,
                           status=source.status)
        if phonebook is not None and body["connected"]:
            manual = {normalize_number(number, config.get("country_code", "44")) for number in config.get("contacts", {})}
            numbers = []
            for call in body["own"]["calls"]:
                number = call.get("peer_number")
                if call.get("kind") != "internal" and normalize_number(number, config.get("country_code", "44")) not in manual:
                    numbers.append(number)
            phonebook.observe(numbers)
            extensions = [call.get("peer_extension") for member in [body["own"]] + body["team"]
                          for call in member["calls"]
                          if call.get("kind") == "internal" and not call.get("peer_first_name")]
            phonebook.observe_extensions(extensions)
        elif phonebook is not None:
            phonebook.observe([])
            phonebook.observe_extensions([])
        body["own"]["presence"] = (dict(actions.own_presence) if actions else
                                      {"state": "unknown", "confirmed": False,
                                       "profile": "", "age_seconds": None})
        controls = dict(actions.capabilities()) if actions else {}
        controls["enabled"] = bool(control_token and actions)
        controls.setdefault("call", controls.get("call_enabled", False))
        controls.setdefault("dnd", controls.get("dnd_enabled", False))
        controls.setdefault("targets", controls.get("speed_dials", []))
        body["controls"] = controls
        body["phonebook"] = {"enabled": phonebook is not None, "scope": "company_and_personal" if phonebook is not None else ""}
        if weather is None:
            body["weather"] = {"enabled": False}
        else:
            try:
                body["weather"] = dict(weather.snapshot())
            except Exception:
                # Weather must never interrupt call monitoring or expose a
                # provider error containing an API key/location request URL.
                body["weather"] = {"enabled": True, "available": False, "status": "unavailable",
                                   "error": "Weather update unavailable",
                                   "rain_next_hour": {"status": "unknown", "precipitation_mm": None}}
        return web.json_response(body)

    async def control(request):
        if not control_token or actions is None:
            return web.json_response({"error": "controls_disabled", "message": "Controls are not configured"}, status=503)
        if not authorized(request, control_token):
            return web.json_response({"error": "unauthorized"}, status=401,
                                     headers={"WWW-Authenticate": "Bearer"})
        if "Origin" in request.headers:
            return web.json_response({"error": "browser_request_denied"}, status=403)
        try:
            if request.content_type != "application/json":
                raise ValueError()
            data = await request.json()
            action = request.match_info["action"]
            required = {"request_id", "session_id", "target" if action == "call" else "enabled"}
            if not isinstance(data, dict) or set(data) != required:
                raise ValueError()
            for field in ("request_id", "session_id"):
                value = data[field]
                pattern = r"[0-9a-f]{32}" if field == "session_id" else r"[A-Za-z0-9_-]{16,96}"
                if not isinstance(value, str) or not re.fullmatch(pattern, value):
                    raise ValueError()
            if action == "call":
                if not isinstance(data["target"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", data["target"]):
                    raise ValueError()
            elif not isinstance(data["enabled"], bool):
                raise ValueError()
        except web.HTTPRequestEntityTooLarge:
            raise
        except (ValueError, TypeError, KeyError):
            return web.json_response({"error": "invalid_request", "message": "Invalid control request"}, status=400)
        try:
            if action == "call":
                result = await actions.make_call(data["target"], data["request_id"], data["session_id"])
            else:
                result = await actions.set_dnd(data["enabled"], data["request_id"], data["session_id"])
        except Exception as error:
            from .actions import ActionError
            if isinstance(error, ActionError):
                return web.json_response({"error": error.code, "message": error.message}, status=error.http_status)
            logging.getLogger(__name__).error("Control backend failed")
            return web.json_response({"error": "control_failure", "message": "Control request failed"}, status=500)
        return web.json_response(result, status=202 if result.get("status") in ("pending", "unknown") else 200)

    async def health(request):
        stale = _stale(config, source)
        healthy = bool(source.connected and not stale)
        return web.json_response({"status": "ok" if healthy else "degraded",
                                  "connected": bool(source.connected),
                                  "stale": stale, "demo": demo},
                                 status=200 if healthy else 503)

    app = web.Application(middlewares=[no_store], client_max_size=1024)
    app.router.add_get("/v1/state", state)
    app.router.add_get("/healthz", health)
    app.router.add_post("/v1/control/{action:call|dnd}", control)

    if hasattr(source, "run"):
        async def transport_lifetime(app):
            task = asyncio.create_task(source.run())
            yield
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        app.cleanup_ctx.append(transport_lifetime)
    if actions is not None and hasattr(actions, "run"):
        async def actions_lifetime(app):
            task = asyncio.create_task(actions.run())
            yield
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if hasattr(actions, "close"):
                await actions.close()
            if presence_provider is not None:
                await presence_provider.close()
        app.cleanup_ctx.append(actions_lifetime)
    if phonebook is not None:
        async def phonebook_lifetime(app):
            yield
            await phonebook.close()
        app.cleanup_ctx.append(phonebook_lifetime)
    if weather is not None:
        async def weather_lifetime(app):
            try:
                await weather.start()
            except Exception:
                logging.getLogger(__name__).warning("Weather background service could not start")
            yield
            try:
                await weather.close()
            except Exception:
                logging.getLogger(__name__).warning("Weather background service could not close")
        app.cleanup_ctx.append(weather_lifetime)
    return app


DEMO_CONFIG = {
    "own_extension": "100", "own_name": "Demo user",
    "team": [{"extension": "101", "name": "Alex"},
             {"extension": "102", "name": "Sam"},
             {"extension": "103", "name": "Jo"}],
    "queues": {"800": "Support"}, "trunk_dns": ["10000"],
    "priority_callers": ["+441632960002"], "priority_ddis": [],
    "priority_extensions": [], "contacts": {"+441632960001": "Demo caller"},
    "ddis": {"+441632960100": "Direct line"},
    "internal_extensions": {"100": "Demo user", "101": "Alex", "102": "Sam", "103": "Jo"},
}


class DemoSource:
    connected = True
    age_seconds = 0.0
    status = "demo"

    def __init__(self, config):
        self._config = config
        self._started = time.monotonic()

    @property
    def snapshot(self):
        config = self._config
        own = str(config["own_extension"])
        team = config.get("team", [])
        dns = [{"dn": own, "type": "Wextension", "devices": [{"dn": own}],
                "participants": []}]
        dns.extend({"dn": str(p["extension"]), "type": "Wextension",
                    "devices": [{"dn": str(p["extension"])}], "participants": []}
                   for p in team)

        def leg(dn, status, number, name, callid, internal=False, **extra):
            return dict({"id": callid, "callid": callid, "legid": callid,
                         "dn": dn, "status": status, "party_caller_id": number,
                         "party_caller_name": name,
                         "party_dn": number if internal else "10000",
                         "party_dn_type": "Wextension" if internal else "Wexternalline",
                         "_direction": "inbound"}, **extra)

        if team:
            dn = str(team[0]["extension"])
            dns[1]["participants"] = [leg(dn, "Connected", "+441632960001", "Demo customer", 1)]
        if len(team) > 1:
            dn = str(team[1]["extension"])
            dns[2]["participants"] = [leg(dn, "Hold", "+441632960003", "Demo supplier", 2)]
        scenario = int((time.monotonic() - self._started) / 8) % 5
        if scenario == 0:
            return dns
        queue = next(iter(config.get("queues", {})), "800")
        ddi = next(iter(config.get("ddis", {})), "+441632960100")
        if scenario == 1:
            dns[0]["participants"] = [leg(own, "Ringing", "+441632960001", "Demo DDI caller", 10,
                                                party_did=ddi)]
        elif scenario == 2:
            internal = str(team[-1]["extension"]) if team else "104"
            dns[0]["participants"] = [leg(own, "Ringing", internal, "Demo internal caller", 11,
                                                internal=True)]
        elif scenario == 3:
            dns[0]["participants"] = [leg(own, "Ringing", "+441632960001", "Demo queue caller", 12,
                                                referred_by_dn=queue, referred_by_type="Wqueue")]
        else:
            numbers = config.get("priority_callers", [])
            number = str(numbers[0]) if numbers else "+441632960002"
            dns[0]["participants"] = [leg(own, "Ringing", number, "Demo priority caller", 13)]
        return dns


def main(argv=None):
    parser = argparse.ArgumentParser(description="3CX state and own-extension controls for Tildagon")
    parser.add_argument("--config", default=None,
                        help="Bridge JSON file (otherwise BRIDGE_CONFIG_JSON, then config.json)")
    parser.add_argument("--demo", action="store_true", help="Cycle synthetic calls without connecting to a PBX")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    try:
        # An explicit file always wins. The environment option makes Docker /
        # Portainer deployment possible without a host-side configuration mount.
        # An invalid or empty environment value fails validation rather than
        # silently selecting a different configuration.
        if args.config is None and "BRIDGE_CONFIG_JSON" in os.environ:
            try:
                raw_config = json.loads(os.environ["BRIDGE_CONFIG_JSON"])
            except json.JSONDecodeError as exc:
                raise ValueError("BRIDGE_CONFIG_JSON must contain valid JSON") from exc
            config = validate_config(raw_config)
        else:
            config_path = args.config or "config.json"
            config = (load_config(config_path) if Path(config_path).is_file() or not args.demo
                      else DEMO_CONFIG)
        token = os.environ.get("BRIDGE_TOKEN") or None
        if args.demo:
            source = DemoSource(config)
        else:
            source = ThreeCXTransport(os.environ.get("PBX_URL", ""),
                                      os.environ.get("PBX_CLIENT_ID", ""),
                                      os.environ.get("PBX_CLIENT_SECRET", ""),
                                      refresh_seconds=config.get("refresh_interval_seconds", 2),
                                      token_format=os.environ.get("PBX_TOKEN_FORMAT", "multipart"))
        control_token = os.environ.get("BRIDGE_CONTROL_TOKEN") or None
        presence_provider = None
        if control_token and not args.demo:
            from .presence import presence_provider_from_env, PresenceError
            try:
                presence_provider = presence_provider_from_env(os.environ.get("PBX_URL", ""), config["own_extension"])
            except PresenceError:
                logging.getLogger(__name__).warning("Own presence needs a new login grant; call monitoring remains enabled")
        app = create_app(config, source, token=token, demo=args.demo,
                         control_token=control_token, presence_provider=presence_provider)
    except (ValueError, OSError) as exc:
        # Validation exceptions are designed to describe fields, never their values.
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.demo:
        logging.getLogger(__name__).warning("DEMO MODE: all call activity is synthetic")
    web.run_app(app, host=args.host, port=args.port, access_log=None,
                print=lambda message: logging.getLogger(__name__).info("Bridge HTTP service started"))
