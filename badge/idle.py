"""Pure MicroPython-compatible quiet-period and rotating idle-page state.

Own calls always interrupt. On-demand mode starts quiet immediately and keeps
all active team calls visible. Legacy quiet-delay mode allows stable answered
teammate calls alongside idle pages. Timestamps/age counters are not call changes.
"""

DEFAULT_PAGES = ("weather", "rain", "clock", "moon")
AVAILABLE_PAGES = DEFAULT_PAGES + ("meteors", "advent")
ACTIVE_CALLS = ("ringing", "dialing", "connected", "busy", "hold", "held")
TRANSIENT_CALLS = ("ringing", "dialing")
ENDED_CALLS = ("ended", "completed", "disconnected", "terminated", "failed", "rejected", "cancelled", "canceled")


def _call(call):
    if not isinstance(call, dict):
        return False, "unknown", ()
    state = str(call.get("state") or "unknown").lower()
    signature = tuple(str(call.get(key) or "") for key in (
        "id", "state", "direction", "peer_extension", "peer_number",
        "peer_name", "peer_first_name", "kind", "priority"))
    return state in ACTIVE_CALLS or state in ENDED_CALLS, state, signature


def _member(member, own=False, block_active=False):
    if not isinstance(member, dict) or not isinstance(member.get("calls"), list):
        return False, True, ()
    state = str(member.get("state") or "unknown").lower()
    known = state == "idle" or state in ACTIVE_CALLS
    blocked = state in ACTIVE_CALLS if own or block_active else state in TRANSIENT_CALLS
    signatures = []
    for call in member["calls"]:
        valid, call_state, signature = _call(call)
        known = known and valid
        blocked = blocked or call_state in (ACTIVE_CALLS if own or block_active else TRANSIENT_CALLS)
        signatures.append(signature)
    if not own and not member["calls"] and state in ("unknown", "offline", "unregistered"):
        known = True
    signature = (str(member.get("extension") or ""), state, tuple(sorted(signatures)))
    return known, blocked, signature


class IdlePages:
    def __init__(self, pages=None, idle_after_ms=60000, rotate_ms=12000, overview_on_demand=False):
        if (isinstance(idle_after_ms, bool) or not isinstance(idle_after_ms, (int, float))
                or not 0 <= idle_after_ms <= 86400000):
            raise ValueError("Invalid idle delay")
        if (isinstance(rotate_ms, bool) or not isinstance(rotate_ms, (int, float))
                or not 1 <= rotate_ms <= 3600000):
            raise ValueError("Invalid page rotation interval")
        if pages is None:
            pages = DEFAULT_PAGES
        if not isinstance(pages, (list, tuple)):
            raise ValueError("Idle pages must be a list")
        self.pages = []
        for page in pages:
            if page in AVAILABLE_PAGES and page not in self.pages:
                self.pages.append(page)
        self.idle_after_ms = int(idle_after_ms)
        self.rotate_ms = int(rotate_ms)
        self.overview_on_demand = overview_on_demand is True
        self._overview_until = 0
        self._overview_hidden = False
        self._own_blocked = True
        self._team_signature = None
        self._quiet_since = None
        self._healthy = False
        self._blocked = True
        self._signature = None
        self._rotation_at = None
        self._rotation_index = 0

    def set_pages(self, pages, now_ms):
        """Change seasonal pages without bypassing call and quiet-period guards."""
        if not isinstance(pages, (tuple, list)):
            return False
        values = []
        for page in pages:
            if page in AVAILABLE_PAGES and page not in values:
                values.append(page)
        if values == self.pages:
            return False
        current = self.page(now_ms)
        self.pages = values
        self._rotation_index = values.index(current) if current in values else 0
        self._rotation_at = now_ms
        return True

    def preview(self, now_ms):
        """Show a user-selected appearance only while PBX state allows idle."""
        if self._healthy and not self._blocked:
            if self.overview_on_demand:
                self._overview_until = now_ms
            self._quiet_since = now_ms - self.idle_after_ms
            self._rotation_index = 0
            self._rotation_at = now_ms
            return True
        return False

    def touch(self, now_ms, manual=False):
        """Return to the overview; begin a new quiet period at this input."""
        self._quiet_since = now_ms
        self._rotation_at = None
        self._rotation_index = 0
        if self.overview_on_demand and manual:
            self._overview_hidden = False
            self._overview_until = now_ms + max(1000,self.idle_after_ms)

    def close_overview(self, now_ms):
        """Explicit Space close; a new team-call change may wake it again."""
        self._overview_until = now_ms
        self._overview_hidden = True
        self._quiet_since = now_ms - self.idle_after_ms
        self._rotation_at = now_ms
        self._rotation_index = 0

    def observe(self, payload, live, now_ms):
        healthy, blocked, signature = False, True, None
        own_blocked, team_signatures = True, []
        if isinstance(payload, dict) and payload.get("connected") is True and live:
            own = payload.get("own")
            team = payload.get("team")
            own_known, blocked, own_signature = _member(own, own=True)
            own_blocked = blocked
            healthy = own_known and isinstance(team, list)
            team_signatures = []
            if isinstance(team, list):
                for member in team:
                    known, active, member_signature = _member(member, block_active=self.overview_on_demand)
                    healthy = healthy and known
                    blocked = blocked or active
                    team_signatures.append(member_signature)
            alert = payload.get("alert")
            alert_signature = ()
            if alert is not None:
                valid, alert_state, alert_signature = _call(alert)
                healthy = healthy and valid
                blocked = blocked or alert_state in ACTIVE_CALLS
                own_blocked = own_blocked or alert_state in ACTIVE_CALLS
            presence = own.get("presence") or {} if isinstance(own, dict) else {}
            presence_signature = tuple(str(presence.get(key) or "") for key in ("state", "profile", "confirmed")) if isinstance(presence, dict) else ()
            signature = (own_signature, tuple(team_signatures), alert_signature, presence_signature)
        if self.overview_on_demand:
            team_signature = tuple(team_signatures)
            if team_signature != self._team_signature:
                self._overview_hidden = False
            self._team_signature = team_signature
            if self._quiet_since is None or (healthy and not blocked and (not self._healthy or self._blocked)):
                self._quiet_since = now_ms - self.idle_after_ms
                self._rotation_at = now_ms
                self._rotation_index = 0
        elif (not healthy or blocked or not self._healthy or self._blocked
                or signature != self._signature or self._quiet_since is None):
            self.touch(now_ms)
        self._healthy, self._blocked, self._signature = bool(healthy), bool(blocked), signature
        self._own_blocked = bool(own_blocked)
        return self.active(now_ms)

    def active(self, now_ms):
        if self.overview_on_demand:
            return bool(self.pages and self._healthy and not self._own_blocked
                        and (not self._blocked or self._overview_hidden) and now_ms >= self._overview_until)
        return bool(self.pages and self._healthy and not self._blocked
                    and self._quiet_since is not None
                    and now_ms - self._quiet_since >= self.idle_after_ms)

    def _index(self, now_ms):
        start = self._rotation_at if self._rotation_at is not None else self._quiet_since + self.idle_after_ms
        return (self._rotation_index + max(0, now_ms - start) // self.rotate_ms) % len(self.pages)

    def page(self, now_ms):
        return self.pages[int(self._index(now_ms))] if self.active(now_ms) else None

    def next(self, direction, now_ms):
        """Browse without waking; give the chosen page its full dwell time."""
        if not self.active(now_ms):
            return None
        step = 1 if direction > 0 else -1 if direction < 0 else 0
        self._rotation_index = (int(self._index(now_ms)) + step) % len(self.pages)
        self._rotation_at = now_ms
        return self.pages[self._rotation_index]


def data_fresh(value, elapsed_ms=0, max_age_seconds=900):
    """Check external-data age independently of PBX liveness.

    Callers still check their data schema/availability; missing or invalid age is
    unknown. The elapsed time is since the containing snapshot was received.
    """
    if not isinstance(value, dict):
        return False
    age = value.get("age_seconds")
    if isinstance(age, bool) or not isinstance(age, (int, float)) or age != age or age < 0:
        return False
    return age + max(0, elapsed_ms) / 1000 <= max_age_seconds
