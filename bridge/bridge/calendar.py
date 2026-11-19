"""Authenticated read-only ICS calendar with bounded display data and private-title masking."""
import asyncio
import contextlib
import json
import os
import time
from datetime import datetime, date, time as daytime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import aiohttp
import icalendar
import recurring_ical_events

ZONE = ZoneInfo("Europe/London")

def events_for_display(data, now):
    calendar = icalendar.Calendar.from_ical(data)
    start = datetime.fromtimestamp(now, ZONE).replace(hour=0,minute=0,second=0,microsecond=0)
    events = []
    for item in recurring_ical_events.of(calendar).between(start,start+timedelta(days=7)):
        if str(item.get("STATUS", "")).upper() == "CANCELLED": continue
        begin=item.decoded("DTSTART")
        all_day=isinstance(begin,date) and not isinstance(begin,datetime)
        finish=item.decoded("DTEND",begin+timedelta(days=1) if all_day else begin)
        def stamp(value):
            if not isinstance(value,datetime): value=datetime.combine(value,daytime.min)
            if value.tzinfo is None:value=value.replace(tzinfo=ZONE)
            return int(value.timestamp())
        first,last=stamp(begin),stamp(finish)
        if last<=now or last<=first:continue
        privacy=str(item.get("CLASS","PUBLIC")).upper()
        title=str(item.get("SUMMARY","Busy")) if privacy=="PUBLIC" else "Busy"
        events.append({"title":" ".join(title.split())[:100] or "Busy","start":first,"end":last,"all_day":all_day})
    return sorted(events,key=lambda e:(e["start"],e["end"]))[:32]

class CalendarService:
    def __init__(self, config_file):
        self.path=Path(config_file);self.events=[];self.updated=0;self.task=None;self.session=None;self.error="not_connected"
    def snapshot(self):
        available=bool(self.updated and time.time()-self.updated<900)
        return {"enabled":True,"available":available,"stale":not available,"status":"connected" if available else self.error,
                "events":[dict(e) for e in self.events if e["end"]>time.time()] if available else []}
    async def refresh(self):
        config=json.loads(self.path.read_text())
        url=config["url"];parts=urlsplit(url)
        if parts.scheme!="https" or not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError("HTTPS calendar URL required")
        async with self.session.get(url,auth=aiohttp.BasicAuth(config["username"],config["password"]),allow_redirects=False) as response:
            if response.status!=200:raise ValueError("Calendar unavailable")
            data=await response.content.read(2_000_001)
            if len(data)>2_000_000:raise ValueError("Calendar too large")
        self.events=await asyncio.to_thread(events_for_display,data,time.time())
        self.updated=time.time();self.error="connected"
    async def run(self):
        while True:
            try:await self.refresh()
            except (aiohttp.ClientError,asyncio.TimeoutError,ValueError,OSError,KeyError,TypeError):self.error="unavailable"
            await asyncio.sleep(300)
    async def start(self):
        self.session=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        self.task=asyncio.create_task(self.run())
    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):await self.task
        if self.session:await self.session.close()
