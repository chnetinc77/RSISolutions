#!/usr/bin/env python3
"""Independent exact verifier for Erdos' minimum overlap upper-bound witnesses.

Shares NO code with problems/erdos_min_overlap.py.  Input (stdin JSON): n, D, a (integer heights,
h_i = a_i/D), claimed_S.  It checks 0 <= a_i <= D, sum(a) = D*n/2 (integral of h is exactly 1) and
recomputes S = max_j sum_i a_i (D - a_{i+j}) with a DIFFERENT algorithm (big-integer polynomial
multiplication), so the bound is C = 2S/(n D^2), exact.
"""
import json
import sys
from fractions import Fraction

LOWER_BOUND = Fraction(379005, 10**6)   # White (2022): mu >= 0.379005


def correlation_max(a, D):
    n = len(a)
    bits = 96
    A = sum(x << (bits * i) for i, x in enumerate(a))
    Brev = sum((D - a[n - 1 - u]) << (bits * u) for u in range(n))
    P = A * Brev
    mask = (1 << bits) - 1
    return max((P >> (bits * m)) & mask for m in range(2 * n - 1))


def main():
    req = json.load(sys.stdin)
    n, D, a = req["n"], req["D"], req["a"]
    out = {"ok": False}
    if len(a) != n or n % 2 or D % 2 or any((not isinstance(x, int)) or x < 0 or x > D for x in a):
        out["reason"] = "malformed witness or bounds violated"
    elif sum(a) != D * n // 2:
        out["reason"] = "integral of h is not exactly 1"
    else:
        S = correlation_max(a, D)
        C = Fraction(2 * S, n * D * D)
        out.update(S=S, C=float(C), matches_claim=(S == req["claimed_S"]))
        if S != req["claimed_S"]:
            out["reason"] = "claimed objective does not match recomputation"
        elif C < LOWER_BOUND:
            out["reason"] = "value below the proven lower bound 0.379005: formulation or evaluation bug"
        else:
            out["ok"] = True
    print(json.dumps(out))


if __name__ == "__main__":
    main()
