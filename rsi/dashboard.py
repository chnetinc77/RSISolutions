"""Research dashboard: stdlib HTTP server, JSON API at /api/state, auto-refreshing page at /."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .memory import Memory
from .perf import performance
from .problem import Ctx


def snapshot(mem: Memory, problems: dict) -> dict:
    probs = []
    for r in mem.rows("SELECT * FROM problems ORDER BY created"):
        pid = r["id"]
        p = problems.get(pid)
        base = p.arms()[0].name if p else None
        claims = mem.rows("SELECT status, COUNT(*) c FROM claims WHERE problem_id=? GROUP BY status", (pid,))
        probs.append({**r, "status": p.status(Ctx(mem, pid)) if p else {},
                      "experiments": mem.count_experiments(pid),
                      "claims": {c["status"]: c["c"] for c in claims},
                      "arm_stats": mem.arm_stats(pid),
                      "scale": mem.get_state(pid, "scale", 1.0),
                      "performance": performance(mem, pid, base),
                      "series": mem.rows("SELECT ts, name, value FROM metrics WHERE problem_id=? AND name LIKE 'rate:%' ORDER BY id DESC LIMIT 200", (pid,))[::-1]})
    claims = mem.rows("SELECT * FROM claims ORDER BY id DESC LIMIT 25")
    for c in claims:
        c["verifications"] = mem.rows("SELECT verifier, verdict FROM verifications WHERE claim_id=?", (c["id"],))
        c["evidence"] = c["evidence"][:200]
    return {"problems": probs,
            "experiments": mem.rows("SELECT id,problem_id,arm,status,summary,duration,started FROM experiments ORDER BY id DESC LIMIT 25"),
            "claims": claims,
            "lessons": mem.rows("SELECT problem_id,tag,text,created FROM lessons ORDER BY id DESC LIMIT 30"),
            "journal": mem.verify_journal()}


PAGE = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>RSI Research Dashboard</title><style>
:root{--bg:#fafaf7;--fg:#1c1c1a;--mut:#6b6b66;--card:#fff;--line:#e3e3dc;--acc:#2a5db0;--ok:#1f7a3f;--bad:#b3261e}
@media(prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecece6;--mut:#9a9a93;--card:#1f1f1c;--line:#34342f;--acc:#7aa7ee;--ok:#5fc27f;--bad:#f2766e}}
body{margin:0;padding:20px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;max-width:1100px;margin:auto}
h1{font-size:20px}h2{font-size:15px;margin:22px 0 8px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:12px}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600}.mut{color:var(--mut)}.ok{color:var(--ok)}.bad{color:var(--bad)}canvas{width:100%;height:150px}
.tag{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:0 6px;font-size:12px;margin-right:4px}
</style></head><body><h1>RSI Research Dashboard</h1><div id=meta class=mut></div><div id=app></div>
<script>
const $=(t,a={},...k)=>{const e=document.createElement(t);for(const[x,v]of Object.entries(a))e.setAttribute(x,v);for(const c of k)e.append(c instanceof Node?c:document.createTextNode(c??''));return e};
const T=(h,rows)=>{const t=$('table');t.append($('tr',{},...h.map(x=>$('th',{},x))));rows.forEach(r=>t.append($('tr',{},...r.map(c=>c instanceof Node?$('td',{},c):$('td',{},c)))));return t};
const cls=s=>s==='verified'?'ok':(s==='rejected'?'bad':'mut');
function chart(series){const c=$('canvas');c.width=1000;c.height=150;setTimeout(()=>{const g=c.getContext('2d'),W=c.width,H=c.height,css=getComputedStyle(document.body);
const arms=[...new Set(series.map(s=>s.name))];const mx=Math.max(1,...series.map(s=>s.value));const cols=['#2a5db0','#c2571a','#1f7a3f','#8a3ab9'];
arms.forEach((a,i)=>{const pts=series.filter(s=>s.name===a);g.strokeStyle=cols[i%4];g.fillStyle=cols[i%4];g.beginPath();pts.forEach((p,j)=>{const x=10+(W-20)*j/Math.max(1,pts.length-1),y=H-10-(H-20)*p.value/mx;j?g.lineTo(x,y):g.moveTo(x,y);g.fillRect(x-2,y-2,4,4)});g.stroke();g.font='12px sans-serif';g.fillText(a.slice(5),12+i*190,14)})});return c}
async function load(){const s=await (await fetch('/api/state')).json();const app=$('div');
document.getElementById('meta').textContent='journal '+(s.journal.ok?'intact ('+s.journal.length+' events)':'BROKEN at '+s.journal.broken_at)+' - updated '+new Date().toLocaleTimeString();
app.append($('h2',{},'Active problems'));
s.problems.forEach(p=>{const perf=p.performance;const card=$('div',{class:'card'},$('b',{},p.title),$('span',{class:'tag'},p.domain),$('div',{class:'mut'},p.statement),
$('div',{},'experiments: '+p.experiments+' - workload scale: '+(+p.scale).toFixed(2)+' - '+Object.entries(p.status).filter(([k,v])=>v).map(([k,v])=>k+': '+(typeof v==='object'?JSON.stringify(v):v)).join(' - ')),
$('div',{},'claims: '+(Object.entries(p.claims).map(([k,v])=>k+'='+v).join(', ')||'none')));
if(perf.speedup_vs_baseline)card.append($('div',{},'self-improvement: best strategy "'+perf.best_arm+'" runs '+perf.speedup_vs_baseline.toFixed(2)+'x faster than baseline (median of recent runs)'));
card.append(T(['strategy','runs','mean reward','best'],Object.entries(p.arm_stats).map(([a,v])=>[a,v.pulls,(v.total_reward/v.pulls).toFixed(3),v.best_reward.toFixed(3)])));
if(p.series.length)card.append($('div',{class:'mut'},'throughput per experiment (items/s)'),chart(p.series));app.append(card)});
app.append($('h2',{},'Claims and independent verification'),T(['id','kind','status','verifiers','statement'],s.claims.map(c=>[c.id,c.kind,$('span',{class:cls(c.status)},c.status),c.verifications.map(v=>v.verifier+':'+v.verdict).join(', '),c.statement])));
app.append($('h2',{},'Recent experiments'),T(['id','arm','status','sec','summary'],s.experiments.map(e=>[e.id,e.arm,e.status,(e.duration||0).toFixed(1),e.summary])));
app.append($('h2',{},'Lessons learned'),T(['tag','lesson'],s.lessons.map(l=>[l.tag,l.text])));
document.getElementById('app').replaceChildren(app)}
load();setInterval(load,5000);
</script></body></html>"""


def serve(db_path: str, problems: dict, host="127.0.0.1", port=8787):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/api/state"):
                body, ctype = json.dumps(snapshot(Memory(db_path), problems), default=str).encode(), "application/json"
            elif self.path == "/":
                body, ctype = PAGE.encode(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return ThreadingHTTPServer((host, port), H)
