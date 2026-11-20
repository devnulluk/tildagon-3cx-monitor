"""A separate display capability. It cannot administer or control the system."""
import hmac
import time
from aiohttp import web


def display_state(state, devices):
    # Do not pass command queues, capabilities, session IDs or administrator data.
    value={k:state[k] for k in ('version','connected','age_seconds','own','team','weather','calendar','notifications') if k in state}
    focus=devices.get('devices',{}).get('spaceagon',{})
    value['focus']={k:v for k,v in focus.get('settings',{}).items() if k in
                    ('focus_phase','focus_paused','focus_remaining','focus_minutes','break_minutes','long_break_minutes')}
    value['focus']['available']=bool(focus.get('online'))
    companion=devices.get('devices',{}).get('waveshare',{})
    settings=companion.get('settings',{})
    value['away']=bool(settings.get('presence_enabled') and (not companion.get('online') or not settings.get('phone_nearby',True)))
    value['server_time']=int(time.time())
    return value


def add_routes(app, token, get_state, devices):
    if not isinstance(token,str) or len(token)<32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError('TABLET_TOKEN must be at least 32 ASCII characters')
    async def page(request):
        from .tablet_page import PAGE
        return web.Response(text=PAGE,content_type='text/html',headers={
            'Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
            'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})
    async def state(request):
        supplied=request.headers.get('Authorization','')
        if not supplied.isascii() or not hmac.compare_digest(supplied,'Bearer '+token):
            return web.json_response({'error':'unauthorized'},status=401)
        return web.json_response(display_state(await get_state(request),devices.admin_snapshot()))
    app.router.add_get('/tablet',page)
    app.router.add_get('/tablet/',page)
    app.router.add_get('/tablet/api/state',state)
