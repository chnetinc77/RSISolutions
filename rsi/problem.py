"""Problem plugin interface.  New problems are added by dropping a Python file
exposing ``get_problems()`` into ``problems/`` - no engine changes needed."""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Arm:
    """A research strategy.  ``tunable`` maps param name -> (lo, hi) for the self-tuner.
    kind='search' arms compete in the bandit; kind='analysis' arms run periodically."""
    name: str
    params: dict = field(default_factory=dict)
    tunable: dict = field(default_factory=dict)
    kind: str = "search"
    period: int = 0
    description: str = ""


@dataclass
class ClaimSpec:
    kind: str          # evidence | counterexample | witness | proof | observation
    statement: str
    evidence: dict = field(default_factory=dict)


@dataclass
class Report:
    verifier: str
    verdict: str       # pass | fail | error
    details: dict = field(default_factory=dict)
    independent: bool = True


@dataclass
class ExperimentResult:
    summary: str
    metrics: dict                 # numeric; must contain "progress" for search arms
    deterministic: dict           # fully determined by (params, seed); hashed for replay
    claims: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)


class Ctx:
    """Per-problem handle to persistent state."""
    def __init__(self, mem, pid):
        self.mem, self.pid = mem, pid

    def get(self, key, default=None):
        return self.mem.get_state(self.pid, key, default)

    def set(self, key, value):
        self.mem.set_state(self.pid, key, value)


class Problem:
    id = ""
    title = ""
    domain = ""
    statement = ""
    source = ""

    def arms(self) -> list[Arm]:
        raise NotImplementedError

    def plan(self, ctx: Ctx, arm: Arm, tuned: dict, scale: float) -> dict:
        """Return fully specified, JSON-serialisable params for the next experiment."""
        raise NotImplementedError

    def run(self, params: dict, seed: int) -> ExperimentResult:
        """Must be a pure function of (params, seed)."""
        raise NotImplementedError

    def verify(self, claim: ClaimSpec) -> list[Report]:
        """Independent verification.  Must not trust the code path that made the claim."""
        return []

    def commit(self, ctx: Ctx, params: dict, result: ExperimentResult) -> None:
        """Called only after all claims verified; advance persistent frontier here."""

    def progress_of(self, result: ExperimentResult) -> float:
        return float(result.metrics.get("progress", 0.0))

    def status(self, ctx: Ctx) -> dict:
        return {}

    def code_hash(self) -> str:
        try:
            with open(inspect.getsourcefile(type(self))) as fh:
                src = fh.read()
        except Exception:
            src = type(self).__name__
        return hashlib.sha256(src.encode()).hexdigest()[:16]


def load_problems(*dirs: str) -> dict[str, Problem]:
    found: dict[str, Problem] = {}
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(f"rsi_problem_{fn[:-3]}", os.path.join(d, fn))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            getter = getattr(mod, "get_problems", None)
            if getter:
                for p in getter():
                    found[p.id] = p
    return found
