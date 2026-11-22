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
python3 -m rsi dashboard --port 8787            # http://127.0.0.1:8787
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
| Dashboard | `rsi/dashboard.py` (`/` page, `/api/state` JSON) |
| Reproducibility | each experiment stores params, seed, code hash, git commit, Python/platform, result digest; `rsi replay` |

See `docs/` for architecture, verification policy, adding problems, and Hou-Zeng details/limits.
