"""Toy problems used to test generality: Goldbach (valid), a lying solver, and a proof claim."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rsi.problem import Arm, ClaimSpec, ExperimentResult, Problem, Report


def tp(m):
    return m >= 2 and all(m % i for i in range(2, int(m ** .5) + 1))


def goldbach_ok(n):
    return any(tp(p) and tp(n - p) for p in range(2, n // 2 + 1))


class ToyGoldbach(Problem):
    id, title, domain, statement = "toy_goldbach", "Toy Goldbach", "number theory", "even n>=4 is a sum of two primes"

    def arms(self):
        return [Arm("slow"), Arm("fast", tunable={"chunk": (10, 1000)}, params={"chunk": 100})]

    def plan(self, ctx, arm, tuned, scale):
        lo = ctx.get("frontier", 2) + 2
        return {**tuned, "lo": lo, "hi": lo + 2 * max(5, int(100 * scale))}

    def run(self, params, seed):
        lo, hi = params["lo"], params["hi"]
        bad = [n for n in range(lo, hi + 1, 2) if not goldbach_ok(n)]
        claims = [ClaimSpec("counterexample", f"{n} not Goldbach", {"n": n}) for n in bad] or \
                 [ClaimSpec("evidence", f"holds on [{lo},{hi}]", {"lo": lo, "hi": hi})]
        return ExperimentResult("ok", {"progress": (hi - lo) // 2 + 1}, {"lo": lo, "hi": hi, "bad": bad}, claims)

    def verify(self, c):
        if c.kind == "evidence":
            lo, hi = c.evidence["lo"], c.evidence["hi"]
            return [Report("brute_a", "pass" if all(goldbach_ok(n) for n in range(lo, hi + 1, 2)) else "fail"),
                    Report("brute_b", "pass" if all(any(tp(p) and tp(n - p) for p in range(n - 1, 1, -1)) for n in range(lo, hi + 1, 2)) else "fail")]
        n = c.evidence["n"]
        a = any(tp(p) and tp(n - p) for p in range(2, n))
        return [Report("brute_a", "fail" if a else "pass"), Report("brute_b", "fail" if a else "pass")]

    def commit(self, ctx, params, result):
        ctx.set("frontier", params["hi"])


class LyingSolver(ToyGoldbach):
    id, title = "toy_liar", "Lying solver"

    def run(self, params, seed):
        return ExperimentResult("bogus", {"progress": 1}, {"x": 1}, [ClaimSpec("counterexample", "10 not Goldbach", {"n": 10})])


class ProofClaimer(ToyGoldbach):
    id, title = "toy_proof", "Overclaiming prover"

    def run(self, params, seed):
        return ExperimentResult("claims a proof", {"progress": 1}, {"x": 1}, [ClaimSpec("proof", "Goldbach is true", {"text": "trust me"})])


def get_problems():
    return [ToyGoldbach(), LyingSolver(), ProofClaimer()]
