"""Command line interface: python -m rsi <command>"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    from .dashboard import serve
    from .engine import Engine
    from .memory import Memory
    from .perf import performance
    from .problem import load_problems

    ap = argparse.ArgumentParser(prog="rsi")
    ap.add_argument("--db", default=os.path.join(ROOT, "memory", "rsi.sqlite"))
    ap.add_argument("--problems", default=os.path.join(ROOT, "problems"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("problems")
    r = sub.add_parser("run"); r.add_argument("problem"); r.add_argument("--steps", type=int, default=1)
    r.add_argument("--target-seconds", type=float, default=20.0); r.add_argument("--arm"); r.add_argument("--seed", type=int, default=0)
    r.add_argument("--forever", action="store_true"); r.add_argument("--mem-limit-mb", type=int, default=5000)
    d = sub.add_parser("dashboard"); d.add_argument("--host", default="127.0.0.1"); d.add_argument("--port", type=int, default=8787)
    sub.add_parser("status"); sub.add_parser("claims"); sub.add_parser("verify-journal")
    rp = sub.add_parser("replay"); rp.add_argument("experiment", type=int)
    sub.add_parser("export")
    a = ap.parse_args(argv)

    problems = load_problems(a.problems)
    mem = Memory(a.db)
    if a.cmd == "problems":
        for p in problems.values():
            print(f"{p.id}\t[{p.domain}]\t{p.title}")
    elif a.cmd == "run":
        if a.mem_limit_mb:
            try:
                import resource
                lim = a.mem_limit_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
            except Exception:  # noqa: BLE001
                pass
        eng = Engine(mem, problems, seed=a.seed, target_seconds=a.target_seconds, repo_root=ROOT)
        n = 0
        while True:
            try:
                out = eng.step(a.problem, a.arm)
            except RuntimeError as e:
                if "MAX_N" in str(e):
                    print("frontier cap reached; stopping cleanly")
                    break
                raise
            n += 1
            print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in out.items()}))
            if not a.forever and n >= a.steps:
                break
            if a.forever and out.get("status") == "failed":
                if "MAX_N" in out.get("error", ""):
                    print("frontier cap reached; stopping cleanly")
                    break
                time.sleep(30)
    elif a.cmd == "dashboard":
        srv = serve(a.db, problems, a.host, a.port)
        print(f"dashboard on http://{a.host}:{a.port}")
        srv.serve_forever()
    elif a.cmd == "status":
        from .dashboard import snapshot
        s = snapshot(mem, problems)
        for p in s["problems"]:
            print(p["id"], "experiments:", p["experiments"], "claims:", p["claims"], "status:", p["status"], "perf:", p["performance"])
        print("journal:", s["journal"])
    elif a.cmd == "claims":
        for c in mem.rows("SELECT id,kind,status,statement FROM claims ORDER BY id"):
            print(c)
    elif a.cmd == "verify-journal":
        res = mem.verify_journal(); print(res); sys.exit(0 if res["ok"] else 1)
    elif a.cmd == "replay":
        res = Engine(mem, problems).replay(a.experiment); print(json.dumps(res, indent=2)); sys.exit(0 if res["reproduced"] else 1)
    elif a.cmd == "export":
        print("\n".join(mem.export_jsonl(os.path.join(ROOT, "memory", "export"))))


if __name__ == "__main__":
    main()
