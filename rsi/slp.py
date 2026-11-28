"""Sequential-LP optimiser for Erdos' minimum overlap problem (numpy + scipy, optional).

Lives in a normal package module so worker processes can import it by name.
"""
from __future__ import annotations

import os


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


def _slp_job(args):
    """One independent restart (top-level so worker processes can run it). Deterministic in (seed, i)."""
    import numpy as np
    start, mode, i, seed, sigma, delta, slp_iters, n_fresh = args
    rng = np.random.default_rng([seed, i])
    if mode == "fresh" or start is None:
        n = n_fresh - (n_fresh % 2)                  # even number of pieces only (the exact verifier requires it)
        h0 = np.clip(0.5 + 0.4 * (rng.random(n) - 0.5), 0.0, 1.0)
    else:
        base = np.array(start, dtype=float)
        h0 = np.clip(base + sigma * rng.standard_normal(len(base)), 0.0, 1.0)
    h0 = np.array(project(list(h0), len(h0)))
    h, v = slp(h0, slp_iters, delta)
    return float(v), i, [float(x) for x in h]


def slp_search(start, mode, restarts, sigma, delta, slp_iters, n_fresh, seed, workers=None):
    """Independent SLP restarts, optionally spread over several CPU cores (env RSI_WORKERS).
    'fresh' = random starts at n_fresh pieces; 'hop' = noisy copies of the incumbent.
    The result does not depend on the number of workers."""
    workers = workers or int(os.environ.get("RSI_WORKERS", "1"))
    jobs = [(start, mode, i, seed, sigma, delta, slp_iters, n_fresh) for i in range(restarts)]
    if workers > 1 and restarts > 1:
        import multiprocessing as mp
        with mp.get_context("fork").Pool(min(workers, restarts)) as pool:
            res = pool.map(_slp_job, jobs)
    else:
        res = [_slp_job(j) for j in jobs]
    return min(res, key=lambda r: (r[0], r[1]))[2]
