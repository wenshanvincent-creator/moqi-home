import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .memory import snapshot


HTML = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moqi home diary</title><style>
body{font:16px system-ui;margin:0;background:#f5f4ef;color:#22352d}
main{max-width:1100px;margin:40px auto;padding:0 24px}h1{font-size:36px}
.hint{color:#57685f}section{background:white;border-radius:12px;padding:24px;margin:20px 0}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:10px;border-bottom:1px solid #ddd;overflow-wrap:anywhere}
.scroll{overflow:auto}.stats{font-size:22px}code{font-size:12px}
</style><main><h1>Moqi home diary</h1><p class="hint">Observe → verify evidence → predict in shadow</p>
<p id="status">Loading local data…</p><section><h2>Evidence</h2><p id="stats" class="stats"></p>
<p>No device control is available. Motion inactivity does not prove an empty room.</p></section>
<section><h2>Persistent habits</h2><p class="hint">Hierarchical contexts, exposure-based forgetting, separate earned trust. Physical execution awaits acceptance.</p><div id="habits" class="scroll"></div></section>
<section><h2>Shadow predictions</h2><div id="forecasts" class="scroll"></div></section>
<section><h2>Recent events</h2><p class="hint">Unknown actions need an evidence note through the annotate command before learning.</p><div id="events" class="scroll"></div></section>
<section><h2>Episodes</h2><p class="hint">Arrival, departure, sleep and waking require configured sensor evidence.</p><div id="episodes" class="scroll"></div></section>
<section><h2>Questions and archive</h2><div id="questions" class="scroll"></div></section>
<section><h2>World models</h2><div id="models" class="scroll"></div></section>
<section><h2>Constraints</h2><div id="constraints" class="scroll"></div></section>
<section><h2>Memory audit</h2><div id="changes" class="scroll"></div></section>
<script>
function table(id,rows,keys){const root=document.getElementById(id);root.replaceChildren();if(!rows.length){root.textContent='No evidence yet.';return;}
const t=document.createElement('table'),head=document.createElement('tr');for(const k of keys){const th=document.createElement('th');th.textContent=k;head.append(th);}t.append(head);
for(const row of rows){const tr=document.createElement('tr');for(const k of keys){const td=document.createElement('td');td.textContent=Array.isArray(row[k])?row[k].join(', '):String(row[k]??'pending');tr.append(td);}t.append(tr);}root.append(t);}
async function refresh(){try{let d;const embedded=document.getElementById('snapshot');if(embedded){d=JSON.parse(embedded.textContent);}else{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('unavailable');d=await r.json();}
document.getElementById('status').textContent=d.mode+' · '+d.timezone+' · updated '+d.asof;
document.getElementById('stats').textContent=d.event_count+' events · '+d.unverified_actions+' unverified actions';
table('habits',d.habits,['entity_id','target','day_type','time_slot','occurrences','successes','failures','probability','trust','risk','status']);
table('forecasts',d.forecasts,['entity_id','target','issued_at','probability','outcome']);
table('events',d.recent_events.slice().reverse(),['event_key','entity_id','occurred_at','old_state','new_state','attributed_source']);
table('episodes',d.episodes,['start','end','boundary','events','rooms']);
table('questions',d.questions,['status','text','occurrences']);
table('models',d.models,['id','status','samples']);
table('constraints',d.constraints,['entity_id','deny_actions','scope','reason','active']);
table('changes',d.changes,['at','kind']);}
catch(e){document.getElementById('status').textContent='Local data unavailable. Check the server terminal.';}}
refresh();setInterval(refresh,30000);
</script></main></html>'''


def export_html(store, config, path):
    payload = json.dumps(snapshot(store, config, datetime.now(timezone.utc)), ensure_ascii=False).replace('<', '\\u003c')
    embedded = '<script id="snapshot" type="application/json">'+payload+'</script>'
    with Path(path).open('x', encoding='utf-8') as output:
        output.write(HTML.replace('<script>', embedded+'<script>', 1))


def serve(store, config, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                body, mime = HTML.encode('utf-8'), 'text/html; charset=utf-8'
            elif self.path == '/api/status':
                body = json.dumps(snapshot(store, config, datetime.now(timezone.utc)), ensure_ascii=False).encode()
                mime = 'application/json; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(('127.0.0.1', port), Handler)
    print(f'Diary available at http://127.0.0.1:{port}; Ctrl+C stops it', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
