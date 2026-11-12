"""Phonebook enrichment stays within authenticated current-call responses."""
import unittest
from aiohttp.test_utils import TestClient, TestServer
from bridge.server import create_app

class Source:
    connected=True
    age_seconds=0
    status='live'
    def __init__(self):
        def dn(number, peer=None):
            return {'dn':number,'devices':[{'dn':number}], 'participants':[] if peer is None else
                [{'id':number,'callid':number,'dn':number,'status':'Connected',
                  'party_caller_id':peer,'party_caller_name':'PBX Name','party_dn':'10000',
                  'party_dn_type':'Wexternalline'}]}
        self.snapshot=[dn('200','+441632960123'),dn('223','+441632960124'),dn('999','+441632960999')]

class Book:
    def __init__(self):
        self.names={}
        self.observed=[]
        self.extensions={}
        self.observed_extensions=[]
        self.closed=False
    def cached_contacts(self):return dict(self.names)
    def observe(self,numbers):self.observed.append(list(numbers))
    def cached_extensions(self):return dict(self.extensions)
    def observe_extensions(self,numbers):self.observed_extensions.append(list(numbers))
    async def close(self):self.closed=True

class PhonebookServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.source,self.book=Source(),Book()
        self.config={'own_extension':'200','team':[{'extension':'223','name':'TB'}], 'country_code':'44'}
        self.client=TestClient(TestServer(create_app(self.config,self.source,token='r'*32,phonebook=self.book)))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
    async def state(self):
        response=await self.client.get('/v1/state',headers={'Authorization':'Bearer '+'r'*32})
        self.assertEqual(response.status,200)
        return await response.json()
    async def test_only_authenticated_own_and_configured_team_active_numbers_are_observed(self):
        response=await self.client.get('/v1/state')
        self.assertEqual(response.status,401)
        self.assertEqual(self.book.observed,[])
        state=await self.state()
        self.assertTrue(state['phonebook']['enabled'])
        self.assertEqual(set(self.book.observed[-1]),{'+441632960123'})
    async def test_async_book_names_enrich_next_snapshot_without_exposing_the_book(self):
        self.assertEqual((await self.state())['own']['calls'][0]['peer_name'],'PBX Name')
        self.book.names={'+441632960123':'Matched Person','+441632960888':'Unrelated Private Contact'}
        state=await self.state()
        self.assertEqual(state['own']['calls'][0]['peer_name'],'Matched Person')
        self.assertNotIn('Unrelated Private Contact',str(state))
        self.assertNotIn('phonebook_contacts',state)
    async def test_manual_alias_wins_and_does_not_trigger_book_lookup(self):
        self.config['contacts']={'01632960123':'Manual Alias'}
        self.book.names={'+441632960123':'Book Name'}
        state=await self.state()
        self.assertEqual(state['own']['calls'][0]['peer_name'],'Manual Alias')
        self.assertNotIn('+441632960123',self.book.observed[-1])
    async def test_stale_snapshot_does_not_start_lookups(self):
        self.source.age_seconds=7
        await self.state()
        self.assertEqual(self.book.observed,[[]])
        self.assertEqual(self.book.observed_extensions,[[]])
    async def test_current_unknown_internal_peer_resolves_first_name_on_next_snapshot(self):
        call=self.source.snapshot[1]['participants'][0]
        call.update(party_dn='271',party_dn_type='Wextension',party_caller_id='271',party_caller_name='')
        first=await self.state()
        self.assertEqual(first['team'][0]['calls'][0]['peer_extension'],'271')
        self.assertIn('271',self.book.observed_extensions[-1])
        self.book.extensions={'271':'Alex'}
        second=await self.state()
        self.assertEqual(second['team'][0]['calls'][0]['peer_first_name'],'Alex')
    async def test_cleanup_closes_book(self):
        await self.client.close()
        self.assertTrue(self.book.closed)
