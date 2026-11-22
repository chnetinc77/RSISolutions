"""Autonomous research loop with recursive self-improvement.

Each step: choose strategy (UCB bandit + periodic analysis/baseline refresh) ->
tune parameters (hill climbing) -> run experiment -> independently verify claims ->
commit progress only if verified -> learn (rewards, lessons, adaptive workload scale).
"""
from __future__ import annotations

import math
import platform
import random
import subprocess
import sys
import time

from .memory import Memory, canon, sha256
from .problem import Ctx, Problem
from .verify import verify_claim


def env_info(repo_root: str | None = None) -> dict:
    commit = None
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=repo_root, timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        pass
    return {"python": sys.version.split()[0], "platform": platform.platform(), "git_commit": commit}


def ucb_select(arms, stats, c=0.6):
    for a in arms:
        if stats.get(a.name, {}).get("pulls", 0) < 2:
            return a
    total = sum(stats[a.name]["pulls"] for a in arms)
    def score(a):
        s = stats[a.name]
        return s["total_reward"] / s["pulls"] + c * math.sqrt(2 * math.log(total) / s["pulls"])
    return max(arms, key=score)


class Engine:
    def __init__(self, mem: Memory, problems: dict[str, Problem], seed=0, target_seconds=20.0,
                 explore_prob=0.35, baseline_refresh=15, repo_root=None):
        self.mem, self.problems, self.seed = mem, problems, seed
        self.target, self.explore_prob, self.baseline_refresh = target_seconds, explore_prob, baseline_refresh
        self.env = env_info(repo_root)

    # ---- helpers -------------------------------------------------------
    def _choose(self, prob, ctx, arms, n_exp, force):
        by_name = {a.name: a for a in arms}
        if force:
            return by_name[force], "forced"
        search = [a for a in arms if a.kind == "search"]
        for a in arms:  # periodic analysis arms
            if a.kind == "analysis" and a.period and n_exp - ctx.get(f"last_idx:{a.name}", 0) >= a.period:
                return a, "analysis"
        n_search = ctx.get("n_search", 0)
        base = search[0]
        if len(search) > 1 and n_search - ctx.get(f"last_search_idx:{base.name}", 0) >= self.baseline_refresh:
            return base, "baseline_refresh"
        return ucb_select(search, self.mem.arm_stats(prob.id)), "bandit"

    @staticmethod
    def _perturb(base, tunable, rng):
        name = rng.choice(sorted(tunable))
        lo, hi = tunable[name]
        v = base.get(name, lo) * rng.choice([0.5, 0.7, 1.4, 2.0])
        v = min(max(v, lo), hi)
        if isinstance(lo, int) and isinstance(hi, int):
            v = int(round(v))
        new = dict(base)
        new[name] = v
        return new if new != base else None

    # ---- one research step --------------------------------------------
    def step(self, pid: str, force_arm: str | None = None) -> dict:
        prob, mem = self.problems[pid], self.mem
        ctx = Ctx(mem, pid)
        mem.upsert_problem(pid, prob.title, prob.domain, prob.statement, prob.source)
        arms = prob.arms()
        n_exp = mem.count_experiments(pid)
        rng = random.Random(self.seed * 1_000_003 + n_exp)
        arm, why = self._choose(prob, ctx, arms, n_exp, force_arm)
        base = {**arm.params, **ctx.get(f"tuned:{arm.name}", {})}
        proposal = None
        if arm.kind == "search" and arm.tunable and why != "forced" and rng.random() < self.explore_prob:
            proposal = self._perturb(base, arm.tunable, rng)
        used = proposal or base
        scale = ctx.get("scale", 1.0)
        params = dict(prob.plan(ctx, arm, used, scale))
        params["arm"] = arm.name
        seed = rng.randrange(2**31)
        eid = mem.start_experiment(pid, arm.name, params, seed, prob.code_hash(), self.env)
        t0 = time.perf_counter()
        try:
            result = prob.run(params, seed)
        except Exception as e:  # noqa: BLE001
            dur = time.perf_counter() - t0
            mem.finish_experiment(eid, "failed", repr(e), {}, {}, "", dur)
            mem.add_lesson(pid, "failed_approach", f"{arm.name} {canon(params)} crashed: {e!r}")
            return {"experiment": eid, "arm": arm.name, "status": "failed", "error": repr(e)}
        dur = time.perf_counter() - t0
        digest = sha256(canon(result.deterministic))
        mem.finish_experiment(eid, "ok", result.summary, result.deterministic, result.metrics, digest, dur)

        # independent verification of every claim
        t1 = time.perf_counter()
        statuses = []
        for spec in result.claims:
            cid = mem.add_claim(pid, eid, spec.kind, spec.statement, spec.evidence)
            status, reports = verify_claim(prob, spec)
            for r in reports:
                mem.add_verification(cid, r.verifier, r.verdict, r.details)
            mem.set_claim_status(cid, status)
            statuses.append((spec.kind, status, cid))
            if spec.kind == "counterexample" and status == "verified":
                mem.add_lesson(pid, "ALERT", f"claim {cid}: independently VERIFIED counterexample - escalate and check original problem conditions before any claim of reward.")
                ctx.set("alert", {"claim": cid, "statement": spec.statement})
            if status == "rejected":
                mem.add_lesson(pid, "failed_approach", f"claim {cid} rejected by independent verification ({arm.name}): {spec.statement}")
        vdur = time.perf_counter() - t1

        refuted = any(k == "counterexample" and s == "verified" for k, s, _ in statuses)
        committed = (not refuted) and all(s == "verified" for k, s, _ in statuses if k in ("evidence", "witness", "counterexample"))
        out = {"experiment": eid, "arm": arm.name, "why": why, "status": "ok", "committed": committed,
               "duration": dur, "verify_seconds": vdur, "claims": [s for _, s, _ in statuses], "summary": result.summary}
        ctx.set(f"last_idx:{arm.name}", n_exp + 1)
        if committed:
            prob.commit(ctx, params, result)
        mem.record_metric(pid, "verify_seconds", vdur)

        if arm.kind == "search" and committed:
            n_search = ctx.get("n_search", 0) + 1
            ctx.set("n_search", n_search)
            ctx.set(f"last_search_idx:{arm.name}", n_search)
            rate = prob.progress_of(result) / max(dur, 1e-9)
            best = max(ctx.get("best_rate", 0.0), rate)
            ctx.set("best_rate", best)
            reward = min(1.0, rate / best)
            mem.update_arm(pid, arm.name, reward)
            mem.record_metric(pid, f"rate:{arm.name}", rate)
            mem.record_metric(pid, "rate", rate)
            out.update(rate=rate, reward=reward)
            self._tune(ctx, mem, pid, arm, base, proposal, rate)
            # adaptive workload scale keeps steps near the target wall time
            ratio = self.target / max(dur + vdur, 1e-9)
            new_scale = min(max(scale * min(max(ratio, 0.5), 2.0), 0.001), 1000.0)
            if abs(new_scale - scale) / scale > 0.05:
                ctx.set("scale", new_scale)
            mem.record_metric(pid, "scale", new_scale)
            if n_search % 10 == 0:
                self._reflect(ctx, mem, pid, prob)
        elif arm.kind == "search":
            mem.add_lesson(pid, "failed_approach", f"experiment {eid} ({arm.name}) did not commit: claims={out['claims']}")
        else:
            ctx.set(f"last_idx:{arm.name}", n_exp + 1)
        return out

    def _tune(self, ctx, mem, pid, arm, base, proposal, rate):
        if not arm.tunable:
            return
        inc = ctx.get(f"incumbent_rate:{arm.name}")
        if proposal is None:
            ctx.set(f"incumbent_rate:{arm.name}", rate if inc is None else 0.5 * inc + 0.5 * rate)
            return
        if inc is None or rate > inc * 1.05:
            ctx.set(f"tuned:{arm.name}", {k: proposal[k] for k in arm.tunable})
            ctx.set(f"incumbent_rate:{arm.name}", rate)
            mem.add_lesson(pid, "tuning", f"{arm.name}: adopted {canon({k: proposal[k] for k in arm.tunable})} (rate {rate:.0f}/s vs incumbent {inc if inc is None else round(inc)})")
        else:
            mem.add_lesson(pid, "tuning", f"{arm.name}: rejected {canon({k: proposal[k] for k in arm.tunable})} (rate {rate:.0f}/s <= 1.05x incumbent {inc:.0f}/s)")

    def _reflect(self, ctx, mem, pid, prob):
        stats = mem.arm_stats(pid)
        if not stats:
            return
        ranking = sorted(stats.items(), key=lambda kv: -kv[1]["total_reward"] / kv[1]["pulls"])
        pref = ranking[0][0]
        if ctx.get("preferred_arm") != pref:
            mem.add_lesson(pid, "strategy", f"preferred strategy is now '{pref}' ({', '.join(f'{k}: {v['total_reward']/v['pulls']:.2f} over {v['pulls']} runs' for k, v in ranking)})")
            ctx.set("preferred_arm", pref)

    def run(self, pid, steps, force_arm=None):
        return [self.step(pid, force_arm) for _ in range(steps)]

    def replay(self, eid: int) -> dict:
        """Re-run a recorded experiment from its stored parameters and compare result digests."""
        rec = self.mem.get_experiment(eid)
        prob = self.problems[rec["problem_id"]]
        import json
        params = json.loads(rec["params"])
        res = prob.run(params, rec["seed"])
        d = sha256(canon(res.deterministic))
        return {"experiment": eid, "original_digest": rec["digest"], "replay_digest": d, "reproduced": d == rec["digest"],
                "code_hash_then": rec["code_hash"], "code_hash_now": prob.code_hash()}
