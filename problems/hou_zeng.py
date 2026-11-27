"""Hou-Zeng conjecture (PPL 013): every integer n > 4 is p + F + C with p an odd prime,
F a positive Fibonacci number and C a Catalan number (C_0 = C_1 = 1 included).

Status in the literature: verified by D. S. McNeil up to ~3e13 (Z.-W. Sun, arXiv:0901.3075).
Our compute budget can only re-verify ranges far below that; the point of this plugin is to
exercise the research/verification/self-improvement machinery honestly.  A computational
result here is EVIDENCE, never a proof.  Check the original prize conditions (Sun, 2009)
before relying on any reward.
"""
from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
from collections import Counter

from rsi.problem import Arm, ClaimSpec, ExperimentResult, Problem, Report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEP = os.path.join(ROOT, "verifiers", "hou_zeng_independent.py")
BASE_SPAN = 2_000_000
MAX_N = 400_000_000          # sieve memory cap (~400 MB)
HARD_THRESHOLD = 10


def fibonacci_upto(m):
    out, a, b = [], 1, 2
    while a <= m:
        out.append(a)
        a, b = b, a + b
    return out


def catalan_upto(m):
    out, k = [], 0
    while True:
        c = math.comb(2 * k, k) // (k + 1)
        if c > m:
            return out
        if not out or c != out[-1]:
            out.append(c)
        k += 1


def pair_sums(m):
    """Counter {s: multiplicity} of F + C = s <= m."""
    cnt = Counter()
    for f in fibonacci_upto(m):
        for c in catalan_upto(m):
            if f + c <= m:
                cnt[f + c] += 1
    return cnt


def odd_prime_sieve(n):
    """bytearray P with P[m] = 1 iff m is an odd prime, 0 <= m <= n."""
    P = bytearray(n + 1)
    if n >= 3:
        P[3::2] = b"\x01" * len(range(3, n + 1, 2))
    for i in range(3, math.isqrt(n) + 1, 2):
        if P[i]:
            P[i * i::2 * i] = bytes(len(range(i * i, n + 1, 2 * i)))
    return P


def _hard_top(hard):
    return [n for _, n in sorted(((-k, n) for k, n in hard))[:50]]


def scan_per_n(P, sums, lo, hi):
    uncovered, hard, maxk = [], [], 0
    for n in range(lo, hi + 1):
        lim = n - 3
        for k, s in enumerate(sums):
            if s > lim:
                uncovered.append(n)
                break
            if P[n - s]:
                if k >= HARD_THRESHOLD:
                    hard.append((-k, n))
                    if len(hard) > 4000:
                        hard = sorted(hard)[:200]
                maxk = max(maxk, k)
                break
        else:
            uncovered.append(n)
    return uncovered, [n for _, n in sorted(hard)[:50]], maxk


def scan_bitset(P, sums, lo, hi, K, seg=1 << 21):
    """Cover whole segments with the first K pair-sums using big-int lane ORs, then
    finish the few residual n individually."""
    uncovered, hard, maxk = [], [], 0
    for a in range(lo, hi + 1, seg):
        b = min(hi, a + seg - 1)
        L = b - a + 1
        cov = 0
        for s in sums[:K]:
            if b - s < 0:
                break
            st = a - s
            chunk = P[st:b - s + 1] if st >= 0 else bytes(-st) + P[0:b - s + 1]
            cov |= int.from_bytes(chunk, "little")
        cb = cov.to_bytes(L, "little")
        idx = cb.find(0)
        while idx != -1:
            n = a + idx
            found = False
            for k in range(K, len(sums)):
                s = sums[k]
                if s > n - 3:
                    break
                if P[n - s]:
                    found = True
                    if k >= HARD_THRESHOLD:
                        hard.append((-k, n))
                    maxk = max(maxk, k)
                    break
            if not found:
                uncovered.append(n)
            idx = cb.find(0, idx + 1)
    return uncovered, [n for _, n in sorted(hard)[:50]], maxk


def trial_is_prime(m):
    if m < 2:
        return False
    if m % 2 == 0:
        return m == 2
    if m % 3 == 0:
        return m == 3
    i = 5
    while i * i <= m:
        if m % i == 0 or m % (i + 2) == 0:
            return False
        i += 6
    return True


class HouZeng(Problem):
    id = "hou_zeng_ppl013"
    title = "Hou-Zeng conjecture (PPL 013)"
    domain = "number theory"
    statement = "Every integer n > 4 can be written as n = p + F + C, p an odd prime, F a positive Fibonacci number, C a Catalan number."
    source = "Z.-W. Sun, arXiv:0901.3075, Conjecture 1.13; OEIS A154404. Prize: $1000 proof / $200 counterexample (verify original terms)."

    prize = {"reward": "$1,000 for a proof / $200 for a verified counterexample (per Sun's list)",
             "terms_verified": False,
             "status": "Open. Checked to ~3e13 in the literature; a counterexample is extremely unlikely. Original prize terms not yet verified."}

    def canary(self, arm, tuned):
        if arm.kind != "search":
            return None
        return {**tuned, "lo": 5, "hi": 40000, "arm": arm.name}

    def arms(self):
        return [
            Arm("per_n_early_exit", description="per-n scan over ascending pair-sums, early exit"),
            Arm("bitset_residual", params={"K": 24}, tunable={"K": (4, 96)},
                description="cover segments with first K pair-sums via big-int lane OR, finish residual n individually"),
            Arm("representation_stats", params={"top_decade": 6, "samples": 1500}, kind="analysis", period=8,
                description="heuristic analysis: sampled r(n) vs probabilistic expectation per decade"),
        ]

    def plan(self, ctx, arm, tuned, scale):
        if arm.kind == "analysis":
            return dict(tuned)
        frontier = ctx.get("frontier", 4)
        lo = frontier + 1
        span = max(1000, int(BASE_SPAN * scale))
        hi = min(lo + span - 1, MAX_N)
        if lo > MAX_N:
            raise RuntimeError("frontier reached MAX_N memory cap")
        return {**tuned, "lo": lo, "hi": hi}

    def commit(self, ctx, params, result):
        if params["arm"] != "representation_stats":
            ctx.set("frontier", params["hi"])

    def status(self, ctx):
        return {"verified_frontier": ctx.get("frontier", 4), "literature_record": "~3e13 (McNeil, per Sun 2009)",
                "alert": ctx.get("alert")}

    def run(self, params, seed):
        if params["arm"] == "representation_stats":
            return self._analysis(params, seed)
        lo, hi = params["lo"], params["hi"]
        sums = sorted(pair_sums(max(hi - 3, 0)))
        P = odd_prime_sieve(hi)
        if params["arm"] == "per_n_early_exit":
            unc, hard, maxk = scan_per_n(P, sums, lo, hi)
        else:
            unc, hard, maxk = scan_bitset(P, sums, lo, hi, int(params["K"]))
        claims = []
        if unc:
            for n in unc[:5]:
                claims.append(ClaimSpec("counterexample", f"n={n} is not p+F+C", {"n": n}))
        else:
            claims.append(ClaimSpec("evidence", f"No counterexample for 5<=n in [{lo},{hi}] (computational evidence only, not a proof)",
                                    {"lo": lo, "hi": hi, "hard": hard, "method": params["arm"], "seed": seed}))
        return ExperimentResult(
            summary=f"scanned [{lo},{hi}] with {params['arm']}: {len(unc)} uncovered, max first-witness index {maxk}",
            metrics={"progress": hi - lo + 1, "max_first_witness_index": maxk, "n_pair_sums": len(sums)},
            deterministic={"lo": lo, "hi": hi, "uncovered": unc}, claims=claims)

    def _analysis(self, params, seed):
        rnd = random.Random(seed)
        top = 10 ** int(params["top_decade"])
        P = odd_prime_sieve(top * 10)
        pairs = sorted(pair_sums(top * 10).items())
        stats = {}
        for k in range(2, int(params["top_decade"]) + 1):
            rs, ex = [], []
            for _ in range(int(params["samples"])):
                n = rnd.randrange(10 ** k, 10 ** (k + 1))
                r = sum(m for s, m in pairs if s <= n - 3 and P[n - s])
                e = sum(2.0 / math.log(n - s) for s, m in pairs if s <= n - 3 and (n - s) % 2 == 1 for _ in range(m))
                rs.append(r)
                ex.append(e)
            stats[str(k)] = {"min_r": min(rs), "mean_r": round(sum(rs) / len(rs), 3),
                             "mean_expected": round(sum(ex) / len(ex), 3),
                             "min_ratio": round(min(r / e for r, e in zip(rs, ex)), 4)}
        mins = [stats[k]["min_r"] for k in sorted(stats)]
        return ExperimentResult(
            summary="sampled r(n) per decade (min_r): " + ", ".join(map(str, mins)) + " [heuristic only; says nothing about n outside samples]",
            metrics={"progress": 0, **{f"min_r_decade_{k}": v["min_r"] for k, v in stats.items()}},
            deterministic={"stats": stats, "params": {k: params[k] for k in ("top_decade", "samples")}}, claims=[])

    # ---- independent verification --------------------------------------
    def verify(self, claim):
        return self._verify_range(claim) if claim.kind == "evidence" else self._verify_cex(claim) if claim.kind == "counterexample" else []

    def _run_indep(self, req, timeout=900):
        r = subprocess.run([sys.executable, INDEP], input=json.dumps(req), capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-300:])
        return json.loads(r.stdout)

    def _verify_range(self, claim):
        ev = claim.evidence
        lo, hi = ev["lo"], ev["hi"]
        reports = []
        out = self._run_indep({"mode": "range", "lo": lo, "hi": hi, "hard": ev.get("hard", []), "seed": ev.get("seed", 0)})
        ok = out["n_failures"] == 0 and not out["bad_witness"]
        reports.append(Report("independent_miller_rabin_subprocess", "pass" if ok else "fail",
                              {k: out[k] for k in ("mode", "checked", "n_failures")}))
        # sieve-oracle cross-check: recompute the primality oracle and compare against trial division
        P = odd_prime_sieve(hi)
        rnd = random.Random(ev.get("seed", 0) + 1)
        bad = [m for m in (rnd.randint(3, hi) for _ in range(20000)) if bool(P[m]) != (m % 2 == 1 and trial_is_prime(m))]
        bad += [m for m in range(3, min(hi, 20000) + 1) if bool(P[m]) != (m % 2 == 1 and trial_is_prime(m))][:5]
        reports.append(Report("sieve_vs_trial_division", "fail" if bad else "pass", {"mismatches": bad[:10], "sampled": 20000}))
        if hi - lo + 1 <= 2_000_000:
            sums = sorted(pair_sums(hi - 3))
            alt = scan_per_n(P, sums, lo, hi)[0] if ev.get("method") != "per_n_early_exit" else scan_bitset(P, sums, lo, hi, 24)[0]
            reports.append(Report("alternate_algorithm_full_rescan", "pass" if not alt else "fail", {"uncovered": alt[:10]}, independent=False))
        return reports

    def _verify_cex(self, claim):
        n = claim.evidence["n"]
        reports = []
        out = self._run_indep({"mode": "single", "n": n})
        reports.append(Report("independent_miller_rabin_subprocess", "fail" if out["n_failures"] == 0 else "pass",
                              {"n": n, "representation_found": out["n_failures"] == 0}))
        if n > 10 ** 12:
            reports.append(Report("trial_division_bruteforce", "error", {"reason": "n too large for trial division"}))
            return reports
        found = None
        for f in fibonacci_upto(n):
            for c in catalan_upto(n):
                p = n - f - c
                if p >= 3 and p % 2 == 1 and trial_is_prime(p):
                    found = (p, f, c)
                    break
            if found:
                break
        reports.append(Report("trial_division_bruteforce", "fail" if found else "pass", {"n": n, "witness": found}))
        return reports


def get_problems():
    return [HouZeng()]
