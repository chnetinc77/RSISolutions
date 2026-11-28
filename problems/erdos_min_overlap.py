"""Erdos' minimum overlap problem (upper bound on mu = lim M(n)/n).

Partition {1..2n} into A, B with |A|=|B|=n; M(n) = min over partitions of max_k #{(a,b): a-b=k}.
Upper bounds come from step functions h:[0,2]->[0,1] with integral 1 via
    C(h) = max_k  integral h(x) (1 - h(x+k)) dx      (Swinnerton-Dyer / Haugland), so mu <= C(h).
For n equal pieces the max is attained at integer shifts, giving the exact value C = 2S/(n D^2) for
integer heights a_i = h_i D, S = max_j sum_i a_i (D - a_{i+j}).

State of the art (literature, not verified here): lower bound 0.379005 (White 2022); upper bounds
0.3809268534 (Haugland 2016), 0.380924 (AlphaEvolve 2025), 0.380876 (TTT-Discover 2026).
Those records came from far larger compute than this server has: a new record is unlikely.
No cash prize is known for this problem (not verified).  Any witness found is exactly checkable.
"""
from __future__ import annotations

import math
import os
import random
import subprocess
import sys
import json
from fractions import Fraction

from rsi.problem import Arm, ClaimSpec, ExperimentResult, Problem, Report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEP = os.path.join(ROOT, "verifiers", "erdos_min_overlap_independent.py")
D = 10 ** 9
START_N, MAX_N = 24, 420
PARTITION_M = 20000
LOWER_BOUND = 0.379005
REFS = {"trivial (h = 1/2)": 0.5, "Haugland 2016": 0.3809268534, "AlphaEvolve 2025": 0.380924, "TTT-Discover 2026": 0.380876}


# ---------- exact evaluation (integers) ----------
def exact_S(a):
    n, best = len(a), 0
    for j in range(-(n - 1), n):
        s = 0
        for i in range(max(0, -j), min(n, n - j)):
            s += a[i] * (D - a[i + j])
        best = max(best, s)
    return best


def C_of(S, n):
    return Fraction(2 * S, n * D * D)


# ---------- float optimisation helpers ----------
def corr(h):
    n = len(h)
    out = []
    for j in range(-(n - 1), n):
        s = 0.0
        for i in range(max(0, -j), min(n, n - j)):
            s += h[i] * (1.0 - h[i + j])
        out.append(s)
    return out


def project(v, n):
    """Euclidean projection onto {0 <= h <= 1, sum h = n/2}."""
    lo, hi = min(v) - 1.0, max(v)
    for _ in range(60):
        lam = (lo + hi) / 2
        if sum(min(1.0, max(0.0, x - lam)) for x in v) > n / 2:
            lo = lam
        else:
            hi = lam
    lam = (lo + hi) / 2
    return [min(1.0, max(0.0, x - lam)) for x in v]


def to_ints(h):
    n = len(h)
    a = [min(D, max(0, int(round(x * D)))) for x in h]
    diff = D * n // 2 - sum(a)
    while diff:
        for i in range(n):
            if diff > 0 and a[i] < D:
                a[i] += 1
                diff -= 1
            elif diff < 0 and a[i] > 0:
                a[i] -= 1
                diff += 1
            if not diff:
                break
    return a


def softmax_descent(h, iters, beta0, beta1, lr0):
    """Projected gradient descent on a log-sum-exp smoothing of the max, sharpening beta over time."""
    n = len(h)
    best, bestv = h[:], float("inf")
    for t in range(iters):
        frac = t / max(1, iters - 1)
        beta = beta0 * (beta1 / beta0) ** frac
        c = corr(h)
        m = max(c)
        if 2.0 / n * m < bestv:
            bestv, best = 2.0 / n * m, h[:]
        w = [math.exp(beta * 2.0 / n * (x - m)) for x in c]
        Z = sum(w)
        g = [0.0] * n
        for jj, wj in enumerate(w):
            wj /= Z
            if wj < 1e-9:
                continue
            j = jj - (n - 1)
            for i in range(max(0, -j), min(n, n - j)):
                g[i] += wj * (1.0 - h[i + j])
                g[i + j] -= wj * h[i]
        gm = max(abs(x) for x in g) + 1e-12
        lr = lr0 * (1.0 - 0.9 * frac)
        h = project([h[i] - lr * g[i] / gm for i in range(n)], n)
    if 2.0 / n * max(corr(h)) < bestv:
        best = h
    return best


def _apply(c, h, p, d):
    n = len(h)
    for j in range(-(n - 1), n):
        k = j + n - 1
        if j == 0:
            c[k] += d * (1 - 2 * h[p]) - d * d
        else:
            if 0 <= p + j < n:
                c[k] += d * (1 - h[p + j])
            if 0 <= p - j < n:
                c[k] -= h[p - j] * d


def anneal(h, iters, step, temp, rng):
    """Simulated annealing with mass-preserving pair moves and incremental correlation updates."""
    n = len(h)
    h = h[:]
    c = corr(h)
    cur = max(c)
    best, bh = cur, h[:]
    for t in range(iters):
        T = temp * (1.0 - t / iters)
        p, q = rng.randrange(n), rng.randrange(n)
        if p == q:
            continue
        d = step * (rng.random() * 2 - 1)
        d = max(min(d, h[q], 1 - h[p]), -h[p], h[q] - 1)
        if d == 0:
            continue
        c2 = c[:]
        _apply(c2, h, p, d)
        h[p] += d
        _apply(c2, h, q, -d)
        h[q] -= d
        new = max(c2)
        delta = (new - cur) * 2.0 / n
        if delta <= 0 or rng.random() < math.exp(-delta / max(T, 1e-12)):
            c, cur = c2, new
            if cur < best:
                best, bh = cur, h[:]
        else:
            h[p] -= d
            h[q] += d
    return bh


def slp_available():
    try:
        import numpy  # noqa: F401
        import scipy.optimize  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _fg(h):
    """Objective values f_s and their gradient rows for all shifts s (numpy)."""
    import numpy as np
    n = len(h)
    G = np.zeros((2 * n - 1, n))
    f = np.zeros(2 * n - 1)
    one = 1.0 - h
    for s in range(-(n - 1), n):
        i = np.arange(max(0, -s), min(n, n - s))
        k = i + s
        f[s + n - 1] = (2.0 / n) * np.sum(h[i] * one[k])
        G[s + n - 1, i] += (2.0 / n) * one[k]
        G[s + n - 1, k] -= (2.0 / n) * h[i]
    return f, G


def slp(h, iters=150, delta=0.05):
    """Sequential linear programming with a trust region (Haugland-style): minimise t subject to the
    linearised constraints f_s(h) + grad f_s . dh <= t, 0 <= h <= 1, sum h = n/2, |dh| <= delta."""
    import numpy as np
    from scipy.optimize import linprog
    n = len(h)
    best, bf = h.copy(), _fg(h)[0].max()
    for _ in range(iters):
        f, G = _fg(h)
        c = np.zeros(n + 1)
        c[-1] = 1.0
        lo, hi = np.maximum(-delta, -h), np.minimum(delta, 1.0 - h)
        Aeq = np.zeros((1, n + 1))
        Aeq[0, :n] = 1.0
        r = linprog(c, A_ub=np.hstack([G, -np.ones((2 * n - 1, 1))]), b_ub=-f, A_eq=Aeq, b_eq=[0.0],
                    bounds=[(lo[i], hi[i]) for i in range(n)] + [(None, None)], method="highs")
        if r.status != 0:
            delta *= 0.5
            continue
        hn = np.clip(h + r.x[:n], 0.0, 1.0)
        hn = np.clip(hn + (n / 2 - hn.sum()) / n, 0.0, 1.0)
        fn = _fg(hn)[0].max()
        if fn < bf - 1e-12:
            h, bf, best = hn, fn, hn.copy()
            delta = min(delta * 1.3, 0.2)
        else:
            delta *= 0.5
        if delta < 1e-9:
            break
    return best, bf


def slp_search(start, mode, restarts, sigma, delta, slp_iters, n_fresh, seed):
    """Restarts of SLP: 'fresh' = random starts at n_fresh pieces; 'hop' = noisy copies of the incumbent."""
    import numpy as np
    rng = np.random.default_rng(seed)
    best_h, best_v = None, float("inf")
    for _ in range(restarts):
        if mode == "fresh" or start is None:
            n = n_fresh
            h0 = np.clip(0.5 + 0.4 * (rng.random(n) - 0.5), 0.0, 1.0)
        else:
            base = np.array(start, dtype=float)
            h0 = np.clip(base + sigma * rng.standard_normal(len(base)), 0.0, 1.0)
        h0 = np.array(project(list(h0), len(h0)))
        h, v = slp(h0, slp_iters, delta)
        if v < best_v:
            best_h, best_v = h, v
    return [float(x) for x in best_h]


def partition_overlap(a, m=None):
    """Sanity check on the ORIGINAL problem: build a random partition of {1..2m} with local density h,
    |A| = |B| = m, and return max_k M_k / m (should be about C, up to O(1/sqrt(m)) noise)."""
    m = m or PARTITION_M
    n = len(a)
    rng = random.Random(12345)
    bits = [1 if rng.random() < a[min(n - 1, x * n // (2 * m))] / D else 0 for x in range(2 * m)]
    cnt = sum(bits)
    while cnt != m:
        x = rng.randrange(2 * m)
        if cnt > m and bits[x]:
            bits[x] = 0
            cnt -= 1
        elif cnt < m and not bits[x]:
            bits[x] = 1
            cnt += 1
    A = int("".join("1" if b else "0" for b in reversed(bits)), 2)
    B = int("".join("0" if b else "1" for b in reversed(bits)), 2)
    best = 0
    for k in range(0, 2 * m):
        best = max(best, bin(A & (B << k)).count("1"), bin((A << k) & B).count("1"))
    return best / m


class MinOverlap(Problem):
    id = "erdos_min_overlap"
    title = "Erdős minimum overlap problem (upper bound)"
    domain = "combinatorial number theory"
    statement = ("Find a step function h on [0,2] with values in [0,1] and integral 1 minimising max_k ∫h(x)(1−h(x+k))dx. "
                 "Its value is an upper bound on the Erdős minimum overlap constant (known to lie between 0.379005 and 0.380876).")
    source = "Erdős 1955; erdosproblems.com Problem 36 (as cited in arXiv:2511.02864); Haugland 2016 (arXiv:1609.08000); White 2022 (arXiv:2201.05704)."
    prize = {"reward": "No cash prize known for this problem (not verified)", "terms_verified": False,
             "status": "Records (AlphaEvolve 2025, TTT-Discover 2026) used far more compute than this server; a new record is unlikely. "
                       "Value here: every result is an exactly checkable witness, so progress and self-improvement are objectively measurable."}

    def arms(self):
        return [
            Arm("anneal_pairs", params={"step": 0.05, "temp": 0.002, "base_iters": 20000}, tunable={"step": (0.002, 0.3), "temp": (1e-5, 0.02)},
                description="simulated annealing with mass-preserving pair moves"),
            Arm("softmax_gradient", params={"beta0": 150.0, "beta1": 3000.0, "lr": 0.02, "base_iters": 1200}, tunable={"beta1": (500.0, 20000.0), "lr": (0.002, 0.2)},
                description="projected gradient descent on a smoothed max"),
            Arm("slp_fresh", params={"restarts": 6, "slp_iters": 150, "delta": 0.05, "n_fresh": 52, "mode": "fresh"},
                tunable={"restarts": (2, 40), "n_fresh": (40, 64), "delta": (0.01, 0.1)},
                description="sequential linear programming from random starts (Haugland-style)"),
            Arm("slp_hop", params={"restarts": 4, "slp_iters": 150, "delta": 0.03, "sigma": 0.03, "mode": "hop"},
                tunable={"restarts": (1, 30), "sigma": (0.005, 0.2), "delta": (0.01, 0.1)},
                description="sequential LP from noisy copies of the best step function"),
            Arm("slp_refine", params={"restarts": 2, "slp_iters": 120, "delta": 0.02, "sigma": 0.01, "mode": "hop", "upsample": True},
                tunable={"restarts": (1, 10), "sigma": (0.002, 0.1)},
                description="double the number of pieces of the best function, then sequential LP"),
            Arm("refine_resolution", params={"beta0": 150.0, "beta1": 3000.0, "lr": 0.02, "base_iters": 600, "upsample": True},
                tunable={"beta1": (500.0, 20000.0), "lr": (0.002, 0.2)}, description="double the number of steps, then descend"),
        ]

    def canary(self, arm, tuned):
        return {**arm.params, **tuned, "start": None, "base_iters": 20, "iters": 20, "restarts": 1, "arm": arm.name, "canary": True}

    def canary_ok(self, proposed, reference):
        for r in (proposed, reference):
            d = r.deterministic
            a = d["a"]
            if len(a) % 2 or sum(a) != D * len(a) // 2 or min(a) < 0 or max(a) > D or exact_S(a) != d["S"] or float(C_of(d["S"], len(a))) < LOWER_BOUND:
                return False
        return True

    def plan(self, ctx, arm, tuned, scale):
        best = ctx.get("best")
        iters = max(30, int(tuned.get("base_iters", arm.params.get("base_iters", 1000)) * scale))
        p = {**tuned, "iters": iters, "start": best["a"] if best else None}
        if arm.name.startswith("slp"):
            p["restarts"] = max(1, int(round(tuned.get("restarts", 4) * scale)))
        return p

    def run(self, params, seed):
        rng = random.Random(seed)
        arm = params["arm"]
        if params.get("start"):
            a0 = params["start"]
            h = [x / D for x in a0]
            before = C_of(exact_S(a0), len(a0))
        else:
            n = START_N if not params.get("canary") else 12
            h = project([0.5 + 0.8 * (rng.random() - 0.5) for _ in range(n)], n)
            before = Fraction(1, 2)
        if params.get("upsample") and len(h) * 2 <= MAX_N:
            h = [x for x in h for _ in (0, 1)]
        iters = int(params["iters"])
        if arm.startswith("slp"):
            if not slp_available():
                return ExperimentResult("sequential LP needs numpy+scipy (apt install python3-numpy python3-scipy)", {"progress": 0.0},
                                        {"n": len(h), "a": to_ints(h), "S": exact_S(to_ints(h)), "improved": False}, extra={"sleep": 600})
            canary = bool(params.get("canary"))
            start = None if (not params.get("start") and not canary) else h
            h = slp_search(start, params["mode"], int(params["restarts"]) if not canary else 1, float(params.get("sigma", 0.0)),
                           float(params["delta"]), int(params["slp_iters"]) if not canary else 15,
                           int(params.get("n_fresh", 52)) if not canary else 12, seed)
        elif arm == "anneal_pairs":
            h = anneal(h, iters, params["step"], params["temp"], rng)
        else:
            h = softmax_descent(project(h, len(h)), iters, params["beta0"], params["beta1"], params["lr"])
        a = to_ints(h)
        S = exact_S(a)
        C = C_of(S, len(a))
        improved = C < before
        claims = []
        if improved:
            claims.append(ClaimSpec(
                "witness",
                f"Step function with {len(a)} equal pieces gives the upper bound mu <= {float(C):.10f} (exact value 2S/(nD^2); record to beat: {REFS['TTT-Discover 2026']})",
                {"n": len(a), "D": D, "a": a, "claimed_S": S, "C": float(C), "beats_haugland": float(C) < REFS["Haugland 2016"],
                 "beats_sota": float(C) < REFS["TTT-Discover 2026"]}))
        return ExperimentResult(
            summary=f"{arm}: n={len(a)} steps, C={float(C):.8f} (incumbent {float(before):.8f}){' improved' if improved else ''}",
            metrics={"progress": float(before - C) if improved else 0.0, "C": float(C), "n": len(a)},
            deterministic={"n": len(a), "a": a, "S": S, "improved": improved}, claims=claims)

    def commit(self, ctx, params, result):
        d = result.deterministic
        best = ctx.get("best")
        if d["improved"] and (best is None or C_of(d["S"], d["n"]) < C_of(best["S"], best["n"])):
            ctx.set("best", {"n": d["n"], "a": d["a"], "S": d["S"], "C": float(C_of(d["S"], d["n"]))})
            ctx.mem.record_metric(self.id, "best_C", float(C_of(d["S"], d["n"])))

    def status(self, ctx):
        b = ctx.get("best")
        if not b:
            return {"best_upper_bound": None, "references": REFS, "known_lower_bound": LOWER_BOUND}
        C = b["C"]
        return {"best_upper_bound": round(C, 9), "step_function_pieces": b["n"],
                "gap_to_haugland_2016": round(C - REFS["Haugland 2016"], 9), "gap_to_record_2026": round(C - REFS["TTT-Discover 2026"], 9),
                "known_lower_bound": LOWER_BOUND, "references": REFS, "alert": ctx.get("alert")}

    def verify(self, claim):
        if claim.kind != "witness":
            return []
        ev = claim.evidence
        r = subprocess.run([sys.executable, INDEP], input=json.dumps({k: ev[k] for k in ("n", "D", "a", "claimed_S")}), capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-300:])
        out = json.loads(r.stdout)
        reports = [Report("independent_bigint_exact_subprocess", "pass" if out["ok"] else "fail", {k: out.get(k) for k in ("ok", "C", "reason")})]
        ratio = partition_overlap(ev["a"])
        tol = 4.0 / math.sqrt(PARTITION_M)
        reports.append(Report("direct_partition_check", "pass" if ratio <= ev["C"] + tol else "fail",
                              {"M_over_m": round(ratio, 5), "claimed_C": round(ev["C"], 6), "m": PARTITION_M, "tolerance": round(tol, 4)}))
        return reports


def get_problems():
    return [MinOverlap()]
