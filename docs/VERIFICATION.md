# Verification policy

* A claim is `verified` only if **>= 2 independent verifiers pass and none fail**. Any failure => `rejected` (and a `failed_approach` lesson is stored). Otherwise `inconclusive`.
* Claim kinds: `evidence` (computational, never promoted to proof), `counterexample`, `witness`, `observation`, `proof`.
* **`proof` claims are never auto-verified.** If a Lean file is supplied (no `sorry`/`admit`/`axiom`) and `lean` is installed and exits 0, status becomes `formally_checked_pending_human_review`; otherwise `unverified_needs_external_review`. A human/expert review of the statement formalisation is always required.
* A verified `counterexample` raises an `ALERT` lesson and blocks frontier commit; verify against the original problem conditions before any reward claim.
* Verifiers must not reuse the claimant's code path.

## Hou-Zeng verifiers
Evidence over [lo, hi]:
1. `independent_miller_rabin_subprocess` - separate process, separate file, no sieve, Catalan by recurrence, deterministic Miller-Rabin, witnesses re-validated. **Full re-check** if span <= 20,000, otherwise **sampled** (both ends, 5,000 random n, and the "hardest" n recorded by the scanner). Sampled results are labelled `mode: sampled` in the stored report.
2. `sieve_vs_trial_division` - recomputes the primality sieve and compares it with trial division on 20,000 random numbers (guards against a corrupt oracle, the main false-negative risk).
3. `alternate_algorithm_full_rescan` (span <= 2e6, recorded but not counted as independent) - other scan algorithm over the whole range.

Counterexample n: Miller-Rabin subprocess exhaustive search + trial-division exhaustive search; both must find no representation.
Tests inject a corrupt sieve and a bogus counterexample and assert both are rejected.
