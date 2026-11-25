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
