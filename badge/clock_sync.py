"""Wi-Fi time bootstrap, called in the existing network worker thread."""
import time


def clock_valid():
    try:
        return 2024 <= time.gmtime()[0] <= 2099
    except Exception:
        return False


def sync_clock():
    """Use firmware NTP in UTC; HTTPS certificate checks remain enabled."""
    try:
        import ntptime
        ntptime.settime()
        return clock_valid()
    except Exception:
        return False


class ClockSync:
    def __init__(self):
        self.connected = False
        self.last_attempt = None
        self.synced = False

    def disconnected(self):
        self.connected = False

    def due(self, now):
        if not self.connected:
            self.connected = True
            self.synced = False
            self.last_attempt = None
        return ((not self.synced or not clock_valid())
                and (self.last_attempt is None or now - self.last_attempt >= 60000))

    def attempted(self, now, success):
        self.last_attempt = now
        self.synced = bool(success)
