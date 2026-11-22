# Adding a research problem

Create `problems/my_problem.py`:
```python
from rsi.problem import Problem, Arm, ClaimSpec, ExperimentResult, Report

class MyProblem(Problem):
    id, title, domain = "my_problem", "Title", "physics"
    statement, source = "...", "..."
    def arms(self): return [Arm("baseline"), Arm("clever", params={"k": 8}, tunable={"k": (1, 64)})]  # first search arm = baseline
    def plan(self, ctx, arm, tuned, scale): return {**tuned, "lo": ctx.get("frontier", 0), "size": int(1000*scale)}
    def run(self, params, seed): ...   # pure function of (params, seed); return ExperimentResult(summary, metrics={"progress": units}, deterministic={...}, claims=[ClaimSpec(...)])
    def verify(self, claim): return [Report("method_a", "pass"), Report("method_b", "pass")]  # independent code paths
    def commit(self, ctx, params, result): ctx.set("frontier", ...)
def get_problems(): return [MyProblem()]
```
Then `python -m rsi problems` and `python -m rsi run my_problem --steps 5`. No engine change needed. `tests/toy.py` is a full worked example (Goldbach, a lying solver, an overclaiming prover).
Problems with no natural "progress" counter (e.g. simulations) can use periodic `kind="analysis"` arms or define `progress_of`.
