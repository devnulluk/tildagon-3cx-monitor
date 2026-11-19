import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from bridge.admin import DeviceCommands,add_routes

class AdminTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.app=web.Application()
  async def state(request):return {'connected':True,'team':[]}
  self.commands=DeviceCommands()
  add_routes(self.app,'a'*40,state,None,None,None,self.commands)
  self.client=TestClient(TestServer(self.app));await self.client.start_server()
 async def asyncTearDown(self):await self.client.close()
 async def test_auth_and_csrf(self):
  self.assertEqual((await self.client.get('/admin/api/state')).status,401)
  self.assertEqual((await self.client.get('/admin/api/state',headers={'Authorization':'Bearer '+'a'*40})).status,403)
  response=await self.client.get('/admin/api/state',headers={'Authorization':'Bearer '+'a'*40,'X-Spaceport-Admin':'1'})
  self.assertEqual(response.status,200)
 async def test_only_safe_commands_and_expiry(self):
  headers={'Authorization':'Bearer '+'a'*40,'X-Spaceport-Admin':'1'}
  response=await self.client.post('/admin/api/device',json={'device':'spaceagon','action':'focus_direction','value':1},headers=headers)
  self.assertEqual(response.status,202)
  self.assertEqual(self.commands.snapshot()['spaceagon']['value'],1)
  with patch('bridge.admin.time.time',return_value=9999999999):self.assertEqual(self.commands.snapshot(),{})
  for action,value in [('volume',100),('presence_off',None),('url','https://bad.invalid')]:
   response=await self.client.post('/admin/api/device',json={'device':'waveshare','action':action,'value':value},headers=headers)
   self.assertEqual(response.status,400)
 async def test_no_secrets_in_shell(self):
  response=await self.client.get('/admin');text=await response.text()
  self.assertNotIn('a'*40,text)
  self.assertIn('frame-ancestors',response.headers['Content-Security-Policy'])
