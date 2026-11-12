"""Narrow, explicitly requested badge controls with no automatic write retries.

The caller authenticates with a separate control token in server.py. This module
only calls the configured own extension and resolves speed-dial IDs on the
server. A server epoch prevents old requests from being replayed after restart.
"""

import asyncio
import math
import re
import secrets
import time
from urllib.parse import quote

import aiohttp

from .transport import BridgeTransportError


class ActionError(Exception):
    def __init__(self, code, http_status, message):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message = message


class ActionController:
    MAX_HISTORY = 4096
    REQUEST_TIMEOUT = 8.0
    COOLDOWN_SECONDS = 3.0

    def __init__(self, source, config, demo=False, presence_provider=None):
        self.source = source
        self.config = config
        self.demo = bool(demo)
        self.presence_provider = presence_provider
        self.session_id = secrets.token_hex(16)
        self._own_extension = str(config.get("own_extension", ""))
        if not re.fullmatch(r"[A-Za-z0-9]{1,32}", self._own_extension):
            raise ValueError("Controls require a valid own_extension")
        self._speed_dials = {}
        for target in config.get("speed_dials", []):
            if not isinstance(target, dict):
                raise ValueError("Each speed dial must be an object")
            identifier = target.get("id")
            number = target.get("number")
            if (not isinstance(identifier, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", identifier)
                    or identifier in self._speed_dials
                    or not isinstance(number, str)
                    or not re.fullmatch(r"\+?[0-9]{2,16}", number)):
                raise ValueError("Speed dials require unique IDs and valid numbers")
            label = "".join(c for c in str(target.get("label", identifier))
                            if " " <= c < "\x7f")[:40]
            self._speed_dials[identifier] = {"id": identifier, "label": label, "number": number}
        self._lock = asyncio.Lock()
        self._presence_lock = asyncio.Lock()
        self._history = {}
        self._active = None
        self._next_action_at = 0.0
        self._presence = {"state": "unknown", "profile": "", "confirmed": False}
        self._presence_at = None
        self._presence_age = 0.0
        self._poll_task = None
        self._closed = False

    @property
    def own_presence(self):
        age = (float("inf") if self._presence_at is None else
               max(0.0, time.monotonic() - self._presence_at) + self._presence_age)
        fresh = bool(self._presence.get("confirmed") and self.source.connected
                     and age <= float(self.config.get("stale_after_seconds", 5)))
        return {"state": self._presence["state"] if fresh else "unknown",
                "profile": self._presence["profile"] if fresh else "",
                "confirmed": fresh, "age_seconds": round(age, 2) if math.isfinite(age) else None}

    def _has_dnd_provider(self):
        return bool(self.presence_provider is not None
                    and callable(getattr(self.presence_provider, "get_presence", None))
                    and callable(getattr(self.presence_provider, "set_dnd", None)))

    def capabilities(self):
        try:
            self._preflight(check_busy=True)
            call_ready = True
        except ActionError:
            call_ready = False
        speed_dials = []
        for target in self._speed_dials.values():
            item = {"id": target["id"], "label": target["label"]}
            if target["number"].isdigit() and len(target["number"]) <= 5:
                item["extension"] = target["number"]
            speed_dials.append(item)
        controls_ready = (not self._closed and self._active is None
                          and time.monotonic() >= self._next_action_at)
        return {"session_id": self.session_id,
                "call": bool(self._speed_dials and call_ready and controls_ready),
                "dnd": bool((self.demo or self._has_dnd_provider()) and controls_ready),
                "targets": speed_dials}

    def _preflight(self, check_busy):
        if self._closed:
            raise ActionError("bridge_offline", 503, "Bridge controls are unavailable")
        if self.demo:
            return
        if not self.source.connected:
            raise ActionError("bridge_offline", 503, "PBX connection is unavailable")
        age = self.source.age_seconds
        if (not isinstance(age, (int, float)) or not math.isfinite(age)
                or age > float(self.config.get("stale_after_seconds", 5))):
            raise ActionError("stale_state", 503, "PBX state is too old for controls")
        own = next((dn for dn in self.source.snapshot if isinstance(dn, dict)
                    and str(dn.get("dn", "")) == self._own_extension), None)
        if own is None or not own.get("devices"):
            raise ActionError("own_unavailable", 409, "Your extension has no registered device")
        if check_busy and own.get("participants"):
            raise ActionError("own_busy", 409, "Your extension already has a call")

    def _validate_request(self, request_id, session_id):
        if not isinstance(session_id, str) or session_id != self.session_id:
            raise ActionError("stale_session", 409, "Refresh badge state before using controls")
        if (not isinstance(request_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,96}", request_id)):
            raise ActionError("invalid_request", 400, "A valid control request ID is required")

    async def _submit(self, body, request_id, session_id, operation):
        self._validate_request(request_id, session_id)
        async with self._lock:
            record = self._history.get(request_id)
            if record is not None:
                if record["body"] != body:
                    raise ActionError("idempotency_conflict", 409, "Request ID was already used for another action")
                task = record["task"]
            else:
                if self._closed:
                    raise ActionError("bridge_offline", 503, "Bridge controls are unavailable")
                if self._active is not None:
                    raise ActionError("action_in_progress", 409, "Another control action is in progress")
                if time.monotonic() < self._next_action_at:
                    raise ActionError("cooldown", 429, "Wait a moment before another control action")
                # Never evict an old request and accidentally permit it to be
                # executed again in the same server epoch. Restart creates a new
                # epoch, so every old client request is then rejected instead.
                if len(self._history) >= self.MAX_HISTORY:
                    raise ActionError("history_full", 503, "Control history is full; restart the bridge")
                task = asyncio.create_task(self._finish(operation, request_id))
                self._history[request_id] = {"body": body, "task": task}
                self._active = task
        # A disconnected HTTP caller must not cancel an in-flight PBX write and
        # leave its outcome unrecorded. A repeated request awaits the same task.
        result = await asyncio.shield(task)
        return dict(result)

    async def _finish(self, operation, request_id):
        try:
            result = await operation()
            return dict(result, request_id=request_id, session_id=self.session_id)
        except ActionError:
            raise
        except Exception:
            # This boundary intentionally never includes raw exception text,
            # response bodies, credentials, destinations, or caller information.
            return {"status": "unknown", "message": "Action outcome is unknown; check your phone before trying again",
                    "request_id": request_id, "session_id": self.session_id}
        finally:
            async with self._lock:
                self._active = None
                self._next_action_at = time.monotonic() + self.COOLDOWN_SECONDS

    async def make_call(self, target_id, request_id, session_id):
        if not isinstance(target_id, str) or target_id not in self._speed_dials:
            raise ActionError("invalid_target", 400, "Choose a configured speed dial")
        target = self._speed_dials[target_id]

        async def perform():
            self._preflight(check_busy=True)
            if self.demo:
                return {"status": "demo", "message": "Demo call only; no phone was called"}
            if self.source._session is None:
                raise ActionError("bridge_offline", 503, "PBX connection is unavailable")
            try:
                token = await asyncio.wait_for(self.source._get_token(), self.REQUEST_TIMEOUT)
            except (BridgeTransportError, aiohttp.ClientError, asyncio.TimeoutError):
                raise ActionError("pbx_unavailable", 503, "PBX authentication is unavailable") from None
            # Authentication may have waited; re-check immediately before POST.
            self._preflight(check_busy=True)
            path = "/callcontrol/{}/makecall".format(quote(self._own_extension, safe=""))
            try:
                async with asyncio.timeout(self.REQUEST_TIMEOUT):
                    async with self.source._session.post(
                        self.source._base_url + path,
                        json={"destination": target["number"]},
                        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                        allow_redirects=False,
                    ) as response:
                        if response.status not in (200, 202):
                            if response.status >= 500:
                                return {"status": "unknown", "message": "Call outcome is unknown; check your phone before trying again"}
                            raise ActionError("pbx_rejected", 502, "PBX rejected the call request")
                        result = await self.source._json(response)
                        if not isinstance(result, dict) or result.get("finalstatus") not in ("Success", "Rejected", "Failed"):
                            return {"status": "unknown", "message": "Call outcome is unknown; check your phone before trying again"}
                        if result["finalstatus"] != "Success":
                            raise ActionError("pbx_rejected", 502, "PBX rejected the call request")
            except (BridgeTransportError, aiohttp.ClientError, asyncio.TimeoutError):
                return {"status": "unknown", "message": "Call outcome is unknown; check your phone before trying again"}
            return {"status": "accepted", "message": "Call requested; answer your phone to connect"}

        return await self._submit(("call", target_id), request_id, session_id, perform)

    def _set_presence(self, value):
        if not isinstance(value, dict):
            self._presence = {"state": "unknown", "profile": "", "confirmed": False}
            self._presence_at = None
            return
        state = value.get("state", "unknown")
        if state not in ("available", "dnd", "away", "unknown"):
            state = "unknown"
        profile = "".join(c for c in str(value.get("profile", "")) if " " <= c < "\x7f")[:80]
        confirmed = value.get("confirmed") is True and state != "unknown"
        age = value.get("age_seconds", 0.0)
        if not isinstance(age, (int, float)) or not math.isfinite(age) or age < 0:
            confirmed = False
            age = 0.0
        self._presence = {"state": state, "profile": profile, "confirmed": confirmed}
        self._presence_at = time.monotonic()
        self._presence_age = age

    async def _read_presence(self):
        value = await asyncio.wait_for(self.presence_provider.get_presence(), self.REQUEST_TIMEOUT)
        self._set_presence(value)
        return self.own_presence

    async def set_dnd(self, enabled, request_id, session_id):
        if not isinstance(enabled, bool):
            raise ActionError("invalid_request", 400, "DND enabled must be a boolean")
        if not self.demo and not self._has_dnd_provider():
            raise ActionError("dnd_unavailable", 501, "DND control is not configured")

        async def perform():
            self._preflight(check_busy=False)
            desired = "dnd" if enabled else "available"
            if self.demo:
                self._set_presence({"state": desired, "profile": "Out of office" if enabled else "Available",
                                    "confirmed": True})
                return {"status": "demo", "message": "Demo DND only; phone status was not changed"}
            async with self._presence_lock:
                try:
                    current = await self._read_presence()
                except Exception:
                    self._set_presence(None)
                    raise ActionError("presence_unavailable", 503, "Current DND state could not be read") from None
                if not current["confirmed"]:
                    raise ActionError("presence_unavailable", 503, "Current DND state could not be confirmed")
                if current["state"] == desired:
                    return {"status": "unchanged", "message": "DND is already on" if enabled else "DND is already off"}
                self._preflight(check_busy=False)
                try:
                    # Exactly one write. Providers must also avoid write retries.
                    await asyncio.wait_for(self.presence_provider.set_dnd(enabled), self.REQUEST_TIMEOUT)
                    confirmed = await self._read_presence()
                except ActionError:
                    self._set_presence(None)
                    raise
                except Exception:
                    self._set_presence(None)
                    return {"status": "unknown", "message": "DND outcome is unknown; check phone status before trying again"}
                if not confirmed["confirmed"] or confirmed["state"] != desired:
                    self._set_presence(None)
                    return {"status": "unknown", "message": "DND change was not confirmed; check phone status"}
                return {"status": "confirmed", "message": "DND is on" if enabled else "DND is off"}

        return await self._submit(("dnd", enabled), request_id, session_id, perform)

    async def run(self):
        if not self._has_dnd_provider():
            return
        while not self._closed:
            if self.source.connected:
                try:
                    async with self._presence_lock:
                        await self._read_presence()
                except Exception:
                    self._set_presence(None)
            else:
                self._set_presence(None)
            await asyncio.sleep(2.0)

    async def start(self):
        if self._poll_task is None and self._has_dnd_provider():
            self._poll_task = asyncio.create_task(self.run())

    async def close(self):
        self._closed = True
        if self._poll_task:
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
        if self._active is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._active), self.REQUEST_TIMEOUT * 3 + 1)
            except (ActionError, asyncio.TimeoutError):
                pass
