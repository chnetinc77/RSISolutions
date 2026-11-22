"""Verification policy.

A claim is 'verified' only if >= MIN_VERIFIERS independent verifiers pass and none fail.
Computational evidence never becomes a proof.  Proof claims are never auto-verified:
at best they become 'formally_checked_pending_human_review'.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from .problem import ClaimSpec, Report

MIN_VERIFIERS = 2


def check_formal_proof(path: str) -> Report:
    if not path or not os.path.isfile(path):
        return Report("lean_checker", "error", {"reason": "no proof file"})
    text = open(path).read()
    if re.search(r"\b(sorry|admit)\b|^\s*axiom\b", text, re.M):
        return Report("lean_checker", "fail", {"reason": "contains sorry/admit/axiom"})
    lean = shutil.which("lean")
    if not lean:
        return Report("lean_checker", "error", {"reason": "lean not installed"})
    try:
        r = subprocess.run([lean, path], capture_output=True, text=True, timeout=600)
    except Exception as e:  # noqa: BLE001
        return Report("lean_checker", "error", {"reason": str(e)})
    return Report("lean_checker", "pass" if r.returncode == 0 else "fail", {"stderr": r.stderr[-500:]})


def verify_claim(problem, spec: ClaimSpec) -> tuple[str, list[Report]]:
    if spec.kind == "proof":
        rep = check_formal_proof(spec.evidence.get("lean_file", ""))
        status = "formally_checked_pending_human_review" if rep.verdict == "pass" else "unverified_needs_external_review"
        return status, [rep]
    try:
        reports = problem.verify(spec)
    except Exception as e:  # noqa: BLE001
        return "inconclusive", [Report("verifier_crash", "error", {"error": repr(e)})]
    if any(r.verdict == "fail" for r in reports):
        return "rejected", reports
    passing = {r.verifier for r in reports if r.verdict == "pass" and r.independent}
    if len(passing) >= MIN_VERIFIERS and all(r.verdict == "pass" for r in reports):
        return "verified", reports
    return "inconclusive", reports
