# Hou-Zeng conjecture (PPL 013)

Statement: every n > 4 equals p + F + C (odd prime, positive Fibonacci, Catalan; C_0 = C_1 = 1 so the Catalan set is {1,2,5,14,42,...}, Fibonacci set {1,2,3,5,8,...}).
Sanity anchor: n = 7 has exactly 3 representations (OEIS A154404; unit-tested).

Prize/terms: Sun (2009) lists prizes of $1000 (proof) and $200 (counterexample). **Original conditions not verified here - confirm before relying on them.**
Known: verified to ~3x10^13 (McNeil, per Sun). A counterexample below that would contradict the literature, so any alleged one is far more likely a bug - the verification stack is built around that prior.

Strategies:
* `per_n_early_exit` (baseline): for each n scan ascending F+C sums until n-(F+C) is an odd prime.
* `bitset_residual`: cover whole segments with the first K sums by OR-ing shifted prime bitmaps (big-int byte lanes), then finish the few residual n individually. K is self-tuned. About 4-6x faster here.
* `representation_stats` (analysis, heuristic): sampled r(n) per decade vs. a probabilistic expectation. Shows r(n) staying well above 0 in samples; this is **not** evidence about unsampled n and not a proof.

Limits: sieve memory cap MAX_N = 4e8 (~400 MB). Reaching the 10^13 literature frontier would need segmented prime windows; not implemented.
A proof would require a genuinely new idea (the sparse Fibonacci x Catalan set defeats standard sieve/circle-method approaches; compare Erdos-type covering obstructions for related questions). The system can only provide computation, not that idea.
