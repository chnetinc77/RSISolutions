# Agents

| Agent | Role | Can it change the system? |
|---|---|---|
| Conductor | Chooses which strategy runs next (UCB bandit), sizes the workload, commits verified progress | Only through RSI-approved settings |
| Solver:<strategy> | Runs experiments for one research strategy and makes claims | No |
| RSI | Proposes parameter/workload changes, measures them, reflects on which strategy is best | Yes, but only after Auditor approval |
| Auditor | Independently verifies every claim (>= 2 verifiers), blocks proof-language overclaims, runs a canary check on every proposed self-modification | Veto power |

All agents are lightweight Python components (no LLM, no GPU). Each action is stored in the `events` table (hash-chained in the journal)
and shown in the live feed.

## Safe self-improvement loop
1. RSI proposes a change (e.g. a different block size K) and the Conductor trials it on real work.
2. If it is >5% faster, the Auditor runs the canary: the proposed configuration and the reference strategy must give identical output on a small fixed workload (`Problem.canary`).
3. Pass -> adopted, logged as a lesson. Fail -> blocked, logged as `failed_approach`, alert in the feed.

## Limits (honest)
The agents improve how they *search* (strategy choice, parameters, workload). They do not write new mathematics or rewrite their own source code,
and without an LLM they cannot invent new proof ideas. New strategies are added as new `Arm`s; the bandit and the Auditor decide whether they earn their place.

## Live dashboard
`python3 -m rsi run <problem> --forever --live` pushes a one-commit `live-data` branch about every 60 s; the Vercel site polls it (`web/config.js`).
Typical latency is 1-5 minutes (GitHub raw caching). The repository must be public for the browser to read the raw file.
