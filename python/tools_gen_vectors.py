"""Generate cross-implementation test vectors for the C reference (c/tests/vec_*.txt).
Python (lifeline package) is the oracle; the C unit test replays every line and must agree exactly.
Usage: python3 tools_gen_vectors.py <outdir>"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lifeline import packet as P, hopsched as H
from lifeline.siphash import siphash24
from lifeline.crc import crc16, crc8
from lifeline.keys import derive_keys
from lifeline.replay import ReplayTable
from lifeline.queue import CustodyQueue, Entry, Q_OK_EVICT

out = sys.argv[1] if len(sys.argv) > 1 else "."
rng = random.Random(20261007)
hx = lambda b: b.hex() if b else "-"
rb = lambda n: bytes(rng.randrange(256) for _ in range(n))

def main():
    L = []
    # SipHash / CRC / KDF
    for n in list(range(0, 24)) + [31, 32, 33, 64]:
        k, m = rb(16), rb(n)
        L.append(f"SIP {k.hex()} {hx(m)} {siphash24(k, m):016x}")
    L.append(f"SIP {bytes(range(16)).hex()} - 726fdb47dd0e0e31")
    for n in list(range(0, 40)):
        m = rb(n); L.append(f"CRC16 {hx(m)} {crc16(m):04x}"); L.append(f"CRC8 {hx(m)} {crc8(m):02x}")
    masters = [rb(16) for _ in range(3)]
    for m in masters:
        K = derive_keys(m); L.append(f"KEY {m.hex()} {K.mac.hex()} {K.hop.hex()}")
    # frames
    for m in masters:
        K = derive_keys(m)
        for _ in range(60):
            cls, ttl, life = rng.randrange(3), rng.randrange(16), rng.randrange(16)
            o, pv, nx, ctr = rng.randrange(65536), rng.randrange(65536), rng.choice([0xFFFF, rng.randrange(65536)]), rng.choice([0, 1, rng.randrange(2**32), 2**32 - 1])
            pl = rb(rng.randrange(0, 15)); frag = rng.randrange(2)
            f = P.encode_data(K, cls, ttl, life, o, pv, nx, ctr, pl, bool(frag))
            L.append(f"ENCD {m.hex()} {cls} {ttl} {life} {o} {pv} {nx} {ctr} {frag} {hx(pl)} {f.hex()}")
        for _ in range(20):
            fl, node, ep, cost, fr = rng.randrange(16), rng.randrange(65536), rng.randrange(2**32), rng.randrange(256), rng.randrange(256)
            L.append(f"ENCB {m.hex()} {fl} {node} {ep} {cost} {fr} {P.encode_beacon(K, node, ep, cost, fr, fl).hex()}")
            cls, st, ak, o, ctr = rng.randrange(3), rng.randrange(3), rng.randrange(65536), rng.randrange(65536), rng.randrange(2**32)
            L.append(f"ENCA {m.hex()} {cls} {st} {ak} {o} {ctr} {P.encode_ack(K, cls, st, ak, o, ctr).hex()}")
        # decode corpus: valid + mutated + garbage; expected status from Python
        frames = [P.encode_data(K, rng.randrange(3), 5, 3, 7, 8, 9, rng.randrange(1000), rb(rng.randrange(15))) for _ in range(30)]
        frames += [P.encode_beacon(K, 3, 99, 2, 40), P.encode_ack(K, 1, 0, 3, 4, 5)]
        for f in frames:
            L.append(f"DEC {m.hex()} {f.hex()} {P.decode(K, f)[0]}")
            for _ in range(12):
                g = bytearray(f); mode = rng.randrange(4)
                if mode == 0: g[rng.randrange(len(g))] ^= 1 << rng.randrange(8)
                elif mode == 1: g = g[:rng.randrange(len(g))]
                elif mode == 2: g += rb(rng.randrange(1, 6))
                else:   # mutate then re-seal CRC: exercises the MAC / structure checks
                    g[rng.randrange(len(g) - 2)] ^= 1 << rng.randrange(8)
                    if len(g) >= 3: g[-2:] = crc16(bytes(g[:-2])).to_bytes(2, "little")
                g = bytes(g); L.append(f"DEC {m.hex()} {hx(g)} {P.decode(K, g)[0]}")
        for _ in range(40):
            g = rb(rng.randrange(0, 40)); L.append(f"DEC {m.hex()} {hx(g)} {P.decode(K, g)[0]}")
    # hop schedule
    for _ in range(40):
        K = derive_keys(rb(16)).hop; e = rng.choice([0, 1, rng.randrange(2**32), 2**32 - 1]); M = rng.choice([8, 13, 16, 40, 64, 79, 126])
        sl, nd, c = rng.randrange(5, 64), rng.randrange(65536), rng.randrange(4)
        L.append(f"HOPB {K.hex()} {e} {M} {H.beacon_channel(K, e, M)}")
        L.append(f"HOPC {K.hex()} {e} {c} {M} {H.common_channel(K, e, c, M)}")
        L.append(f"HOPR {K.hex()} {e} {sl} {nd} {M} {H.rx_channel(K, e, sl, nd, M)}")
        R = rng.randrange(1, 8)
        L.append(f"LST {K.hex()} {nd} {e} {R} {','.join(map(str, H.listen_slots(K, nd, e, R)))}")
    open(os.path.join(out, "vec_main.txt"), "w").write("\n".join(L) + "\n")

    # replay trace: 90 origin/class keys > capacity 64 so LRU eviction is exercised
    T = ReplayTable(64); R_ = []; hi = {}
    pool = [(rng.randrange(65536), rng.randrange(3)) for _ in range(90)]
    for _ in range(6000):
        o, c = rng.choice(pool[:20]) if rng.random() < 0.6 else rng.choice(pool)
        base = hi.get((o, c), 0)
        ctr = max(0, base + rng.choice([1, 1, 1, 2, 5, -1, -3, -30, -70, 0, 80, 200]))
        r = T.check_and_update(o, c, ctr); hi[(o, c)] = max(base, ctr)
        R_.append(f"RP {o} {c} {ctr} {r}")
    open(os.path.join(out, "vec_replay.txt"), "w").write("\n".join(R_) + "\n")

    # custody queue trace (capacity 32 = LL_QCAP)
    Q = CustodyQueue(32); QL = []; now = 1000; ctr = 0; stored = []
    for _ in range(4000):
        now += rng.choice([0, 1, 5, 20]); r = rng.random()
        if r < 0.45:
            ctr = ctr + 1 if rng.random() < 0.9 else rng.choice(stored)[2] if stored else 1
            cls, o = rng.choice([0, 1, 1, 2, 2, 2]), rng.randrange(1, 6)
            e = Entry(cls, o, ctr, now + rng.choice([0, 5, 100, 400, 3000]))
            st, ev = Q.push(e, now); stored.append((o, cls, ctr)); stored = stored[-50:]
            QL.append(f"PUSH {cls} {o} {ctr} {e.expiry} {now} {st} " + (f"{ev.origin},{ev.cls},{ev.ctr}" if ev else "-"))
        elif r < 0.70:
            x = Q.select(now); until = now + rng.choice([0, 3, 50])
            if x is not None: Q.defer(x, until)
            QL.append(f"SELDEF {now} {until} " + (f"{x.origin},{x.cls},{x.ctr}" if x else "-"))
        elif r < 0.85:
            x = Q.select(now)
            if x is not None: Q.remove(x)
            QL.append(f"SELREM {now} " + (f"{x.origin},{x.cls},{x.ctr}" if x else "-"))
        elif r < 0.92 and stored:
            o, c, k = rng.choice(stored); QL.append(f"REMID {o} {c} {k} {int(Q.remove_key((o, c, k)))}")
        else:
            QL.append(f"EXP {now} {len(Q.expire(now))}")
        QL.append(f"CNT {len(Q)}")
    open(os.path.join(out, "vec_queue.txt"), "w").write("\n".join(QL) + "\n")
    print("vectors:", len(L), len(R_), len(QL))

main()
