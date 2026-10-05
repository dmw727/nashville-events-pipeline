import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from nashville_weekly.collectors import tribe, ics, bedework, schema_event
from nashville_weekly.normalize import normalize, deduplicate, age_info, canonical
from nashville_weekly.network import Client, CollectionError

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'config/settings.json').read_text())
SOURCE={'id':'test','name':'Test official venue','url':'https://example.org/events','official':True,'fixed_location':True,'city':'Nashville','venue':'Test Museum'}
START=date(2026,9,19); END=date(2026,10,30)
def candidate(**kw):
    return {'title':'Robot workshop','description':'Ages 8–12. Registration required.','start':'2026-09-20T14:00:00-05:00','end':'2026-09-20T15:00:00-05:00','url':'https://example.org/event/robots','venue':'Test Museum',**kw}
def event(**kw): return normalize(candidate(**kw),SOURCE,CONFIG,START,END)[0]

class Rules(unittest.TestCase):
    def test_age_ranges_and_unknowns(self):
        self.assertEqual(event()['age_status'],'stated range')
        self.assertIsNone(event(description='Ages 3–5.'))
        self.assertIsNone(event(description='Ages 12 and older.'))
        self.assertIsNone(event(description='Ages 21+ only.'))
        self.assertIsNone(event(title='Preschool Play',description=''))
        self.assertEqual(event(description='Make a robot.')['age_status'],'check age')
        self.assertIsNone(event(description='Adults only.'))
        self.assertIsNone(event(description='21+ event'))
    def test_no_false_free(self):
        self.assertTrue(event(cost_text='Free')['free'])
        self.assertTrue(event(cost_text='0 USD')['free'])
        self.assertFalse(event(cost_text='$0–$25')['free'])
        self.assertFalse(event(cost_text='Kids under 5 free; adults $15')['free'])
        self.assertFalse(event(description='Free parking and a paid workshop')['free'])
    def test_closures_cancelled_past_and_remote(self):
        for kw in [{'title':'Closed Mondays'},{'status':'https://schema.org/EventCancelled'},
                   {'start':'2025-09-20','end':'2025-09-21'}, {'attendance':'https://schema.org/OnlineEventAttendanceMode'}]:
            self.assertIsNone(event(**kw))
    def test_timezone_dst_and_range(self):
        e=event(start='2026-09-20T19:00:00Z',end='2026-09-20T20:00:00Z')
        self.assertEqual(e['start'],'2026-09-20T14:00:00-05:00')
        d=normalize(candidate(start='2026-11-01T19:00:00Z',end='2026-11-01T20:00:00Z'),SOURCE,CONFIG,date(2026,11,1),date(2026,11,2))[0]
        self.assertEqual(d['start'],'2026-11-01T13:00:00-06:00')
        self.assertIsNotNone(event(start='2026-09-01',end='2026-10-01',all_day=True))
        self.assertEqual(event(start='2026-09-20 19:00:00',end='2026-09-20 20:00:00',timezone='UTC+0')['start'],'2026-09-20T14:00:00-05:00')
    def test_geo_unknown_and_far(self):
        self.assertIsNone(event(lat=35.15,lon=-90.05))
        e=normalize(candidate(venue='Unknown place'),{**SOURCE,'fixed_location':False},CONFIG,START,END)[0]
        self.assertIsNone(e['drive_minutes_estimate'])
        self.assertIn('city center',event()['distance_basis'])
    def test_dedupe_keeps_sessions_and_official_provenance(self):
        a=event(); b={**a,'official':False,'source_url':'https://aggregator.example/event','sources':[{'name':'Aggregator','url':'https://aggregator.example/event','official':False}]}
        later=event(start='2026-09-20T16:00:00-05:00',end='2026-09-20T17:00:00-05:00')
        other=event(venue='Other Museum',url='https://example.org/other')
        result=deduplicate([b,later,other,a]);self.assertEqual(len(result),3)
        merged=next(e for e in result if e['id']==a['id'])
        self.assertTrue(merged['official']);self.assertEqual(len(merged['sources']),2)
    def test_url_tracking_and_unsafe_scheme(self):
        self.assertEqual(canonical('https://example.org/x?utm_source=a&date=2026-09-20#x'),'https://example.org/x?date=2026-09-20')
        self.assertEqual(canonical('javascript:alert(1)'),'')

class Adapters(unittest.TestCase):
    def test_pagination(self):
        class Fake:
            calls=0
            def get(self,url):
                self.calls+=1
                return json.dumps({'events':[{'title':'Event '+str(self.calls),'start_date':'2026-09-20','venue':[]}],'total_pages':3})
        client=Fake(); rows,warnings=tribe({'endpoint':'https://example.org/api'},client,START,END)
        self.assertEqual(len(rows),3);self.assertFalse(warnings)
    def test_ics_recurrence_exclusion_override_and_exclusive_end(self):
        body='\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Test//EN','BEGIN:VEVENT','UID:test',
          'DTSTART;VALUE=DATE:20260919','DTEND;VALUE=DATE:20260920','RRULE:FREQ=DAILY;COUNT=3',
          'EXDATE;VALUE=DATE:20260920','SUMMARY:Maker day','END:VEVENT','BEGIN:VEVENT','UID:test',
          'RECURRENCE-ID;VALUE=DATE:20260921','DTSTART;VALUE=DATE:20260922','DTEND;VALUE=DATE:20260923',
          'SUMMARY:Moved maker day','END:VEVENT','END:VCALENDAR'])
        class Fake:
            def get(self,url):return body
        rows,_=ics({'url':'https://example.org/calendar.ics'},Fake(),START,END)
        self.assertEqual({e['start'] for e in rows},{'2026-09-19','2026-09-22'})
        self.assertTrue(all(e['start']==e['end'] for e in rows))
    def test_bedework_cap_splits_windows(self):
        class Fake:
            calls=0
            def get(self,url):
                self.calls+=1
                return json.dumps({'bwEventList':{'resultSize':201 if self.calls==1 else 0,'events':[]}})
        c=Fake();rows,warnings=bedework({'endpoint':'https://example.org/feed'},c,START,date(2026,9,25))
        self.assertEqual(c.calls,3);self.assertFalse(warnings)
    def test_offline_missing_cache_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(CollectionError):Client(d,offline=True).get('https://example.org')

if __name__=='__main__':unittest.main()
