# AI prover (free-tier LLM + Lean)

Problem id `erdos_formal`. Open, formalised Erdős problems come from DeepMind's `formal-conjectures` repository (Lean 4 + Mathlib).

Pipeline per experiment: pick an open challenge -> strategy (`automation_sweep` no LLM / `llm_direct` with error-repair rounds / `llm_decompose` skeleton then fill)
-> the model returns ONLY a tactic block -> the theorem statement is spliced in from the repository file (a proof cannot change what is proved)
-> sanitiser (no sorry, axioms, macros, `#` commands, new declarations) -> Lean compiles it in an unprivileged account with an empty environment
-> accepted only if `#print axioms` lists nothing beyond propext, Classical.choice, Quot.sound.

## Auditor for a proof candidate
`static_audit`, `statement_fidelity` (saved file == repository file with the proof spliced in) and `lean_kernel_recheck` (fresh compile). Even if all pass the status is
`formally_checked_pending_human_review`, never `verified`. A human must confirm (1) the formal statement matches the real problem
(formalisation errors can make a problem trivially provable or false), and (2) the result is new (several open problems have been solved since being formalised).

## Free-tier use
Keys live only in `/root/rsi.env` (chmod 600). Hard daily request caps per provider (`GEMINI_DAILY_CAP`, default 200) and spacing between calls keep usage inside free quotas;
keep billing disabled on the Google project. Only public problem text and Lean code are sent; free tiers may use prompts for training.

## Setup
1. `sh scripts/setup_lean.sh` (as root; creates user `rsi`, installs Lean + Mathlib cache, builds the shared libraries FormalConjecturesForMathlib and FormalConjecturesUtil; 20-60 min, several GB).
2. `python3 -m rsi lean-index` (lists open challenges), `python3 -m rsi llm-test` (checks the key).
3. `systemctl enable --now rsi-prover`.

## Learning signal
Proofs are rare, so the bandit mostly sees zero reward; `llm_decompose` earns partial credit for a skeleton that compiles. Parameter tuning (temperature, repair rounds)
only changes search effort, never what is accepted: acceptance is decided solely by Lean.
