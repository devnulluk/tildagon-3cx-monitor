"""Independent administrator capability. No provider or device secrets leave the server."""
import hmac
import json
import secrets
import time
from aiohttp import web


class DeviceCommands:
    def __init__(self):
        self.commands = {}

    def submit(self, device, action, value=None):
        choices = {
            'waveshare': {'mute', 'unmute', 'silence', 'dismiss', 'page', 'volume', 'priority_volume', 'brightness', 'test', 'demo', 'live'},
            'spaceagon': {'ring_brightness', 'eeh_brightness', 'matrix_brightness', 'focus_brightness', 'focus_direction', 'theme', 'clock', 'focus_start', 'focus_pause', 'focus_reset'},
        }
        if device not in choices or action not in choices[device]:
            raise ValueError('Unsupported device command')
        if action == 'focus_direction':
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
        self.commands[device] = command
        return {'status': 'queued', 'id': command['id'], 'expires_in': 60}

    def snapshot(self):
        return {device: dict(c) for device, c in self.commands.items() if c['expires'] > time.time()}


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
