"""LifeLine-Mesh network simulator (superframe-level, slot-resolved link model).  NOT a radio/propagation simulator.

Time unit = one superframe (SF, 64 slots).  Everything inside an SF (rendezvous slot choice, collisions, jamming,
ACKs) is resolved per slot using the REAL keyed hop functions (hopsched.rx_channel_vec / listen_slots_vec), the real
CustodyQueue and the real ReplayTable.  Frame bytes are not materialised (the codec/C code are tested separately);
every message is one frame.  See docs/PROTOCOL.md section 10 for the model and its limits.

Protocols: 'flood' (rebroadcast once on first reception), 'gossip' (each held message is rebroadcast w.p. p per SF,
up to k times), 'custody' (unicast to a lower-cost neighbour on a private rendezvous slot, link ACK, hand-off of custody,
retry with backoff, store-carry-forward).  All three use the same duplicate suppression, queue capacity and per-node
transmit budget.  Flood/gossip use the 4 common (broadcast) slots; custody uses the private listen slots.
"""
from dataclasses import dataclass, field
import math
import numpy as np
from . import hopsched as H
from .keys import derive_keys
from .queue import CustodyQueue, Entry, Q_OK, Q_OK_EVICT, Q_DUP, Q_REJ_FULL
from .replay import ReplayTable, NEW

SF_S = 0.64                                  # 64 slots x 10 ms
CLASS_LIFE = (15, 11, 8)                     # life codes for SOS / STATUS / BULK (PROTOCOL.md 6.2)
CLASS_NAMES = ("SOS", "STATUS", "BULK")


def life_seconds(code):                      # life code 0..15 -> seconds (PROTOCOL.md 6.2)
    return 4.0 * 1.5 ** code


# radio energy model: ASSUMED nRF24L01+-class numbers (typical datasheet values recalled from memory, not measured)
V, I_TX, I_RX, I_SLEEP = 3.0, 11.3e-3, 13.5e-3, 5e-6     # volts, amps (sleep includes an assumed MCU in deep sleep)
T_WIN, T_DATA, T_SHORT = 0.6e-3, 0.33e-3, 0.20e-3        # s: empty listen window, 32 B tx incl. settling, 15 B tx


@dataclass
class Cfg:
    n: int = 36
    topo: str = "rgg"               # grid | rgg | line | clusters
    deg: float = 8.0                # target mean degree (rgg/clusters)
    connected: bool = True          # enforce connectivity of the initial graph
    n_sinks: int = 1
    proto: str = "custody"          # flood | gossip | custody
    hop: str = "keyed"              # keyed | fixed (fixed = every node always on channel 0)
    prio: bool = True
    gen_s: float = 600.0
    run_s: float = 900.0
    rate: float = 0.4               # offered messages per second, whole network
    mix: tuple = (0.1, 0.3, 0.6)
    fail_frac: float = 0.0
    fail_at: float = 0.33           # fraction of gen_s
    jam: tuple = ()                 # tuples (x, y, radius, t0_s, t1_s, J, mode) mode 'static'|'random'
    mobile_frac: float = 0.0
    speed: float = 1.5              # m/s
    M: int = 40
    R: int = 6
    R_sink: int = 6
    qcap: int = 32
    tmax: int = 2
    p_loss: float = 0.02
    gossip_p: float = 0.3
    gossip_k: int = 4
    area: float = 1000.0
    seed: int = 1


def _bfs(adj, alive, sinks):
    n = len(alive); cost = np.full(n, 255, dtype=np.int32)
    fr = [s for s in sinks if alive[s]]
    for s in fr: cost[s] = 0
    d = 0
    while fr:
        d += 1; nxt = []
        for u in fr:
            for v in np.nonzero(adj[u] & alive)[0]:
                if cost[v] == 255: cost[v] = d; nxt.append(v)
        fr = nxt
    return cost


def _connected(adj):
    seen = {0}; st = [0]
    while st:
        u = st.pop()
        for v in np.nonzero(adj[u])[0]:
            if v not in seen: seen.add(int(v)); st.append(int(v))
    return len(seen) == len(adj)


def make_topology(c, rng):
    n, A = c.n, c.area
    if c.topo == "grid":
        s = math.ceil(math.sqrt(n)); sp = A / s
        pos = np.array([[(i % s + .5) * sp, (i // s + .5) * sp] for i in range(n)]); rg = 1.5 * sp
    elif c.topo == "line":
        sp = A / n; pos = np.array([[(i + .5) * sp, A / 2] for i in range(n)]); rg = 2.1 * sp
    else:
        rg = math.sqrt(c.deg * A * A / (math.pi * n))
        for _ in range(200):
            if c.topo == "clusters":
                cen = np.array([[.2, .3], [.5, .7], [.8, .3]]) * A
                pos = np.clip(cen[rng.integers(0, 3, n)] + rng.normal(0, .08 * A, (n, 2)), 0, A)
            else:
                pos = rng.uniform(0, A, (n, 2))
            d = np.linalg.norm(pos[:, None] - pos[None], axis=2)
            if not c.connected or _connected((d < rg) & ~np.eye(n, dtype=bool)): break
        else:
            rg *= 1.15
    return pos, rg


class Sim:
    def __init__(self, c: Cfg):
        self.c = c; self.rng = np.random.default_rng(c.seed)
        self.pos, self.rg = make_topology(c, self.rng)
        n = c.n
        # sinks: nodes nearest the corner(s) / far end (rescue centres)
        corners = [(0, 0), (c.area, c.area)][:c.n_sinks]
        self.sinks = [int(np.argmin(np.linalg.norm(self.pos - np.array(k), axis=1))) for k in corners]
        self.is_sink = np.zeros(n, bool); self.is_sink[self.sinks] = True
        self.alive = np.ones(n, bool); self.known_alive = self.alive.copy()
        self.q = [CustodyQueue(c.qcap, prio=c.prio) for _ in range(n)]
        self.rp = [ReplayTable(64) for _ in range(n)]
        self.ctr = np.zeros((n, 3), dtype=np.int64)
        self.hopkey = derive_keys(bytes(self.rng.integers(0, 256, 16, dtype=np.uint8))).hop
        mob = self.rng.permutation([i for i in range(n) if i not in self.sinks])[:int(round(c.mobile_frac * n))]
        self.mobile = np.zeros(n, bool); self.mobile[mob] = True
        self.wp = self.pos.copy(); self.cost = np.full(n, 255, np.int32)
        self.gen = {}; self.dlv = {}              # msg id -> (cls, gen_sf) ; msg id -> deliver_sf
        self.m = dict(tx_data=0, tx_ack=0, tx_beacon=0, collisions=0, jam_loss=0, dup_rx_sink=0, evicted=0, src_drop=0,
                      lost_failed=0, expired=0, full_ack=0, old_drop=0, q_sum=0.0, q_max=0, q_n=0)
        self.energy = np.zeros(n)
        self.occ_ts = []

    # ---- helpers ----
    def adj_now(self):
        d = np.linalg.norm(self.pos[:, None] - self.pos[None], axis=2)
        a = (d < self.rg) & ~np.eye(self.c.n, dtype=bool)
        return a & self.alive[:, None] & self.alive[None, :]

    def move(self):
        c = self.c
        for i in np.nonzero(self.mobile)[0]:
            v = self.wp[i] - self.pos[i]; dist = np.linalg.norm(v); step = c.speed * SF_S
            if dist < step: self.pos[i] = self.wp[i]; self.wp[i] = self.rng.uniform(0, c.area, 2)
            else: self.pos[i] += v / dist * step

    def make_msg(self, sf):
        c = self.c; alive_src = [i for i in range(c.n) if self.alive[i] and not self.is_sink[i]]
        o = int(self.rng.choice(alive_src)); cls = int(self.rng.choice(3, p=c.mix))
        self.ctr[o, cls] += 1; ctr = int(self.ctr[o, cls])
        life_sf = int(life_seconds(CLASS_LIFE[cls]) / SF_S)
        e = Entry(cls, o, ctr, sf + life_sf, ttl=15, meta=sf)
        self.gen[e.key] = (cls, sf, bool(self.cost[o] < 255))
        self.rp[o].check_and_update(o, cls, ctr)
        st, ev = self.q[o].push(e, sf)
        if st == Q_REJ_FULL: self.m["src_drop"] += 1
        if ev is not None: self.m["evicted"] += 1
        return e

    def deliver(self, e, sf):
        if e.key in self.dlv: self.m["dup_rx_sink"] += 1
        else: self.dlv[e.key] = sf

    def store(self, r, e, sf):
        """Receiver r accepts a copy; returns ACK status 0 accepted / 1 duplicate / 2 full."""
        if self.is_sink[r]:
            self.deliver(e, sf); return 0
        v = self.rp[r].check_and_update(e.origin, e.cls, e.ctr)
        if v != NEW:
            if v == 2: self.m["old_drop"] += 1
            return 1
        ne = Entry(e.cls, e.origin, e.ctr, e.expiry, ttl=e.ttl - 1, meta=e.meta)
        if ne.ttl < 0: return 0
        st, ev = self.q[r].push(ne, sf)
        if ev is not None: self.m["evicted"] += 1
        if st == Q_REJ_FULL:
            self.m["full_ack"] += 1; self._unsee(r, e); return 2
        return 0

    def _unsee(self, r, e):
        """A refused (FULL) frame must stay re-acceptable later: roll the replay bit back."""
        ent = self.rp[r].ent.get((e.origin, e.cls))
        if ent is not None:
            d = ent[0] - e.ctr
            if 0 <= d < 64: ent[1] &= ~(1 << d)

    # ---- jam ----
    def jam_state(self, sf):
        c = self.c; t = sf * SF_S; act = []
        for (x, y, rad, t0, t1, J, mode) in c.jam:
            if t0 <= t < t1:
                inside = np.linalg.norm(self.pos - np.array([x, y]), axis=1) <= rad
                if mode == "static":
                    mk = np.zeros((64, c.M), bool); mk[:, :J] = True
                else:
                    mk = np.zeros((64, c.M), bool)
                    idx = np.argsort(self.rng.random((64, c.M)), axis=1)[:, :J]
                    np.put_along_axis(mk, idx, True, axis=1)
                act.append((inside, mk))
        return act

    @staticmethod
    def jammed(act, node, slot, ch):
        for inside, mk in act:
            if inside[node] and mk[slot, ch]: return True
        return False

    # ---- main loop ----
    def run(self):
        c = self.c; n = c.n; T = int(c.run_s / SF_S); Tg = int(c.gen_s / SF_S)
        fail_sf = int(c.fail_at * Tg); nodes = np.arange(n)
        ls_cache = {}
        for sf in range(T):
            if sf == fail_sf and c.fail_frac > 0:
                cand = [i for i in range(n) if not self.is_sink[i]]
                for i in self.rng.permutation(cand)[:int(round(c.fail_frac * len(cand)))]:
                    self.alive[i] = False
                    self.m["lost_failed"] += sum(1 for e in self.q[i].items)
                    self.q[i].items.clear(); self.q[i].keys.clear()
            if c.mobile_frac > 0: self.move()
            adj = self.adj_now()
            if sf % 8 == 0:
                self.cost = _bfs(adj, self.alive, self.sinks); self.known_alive = self.alive.copy()
            if sf < Tg:
                for _ in range(self.rng.poisson(c.rate * SF_S)): self.make_msg(sf)
            for i in range(n):
                if self.alive[i]:
                    dead = self.q[i].expire(sf); self.m["expired"] += len(dead)
            act = self.jam_state(sf)
            chan = (H.rx_channel_vec(self.hopkey, sf, np.arange(64)[None, :], nodes[:, None], c.M)
                    if c.hop == "keyed" else np.zeros((n, 64), np.int64))
            if c.proto == "custody":
                lsl = H.listen_slots_vec(self.hopkey, nodes, sf, c.R)
                lsl_sink = H.listen_slots_vec(self.hopkey, np.array(self.sinks), sf, c.R_sink)
                for k, s in enumerate(self.sinks): ls_cache[s] = lsl_sink[k]
                self.custody_step(sf, adj, chan, lsl, ls_cache, act)
                wins = c.R + H.N_COMMON + 1
            else:
                self.broadcast_step(sf, adj, act)
                wins = H.N_COMMON + 1
            # energy: listen windows + beacon share + sleep
            for i in np.nonzero(self.alive)[0]:
                w = wins + (c.R_sink - c.R if self.is_sink[i] and c.proto == "custody" else 0)
                self.energy[i] += w * T_WIN * I_RX * V + (SF_S - w * T_WIN) * I_SLEEP * V
                if self.rng.random() < 1 / 8: self.energy[i] += T_SHORT * I_TX * V; self.m["tx_beacon"] += 1
            occ = [len(self.q[i]) for i in range(n) if self.alive[i] and not self.is_sink[i]]
            self.m["q_sum"] += float(np.mean(occ)); self.m["q_n"] += 1; self.m["q_max"] = max(self.m["q_max"], max(occ))
            if sf % 8 == 0: self.occ_ts.append(float(np.mean(occ)))
        return self.summary(T)

    # ---- custody (unicast, ACK, hand-off) ----
    def custody_step(self, sf, adj, chan, lsl, ls_cache, act):
        c = self.c; txs = []; busy = {}
        for i in range(c.n):
            if not self.alive[i] or self.is_sink[i]: continue
            q = self.q[i]
            for _ in range(c.tmax):
                e = q.select(sf)
                if e is None: break
                nb = np.nonzero(adj[i] & self.known_alive & (self.cost < self.cost[i]))[0]
                if len(nb) == 0:
                    e.next_try = sf + 2; continue
                if e.tries >= 2: r = int(self.rng.choice(nb))
                else:
                    cm = self.cost[nb].min(); r = int(self.rng.choice(nb[self.cost[nb] == cm]))
                lst = ls_cache[r] if self.is_sink[r] else lsl[r]
                used = busy.setdefault(i, set())
                opts = [int(s) for s in lst if int(s) not in used and int(s) + 1 not in used and int(s) <= 62 and int(s) - 1 not in used]
                if not opts:
                    e.next_try = sf + 1; continue
                s = int(self.rng.choice(opts)); used.update((s, s + 1))
                q.defer(e, sf + 1)                         # counts the attempt; outcome below overrides
                txs.append((i, r, s, e))
        by_slot = {}
        for t in txs: by_slot.setdefault(t[2], []).append(t)
        tx_at = {}
        for (i, r, s, e) in txs: tx_at.setdefault(i, set()).add(s)
        for (i, r, s, e) in txs:
            self.m["tx_data"] += 1
            self.energy[i] += T_DATA * I_TX * V + T_WIN * I_RX * V         # data + ack listen window
            ch = int(chan[r, s]); ok = True
            same_r = [t for t in by_slot[s] if t[1] == r]
            if len(same_r) > 1: ok = False; self.m["collisions"] += 1
            elif s in tx_at.get(r, ()): ok = False
            elif any(t[0] != i and adj[t[0], r] and int(chan[t[1], s]) == ch for t in by_slot[s]):
                ok = False; self.m["collisions"] += 1
            elif self.jammed(act, r, s, ch): ok = False; self.m["jam_loss"] += 1
            elif self.rng.random() < c.p_loss: ok = False
            if ok and not self.alive[r]: ok = False
            if not ok:
                e.next_try = sf + min(1 << min(e.tries, 4), 16); continue
            st = self.store(r, e, sf)
            self.m["tx_ack"] += 1; self.energy[r] += T_SHORT * I_TX * V
            ach = int(chan[i, s + 1])
            if self.jammed(act, i, s + 1, ach) or self.rng.random() < c.p_loss:
                e.next_try = sf + min(1 << min(e.tries, 4), 16); continue      # ACK lost: retry -> receiver answers DUPLICATE
            if st in (0, 1):
                if any(x is e for x in self.q[i].items): self.q[i].remove(e)      # may have been evicted in-flight
            else: e.next_try = sf + min(1 << min(e.tries, 4), 16)

    # ---- flooding / gossip (broadcast on the common slots) ----
    def broadcast_step(self, sf, adj, act):
        c = self.c; n = c.n; txs = {k: [] for k in range(H.N_COMMON)}
        for i in range(n):
            if not self.alive[i] or self.is_sink[i]: continue
            q = self.q[i]; slots = list(self.rng.permutation(H.N_COMMON)); picked = 0
            while picked < c.tmax:
                e = q.select(sf)
                if e is None: break
                if c.proto == "gossip" and self.rng.random() > c.gossip_p:
                    q.defer(e, sf + 1); e.tries -= 1; continue      # coin said no: not an attempt
                if e.ttl <= 0: q.remove(e); continue
                txs[slots[picked]].append((i, e)); picked += 1
                kmax = 1 if c.proto == "flood" else c.gossip_k
                q.defer(e, sf + 1)
                if e.tries >= kmax: q.remove(e)
        for k in range(H.N_COMMON):
            if not txs[k]: continue
            tx_vec = np.zeros(n); senders = {}
            for (i, e) in txs[k]: tx_vec[i] += 1; senders[i] = e
            heard = adj.astype(float) @ tx_vec
            ch = (int(H.common_channel(self.hopkey, sf, k, c.M)) if c.hop == "keyed" else 0)
            for (i, e) in txs[k]:
                self.m["tx_data"] += 1; self.energy[i] += T_DATA * I_TX * V
            for r in np.nonzero(self.alive & (heard > 0))[0]:
                if tx_vec[r] > 0: continue
                if heard[r] > 1: self.m["collisions"] += 1; continue
                if self.jammed(act, r, 1 + k, ch): self.m["jam_loss"] += 1; continue
                if self.rng.random() < c.p_loss: continue
                s = next(i for i in np.nonzero(adj[r])[0] if tx_vec[i] > 0)
                e = senders[int(s)]
                self.store(int(r), e, sf)

    def summary(self, T):
        c, m = self.c, self.m; out = {}
        gen = np.array([v[0] for v in self.gen.values()]); dl = {k: v for k, v in self.dlv.items()}
        out["generated"] = len(gen); out["delivered"] = len(dl)
        out["ratio"] = len(dl) / max(1, len(gen))
        reach = [k for k, v in self.gen.items() if v[2]]          # origin had a path to a sink (last cost table) at creation
        out["ratio_reach"] = sum(1 for k in reach if k in dl) / max(1, len(reach))
        lat = []; per = {0: [0, 0], 1: [0, 0], 2: [0, 0]}; latc = {0: [], 1: [], 2: []}
        for k, (cls, g, _r) in self.gen.items():
            per[cls][0] += 1
            if k in dl: per[cls][1] += 1; latc[cls].append((dl[k] - g) * SF_S); lat.append((dl[k] - g) * SF_S)
        for cls in range(3):
            out[f"ratio_{CLASS_NAMES[cls]}"] = per[cls][1] / per[cls][0] if per[cls][0] else float("nan")
            out[f"lat_med_{CLASS_NAMES[cls]}"] = float(np.median(latc[cls])) if latc[cls] else float("nan")
        out["lat_mean"] = float(np.mean(lat)) if lat else float("nan")
        out["lat_med"] = float(np.median(lat)) if lat else float("nan")
        out["lat_p95"] = float(np.percentile(lat, 95)) if lat else float("nan")
        out["tx_data"] = m["tx_data"]; out["tx_per_msg"] = m["tx_data"] / max(1, len(dl))
        ne = self.energy[self.alive & ~self.is_sink]
        out["energy_node_J"] = float(ne.mean()); out["mean_current_uA"] = float(ne.mean() / V / c.run_s * 1e6)
        out["energy_per_deliv_J"] = float(self.energy.sum() / max(1, len(dl)))
        out["q_mean"] = m["q_sum"] / max(1, m["q_n"]); out["q_max"] = m["q_max"]
        for k in ("collisions", "jam_loss", "dup_rx_sink", "evicted", "src_drop", "lost_failed", "expired", "full_ack", "old_drop"):
            out[k] = m[k]
        return out


def run(cfg: Cfg):
    return Sim(cfg).run()
