import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lifeline.sim import Cfg, Sim, run
from lifeline.queue import Entry

S = dict(n=25, gen_s=120.0, run_s=200.0, rate=0.5)


class TestSim(unittest.TestCase):
    def test_deterministic(self):
        a = run(Cfg(seed=3, **S)); b = run(Cfg(seed=3, **S)); self.assertEqual(a, b)
        self.assertNotEqual(a, run(Cfg(seed=4, **S)))

    def test_accounting(self):
        for p in ("flood", "gossip", "custody"):
            r = run(Cfg(seed=2, proto=p, **S))
            self.assertLessEqual(r["delivered"], r["generated"]); self.assertGreater(r["generated"], 20)
            self.assertTrue(0 <= r["ratio"] <= 1 and 0 <= r["ratio_reach"] <= 1)
            self.assertGreaterEqual(r["q_max"], 0); self.assertLessEqual(r["q_max"], 32)

    def test_custody_benign_and_cheaper_than_flood(self):
        c = run(Cfg(seed=2, proto="custody", **S)); f = run(Cfg(seed=2, proto="flood", **S))
        self.assertGreater(c["ratio"], 0.95); self.assertLess(c["tx_per_msg"], f["tx_per_msg"])

    def test_keyed_hopping_beats_fixed_under_known_static_jammer(self):
        j = ((500, 500, 450, 0.0, 200.0, 30, "static"),)
        k = run(Cfg(seed=5, jam=j, **S)); f = run(Cfg(seed=5, jam=j, hop="fixed", **S))
        self.assertGreater(k["ratio"], f["ratio"])

    def test_full_refusal_is_reacceptable(self):
        s = Sim(Cfg(seed=1, n=10, qcap=2)); r = next(i for i in range(10) if not s.is_sink[i])
        mk = lambda ctr, cls: Entry(cls, 9, ctr, 10 ** 6, ttl=5)
        self.assertEqual(s.store(r, mk(1, 2), 0), 0); self.assertEqual(s.store(r, mk(2, 2), 0), 0)
        self.assertEqual(s.store(r, mk(3, 2), 0), 2)            # full -> refused, ACK(FULL)
        self.assertEqual(s.store(r, mk(3, 2), 0), 2)            # replay bit rolled back: still re-acceptable, not a "duplicate"
        self.assertEqual(s.store(r, mk(1, 2), 0), 1)            # genuine duplicate
        self.assertEqual(s.store(r, mk(4, 0), 0), 0)            # SOS evicts a BULK entry

    def test_node_failure_hurts_but_runs(self):
        r = run(Cfg(seed=2, fail_frac=0.4, **S)); self.assertLess(r["ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
