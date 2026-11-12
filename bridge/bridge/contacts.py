"""Bounded, memory-only names for current external callers and internal DNs."""

import asyncio
from collections import OrderedDict
import time

from .model import normalize_number, text


class PhonebookResolver:
    """Observe current call numbers without blocking a state response.

    Manual config aliases must take precedence over cached_contacts() when the
    server builds model input. This class never enumerates or writes contacts.
    """

    def __init__(self, provider, country_code="44", positive_ttl=600,
                 negative_ttl=60, max_entries=512, clock=time.monotonic,
                 allow_internal=True):
        if not 1 <= max_entries <= 512 or positive_ttl <= 0 or negative_ttl <= 0:
            raise ValueError("Invalid phonebook cache settings")
        self._provider = provider
        self._country = str(country_code)
        self._positive_ttl = positive_ttl
        self._negative_ttl = negative_ttl
        self._max_entries = max_entries
        self._clock = clock
        self._cache = OrderedDict()
        self._queue = asyncio.Queue(maxsize=32)
        self._pending = set()
        self._observed = set()
        self._task = None
        self._closed = False
        self._allow_internal = bool(allow_internal)

    def _number(self, number):
        normalized = normalize_number(number, self._country)
        digits = normalized.lstrip("+")
        return normalized if normalized and 7 <= len(digits) <= 15 else ""

    def _extension(self, value):
        return value if (self._allow_internal and isinstance(value, str) and value.isascii()
                         and value.isdigit() and 1 <= len(value) <= 6) else ""

    def _prune(self):
        now = self._clock()
        for key, (deadline, unused) in list(self._cache.items()):
            if deadline <= now:
                del self._cache[key]

    def name_for(self, number):
        self._prune()
        entry = self._cache.get(self._number(number) or self._extension(number))
        return entry[1] if entry else None

    def cached_contacts(self):
        self._prune()
        return {number: name for number, (unused, name) in self._cache.items() if name and self._number(number)}

    def cached_extensions(self):
        """Return actual FirstName fields for observed local extension peers."""
        self._prune()
        return {number: name for number, (unused, name) in self._cache.items() if name and self._extension(number)}

    def observe(self, numbers):
        """Schedule only currently supplied call numbers; return immediately."""
        if self._closed or self._provider is None:
            return
        self._prune()
        self._observed = ({number for number in self._observed if self._extension(number)}
                          | {number for raw in numbers if (number := self._number(raw))})
        self._schedule()

    def observe_extensions(self, extensions):
        """Schedule only explicit current internal DNs, never enumerate users."""
        if self._closed or self._provider is None:
            return
        self._prune()
        self._observed = ({number for number in self._observed if self._number(number)}
                          | {number for raw in extensions if (number := self._extension(raw))})
        self._schedule()

    def _schedule(self):
        for number in self._observed:
            if not number or number in self._cache or number in self._pending:
                continue
            if self._queue.full():
                break
            self._pending.add(number)
            self._queue.put_nowait(number)
        if not self._queue.empty() and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._resolve())

    async def _resolve(self):
        while not self._closed:
            try:
                number = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                if number not in self._observed:
                    continue
                internal = bool(self._extension(number))
                value = (await self._provider.lookup_extension(number) if internal
                         else await self._provider.lookup_contact(number, country_code=self._country))
                name = None
                if (isinstance(value, dict)
                        and (self._extension(value.get("number")) if internal else self._number(value.get("number"))) == number
                        and isinstance(value.get("first_name" if internal else "name"), str)):
                    name = text(value["first_name" if internal else "name"], 100).strip() or None
                ttl = self._positive_ttl if name else self._negative_ttl
                self._cache[number] = (self._clock() + ttl, name)
                self._cache.move_to_end(number)
                while len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A short backoff also bounds retries during PBX/auth outages.
                # Caller numbers, names and server errors are never logged.
                self._cache[number] = (self._clock() + self._negative_ttl, None)
                while len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)
            finally:
                self._pending.discard(number)

    async def close(self):
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        while not self._queue.empty():
            self._queue.get_nowait()
        self._pending.clear()
        self._observed.clear()
        self._cache.clear()
