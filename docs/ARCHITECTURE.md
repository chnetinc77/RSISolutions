# Architecture

```
problems/*.py  (plugins)        verifiers/*.py (independent, subprocess)
      |                                  ^
      v                                  |
 rsi/problem.py  <-- rsi/engine.py --> rsi/verify.py  (policy)
                        |
                        v
                  rsi/memory.py (SQLite + hash-chained journal)
                        |
              rsi/perf.py, rsi/dashboard.py, rsi/cli.py
```

## One engine step
1. **Choose** a strategy ("arm"): periodic *analysis* arms; a periodic *baseline refresh* (so speedups are measured on current ranges); otherwise UCB1 over *search* arms using stored rewards.
2. **Tune**: with probability 0.35, perturb one tunable parameter (x0.5, x0.7, x1.4, x2). Adopted only if throughput beats the incumbent by >5%.
3. **Plan** exact params (`Problem.plan`) from persisted frontier and workload `scale`. `Problem.run(params, seed)` is a pure function of those.
4. **Run**, record experiment (params, seed, code hash, git commit, environment, result digest).
5. **Verify** every claim (see VERIFICATION.md). Frontier advances (`Problem.commit`) only if all claims verified.
6. **Learn**: reward = throughput / best throughput seen; update arm stats; adapt `scale` so a step takes ~`--target-seconds`; write lessons (adopted/rejected tunings, preferred strategy, failed approaches, rejected claims).

## Self-improvement and its honest limits
The agent improves *how it searches* (strategy choice, parameters, workload sizing), measured as speedup vs. the baseline strategy.
It does not rewrite its own source code or invent new mathematics. New strategies are added by a human (or a future code-generating arm) as new `Arm`s; the bandit then decides whether they earn their keep.
Reward comparisons across consecutive ranges are slightly confounded by drift in n; the periodic baseline refresh bounds this.

## Memory
Tables: problems, experiments, claims, verifications, lessons, arm_stats, metrics, state, journal. Every write is mirrored into a hash chain (`rsi verify-journal`). `rsi export` writes JSONL for committing to git. The chain detects edits to history; it is not protection against someone who can rewrite the whole database.
