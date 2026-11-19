"""Independent administrator capability. No provider or device secrets leave the server."""
import hmac
import json
import secrets
import time
from aiohttp import web


class DeviceCommands:
    def __init__(self):
        self.commands = {}
        self.reports = {}
        self.history = {}
        self.pending = {}

    def submit(self, device, action, value=None):
        choices = {
            'waveshare': {'mute', 'unmute', 'silence', 'dismiss', 'page', 'volume', 'priority_volume', 'brightness', 'test', 'demo', 'live'},
            'spaceagon': {'ring_brightness', 'eeh_brightness', 'matrix_brightness', 'focus_brightness', 'focus_direction', 'focus_minutes', 'break_minutes', 'long_break_minutes', 'long_break_every', 'theme', 'clock', 'focus_start', 'focus_pause', 'focus_reset'},
        }
        if device not in choices or action not in choices[device]:
            raise ValueError('Unsupported device command')
        if action in ('focus_minutes','break_minutes','long_break_minutes','long_break_every'):
            low, high = {'focus_minutes':(5,90),'break_minutes':(1,60),'long_break_minutes':(1,90),'long_break_every':(2,12)}[action]
            if type(value) is not int or not low <= value <= high: raise ValueError('Invalid focus duration')
        elif action == 'focus_direction':
            if type(value) is not int or not 0 <= value < 4: raise ValueError('Invalid orientation')
        elif action in ('volume', 'priority_volume', 'brightness', 'ring_brightness', 'eeh_brightness', 'matrix_brightness', 'focus_brightness'):
            maximum = 75 if action in ('volume', 'priority_volume') else 100
            minimum = 5 if action == 'brightness' else 0
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError('Setting outside supported range')
        elif action in ('theme', 'clock'):
            if not isinstance(value, str) or not 1 <= len(value) <= 48 or not all(c.isascii() and (c.isalnum() or c == '_') for c in value):
                raise ValueError('Invalid appearance')
        elif value is not None:
            raise ValueError('Unexpected value')
        command = {'id': secrets.token_hex(12), 'action': action, 'value': value, 'expires': int(time.time()) + 60}
        self.snapshot()
        if device in self.commands:
            queue=self.pending.setdefault(device,[])
            if len(queue)>=8:raise ValueError('Device command queue full')
            queue.append(command)
        else:self.commands[device] = command
        self.history[command['id']] = dict(command,device=device,status='queued')
        while len(self.history)>100:del self.history[next(iter(self.history))]
        return {'status': 'queued', 'id': command['id'], 'expires_in': 60}

    def snapshot(self):
        for device in ('spaceagon','waveshare'):
            current=self.commands.get(device)
            if current and current['expires']<=time.time():
                self.history[current['id']]['status']='expired';self.commands.pop(device,None)
            while device not in self.commands and self.pending.get(device):
                item=self.pending[device].pop(0)
                if item['expires']>time.time():self.commands[device]=item
                else:self.history[item['id']]['status']='expired'
        return {device: dict(c) for device, c in self.commands.items() if c['expires'] > time.time()}

    def report(self,data):
        if not isinstance(data,dict) or set(data)-{'device','boot','seq','settings','ack','version'}:raise ValueError()
        device=data.get('device');settings=data.get('settings')
        allowed={'spaceagon':{'ring_brightness','eeh_brightness','matrix_brightness','focus_brightness','focus_direction','theme','clock','focus_minutes','break_minutes','long_break_minutes','long_break_every','focus_phase','focus_paused','focus_remaining','frame_counter'},
                 'waveshare':{'volume','priority_volume','brightness','muted','demo','page','frame_counter'}}
        if device not in allowed or not isinstance(settings,dict) or set(settings)-allowed[device]:raise ValueError()
        if not isinstance(data.get('boot'),str) or not 1<=len(data['boot'])<=40 or type(data.get('seq')) is not int or data['seq']<0:raise ValueError()
        for value in settings.values():
            if type(value) not in (str,int,float,bool) or (isinstance(value,str) and len(value)>48):raise ValueError()
            if isinstance(value,float) and not __import__('math').isfinite(value):raise ValueError()
        previous=self.reports.get(device)
        if previous and previous['boot']==data['boot'] and data['seq']<=previous['seq']:raise ValueError()
        ack=data.get('ack')
        if ack:
            if not isinstance(ack,dict) or set(ack)!={'id','status'} or ack['status'] not in ('applied','rejected'):raise ValueError()
            item=self.history.get(ack['id'])
            if item and item['device']==device and item['status'] in ('queued','expired'):
                matches=item['action'] not in settings or settings[item['action']]==item['value']
                item['status']=ack['status'] if matches else 'rejected';item['confirmed_at']=int(time.time())
                if self.commands.get(device,{}).get('id')==ack['id']:self.commands.pop(device,None)
                self.snapshot()
        now=time.monotonic()
        changed=not previous or previous['boot']!=data['boot'] or previous['settings'].get('frame_counter')!=settings.get('frame_counter')
        self.reports[device]={'boot':data['boot'],'seq':data['seq'],'settings':dict(settings),'version':str(data.get('version',''))[:20],'received':now,
                              'frame_changed':now if changed else previous['frame_changed']}

    def admin_snapshot(self):
        result={}
        for device in ('spaceagon','waveshare'):
            report=self.reports.get(device)
            age=time.monotonic()-report['received'] if report else None
            stalled=bool(report and time.monotonic()-report['frame_changed']>=35)
            result[device]={'online':age is not None and age<35 and not stalled,'render_stalled':stalled,'age_seconds':round(age,1) if age is not None else None,
                            'settings':dict(report['settings']) if report else {},'version':report['version'] if report else ''}
        for item in self.history.values():
            if item['status']=='queued' and item['expires']<=time.time():item['status']='expired'
        return {'devices':result,'command_history':[dict(v) for v in list(self.history.values())[-30:]]}


def add_routes(app, token, get_state, actions, notifications, calendar, commands):
    if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError('ADMIN_TOKEN must be at least 32 ASCII characters')
    async def page(request):
        from .admin_page import PAGE
        return web.Response(text=PAGE, content_type='text/html', headers={
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})

    async def api(request):
        supplied = request.headers.get('Authorization', '')
        if not supplied.isascii() or not hmac.compare_digest(supplied, 'Bearer ' + token):
            return web.json_response({'error': 'unauthorized'}, status=401)
        if request.headers.get('X-Spaceport-Admin') != '1':
            return web.json_response({'error': 'admin_header_required'}, status=403)
        if request.method == 'GET':
            return web.json_response(await get_state(request))
        if request.content_type != 'application/json':
            return web.json_response({'error': 'invalid_request'}, status=400)
        try:
            data = await request.clone(client_max_size=8192).json()
            if not isinstance(data, dict): raise ValueError()
            action = request.match_info['action']
            if action == 'device' and set(data) <= {'device', 'action', 'value'}:
                return web.json_response(commands.submit(data['device'], data['action'], data.get('value')), status=202)
            if action == 'notify':
                return web.json_response(notifications.submit(data), status=202)
            if action in ('call', 'dnd') and actions:
                field = 'target' if action == 'call' else 'enabled'
                if set(data) != {field, 'request_id', 'session_id'}: raise ValueError()
                if action == 'dnd' and type(data[field]) is not bool: raise ValueError()
                if action == 'call' and (not isinstance(data[field], str) or len(data[field]) > 24): raise ValueError()
                if not isinstance(data['request_id'], str) or len(data['request_id']) != 32: raise ValueError()
                result = await (actions.make_call(data[field], data['request_id'], data['session_id']) if action == 'call'
                                else actions.set_dnd(data[field], data['request_id'], data['session_id']))
                return web.json_response(result)
            if action == 'calendar_refresh' and calendar and not data:
                await calendar.refresh()
                return web.json_response(calendar.snapshot())
            raise ValueError()
        except Exception as error:
            from .actions import ActionError
            if isinstance(error, ActionError):
                return web.json_response({'error': error.code, 'message': error.message}, status=error.http_status)
            return web.json_response({'error': 'request_failed', 'message': 'Check the setting or connection and try again.'}, status=400)

    app.router.add_get('/admin', page)
    app.router.add_get('/admin/', page)
    app.router.add_get('/admin/api/state', api)
    app.router.add_post('/admin/api/{action:device|notify|call|dnd|calendar_refresh}', api)
