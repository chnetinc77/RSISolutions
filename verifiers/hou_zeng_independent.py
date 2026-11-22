#!/usr/bin/env python3
"""Independent verifier for the Hou-Zeng conjecture (n = p + F + C).

Deliberately shares NO code with problems/hou_zeng.py: Catalan numbers come from the
recurrence C(k+1)=C(k)*2(2k+1)/(k+2), primality from deterministic Miller-Rabin
(no sieve), and representations are searched in a different order.
Reads a JSON request on stdin, writes a JSON report on stdout.
"""
import json
import random
import sys

_MR = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)  # deterministic for n < 3.3e24


def is_prime(n):
    if n < 2:
        return False
    for q in _MR:
        if n % q == 0:
            return n == q
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for a in _MR:
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def catalans(limit):
    out, c, k = [], 1, 0
    while c <= limit:
        if not out or out[-1] != c:
            out.append(c)
        c = c * 2 * (2 * k + 1) // (k + 2)
        k += 1
    return out


def fibs(limit):
    out, a, b = [], 1, 2
    while a <= limit:
        out.append(a)
        a, b = b, a + b
    return out


def represent(n):
    cs, fs = catalans(n), fibs(n)
    for c in reversed(cs):
        for f in reversed(fs):
            p = n - c - f
            if p < 3:
                continue
            if p & 1 and is_prime(p):
                return (p, f, c)
    return None


def check_witness(n, w):
    p, f, c = w
    return (p + f + c == n and p % 2 == 1 and is_prime(p) and f in fibs(n) and c in catalans(n))


def main():
    req = json.load(sys.stdin)
    if req["mode"] == "single":
        ns = [req["n"]]
        mode = "single"
    else:
        lo, hi = req["lo"], req["hi"]
        if hi - lo + 1 <= req.get("full_limit", 20000):
            ns, mode = list(range(lo, hi + 1)), "full"
        else:
            rnd = random.Random(req.get("seed", 0))
            s = set(range(lo, min(hi, lo + 499) + 1)) | set(range(max(lo, hi - 499), hi + 1))
            s |= {rnd.randint(lo, hi) for _ in range(req.get("sample", 5000))}
            s |= {x for x in req.get("hard", []) if lo <= x <= hi}
            ns, mode = sorted(s), "sampled"
    failures, bad_witness = [], []
    for n in ns:
        if n <= 4:
            continue
        w = represent(n)
        if w is None:
            failures.append(n)
        elif not check_witness(n, w):
            bad_witness.append(n)
    print(json.dumps({"mode": mode, "checked": len(ns), "failures": failures[:20], "n_failures": len(failures),
                      "bad_witness": bad_witness[:20]}))


if __name__ == "__main__":
    main()
