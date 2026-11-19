import os, random, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from lifeline import packet as P, hopsched as H
from lifeline.siphash import siphash24, siphash24_u64_vec
from lifeline.crc import crc16, crc8
from lifeline.keys import derive_keys
from lifeline.replay import ReplayTable, NEW, DUP, OLD
from lifeline.queue import CustodyQueue, Entry, Q_OK, Q_OK_EVICT, Q_DUP, Q_REJ_FULL, Q_REJ_EXPIRED

K = derive_keys(bytes(range(16)))


class TestPrimitives(unittest.TestCase):
    def test_siphash_official(self):
        key = bytes(range(16))
        self.assertEqual(siphash24(key, b""), 0x726fdb47dd0e0e31)
        self.assertEqual(siphash24(key, bytes(range(15))), 0xa129ca6149be45e5)

    def test_siphash_vec_matches_scalar(self):
        rng = random.Random(1); key = bytes(rng.randrange(256) for _ in range(16))
        ms = [rng.getrandbits(64) for _ in range(200)]
        v = siphash24_u64_vec(key, np.array(ms, dtype=np.uint64))
        for m, x in zip(ms, v): self.assertEqual(int(x), siphash24(key, m.to_bytes(8, "little")))

    def test_crc(self):
        self.assertEqual(crc16(b"123456789"), 0x29B1); self.assertEqual(crc8(b"123456789"), 0xF4)


class TestPackets(unittest.TestCase):
    def test_roundtrip_and_tamper(self):
        rng = random.Random(2)
        for _ in range(300):
            pl = bytes(rng.randrange(256) for _ in range(rng.randrange(15)))
            f = P.encode_data(K, rng.randrange(3), rng.randrange(16), rng.randrange(16), rng.randrange(65536), 1, 2, rng.randrange(2**32), pl, bool(rng.randrange(2)))
            st, d = P.decode(K, f); self.assertEqual(st, P.OK); self.assertEqual(P.reencode(K, d), f)
            self.assertLessEqual(len(f), 32)
            for i in range(len(f) * 8):                     # every single-bit flip rejected
                g = bytearray(f); g[i // 8] ^= 1 << (i % 8); self.assertNotEqual(P.decode(K, bytes(g))[0], P.OK)

    def test_mac_covers_immutable_not_mutable(self):
        f = P.encode_data(K, 0, 7, 3, 10, 11, 12, 99, b"abc")
        for pos in range(len(f) - 2):
            g = bytearray(f); g[pos] ^= 0x04; g[-2:] = crc16(bytes(g[:-2])).to_bytes(2, "little")
            st = P.decode(K, bytes(g))[0]
            self.assertEqual(st == P.OK, pos in (1, 4, 5, 6, 7), f"byte {pos} status {st}")

    def test_limits(self):
        with self.assertRaises(ValueError): P.encode_data(K, 0, 1, 1, 1, 1, 1, 1, bytes(15))
        self.assertEqual(len(P.encode_data(K, 0, 1, 1, 1, 1, 1, 1, bytes(14))), 32)
        self.assertEqual(len(P.encode_beacon(K, 1, 2, 3, 4)), 15); self.assertEqual(len(P.encode_ack(K, 0, 0, 1, 2, 3)), 15)


class TestHop(unittest.TestCase):
    def test_uniform_and_listen_slots(self):
        key = derive_keys(b"0123456789abcdef").hop; M = 40
        ch = np.array([H.beacon_channel(key, e, M) for e in range(40000)])
        cnt = np.bincount(ch, minlength=M); exp = 40000 / M
        chi2 = ((cnt - exp) ** 2 / exp).sum()
        self.assertLess(chi2, 70)          # df=39, 99.9% quantile ~ 72
        for e in range(300):
            s = H.listen_slots(key, e % 17, e, 8); self.assertEqual(len(set(s)), 8); self.assertTrue(all(5 <= x < 64 for x in s))

    def test_vector_matches_scalar(self):
        key = derive_keys(b"0123456789abcdef").hop
        nodes = np.arange(30); e = 12345
        v = H.rx_channel_vec(key, e, 17, nodes, 40)
        self.assertEqual([int(x) for x in v], [H.rx_channel(key, e, 17, int(n), 40) for n in nodes])
        ls = H.listen_slots_vec(key, nodes, e, 4)
        for n in nodes: self.assertEqual(list(ls[n]), H.listen_slots(key, int(n), e, 4))


class TestReplay(unittest.TestCase):
    def test_window(self):
        t = ReplayTable(8)
        self.assertEqual(t.check_and_update(1, 0, 100), NEW); self.assertEqual(t.check_and_update(1, 0, 100), DUP)
        self.assertEqual(t.check_and_update(1, 0, 90), NEW); self.assertEqual(t.check_and_update(1, 0, 90), DUP)
        self.assertEqual(t.check_and_update(1, 0, 164), NEW); self.assertEqual(t.check_and_update(1, 0, 100), OLD)
        self.assertEqual(t.check_and_update(1, 1, 100), NEW)       # per-class windows

    def test_eviction_weakness_documented(self):
        t = ReplayTable(2)
        t.check_and_update(1, 0, 5); t.check_and_update(2, 0, 5); t.check_and_update(3, 0, 5)   # evicts origin 1
        self.assertEqual(t.check_and_update(1, 0, 5), NEW)        # replay accepted after eviction (known limit)


class TestQueue(unittest.TestCase):
    def test_priority_eviction_expiry(self):
        q = CustodyQueue(3)
        e = lambda c, k, exp=100: Entry(c, 1, k, exp)
        self.assertEqual(q.push(e(2, 1), 0)[0], Q_OK); self.assertEqual(q.push(e(2, 1), 0)[0], Q_DUP)
        q.push(e(1, 2), 0); q.push(e(2, 3), 0)
        self.assertEqual(q.push(e(2, 4), 0)[0], Q_REJ_FULL)
        st, ev = q.push(e(0, 5), 0); self.assertEqual(st, Q_OK_EVICT); self.assertEqual((ev.cls, ev.ctr), (2, 1))   # oldest BULK evicted
        self.assertEqual(q.select(1).cls, 0)
        self.assertEqual(q.push(e(0, 6, 5), 10)[0], Q_REJ_EXPIRED)
        self.assertEqual(len(q.expire(100)), 3)


if __name__ == "__main__":
    unittest.main()
