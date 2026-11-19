import unittest
from bridge.calendar import events_for_display,CalendarService
from datetime import datetime,timezone

def feed(extra="",privacy="PUBLIC",repeat=""):
 return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:test\r\nDTSTART:20261119T100000Z\r\nDTEND:20261119T110000Z\r\nSUMMARY:Planning\r\nCLASS:"+privacy+"\r\n"+repeat+extra+"END:VEVENT\r\nEND:VCALENDAR\r\n").encode()
NOW=datetime(2026,11,19,9,tzinfo=timezone.utc).timestamp()
class CalendarTests(unittest.TestCase):
 def test_private_masks(self):
  for privacy in ('PRIVATE','CONFIDENTIAL','UNKNOWN'):
   e=events_for_display(feed(privacy=privacy),NOW)[0]
   self.assertEqual(e['title'],'Busy');self.assertEqual(set(e),{'title','start','end','all_day'})
 def test_public(self):self.assertEqual(events_for_display(feed(),NOW)[0]['title'],'Planning')
 def test_cancelled_and_past(self):
  self.assertEqual(events_for_display(feed('STATUS:CANCELLED\r\n'),NOW),[])
  self.assertEqual(events_for_display(feed(),NOW+86400),[])
 def test_recurrence(self):self.assertEqual(len(events_for_display(feed(repeat='RRULE:FREQ=DAILY;COUNT=3\r\n'),NOW)),3)
 def test_stale_hides(self):
  s=CalendarService('unused');s.events=[{'title':'Old','end':9999999999}]
  self.assertEqual(s.snapshot()['events'],[])
