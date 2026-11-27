"""Erdős problems via AI proof search with Lean verification.

Free-tier language models (Gemini etc.) propose Lean 4 tactic proofs for OPEN, formalised problems
from DeepMind's formal-conjectures collection; the Lean kernel accepts or rejects each one.
A kernel-checked proof is only ever a *candidate*: a human must confirm that the formal statement
matches the real problem and that the result is new before anything is claimed.

Honest odds: DeepMind's own prover (frontier models, large budgets) proved a minority of this
collection's open problems.  Free lighter models are weaker; success is possible but not likely.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from rsi import lean
from rsi.llm import LLMBudget, LLMError, Usage, build_llm_from_env
from rsi.problem import Arm, ClaimSpec, ExperimentResult, Problem, Report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "lean_challenges", "index.json")
PROOFS = os.path.join(ROOT, "proofs")
MAX_PER_ARM = 3
SWEEP = "first | decide | omega | norm_num | simp | aesop | tauto | linarith"
SYSTEM = ("You are an expert in Lean 4 and Mathlib who writes correct, complete tactic proofs. "
          "Never use sorry or new top-level declarations. If a statement looks false, say nothing extra: just give your best proof attempt.")

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = build_llm_from_env()
    return _llm


def load_index():
    try:
        with open(INDEX) as f:
            d = json.load(f)
        return d["repo"], {c["id"]: c for c in d["challenges"]}
    except Exception:  # noqa: BLE001
        return None, {}


def _prompt(ch, feedback=None, skeleton=False):
    ans = ("\nThe statement contains `answer(sorry)`: the FIRST line of your reply must be `ANSWER: True` or `ANSWER: False` "
           "(whether the right-hand side holds), then a proof for that choice.\n") if ch["has_answer"] else ""
    task = ("Write a proof SKELETON: the main proof structure using `have name : <statement> := by sorry` for each hard step, "
            "ending with a complete argument that uses those steps. At most 4 `sorry`s.") if skeleton else \
           "Write the complete proof."
    fb = f"\nYour previous attempt failed with these Lean errors; fix them:\n{feedback[:1800]}\n" if feedback else ""
    return (f"Prove this Lean 4 theorem (Mathlib is imported). It is an open research problem; give your best attempt.\n"
            f"Definitions in the file before the theorem:\n```lean\n{ch['context'][-3000:]}\n```\n"
            f"Theorem:\n```lean\ntheorem {ch['name']} {ch['statement']} := by\n```\n{ans}{task}\n"
            f"Reply with ONE ```lean code block containing ONLY the tactic lines that follow `:= by` (no theorem statement, "
            f"no new top-level declarations; use `have` inside the proof).{fb}")


def _fill_prompt(ch, tactics, pos):
    lines = tactics[:pos].splitlines()[-8:]
    return (f"In this partial Lean 4 proof of `{ch['name']}`, replace the marked `sorry` by tactics that prove that step.\n"
            f"Context before the sorry:\n```lean\n{chr(10).join(lines)}\n  sorry  -- <== prove this\n```\n"
            f"Reply with ONE ```lean block containing ONLY the replacement tactics.")


class FormalErdos(Problem):
    id = "erdos_formal"
    title = "Erdős problems: AI proof search with Lean verification"
    domain = "mathematics (formal proof)"
    statement = ("Open, formalised Erdős problems are attacked by language-model proof attempts. Every attempt is compiled by the Lean kernel; "
                 "only kernel-accepted proofs are kept, and each still needs human review of the statement and novelty before any claim.")
    source = "google-deepmind/formal-conjectures (FormalConjectures/ErdosProblems); erdosproblems.com"
    replayable = False
    prize = {"reward": "Varies by problem; most open formalised problems carry no cash prize (check erdosproblems.com for each)",
             "terms_verified": False,
             "status": "Free-tier models are much weaker than the frontier systems that have solved a few of these. A verified proof is a candidate only."}

    def arms(self):
        return [
            Arm("automation_sweep", description="no language model: try standard Lean automation tactics"),
            Arm("llm_direct", params={"repair_rounds": 2, "temperature": 0.4}, tunable={"repair_rounds": (0, 4), "temperature": (0.1, 1.0)},
                description="free LLM writes a proof; Lean errors are fed back for repair"),
            Arm("llm_decompose", params={"temperature": 0.5, "max_subgoals": 4}, tunable={"temperature": (0.1, 1.0)},
                description="free LLM writes a skeleton; each sorry is then filled separately"),
        ]

    def plan(self, ctx, arm, tuned, scale):
        _, idx = load_index()
        att, done = ctx.get("attempts", {}), set(ctx.get("candidate_ids", []))
        pool = [c for c in idx.values() if c["id"] not in done and att.get(c["id"], {}).get(arm.name, 0) < MAX_PER_ARM]
        if not pool:
            return {**tuned, "challenge": None}
        pick = min(pool, key=lambda c: (sum(att.get(c["id"], {}).values()), len(c["statement"])))
        return {**tuned, "challenge": pick["id"]}

    # ---- attempts ------------------------------------------------------
    def _save(self, ch, tactics, answer, full_text, axioms):
        os.makedirs(PROOFS, exist_ok=True)
        path = os.path.join(PROOFS, re.sub(r"[^A-Za-z0-9_]", "_", ch["id"]) + "_" + hashlib.sha256(full_text.encode()).hexdigest()[:8] + ".lean")
        with open(path, "w", encoding="utf-8") as f:
            f.write(full_text)
        return path

    def _try(self, text, ch, tactics, answer, tag, allow_sorry=False):
        lean.sanitize_tactics(tactics, allow_sorry)
        full = lean.splice(text, ch, tactics, answer)
        return full, lean.check(full, ch["full_name"], tag, allow_sorry=allow_sorry)

    def _sweep(self, params, text, ch, seed):
        calls = 0
        for ans in (["True", "False"] if ch["has_answer"] else [None]):
            full, r = self._try(text, ch, SWEEP, ans, f"sw_{seed}")
            calls += 1
            if r["ok"]:
                return {"proven": True, "tactics": SWEEP, "answer": ans, "full": full, "axioms": r["axioms"], "progress": 1.0, "calls": calls}
        return {"proven": False, "progress": 0.0, "calls": calls}

    def _direct(self, params, text, ch, seed):
        llm, feedback, calls = get_llm(), None, 0
        for rnd in range(int(params["repair_rounds"]) + 1):
            resp = llm.complete(_prompt(ch, feedback), SYSTEM, float(params["temperature"]))
            tactics, ans = lean.extract_tactics(resp), (lean.extract_answer(resp) if ch["has_answer"] else None)
            if ch["has_answer"] and ans is None:
                feedback = "You must start your reply with `ANSWER: True` or `ANSWER: False`."
                continue
            try:
                full, r = self._try(text, ch, tactics, ans, f"d_{seed}_{rnd}")
            except ValueError as e:
                feedback = f"Rejected before compiling: {e}"
                continue
            calls += 1
            if r["ok"]:
                return {"proven": True, "tactics": tactics, "answer": ans, "full": full, "axioms": r["axioms"], "progress": 1.0, "calls": calls}
            feedback = "\n".join(r["errors"]) or r["tail"]
        return {"proven": False, "progress": 0.0, "calls": calls}

    def _decompose(self, params, text, ch, seed):
        llm, calls = get_llm(), 0
        resp = llm.complete(_prompt(ch, skeleton=True), SYSTEM, float(params["temperature"]))
        tactics, ans = lean.extract_tactics(resp), (lean.extract_answer(resp) if ch["has_answer"] else None)
        if ch["has_answer"] and ans is None:
            return {"proven": False, "progress": 0.0, "calls": 0}
        try:
            _, r = self._try(text, ch, tactics, ans, f"s_{seed}", allow_sorry=True)
        except ValueError:
            return {"proven": False, "progress": 0.0, "calls": 0}
        calls += 1
        if not r["ok"]:
            return {"proven": False, "progress": 0.0, "calls": calls}
        total = len(re.findall(r"\bsorry\b", tactics))
        filled, pos = 0, 0
        for _ in range(min(total, int(params["max_subgoals"]))):
            m = re.compile(r"\bsorry\b").search(tactics, pos)
            if not m:
                break
            sub = lean.extract_tactics(llm.complete(_fill_prompt(ch, tactics, m.start()), SYSTEM, float(params["temperature"])))
            indent = " " * (len(tactics[:m.start()].splitlines()[-1]) - len(tactics[:m.start()].splitlines()[-1].lstrip())) if tactics[:m.start()].splitlines() else ""
            block = ("\n" + indent).join(sub.splitlines()) if len(sub.splitlines()) > 1 else sub
            cand = tactics[:m.start()] + block + tactics[m.end():]
            try:
                _, r2 = self._try(text, ch, cand, ans, f"f_{seed}_{filled}", allow_sorry=True)
            except ValueError:
                pos = m.end()
                continue
            calls += 1
            if r2["ok"]:
                tactics, filled, pos = cand, filled + 1, m.start() + len(block)
            else:
                pos = m.end()
        if not re.search(r"\bsorry\b", tactics):
            try:
                full, r3 = self._try(text, ch, tactics, ans, f"p_{seed}")
                calls += 1
                if r3["ok"]:
                    return {"proven": True, "tactics": tactics, "answer": ans, "full": full, "axioms": r3["axioms"], "progress": 1.0, "calls": calls}
            except ValueError:
                pass
        return {"proven": False, "progress": round(0.1 + 0.9 * filled / max(total, 1) * 0.99, 4), "calls": calls}

    def run(self, params, seed):
        def none(msg, sleep=0, counted=False, cid=None):
            return ExperimentResult(msg, {"progress": 0.0}, {"challenge": cid, "proven": False, "counted": counted}, extra={"sleep": sleep})
        repo, idx = load_index()
        if not params.get("challenge") or not idx:
            return none("no eligible challenge (run `python3 -m rsi lean-index`, or all attempts are used up)", 1800)
        if not lean.lean_available():
            return none("Lean is not installed yet (run scripts/setup_lean.sh)", 1800)
        ch = idx[params["challenge"]]
        text = open(os.path.join(repo, ch["file"]), encoding="utf-8").read()
        if hashlib.sha256(text.encode()).hexdigest()[:16] != ch["file_sha"]:
            return none("challenge file changed since indexing; re-run `python3 -m rsi lean-index`", 600)
        arm = params["arm"]
        try:
            fn = {"automation_sweep": self._sweep, "llm_direct": self._direct, "llm_decompose": self._decompose}[arm]
            out = fn(params, text, ch, seed)
        except LLMBudget:
            return none("free-tier daily request cap reached; waiting", 3600)
        except LLMError as e:
            return none(f"LLM unavailable ({e}); retrying later", 300)
        claims = []
        if out["proven"]:
            path = self._save(ch, out["tactics"], out["answer"], out["full"], out["axioms"])
            claims.append(ClaimSpec("proof", f"Lean 4 proof candidate for {ch['full_name']} ({ch['file']}); kernel-checked with standard axioms only; "
                                    f"NOT yet reviewed by a human; statement fidelity and novelty unverified",
                                    {"challenge": ch["id"], "full_name": ch["full_name"], "tactics": out["tactics"], "answer": out["answer"],
                                     "lean_file": path, "axioms": out["axioms"]}))
        return ExperimentResult(
            f"{arm} on {ch['id']}: " + ("PROOF CANDIDATE (kernel-checked)" if out["proven"] else f"no proof ({out['calls']} Lean runs, progress {out['progress']})"),
            {"progress": out["progress"], "lean_calls": out["calls"]},
            {"challenge": ch["id"], "proven": out["proven"], "counted": True, "progress": out["progress"]}, claims=claims)

    def verify(self, claim):
        if claim.kind != "proof":
            return []
        ev = claim.evidence
        repo, idx = load_index()
        ch = idx[ev["challenge"]]
        text = open(os.path.join(repo, ch["file"]), encoding="utf-8").read()
        reports = []
        try:
            lean.sanitize_tactics(ev["tactics"])
            reports.append(Report("static_audit", "pass", {}))
        except ValueError as e:
            reports.append(Report("static_audit", "fail", {"reason": str(e)}))
            return reports
        for name, ok, det in lean.recheck_saved(ev, ch, text):
            reports.append(Report(name, "pass" if ok else "fail", det))
        return reports

    def commit(self, ctx, params, result):
        d = result.deterministic
        if not d.get("challenge") or not d.get("counted"):
            return
        att = ctx.get("attempts", {})
        a = att.setdefault(d["challenge"], {})
        a[params["arm"]] = a.get(params["arm"], 0) + 1
        ctx.set("attempts", att)
        if d.get("proven") and result.extra.get("claim_statuses") == ["formally_checked_pending_human_review"]:
            cands = ctx.get("candidates", [])
            cands.append({"id": d["challenge"], "arm": params["arm"]})
            ctx.set("candidates", cands)
            ctx.set("candidate_ids", [c["id"] for c in cands])
            ctx.mem.add_lesson(self.id, "ALERT", f"Lean-verified proof candidate for {d['challenge']}: human review of the statement and novelty is required before any claim.")
            ctx.mem.add_event(self.id, "Auditor", "alert", f"LEAN-VERIFIED PROOF CANDIDATE for {d['challenge']} - human review required (statement fidelity, novelty)")

    def status(self, ctx):
        _, idx = load_index()
        att = ctx.get("attempts", {})
        llm = get_llm()
        usage = Usage(os.path.join(ROOT, "memory", "llm_usage.json"))
        return {"challenges_indexed": len(idx), "challenges_attempted": len(att),
                "proof_candidates": [c["id"] for c in ctx.get("candidates", [])],
                "llm_providers": [c.name for c in llm.clients] if hasattr(llm, "clients") else ["mock"],
                "llm_requests_today": sum(usage.count(c.name) for c in getattr(llm, "clients", [])),
                "lean_ready": lean.lean_available()}


def get_problems():
    return [FormalErdos()]
