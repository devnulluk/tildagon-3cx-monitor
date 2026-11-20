import unittest
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from bridge.tablet import add_routes,display_state
from bridge.admin import DeviceCommands

class TabletTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.devices=DeviceCommands();self.app=web.Application()
  async def state(request):return {'version':1,'connected':True,'own':{'calls':[]},'team':[],
                                 'controls':{'session_id':'secret'},'device_commands':{'bad':'secret'},'token':'secret'}
  add_routes(self.app,'t'*40,state,self.devices)
  self.client=TestClient(TestServer(self.app));await self.client.start_server()
 async def asyncTearDown(self):await self.client.close()
 async def test_no_login_or_secret_in_public_shell(self):
  r=await self.client.get('/tablet');body=await r.text()
  self.assertEqual(r.status,200);self.assertNotIn('t'*40,body);self.assertNotIn('type=password',body)
  self.assertIn("form-action 'none'",r.headers['Content-Security-Policy'])
 async def test_read_only_and_no_admin_data(self):
  self.assertEqual((await self.client.get('/tablet/api/state')).status,401)
  self.assertEqual((await self.client.get('/tablet/api/state',headers={'Authorization':'Bearer '+'a'*40})).status,401)
  r=await self.client.get('/tablet/api/state',headers={'Authorization':'Bearer '+'t'*40});data=await r.json()
  self.assertEqual(r.status,200);self.assertNotIn('controls',data);self.assertNotIn('device_commands',data);self.assertNotIn('token',data)
  self.assertEqual((await self.client.post('/tablet/api/state',json={},headers={'Authorization':'Bearer '+'t'*40})).status,405)
 async def test_presence_hides_calendar_on_client(self):
  state={'calendar':{'available':True,'events':[{'title':'Test'}]}}
  value=display_state(state,{'devices':{'waveshare':{'online':True,'settings':{'presence_enabled':True,'phone_nearby':False}}}})
  self.assertTrue(value['away'])
 async def test_missing_or_stale_focus_not_claimed_available(self):
  self.assertFalse(display_state({},{} )['focus']['available'])
