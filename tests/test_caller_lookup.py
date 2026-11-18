"""No network or real numbers: database, grounding, spend limits and admin scope."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from bridge.caller_lookup import CallerBook, OpenAIBusinessLookup, parse_answer, number_key
from bridge.server import create_app
from test_phonebook_server import Source, Book

NUMBER = '+441632960123'
URL = 'https://example.com/contact'


def response(**changes):
    answer = {'match': True, 'company': 'Example Co', 'entity_type': 'business',
              'confidence': 'high', 'phone': NUMBER, 'source_url': URL,
              'evidence': 'Example Co. Telephone: 01632 960123.'}
    answer.update(changes)
    return {'status': 'completed', 'output': [
        {'type': 'web_search_call', 'status': 'completed', 'action': {'sources': [{'url': URL}]}},
        {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(answer)}]}]}


class GroundingTests(unittest.TestCase):
    def test_accepts_exact_published_business_number(self):
        self.assertEqual(parse_answer(response(), NUMBER)['name'], 'Example Co')

    def test_refuses_wrong_phone_person_weak_and_invented_source(self):
        for change in ({'phone': '+441632960124'}, {'entity_type': 'person'},
                       {'confidence': 'low'}, {'evidence': 'Call 01632 960124'},
                       {'source_url': 'https://invented.example/contact'},
                       {'company': '<script>\nalert(1)</script>'}):
            self.assertIsNone(parse_answer(response(**change), NUMBER))

    def test_requires_completed_real_search_and_json(self):
        value = response(); value['output'].pop(0)
        with self.assertRaises(ValueError): parse_answer(value, NUMBER)
        value = response(); value['status'] = 'incomplete'
        with self.assertRaises(ValueError): parse_answer(value, NUMBER)

    def test_unknown_is_neutral_and_extensions_are_not_external_numbers(self):
        self.assertIsNone(parse_answer(response(match=False), NUMBER))
        self.assertEqual(number_key('200'), '')


class Provider:
    model = 'test-model'
    def __init__(self): self.calls = []; self.gate = None; self.answer = {'name': 'Example Co', 'source_url': URL, 'evidence': '01632 960123'}
    async def lookup(self, number):
        self.calls.append(number)
        if self.gate: await self.gate.wait()
        if isinstance(self.answer, Exception): raise self.answer
        return self.answer


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_body_is_read_across_multiple_network_chunks(self):
        raw = json.dumps(response()).encode()
        sent = []
        class Content:
            async def iter_chunked(self, size):
                for offset in range(0, len(raw), 17): yield raw[offset:offset+17]
        class Response:
            status=200; content=Content()
            async def __aenter__(self): return self
            async def __aexit__(self,*unused): pass
        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self,*unused): pass
            def post(self,url,**kwargs): sent.append((url,kwargs)); return Response()
        with patch('bridge.caller_lookup.aiohttp.ClientSession',return_value=Session()):
            result = await OpenAIBusinessLookup('secret-test-key').lookup(NUMBER)
        self.assertEqual(result['name'], 'Example Co')
        self.assertFalse(sent[0][1]['json']['store'])
        self.assertEqual(sent[0][1]['json']['max_tool_calls'],2)
        self.assertNotIn('secret-test-key',str(sent[0][1]['json']))


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'book.sqlite3'
        self.clock = [1800000000.0]; self.provider = Provider()
        self.book = CallerBook(self.path, self.provider, daily_limit=2, clock=lambda:self.clock[0])
        self.addAsyncCleanup(self.close)
    async def close(self):
        if not self.book.closed: await self.book.close()
    async def settle(self): await asyncio.gather(*list(self.book.tasks))

    async def test_background_dedup_cache_reopen_and_both_directions(self):
        self.provider.gate = asyncio.Event()
        self.book.observe(NUMBER, 'inbound'); self.book.observe(NUMBER, 'outbound')
        await asyncio.sleep(0)
        self.assertEqual(self.provider.calls, [NUMBER]); self.assertEqual(self.book.names(), {})
        self.provider.gate.set(); await self.settle()
        self.assertTrue(self.book.names()[NUMBER]['likely'])
        await self.book.close()
        self.book = CallerBook(self.path, self.provider, clock=lambda:self.clock[0])
        self.book.observe(NUMBER, 'outbound'); await self.settle()
        self.assertEqual(self.provider.calls, [NUMBER])

    async def test_confirm_correct_reject_prevent_api_and_survive_expiry(self):
        self.book.observe(NUMBER); await self.settle(); self.book.review(NUMBER, 'confirm')
        self.clock[0] += 60*86400
        self.book.observe(NUMBER); await self.settle()
        self.assertFalse(self.book.names()[NUMBER]['likely'])
        self.book.review(NUMBER, 'correct', 'Correct Company')
        self.assertEqual(self.book.names()[NUMBER]['name'], 'Correct Company')
        other = '+441632960124'; self.book.review(other, 'reject')
        self.book.observe(other); await self.settle()
        self.assertEqual(self.provider.calls, [NUMBER])

    async def test_review_wins_over_inflight_response(self):
        self.provider.gate = asyncio.Event(); self.book.observe(NUMBER)
        await asyncio.sleep(0); self.book.review(NUMBER, 'correct', 'My correction')
        self.provider.gate.set(); await self.settle()
        self.assertEqual(self.book.names()[NUMBER]['name'], 'My correction')
        self.assertFalse(self.book.names()[NUMBER]['likely'])

    async def test_negative_cache_errors_and_daily_limit_persist(self):
        self.provider.answer = None; self.book.observe(NUMBER); await self.settle()
        self.book.observe(NUMBER); await self.settle(); self.assertEqual(len(self.provider.calls), 1)
        self.provider.answer = RuntimeError('never expose secret URL')
        self.book.observe('+441632960124'); await self.settle()
        await self.book.close(); self.book = CallerBook(self.path, self.provider, daily_limit=2, clock=lambda:self.clock[0])
        self.book.observe('+441632960125'); await self.settle()
        self.assertEqual(self.book.status()['requests_today'], 2)
        self.assertEqual(len(self.provider.calls), 2)

    async def test_internal_ineligible_and_bad_review(self):
        self.book.observe('200'); self.book.observe(NUMBER, eligible=False); await self.settle()
        self.assertEqual(self.provider.calls, [])
        for args in [('200','correct','Name'),(NUMBER,'confirm',''),(NUMBER,'correct','bad\nname')]:
            with self.assertRaises(ValueError): self.book.review(*args)

    async def test_failed_refresh_does_not_revive_expired_guess(self):
        self.book.observe(NUMBER); await self.settle()
        self.clock[0] += 31*86400
        self.provider.answer = RuntimeError('unavailable')
        self.book.observe(NUMBER); await self.settle()
        self.assertNotIn(NUMBER, self.book.names())

    async def test_correction_removes_evidence_for_the_old_guess(self):
        self.book.observe(NUMBER); await self.settle()
        self.book.review(NUMBER, 'correct', 'A different company')
        self.assertEqual(self.book.entries()[0]['source_url'], '')
        self.assertEqual(self.book.entries()[0]['evidence'], '')


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.provider = Provider(); self.book = CallerBook(Path(self.folder.name)/'book.sqlite3', self.provider)
        self.source, self.pb = Source(), Book()
        self.source.snapshot[0]['participants'][0]['party_caller_name'] = ''
        self.config = {'own_extension':'200','team':[{'extension':'223','name':'TB'}]}
        app = create_app(self.config,self.source,token='r'*32,phonebook=self.pb,
                         caller_book=self.book,lookup_admin_token='a'*32)
        self.client = TestClient(TestServer(app)); await self.client.start_server(); self.addAsyncCleanup(self.client.close)
        self.admin = {'Authorization':'Bearer '+'a'*32,'X-Caller-Review':'1'}
    async def state(self):
        r = await self.client.get('/v1/state',headers={'Authorization':'Bearer '+'r'*32})
        return await r.json()

    async def test_auth_and_csrf_capability_separate_from_badge_tokens(self):
        for h in ({}, {'Authorization':'Bearer '+'r'*32}, {'Authorization':'Bearer '+'a'*32}):
            r = await self.client.get('/lookup/api/entries',headers=h)
            self.assertIn(r.status, (401,403))
        r = await self.client.post('/lookup/api/review',headers=self.admin,
                                  json={'number':NUMBER,'action':'correct','name':'My company'})
        self.assertEqual(r.status,200)
        r = await self.client.get('/lookup/api/entries',headers=self.admin)
        self.assertEqual((await r.json())['entries'][0]['name'], 'My company')

    async def test_3cx_first_then_ai_incoming_outgoing_and_confirmed_override(self):
        await self.state(); self.assertEqual(self.provider.calls, [])
        self.pb.lookup_complete = lambda number: True
        self.pb.names = {NUMBER:'3CX contact'}
        self.assertEqual((await self.state())['own']['calls'][0]['peer_name'], '3CX contact')
        self.assertEqual(self.provider.calls, [])
        self.pb.names = {}
        for direction in ('inbound','outbound'):
            self.source.snapshot[0]['participants'][0]['_direction'] = direction
            await self.state(); await asyncio.gather(*list(self.book.tasks))
            call = (await self.state())['own']['calls'][0]
            self.assertEqual(call['peer_name'], 'Likely: Example Co')
            self.assertTrue(call['peer_name_likely']); self.assertEqual(call['direction'], direction)
        self.assertEqual(self.provider.calls, [NUMBER])
        self.book.review(NUMBER,'correct','My correction'); self.pb.names={NUMBER:'3CX contact'}
        call = (await self.state())['own']['calls'][0]
        self.assertEqual(call['peer_name'],'My correction'); self.assertFalse(call['peer_name_likely'])

    async def test_unauthenticated_stale_and_team_calls_do_not_trigger_ai(self):
        self.pb.lookup_complete=lambda number:True
        r=await self.client.get('/v1/state');self.assertEqual(r.status,401)
        self.source.age_seconds=9;await self.state();await asyncio.sleep(0)
        self.assertEqual(self.provider.calls,[])
        self.source.age_seconds=0;await self.state();await asyncio.gather(*list(self.book.tasks))
        self.assertEqual(self.provider.calls,[NUMBER])
