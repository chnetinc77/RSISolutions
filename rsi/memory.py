"""Permanent research memory.

SQLite (WAL) holds experiments, claims, verifications, lessons, strategy
statistics, metrics and per-problem state.  Every mutation is also appended to a
hash-chained journal so silent edits of history are detectable.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS problems(id TEXT PRIMARY KEY, title TEXT, domain TEXT,
  statement TEXT, source TEXT, created REAL);
CREATE TABLE IF NOT EXISTS experiments(id INTEGER PRIMARY KEY AUTOINCREMENT, problem_id TEXT,
  arm TEXT, params TEXT, seed INTEGER, status TEXT, summary TEXT, result TEXT, metrics TEXT,
  digest TEXT, code_hash TEXT, env TEXT, started REAL, duration REAL);
CREATE TABLE IF NOT EXISTS claims(id INTEGER PRIMARY KEY AUTOINCREMENT, problem_id TEXT,
  experiment_id INTEGER, kind TEXT, statement TEXT, evidence TEXT, status TEXT, created REAL);
CREATE TABLE IF NOT EXISTS verifications(id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id INTEGER,
  verifier TEXT, verdict TEXT, details TEXT, created REAL);
CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY AUTOINCREMENT, problem_id TEXT,
  tag TEXT, text TEXT, created REAL);
CREATE TABLE IF NOT EXISTS arm_stats(problem_id TEXT, arm TEXT, pulls INTEGER, total_reward REAL,
  best_reward REAL, PRIMARY KEY(problem_id, arm));
CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, problem_id TEXT,
  name TEXT, value REAL);
CREATE TABLE IF NOT EXISTS state(problem_id TEXT, key TEXT, value TEXT, PRIMARY KEY(problem_id, key));
CREATE TABLE IF NOT EXISTS journal(seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT,
  payload TEXT, prev TEXT, hash TEXT);
"""

GENESIS = "0" * 64


def canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Memory:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            if path != ":memory:":
                self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            self.db.commit()

    # ---- journal -------------------------------------------------------
    def _journal(self, kind: str, payload: dict) -> None:
        ts = time.time()
        row = self.db.execute("SELECT hash FROM journal ORDER BY seq DESC LIMIT 1").fetchone()
        prev = row["hash"] if row else GENESIS
        body = canon(payload)
        h = sha256(prev + repr(ts) + kind + body)
        self.db.execute("INSERT INTO journal(ts,kind,payload,prev,hash) VALUES(?,?,?,?,?)",
                        (ts, kind, body, prev, h))

    def verify_journal(self) -> dict:
        with self.lock:
            prev = GENESIS
            n = 0
            for r in self.db.execute("SELECT * FROM journal ORDER BY seq"):
                if r["prev"] != prev or sha256(prev + repr(r["ts"]) + r["kind"] + r["payload"]) != r["hash"]:
                    return {"ok": False, "broken_at": r["seq"], "length": n}
                prev = r["hash"]
                n += 1
            return {"ok": True, "length": n, "head": prev}

    # ---- problems / state ---------------------------------------------
    def upsert_problem(self, pid, title, domain, statement, source):
        with self.lock:
            if not self.db.execute("SELECT 1 FROM problems WHERE id=?", (pid,)).fetchone():
                self.db.execute("INSERT INTO problems VALUES(?,?,?,?,?,?)",
                                (pid, title, domain, statement, source, time.time()))
                self._journal("problem", {"id": pid, "title": title, "domain": domain})
                self.db.commit()

    def get_state(self, pid, key, default=None):
        with self.lock:
            r = self.db.execute("SELECT value FROM state WHERE problem_id=? AND key=?", (pid, key)).fetchone()
            return json.loads(r["value"]) if r else default

    def set_state(self, pid, key, value):
        with self.lock:
            self.db.execute("INSERT INTO state VALUES(?,?,?) ON CONFLICT(problem_id,key) DO UPDATE SET value=excluded.value",
                            (pid, key, json.dumps(value)))
            self._journal("state", {"problem": pid, "key": key, "value": value})
            self.db.commit()

    # ---- experiments ---------------------------------------------------
    def start_experiment(self, pid, arm, params, seed, code_hash, env) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO experiments(problem_id,arm,params,seed,status,code_hash,env,started) VALUES(?,?,?,?,?,?,?,?)",
                (pid, arm, canon(params), seed, "running", code_hash, canon(env), time.time()))
            self._journal("experiment_start", {"id": cur.lastrowid, "problem": pid, "arm": arm,
                                               "params": params, "seed": seed, "code_hash": code_hash})
            self.db.commit()
            return cur.lastrowid

    def finish_experiment(self, eid, status, summary, result, metrics, digest, duration):
        with self.lock:
            self.db.execute("UPDATE experiments SET status=?,summary=?,result=?,metrics=?,digest=?,duration=? WHERE id=?",
                            (status, summary, canon(result), canon(metrics), digest, duration, eid))
            self._journal("experiment_finish", {"id": eid, "status": status, "digest": digest,
                                                "metrics": metrics, "duration": duration})
            self.db.commit()

    def get_experiment(self, eid) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
            return dict(r) if r else None

    def count_experiments(self, pid) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) c FROM experiments WHERE problem_id=?", (pid,)).fetchone()["c"]

    # ---- claims & verification ----------------------------------------
    def add_claim(self, pid, eid, kind, statement, evidence) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO claims(problem_id,experiment_id,kind,statement,evidence,status,created) VALUES(?,?,?,?,?,?,?)",
                                  (pid, eid, kind, statement, canon(evidence), "pending", time.time()))
            self._journal("claim", {"id": cur.lastrowid, "problem": pid, "experiment": eid, "kind": kind,
                                    "statement": statement, "evidence": evidence})
            self.db.commit()
            return cur.lastrowid

    def add_verification(self, claim_id, verifier, verdict, details):
        with self.lock:
            self.db.execute("INSERT INTO verifications(claim_id,verifier,verdict,details,created) VALUES(?,?,?,?,?)",
                            (claim_id, verifier, verdict, canon(details), time.time()))
            self._journal("verification", {"claim": claim_id, "verifier": verifier, "verdict": verdict, "details": details})
            self.db.commit()

    def set_claim_status(self, claim_id, status):
        with self.lock:
            self.db.execute("UPDATE claims SET status=? WHERE id=?", (status, claim_id))
            self._journal("claim_status", {"claim": claim_id, "status": status})
            self.db.commit()

    # ---- lessons, metrics, bandit stats -------------------------------
    def add_lesson(self, pid, tag, text):
        with self.lock:
            self.db.execute("INSERT INTO lessons(problem_id,tag,text,created) VALUES(?,?,?,?)", (pid, tag, text, time.time()))
            self._journal("lesson", {"problem": pid, "tag": tag, "text": text})
            self.db.commit()

    def record_metric(self, pid, name, value):
        with self.lock:
            self.db.execute("INSERT INTO metrics(ts,problem_id,name,value) VALUES(?,?,?,?)", (time.time(), pid, name, float(value)))
            self.db.commit()

    def update_arm(self, pid, arm, reward):
        with self.lock:
            r = self.db.execute("SELECT * FROM arm_stats WHERE problem_id=? AND arm=?", (pid, arm)).fetchone()
            if r:
                self.db.execute("UPDATE arm_stats SET pulls=pulls+1,total_reward=total_reward+?,best_reward=MAX(best_reward,?) WHERE problem_id=? AND arm=?",
                                (reward, reward, pid, arm))
            else:
                self.db.execute("INSERT INTO arm_stats VALUES(?,?,?,?,?)", (pid, arm, 1, reward, reward))
            self._journal("arm_update", {"problem": pid, "arm": arm, "reward": reward})
            self.db.commit()

    def arm_stats(self, pid) -> dict:
        with self.lock:
            return {r["arm"]: dict(r) for r in self.db.execute("SELECT * FROM arm_stats WHERE problem_id=?", (pid,))}

    # ---- queries -------------------------------------------------------
    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args)]

    def export_jsonl(self, outdir: str) -> list[str]:
        """Write human-diffable JSONL dumps (suitable for committing to git)."""
        os.makedirs(outdir, exist_ok=True)
        files = []
        for table in ["problems", "experiments", "claims", "verifications", "lessons", "arm_stats", "metrics", "state", "journal"]:
            p = os.path.join(outdir, f"{table}.jsonl")
            with open(p, "w") as f:
                for r in self.rows(f"SELECT * FROM {table}"):
                    f.write(canon(r) + "\n")
            files.append(p)
        return files
