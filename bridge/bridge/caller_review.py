"""An independent admin capability; badge/read/control tokens cannot review callers."""
import hmac
from aiohttp import web

PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Spaceport · Number book</title>
<style>
:root{color-scheme:dark;font:16px system-ui;background:#07111f;color:#deebfb}*{box-sizing:border-box}body{max-width:1050px;margin:0 auto;padding:40px 24px}header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #26425c;padding-bottom:24px;margin-bottom:28px}h1{font-size:32px;letter-spacing:-1px;margin:8px 0}.eyebrow{color:#5ce5cd;font-size:12px;letter-spacing:3px}p{color:#a9bad0;line-height:1.6}.panel,article{background:#101e30;border:1px solid #263d55;border-radius:18px;padding:22px;margin:18px 0}input,button,select{font:inherit;border-radius:9px;padding:11px 14px;border:1px solid #39546e;background:#0a1524;color:#e4f0ff}input{max-width:100%;min-width:0}button{cursor:pointer;background:#163a49;margin:4px}button.primary{background:#5ce5cd;color:#062126;border:0;font-weight:650}button:disabled{opacity:.45}label{display:inline-flex;flex-direction:column;gap:8px;margin:6px}.badge{display:inline-block;font-size:12px;padding:5px 10px;border-radius:20px;background:#24394c;color:#abd8ff}.guessed{color:#ffcf80;background:#4a3821}.confirmed{color:#89efd4;background:#164335}.rejected{color:#f6acb8;background:#422b38}.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.name{font-size:24px;font-weight:650;flex:1}.number{font:18px ui-monospace,monospace;color:#98b2d0}.sources{font-size:13px;color:#9ab3cc;word-break:break-word}a{color:#71d7ef}small{color:#9ab3cc}.hidden{display:none!important}#message{color:#80e9d5}#error{color:#ffafbf}#stats{max-width:360px;text-align:right;font-size:13px}.actions{margin-top:12px}.actions input{width:300px}.empty{text-align:center;padding:50px}#login input{width:390px}footer{font-size:12px;color:#7890aa;margin-top:40px}@media(max-width:650px){header{display:block}#stats{text-align:left;margin-top:15px}.actions input{width:100%}}
</style>
<header><div><div class="eyebrow">SPACEPORT / CALLER INTELLIGENCE</div><h1>Your number book</h1><small>Incoming &amp; outgoing · Your decisions come first</small></div><div id="stats">Private review console</div></header>
<section id="login" class="panel"><h2>Unlock your number book</h2><p>Use the separate review password provided during setup. It is held only in this tab’s memory; no badge or 3CX token is needed.</p><form id="loginForm"><label>Review password<input id="password" type="password" autocomplete="off" required></label><button class="primary">Unlock</button></form></section>
<main id="app" class="hidden"><section class="panel"><div class="row"><h2 style="flex:1;margin:0">Keep the good matches</h2><button id="refresh">Refresh</button><button id="lock">Lock</button></div><p>AI results are suggestions marked <b>Likely</b>. Confirm a good match or save a correction to use it permanently, without another API call. Reject a guess to keep the number and stop future AI lookup for it.</p><form id="addForm" class="row"><label>Number<input id="newNumber" type="tel" placeholder="01234 567890" required maxlength="40"></label><label>Confirmed name<input id="newName" placeholder="Company or contact name" required maxlength="80"></label><button class="primary">Add confirmed number</button></form></section><section class="row"><input id="search" placeholder="Filter name or number…" aria-label="Filter name or number"><select id="filter" aria-label="Filter status"><option value="">All entries</option><option value="guessed">Needs review</option><option value="confirmed">Confirmed</option><option value="unknown">No match</option><option value="rejected">Rejected</option></select></section><div id="entries"></div></main>
<p id="message" role="status"></p><p id="error" role="alert"></p><footer>Only unknown external numbers on your own extension are sent for web search. No contacts are uploaded in bulk. Cached guesses expire after 30 days; confirmed entries and corrections stay until you change them. A source is evidence of a published association, not proof of who is calling.</footer>
<script>
'use strict';let token='',rows=[];const $=id=>document.getElementById(id);function message(s){$('message').textContent=s;$('error').textContent=''}
async function api(path,data){const options={headers:{Authorization:'Bearer '+token,'X-Caller-Review':'1'},cache:'no-store'};if(data){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}const r=await fetch('/lookup/api/'+path,options);if(!r.ok)throw Error(r.status===401?'Review password not accepted.':'Request failed ('+r.status+').');return r.json()}
function element(tag,txt,cls){const e=document.createElement(tag);if(txt)e.textContent=txt;if(cls)e.className=cls;return e}
async function review(number,action,name){try{await api('review',{number,action,name});message(action==='reject'?'Rejected. This number will not trigger another AI lookup.':'Saved as confirmed. No API call is needed for this number.');await refresh()}catch(e){$('error').textContent=e.message}}
function render(){const q=$('search').value.toLowerCase(),f=$('filter').value;$('entries').replaceChildren();let count=0;for(const r of rows){if(f&&r.status!==f||q&&!((r.name+' '+r.number).toLowerCase().includes(q)))continue;count++;const card=element('article'),top=element('div',null,'row');top.append(element('div',(r.status==='guessed'?'Likely: ':'')+(r.name||'No match yet'),'name'),element('span',r.status,'badge '+r.status));card.append(top,element('p',r.number,'number'));if(r.source_url){const a=element('a','View source ↗');a.href=r.source_url;a.target='_blank';a.rel='noopener noreferrer';card.append(a);if(r.evidence)card.append(element('p',r.evidence,'sources'))}card.append(element('p',(r.direction||'Saved number')+' · '+(r.last_seen?new Date(r.last_seen*1000).toLocaleString():''),'sources'));const actions=element('div',null,'actions row'),input=element('input');input.value=r.name;input.maxLength=80;input.placeholder='Correct name';input.setAttribute('aria-label','Correct name for '+r.number);actions.append(input);const save=element('button','Save correction','primary');save.onclick=()=>review(r.number,'correct',input.value);actions.append(save);if(r.status==='guessed'){const confirm=element('button','Confirm match');confirm.onclick=()=>review(r.number,'confirm','');actions.append(confirm)}if(r.status!=='rejected'){const reject=element('button','Reject / keep number');reject.onclick=()=>review(r.number,'reject','');actions.append(reject)}card.append(actions);$('entries').append(card)}if(!count)$('entries').append(element('div',rows.length?'No entries match this filter.':'Your number book is ready. Incoming and outgoing external calls will appear here.','panel empty'))}
async function refresh(){const [book,status]=await Promise.all([api('entries'),api('status')]);rows=book.entries;$('stats').textContent=(status.enabled?status.model+' · web search':'AI lookup disabled')+' / '+status.requests_today+' of '+status.daily_limit+' daily requests';render()}
$('loginForm').onsubmit=async e=>{e.preventDefault();token=$('password').value;$('password').value='';try{await refresh();$('login').classList.add('hidden');$('app').classList.remove('hidden');message('Unlocked.')}catch(e){token='';$('error').textContent=e.message}};$('refresh').onclick=()=>refresh().catch(e=>$('error').textContent=e.message);$('lock').onclick=()=>{token='';rows=[];$('entries').replaceChildren();$('app').classList.add('hidden');$('login').classList.remove('hidden');$('stats').textContent='Locked';message('Locked.')};$('search').oninput=render;$('filter').onchange=render;$('addForm').onsubmit=async e=>{e.preventDefault();await review($('newNumber').value,'correct',$('newName').value)};
</script></html>'''


def add_routes(app, book, admin_token):
    if not isinstance(admin_token, str) or len(admin_token) < 24 or not admin_token.isascii() or any(c.isspace() for c in admin_token):
        raise ValueError('LOOKUP_ADMIN_TOKEN must be at least 24 ASCII characters')

    def authorized(request):
        value = request.headers.get('Authorization', '')
        return value.isascii() and hmac.compare_digest(value, 'Bearer ' + admin_token)

    async def page(request):
        return web.Response(text=PAGE, content_type='text/html', headers={
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})

    async def api(request):
        if not authorized(request):
            return web.json_response({'error': 'unauthorized'}, status=401)
        # Explicit capability header prevents ambient-credential browser CSRF.
        if request.headers.get('X-Caller-Review') != '1':
            return web.json_response({'error': 'review_header_required'}, status=403)
        if request.method == 'POST':
            if request.content_type != 'application/json':
                return web.json_response({'error': 'invalid_request'}, status=400)
            try:
                value = await request.json()
                if not isinstance(value, dict) or set(value) != {'number', 'action', 'name'}:
                    raise ValueError()
                book.review(value['number'], value['action'], value['name'])
            except (ValueError, TypeError):
                return web.json_response({'error': 'invalid_review'}, status=400)
            return web.json_response({'saved': True})
        if request.match_info['what'] == 'entries':
            return web.json_response({'entries': book.entries()})
        return web.json_response(book.status())

    app.router.add_get('/lookup', page)
    app.router.add_get('/lookup/', page)
    app.router.add_get('/lookup/api/{what:entries|status}', api)
    app.router.add_post('/lookup/api/review', api)
