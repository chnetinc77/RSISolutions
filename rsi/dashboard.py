"""Research dashboard: stdlib HTTP server, JSON API at /api/state, auto-refreshing page at /."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
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
        probs.append({**r, "prize": (p.prize if p else {}),
                      "status": p.status(Ctx(mem, pid)) if p else {},
                      "experiments": mem.count_experiments(pid),
                      "claims": {c["status"]: c["c"] for c in claims},
                      "arm_stats": mem.arm_stats(pid),
                      "scale": mem.get_state(pid, "scale", 1.0),
                      "performance": performance(mem, pid, base),
                      "best_series": mem.rows("SELECT ts, value FROM metrics WHERE problem_id=? AND name='best_C' ORDER BY id DESC LIMIT 300", (pid,))[::-1],
                      "series": mem.rows("SELECT ts, name, value FROM metrics WHERE problem_id=? AND name LIKE 'rate:%' ORDER BY id DESC LIMIT 200", (pid,))[::-1]})
    claims = mem.rows("SELECT * FROM claims ORDER BY id DESC LIMIT 25")
    for c in claims:
        c["verifications"] = mem.rows("SELECT verifier, verdict FROM verifications WHERE claim_id=?", (c["id"],))
        c["evidence"] = c["evidence"][:200]
    roles = {"Conductor": "Allocates compute between strategies and sizes the workload",
             "RSI": "Proposes and tests improvements to the system's own search",
             "Auditor": "Independently verifies claims and gates every self-modification"}
    agents = []
    for r in mem.rows("SELECT agent, COUNT(*) n, MAX(ts) last_ts FROM events GROUP BY agent ORDER BY MIN(id)"):
        last = mem.rows("SELECT kind, message FROM events WHERE agent=? ORDER BY id DESC LIMIT 1", (r["agent"],))[0]
        agents.append({"name": r["agent"], "role": roles.get(r["agent"], "Runs the " + r["agent"].split(":")[-1] + " research strategy"),
                       "events": r["n"], "last_ts": r["last_ts"], "last_kind": last["kind"], "last_message": last["message"]})
    return {"agents": agents,
            "events": mem.rows("SELECT id,ts,problem_id,agent,kind,message FROM events ORDER BY id DESC LIMIT 80"),
            "problems": probs,
            "experiments": mem.rows("SELECT id,problem_id,arm,status,summary,duration,started FROM experiments ORDER BY id DESC LIMIT 25"),
            "claims": claims,
            "lessons": mem.rows("SELECT problem_id,tag,text,created FROM lessons ORDER BY id DESC LIMIT 30"),
            "journal": mem.verify_journal()}


def publish(mem: Memory, problems: dict, outdir: str) -> str:
    """Write the public, static dashboard data (consumed by web/app.js on Vercel)."""
    from . import __version__
    snap = snapshot(mem, problems)
    snap["generated_at"] = time.time()
    snap["rsi_version"] = __version__
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "state.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snap, f, default=str, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def publish_live(mem: Memory, problems: dict, root: str) -> str:
    """Push the current snapshot to a one-commit `live-data` branch (no Vercel redeploy needed;
    the static site polls it).  Returns 'pushed' or 'unchanged'."""
    import fcntl
    lock = open(os.path.join(root, ".live-data.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    snap = snapshot(mem, problems)
    live = os.path.join(root, ".live-data")

    def git(*a, check=True, cwd=live):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=check)

    if not os.path.isdir(os.path.join(live, ".git")):
        url = git("remote", "get-url", "origin", cwd=root).stdout.strip()
        r = subprocess.run(["git", "clone", "-q", "--branch", "live-data", "--single-branch", url, live], capture_output=True, text=True)
        if r.returncode != 0:
            shutil.rmtree(live, ignore_errors=True)
            os.makedirs(live)
            git("init", "-q")
            git("checkout", "-q", "--orphan", "live-data")
            git("remote", "add", "origin", url)
        for key in ("user.name", "user.email"):
            val = git("config", key, check=False, cwd=root).stdout.strip()
            if val:
                git("config", key, val)
    path = os.path.join(live, "state.json")
    if os.path.isfile(path):
        try:
            old = json.load(open(path))
            old.pop("generated_at", None)
            if old == json.loads(json.dumps(snap, default=str)):
                return "unchanged"
        except Exception:  # noqa: BLE001
            pass
    snap["generated_at"] = time.time()
    with open(path + ".tmp", "w") as f:
        json.dump(snap, f, default=str, separators=(",", ":"))
    os.replace(path + ".tmp", path)
    git("add", "state.json")
    has_head = git("rev-parse", "--verify", "HEAD", check=False).returncode == 0
    git("commit", "-q", *(["--amend"] if has_head else []), "-m", "live data")
    git("push", "-q", "--force", "-u", "origin", "live-data")
    return "pushed"


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
