import json, os, stat, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from rsi import lean
from rsi.engine import Engine
from rsi.llm import FailoverLLM, GeminiClient, LLMBudget, LLMError, MockLLM, Usage
from rsi.memory import Memory
from rsi.problem import Ctx, load_problems

SAMPLE = """import FormalConjectures.Util.ProblemImports

namespace Erdos1
open Finset

/-- helper -/
def Foo (n : Nat) : Prop := True

/-- Is it true that something? -/
@[category research open, AMS 5 11]
theorem erdos_1 : ∃ C : Nat, ∀ N : Nat, C ≤ N + C := by sorry

@[category research solved, AMS 5]
theorem erdos_1.variants.lb : 1 = 1 := by
  sorry

@[category research open, AMS 5]
theorem erdos_1.yesno : answer(sorry) ↔ (2 = 2) := by
  sorry

end Erdos1
"""
FAKE_LEAN = """#!/bin/sh
f="$1"
if grep -q "BAD_PROOF" "$f"; then echo "$f:9:2: error: unsolved goals"; fi
n=$(grep -o "#print axioms [A-Za-z0-9_.']*" "$f" | head -1 | sed 's/#print axioms //')
echo "'$n' depends on axioms: [propext, Classical.choice, Quot.sound]"
exit 0
"""


def make_env():
    d = tempfile.mkdtemp()
    repo = os.path.join(d, "repo"); os.makedirs(os.path.join(repo, "FormalConjectures", "ErdosProblems"))
    open(os.path.join(repo, "FormalConjectures", "ErdosProblems", "1.lean"), "w").write(SAMPLE)
    fake = os.path.join(d, "fakelean.sh"); open(fake, "w").write(FAKE_LEAN); os.chmod(fake, 0o755)
    os.environ.update(RSI_LEAN_PROJECT=repo, RSI_LEAN_BIN=fake, RSI_LEAN_USER="nobody_such_user")
    index = os.path.join(d, "index.json"); lean.index_repo(repo, index)
    return d, repo, index


class LeanTextTests(unittest.TestCase):
    def test_indexing_finds_only_open_with_sorry_and_namespaces(self):
        d, repo, index = make_env()
        ids = {c["id"]: c for c in json.load(open(index))["challenges"]}
        self.assertEqual(set(ids), {"1:erdos_1", "1:erdos_1.yesno"})
        self.assertEqual(ids["1:erdos_1"]["full_name"], "Erdos1.erdos_1")
        self.assertTrue(ids["1:erdos_1.yesno"]["has_answer"]); self.assertFalse(ids["1:erdos_1"]["has_answer"])

    def test_splice_keeps_statement_and_sanitizer_blocks_cheats(self):
        ch = lean.parse_file(SAMPLE)[0]
        out = lean.splice(SAMPLE, ch, "intro N\n  simp")
        self.assertIn("theorem erdos_1 : ∃ C : Nat, ∀ N : Nat, C ≤ N + C := by\n  intro N", out)
        for bad in ["sorry", "exact foo -- ok\n#eval 1", "macro \"x\" : tactic => `(tactic| rfl)", "native_decide", "theorem x : True := trivial",
                    "/- unclosed", "set_option maxHeartbeats 0 in\nsimp", "@[simp] x"]:
            with self.assertRaises(ValueError, msg=bad): lean.sanitize_tactics(bad)
        self.assertEqual(lean.sanitize_tactics("have h : 1 = 1 := by rfl\nexact ⟨0, fun N => by omega⟩"), "have h : 1 = 1 := by rfl\nexact ⟨0, fun N => by omega⟩")
        self.assertEqual(lean.sanitize_tactics("have h : True := by sorry\ntrivial", allow_sorry=True)[:4], "have")

    def test_answer_substitution_and_extraction(self):
        ch = [c for c in lean.parse_file(SAMPLE) if c["has_answer"]][0]
        self.assertIn("answer(True)", lean.splice(SAMPLE, ch, "simp", "True"))
        reply = "ANSWER: False\n```lean\ntheorem erdos_1.yesno : answer(sorry) ↔ (2 = 2) := by\n  intro h\n  simp\n```"
        self.assertEqual(lean.extract_answer(reply), "False"); self.assertEqual(lean.extract_tactics(reply), "intro h\nsimp")

    def test_check_requires_standard_axioms_only(self):
        d, repo, index = make_env()
        self.assertTrue(lean.check(SAMPLE, "Erdos1.erdos_1", "t1")["ok"])
        self.assertFalse(lean.check(SAMPLE.replace("Foo", "BAD_PROOF"), "Erdos1.erdos_1", "t2")["ok"])   # compile error
        os.environ["RSI_LEAN_BIN"] = os.path.join(d, "evil.sh")
        open(os.environ["RSI_LEAN_BIN"], "w").write("#!/bin/sh\necho \"'X' depends on axioms: [propext, sorryAx]\"\n"); os.chmod(os.environ["RSI_LEAN_BIN"], 0o755)
        self.assertFalse(lean.check(SAMPLE, "X", "t3")["ok"])                                           # sorryAx -> rejected
        open(os.environ["RSI_LEAN_BIN"], "w").write("#!/bin/sh\necho \"'X' depends on axioms: [propext, Lean.ofReduceBool]\"\n")
        self.assertFalse(lean.check(SAMPLE, "X", "t4")["ok"])                                           # native_decide axiom -> rejected


class ProverPipelineTests(unittest.TestCase):
    def setUp(self):
        self.d, self.repo, self.index = make_env()
        probs = load_problems(os.path.join(ROOT, "problems")); self.prob = probs["erdos_formal"]
        self.mod = sys.modules[type(self.prob).__module__]
        self.mod.INDEX, self.mod.PROOFS = self.index, os.path.join(self.d, "proofs")
        self.mem = Memory(":memory:"); self.eng = Engine(self.mem, {self.prob.id: self.prob}, target_seconds=5)
        # default: only the plain (non yes/no) challenge is eligible; the yes/no one has a dedicated test
        Ctx(self.mem, "erdos_formal").set("attempts", {"1:erdos_1.yesno": {a.name: 3 for a in self.prob.arms()}})

    def llm(self, replies):
        m = MockLLM(replies); self.mod.get_llm = lambda: m; return m

    def test_llm_proof_with_repair_becomes_candidate_never_verified(self):
        m = self.llm(["```lean\nBAD_PROOF\nsimp\n```", "```lean\nrefine ⟨0, fun N => ?_⟩\nomega\n```"])
        o = self.eng.step("erdos_formal", force_arm="llm_direct")
        self.assertEqual(o["claims"], ["formally_checked_pending_human_review"])
        self.assertTrue(any("Lean errors" in c for c in m.calls[1:]))                    # error feedback reached the model
        self.assertEqual(Ctx(self.mem, "erdos_formal").get("candidate_ids"), ["1:erdos_1"])
        self.assertTrue(self.mem.rows("SELECT * FROM events WHERE kind='alert' AND message LIKE '%LEAN-VERIFIED%'"))
        self.assertFalse(self.mem.rows("SELECT * FROM claims WHERE status='verified'"))
        self.assertIn("reproduced", self.eng.replay(o["experiment"]))

    def test_forbidden_or_failing_proofs_make_no_claim(self):
        self.llm(["```lean\nsorry\n```"] * 3 + ["```lean\nBAD_PROOF\n```"] * 3)
        o = self.eng.step("erdos_formal", force_arm="llm_direct")
        self.assertEqual(o["claims"], []); self.assertEqual(self.mem.rows("SELECT * FROM claims"), [])

    def test_tampered_saved_proof_is_rejected_by_auditor(self):
        from rsi.problem import ClaimSpec
        from rsi.verify import verify_claim
        self.llm(["```lean\nomega\n```"]); self.eng.step("erdos_formal", force_arm="llm_direct")
        ev = json.loads(self.mem.rows("SELECT evidence FROM claims")[0]["evidence"])
        text = open(ev["lean_file"]).read().replace("C ≤ N + C", "True")                  # changes the theorem statement
        open(ev["lean_file"], "w").write(text)
        status, reps = verify_claim(self.prob, ClaimSpec("proof", "x", ev))
        self.assertEqual(status, "rejected"); self.assertIn("statement_fidelity", [r.verifier for r in reps if r.verdict == "fail"])

    def test_decompose_fills_subgoals(self):
        self.llm(["```lean\nhave h : True := by\n  sorry\nrefine ⟨0, fun N => ?_⟩\nomega\n```", "```lean\ntrivial\n```"])
        o = self.eng.step("erdos_formal", force_arm="llm_decompose")
        self.assertEqual(o["claims"], ["formally_checked_pending_human_review"])

    def test_yes_no_problem_requires_an_answer_line(self):
        Ctx(self.mem, "erdos_formal").set("attempts", {"1:erdos_1": {a.name: 3 for a in self.prob.arms()}})
        self.llm(["```lean\nsimp\n```", "ANSWER: True\n```lean\nsimp\n```", "ANSWER: True\n```lean\nsimp\n```"])
        o = self.eng.step("erdos_formal", force_arm="llm_direct")
        self.assertEqual(o["claims"], ["formally_checked_pending_human_review"])
        self.assertIn("answer(True)", open(json.loads(self.mem.rows("SELECT evidence FROM claims")[0]["evidence"])["lean_file"]).read())

    def test_budget_and_missing_llm_are_handled(self):
        class Broke:
            available = True
            def complete(self, *a, **k): raise LLMBudget("cap")
        self.mod.get_llm = lambda: Broke()
        o = self.eng.step("erdos_formal", force_arm="llm_direct")
        self.assertEqual(o["sleep"], 3600); self.assertNotIn("1:erdos_1", Ctx(self.mem, "erdos_formal").get("attempts", {}))   # not counted as an attempt

    def test_automation_sweep_needs_no_llm(self):
        self.mod.get_llm = lambda: (_ for _ in ()).throw(AssertionError("LLM must not be called"))
        o = self.eng.step("erdos_formal", force_arm="automation_sweep"); self.assertEqual(o["status"], "ok")


class LLMClientTests(unittest.TestCase):
    def test_gemini_client_header_key_cap_and_failover(self):
        seen = {}
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                seen["key"] = self.headers.get("x-goog-api-key"); seen["path"] = self.path
                self.rfile.read(int(self.headers["Content-Length"]))
                body = json.dumps({"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        u = Usage(os.path.join(tempfile.mkdtemp(), "u.json"))
        g = GeminiClient("SECRET", u, ["m1"], f"http://127.0.0.1:{srv.server_address[1]}", cap=2, min_interval=0)
        self.assertEqual(g.complete("hi"), "OK"); self.assertEqual(seen["key"], "SECRET"); self.assertNotIn("SECRET", seen["path"])   # key in header, never in URL
        g.complete("hi")
        with self.assertRaises(LLMBudget): g.complete("hi")                                                                          # hard daily cap
        self.assertEqual(FailoverLLM([g, MockLLM(["from backup"])]).complete("x"), "from backup")
        with self.assertRaises(LLMBudget): FailoverLLM([g]).complete("x")
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
