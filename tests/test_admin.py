import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from bridge.admin import DeviceCommands,add_routes

class AdminTests(unittest.IsolatedAsyncioTestCase):
 async def test_actual_reports_acknowledgements_and_serial_queue(self):
  first=self.commands.submit('spaceagon','focus_minutes',30)
  second=self.commands.submit('spaceagon','break_minutes',7)
  self.assertEqual(self.commands.snapshot()['spaceagon']['id'],first['id'])
  report={'device':'spaceagon','boot':'test','seq':1,'settings':{'focus_minutes':30,'frame_counter':1},'ack':{'id':first['id'],'status':'applied'}}
  self.commands.report(report)
  self.assertEqual(self.commands.snapshot()['spaceagon']['id'],second['id'])
  data=self.commands.admin_snapshot();self.assertTrue(data['devices']['spaceagon']['online'])
  self.assertEqual(data['command_history'][0]['status'],'applied')
  self.assertEqual(data['devices']['spaceagon']['settings']['focus_minutes'],30)
  with self.assertRaises(ValueError):self.commands.report(report)
 async def test_stale_and_frozen_reports_do_not_claim_online(self):
  with patch('bridge.admin.time.monotonic',return_value=10):
   self.commands.report({'device':'waveshare','boot':'test','seq':1,'settings':{'brightness':50,'frame_counter':1}})
  with patch('bridge.admin.time.monotonic',return_value=50):
   self.commands.report({'device':'waveshare','boot':'test','seq':2,'settings':{'brightness':50,'frame_counter':1}})
   self.assertFalse(self.commands.admin_snapshot()['devices']['waveshare']['online'])
   self.assertTrue(self.commands.admin_snapshot()['devices']['waveshare']['render_stalled'])
 async def test_wrong_value_is_not_confirmed_and_secret_fields_rejected(self):
  command=self.commands.submit('waveshare','brightness',40)
  self.commands.report({'device':'waveshare','boot':'test','seq':1,'settings':{'brightness':50},'ack':{'id':command['id'],'status':'applied'}})
  self.assertEqual(self.commands.admin_snapshot()['command_history'][0]['status'],'rejected')
  with self.assertRaises(ValueError):self.commands.report({'device':'waveshare','boot':'test','seq':2,'settings':{'password':'secret'}})
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
