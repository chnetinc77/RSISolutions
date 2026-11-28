import json, os, sys, tempfile, threading, unittest, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
from rsi.engine import Engine
from rsi.memory import Memory
from rsi.problem import load_problems
from rsi.dashboard import serve, snapshot
import toy

hz = load_problems(os.path.join(ROOT, "problems"))["hou_zeng_ppl013"]
import importlib; hzmod = sys.modules[type(hz).__module__]


def engine(problems):
    mem = Memory(":memory:")
    return mem, Engine(mem, problems, seed=1, target_seconds=5)


class MemoryTests(unittest.TestCase):
    def test_journal_detects_tampering(self):
        d = tempfile.mkdtemp(); mem = Memory(os.path.join(d, "m.sqlite"))
        mem.add_lesson("p", "t", "a"); mem.add_lesson("p", "t", "b")
        self.assertTrue(mem.verify_journal()["ok"])
        mem.db.execute("UPDATE journal SET payload='{}' WHERE seq=1"); mem.db.commit()
        self.assertFalse(mem.verify_journal()["ok"])


class HouZengMath(unittest.TestCase):
    def brute(self, n):
        F, C = hzmod.fibonacci_upto(n), hzmod.catalan_upto(n)
        return sum(1 for f in F for c in C for p in [n - f - c] if p >= 3 and hzmod.trial_is_prime(p) and p % 2)

    def test_sequences(self):
        self.assertEqual(hzmod.fibonacci_upto(30), [1, 2, 3, 5, 8, 13, 21])
        self.assertEqual(hzmod.catalan_upto(500), [1, 2, 5, 14, 42, 132, 429])

    def test_a154404_n7_has_three_representations(self):  # OEIS: 3+2+2, 3+3+1, 5+1+1
        self.assertEqual(self.brute(7), 3)

    def test_scans_agree_with_bruteforce(self):
        N = 3000; P = hzmod.odd_prime_sieve(N); sums = sorted(hzmod.pair_sums(N))
        expect = [n for n in range(5, N + 1) if self.brute(n) == 0]
        self.assertEqual(expect, [])
        self.assertEqual(hzmod.scan_per_n(P, sums, 5, N)[0], expect)
        for K in (4, 24, 96):
            self.assertEqual(hzmod.scan_bitset(P, sums, 5, N, K, seg=512)[0], expect)

    def test_scan_finds_planted_gap(self):  # break the oracle: remove all primes -> everything uncovered
        N = 200; P = bytearray(N + 1); sums = sorted(hzmod.pair_sums(N))
        self.assertEqual(len(hzmod.scan_per_n(P, sums, 5, N)[0]), N - 4)
        self.assertEqual(len(hzmod.scan_bitset(P, sums, 5, N, 8)[0]), N - 4)

    def test_sieve(self):
        P = hzmod.odd_prime_sieve(100)
        self.assertEqual([i for i in range(101) if P[i]], [p for p in range(3, 101) if hzmod.trial_is_prime(p)])


class EngineTests(unittest.TestCase):
    def test_hou_zeng_end_to_end_verified_and_replayable(self):
        mem, eng = engine({hz.id: hz})
        mem.set_state(hz.id, "scale", 0.002)
        out = eng.run(hz.id, 3)
        self.assertTrue(all(o["committed"] for o in out), out)
        self.assertGreater(mem.get_state(hz.id, "frontier"), 4000)
        claims = mem.rows("SELECT status,kind FROM claims")
        self.assertTrue(all(c["status"] == "verified" and c["kind"] == "evidence" for c in claims))
        self.assertGreaterEqual(len(mem.rows("SELECT * FROM verifications WHERE claim_id=1")), 2)
        rep = eng.replay(out[0]["experiment"]); self.assertTrue(rep["reproduced"])
        self.assertTrue(mem.verify_journal()["ok"])

    def test_analysis_arm_runs_and_replays(self):
        mem, eng = engine({hz.id: hz})
        arm = [a for a in hz.arms() if a.kind == "analysis"][0]
        res = hz.run({**arm.params, "arm": arm.name, "top_decade": 4, "samples": 50}, 3)
        self.assertEqual(res.claims, []); self.assertIn("2", res.deterministic["stats"])

    def test_generic_problem_and_bandit_and_tuner(self):
        probs = {p.id: p for p in toy.get_problems()}
        mem, eng = engine(probs); eng.target = 0.05
        out = eng.run("toy_goldbach", 12)
        self.assertTrue(all(o["committed"] for o in out))
        self.assertEqual(set(mem.arm_stats("toy_goldbach")), {"slow", "fast"})
        self.assertNotEqual(mem.get_state("toy_goldbach", "scale", 1.0), 1.0)  # workload scale adapted

    def test_false_counterexample_is_rejected(self):
        mem, eng = engine({p.id: p for p in toy.get_problems()})
        o = eng.step("toy_liar")
        self.assertFalse(o["committed"]); self.assertEqual(o["claims"], ["rejected"])
        self.assertTrue(mem.rows("SELECT * FROM lessons WHERE tag='failed_approach'"))

    def test_proof_claims_never_auto_verified(self):
        mem, eng = engine({p.id: p for p in toy.get_problems()})
        o = eng.step("toy_proof")
        self.assertEqual(o["claims"], ["unverified_needs_external_review"])

    def test_hou_zeng_verifier_rejects_bogus_counterexample_and_corrupt_sieve(self):
        from rsi.problem import ClaimSpec
        from rsi.verify import verify_claim
        status, _ = verify_claim(hz, ClaimSpec("counterexample", "n=100", {"n": 100}))
        self.assertEqual(status, "rejected")
        real = hzmod.odd_prime_sieve
        def corrupt(n):
            P = real(n); P[9] = 1; P[15] = 1; return P   # claim composites are prime
        hzmod.odd_prime_sieve = corrupt
        try:
            status, reps = verify_claim(hz, ClaimSpec("evidence", "x", {"lo": 5, "hi": 3000, "hard": [], "seed": 0}))
        finally:
            hzmod.odd_prime_sieve = real
        self.assertEqual(status, "rejected"); self.assertIn("sieve_vs_trial_division", [r.verifier for r in reps if r.verdict == "fail"])


class AgentTests(unittest.TestCase):
    def test_event_feed_and_agent_roster(self):
        probs = {p.id: p for p in toy.get_problems()}
        mem, eng = engine(probs); eng.run("toy_goldbach", 2)
        agents = {a["name"] for a in snapshot(mem, probs)["agents"]}
        self.assertTrue({"Conductor", "Auditor"} <= agents)
        self.assertTrue(any(a.startswith("Solver:") for a in agents))
        kinds = {e["kind"] for e in snapshot(mem, probs)["events"]}
        self.assertTrue({"dispatch", "start", "result", "verdict", "commit"} <= kinds)
        self.assertTrue(mem.verify_journal()["ok"])

    def test_auditor_blocks_unsafe_self_modification(self):
        from rsi.problem import Ctx
        probs = {p.id: p for p in toy.get_problems()}
        mem, eng = engine(probs); prob = probs["toy_canary"]; ctx = Ctx(mem, "toy_canary")
        arms = prob.arms(); fast = arms[1]
        ctx.set("incumbent_rate:fast", 1.0)
        eng._tune(prob, ctx, "toy_canary", arms, fast, {"chunk": 100}, {"chunk": 800}, 1e9)   # fast but wrong
        self.assertIsNone(ctx.get("tuned:fast"))
        alerts = mem.rows("SELECT * FROM events WHERE kind='alert' AND agent='Auditor'")
        self.assertTrue(alerts and "FAILED" in alerts[0]["message"])
        eng._tune(prob, ctx, "toy_canary", arms, fast, {"chunk": 100}, {"chunk": 200}, 1e9)   # fast and correct
        self.assertEqual(ctx.get("tuned:fast"), {"chunk": 200})
        self.assertTrue(mem.rows("SELECT * FROM events WHERE kind='adopted' AND agent='RSI'"))

    def test_overclaiming_is_rejected(self):
        mem, eng = engine({p.id: p for p in toy.get_problems()})
        o = eng.step("toy_overclaim")
        self.assertEqual(o["claims"], ["rejected"]); self.assertFalse(o["committed"])


class LivePublishTests(unittest.TestCase):
    def test_live_branch_is_a_single_rewritten_commit(self):
        import subprocess
        from rsi.dashboard import publish_live
        d = tempfile.mkdtemp(); env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        run = lambda *a, cwd=d: subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True, env=env)
        run("git", "init", "-q", "--bare", "origin.git"); run("git", "clone", "-q", "origin.git", "work")
        work = os.path.join(d, "work"); run("git", "config", "user.name", "t", cwd=work); run("git", "config", "user.email", "t@t", cwd=work)
        probs = {p.id: p for p in toy.get_problems()}; mem = Memory(os.path.join(d, "m.sqlite")); eng = Engine(mem, probs, target_seconds=1)
        eng.run("toy_goldbach", 1)
        self.assertEqual(publish_live(mem, probs, work), "pushed")
        self.assertEqual(publish_live(mem, probs, work), "unchanged")
        eng.run("toy_goldbach", 1)
        self.assertEqual(publish_live(mem, probs, work), "pushed")
        origin = os.path.join(d, "origin.git")
        self.assertEqual(run("git", "--git-dir", origin, "rev-list", "--count", "live-data").stdout.strip(), "1")
        state = json.loads(run("git", "--git-dir", origin, "show", "live-data:state.json").stdout)
        self.assertEqual(state["problems"][0]["id"], "toy_goldbach"); self.assertTrue(state["events"]); self.assertTrue(state["agents"])


class DashboardTests(unittest.TestCase):
    def test_api(self):
        d = tempfile.mkdtemp(); db = os.path.join(d, "m.sqlite"); mem = Memory(db)
        probs = {p.id: p for p in toy.get_problems()}
        Engine(mem, probs, target_seconds=1).run("toy_goldbach", 2)
        srv = serve(db, probs, port=0); port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state"))
        self.assertEqual(data["problems"][0]["id"], "toy_goldbach"); self.assertTrue(data["journal"]["ok"])
        self.assertIn("RSI Research Dashboard", urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode())
        srv.shutdown()


class ErdosMinOverlapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eo = sys.modules[type(load_problems(os.path.join(ROOT, "problems"))["erdos_min_overlap"]).__module__]
        cls.eo.PARTITION_M = 5000
        import importlib.util
        spec = importlib.util.spec_from_file_location("eo_indep", os.path.join(ROOT, "verifiers", "erdos_min_overlap_independent.py"))
        cls.indep = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.indep)

    def test_constant_half_gives_one_half_and_two_algorithms_agree(self):
        eo = self.eo; a = [eo.D // 2] * 24; S = eo.exact_S(a)
        self.assertEqual(eo.C_of(S, 24), eo.Fraction(1, 2))
        self.assertEqual(self.indep.correlation_max(a, eo.D), S)

    def test_projection_and_rounding_keep_constraints_exactly(self):
        eo = self.eo; import random as r
        rng = r.Random(3); h = eo.project([rng.uniform(-1, 2) for _ in range(30)], 30)
        self.assertAlmostEqual(sum(h), 15, places=9); self.assertTrue(all(0 <= x <= 1 for x in h))
        a = eo.to_ints(h); self.assertEqual(sum(a), eo.D * 15)

    def test_end_to_end_witnesses_verified_and_tampering_rejected(self):
        from rsi.problem import ClaimSpec
        from rsi.verify import verify_claim
        prob = load_problems(os.path.join(ROOT, "problems"))["erdos_min_overlap"]
        mem, eng = engine({prob.id: prob}); mem.set_state(prob.id, "scale", 0.05)
        outs = eng.run(prob.id, 3)
        self.assertTrue(all(o["committed"] for o in outs), outs)
        best = mem.get_state(prob.id, "best"); self.assertLess(best["C"], 0.5); self.assertGreater(best["C"], 0.379005)
        self.assertTrue(all(c["status"] == "verified" for c in mem.rows("SELECT status FROM claims")))
        ev = {"n": best["n"], "D": self.eo.D, "a": list(best["a"]), "claimed_S": best["S"], "C": best["C"]}
        bad = dict(ev, a=[ev["a"][0] + 5] + ev["a"][1:])          # breaks the integral-equals-1 constraint
        self.assertEqual(verify_claim(prob, ClaimSpec("witness", "tampered", bad))[0], "rejected")
        lie = dict(ev, claimed_S=ev["claimed_S"] - 1000)           # claims a better value than the truth
        self.assertEqual(verify_claim(prob, ClaimSpec("witness", "lie", lie))[0], "rejected")

    @unittest.skipUnless(__import__("importlib").util.find_spec("scipy") is not None, "scipy not installed")
    def test_sequential_lp_arm_finds_verified_witness(self):
        prob = load_problems(os.path.join(ROOT, "problems"))["erdos_min_overlap"]
        mem, eng = engine({prob.id: prob}); mem.set_state(prob.id, "scale", 0.15)
        o = eng.step(prob.id, force_arm="slp_fresh")
        self.assertEqual(o["claims"], ["verified"], o)
        self.assertLess(mem.get_state(prob.id, "best")["C"], 0.39)       # far below the trivial 0.5

    @unittest.skipUnless(__import__("importlib").util.find_spec("scipy") is not None, "scipy not installed")
    def test_parallel_restarts_give_identical_results_and_even_pieces(self):
        eo = self.eo
        a = eo.slp_search(None, "fresh", 4, 0.0, 0.05, 15, 21, seed=5, workers=1)
        b = eo.slp_search(None, "fresh", 4, 0.0, 0.05, 15, 21, seed=5, workers=2)
        self.assertEqual(a, b); self.assertEqual(len(a) % 2, 0)             # same answer on 1 or 2 workers; 21 -> 20 pieces

    def test_canary_rejects_invalid_witness(self):
        from rsi.problem import ExperimentResult
        prob = load_problems(os.path.join(ROOT, "problems"))["erdos_min_overlap"]; eo = self.eo
        good = ExperimentResult("", {}, {"n": 4, "a": [eo.D // 2] * 4, "S": eo.exact_S([eo.D // 2] * 4), "improved": True})
        broken = ExperimentResult("", {}, {"n": 4, "a": [eo.D] * 4, "S": 0, "improved": True})
        self.assertTrue(prob.canary_ok(good, good)); self.assertFalse(prob.canary_ok(good, broken))


class PerfTests(unittest.TestCase):
    def test_zero_baseline_rate_does_not_crash(self):
        from rsi.perf import performance
        mem = Memory(":memory:")
        for v in (0.0, 0.0, 0.0):
            mem.record_metric("p", "rate:base", v)
        mem.record_metric("p", "rate:other", 5.0)
        out = performance(mem, "p", "base")
        self.assertNotIn("speedup_vs_baseline", out); self.assertEqual(out["recent_rate"]["other"], 5.0)


class PublishTests(unittest.TestCase):
    def test_publish_writes_static_state_and_site_files_exist(self):
        from rsi.dashboard import publish
        d = tempfile.mkdtemp(); mem = Memory(os.path.join(d, "m.sqlite"))
        probs = {p.id: p for p in toy.get_problems()}
        Engine(mem, probs, target_seconds=1).run("toy_goldbach", 2)
        path = publish(mem, probs, os.path.join(d, "data"))
        data = json.load(open(path))
        self.assertEqual(data["problems"][0]["id"], "toy_goldbach"); self.assertTrue(data["journal"]["ok"]); self.assertGreater(data["generated_at"], 0)
        for f in ("index.html", "style.css", "app.js", os.path.join("data", "state.json")):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "web", f)), f)
        self.assertIn("data/state.json", open(os.path.join(ROOT, "web", "app.js")).read())


if __name__ == "__main__":
    unittest.main()
