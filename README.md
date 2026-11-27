# RSISolutions

A lightweight (pure-stdlib Python 3.10+, no GPU, no APIs, no pretrained models) autonomous research
platform: it runs computational experiments on open problems, **independently verifies every claim**,
remembers everything permanently, and improves its own research strategy over time.

First target: **Hou-Zeng conjecture (PPL 013)** - every integer n > 4 is `p + F + C`
(p odd prime, F positive Fibonacci, C Catalan). Literature: arXiv:0901.3075 (Conj. 1.13), OEIS A154404.
Verified by D. S. McNeil to ~3x10^13, so this machine cannot reach new territory by brute force;
the plugin exists to exercise the machinery honestly. **Check the original prize terms before relying on any reward.**

## Quick start
```bash
python3 -m unittest discover -s tests -v        # 13 tests
python3 -m rsi run hou_zeng_ppl013 --steps 10 --target-seconds 10
python3 -m rsi publish --push                  # update the public static dashboard (GitHub -> Vercel)
python3 -m rsi status | claims | verify-journal | replay <exp_id> | export
python3 -m rsi run hou_zeng_ppl013 --forever    # daemon; see deploy/*.service
```

## What is where
| Requirement | Implementation |
|---|---|
| Autonomous engine | `rsi/engine.py` - choose strategy -> tune -> run -> verify -> commit -> learn |
| Domain-agnostic problems | `rsi/problem.py` plugin API; drop a file with `get_problems()` into `problems/` |
| Recursive self-improvement | UCB bandit over strategies, hill-climbing parameter tuner, adaptive workload scale, periodic baseline refresh, lessons (`engine.py`) |
| Permanent memory | `rsi/memory.py` SQLite + hash-chained journal + JSONL export |
| Independent verification | `rsi/verify.py` policy + per-problem verifiers (`verifiers/`, separate process, separate code) |
| Measured improvement | `rsi/perf.py`: median recent throughput per strategy, speedup vs baseline; dashboard chart |
| Dashboard | static site in `web/` (FL Superintelligence Labs style) deployed on Vercel; data from `rsi publish` (`docs/DASHBOARD.md`) |
| Reproducibility | each experiment stores params, seed, code hash, git commit, Python/platform, result digest; `rsi replay` |

See `docs/` for architecture, verification policy, adding problems, and Hou-Zeng details/limits.

## Multi-agent system (v0.2)
Conductor, one Solver per strategy, an RSI agent and an Auditor cooperate on every problem; each action appears in the live feed
on the Vercel dashboard. The RSI agent may only adopt a self-modification if it is faster **and** the Auditor's canary check shows
it gives exactly the same answers as the reference strategy. See `docs/AGENTS.md`.

## Active research targets
* `hou_zeng_ppl013`: Hou-Zeng conjecture, verified (as evidence only) to 4e8; finished.
* `erdos_min_overlap`: Erdős minimum overlap problem (upper bound). Agents search for step functions; every witness is checked exactly by two independent verifiers. Published records: 0.3809268534 (Haugland 2016), 0.380924 (AlphaEvolve 2025), 0.380876 (TTT-Discover 2026).
