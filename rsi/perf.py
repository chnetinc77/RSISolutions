"""Measurable research-performance tracking."""
from __future__ import annotations

import statistics


def performance(mem, pid, baseline_arm: str | None = None, window=3) -> dict:
    rows = mem.rows("SELECT name,value FROM metrics WHERE problem_id=? AND name LIKE 'rate:%' ORDER BY id", (pid,))
    per_arm: dict[str, list[float]] = {}
    for r in rows:
        per_arm.setdefault(r["name"][5:], []).append(r["value"])
    recent = {a: statistics.median(v[-window:]) for a, v in per_arm.items()}
    out = {"recent_rate": recent, "runs": {a: len(v) for a, v in per_arm.items()}}
    if baseline_arm and recent.get(baseline_arm, 0) > 0:
        best = max(recent, key=recent.get)
        out["best_arm"] = best
        out["speedup_vs_baseline"] = recent[best] / recent[baseline_arm]
    return out
