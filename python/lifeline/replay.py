"""Anti-replay + duplicate suppression: sliding 64-counter window per (origin, class). Mirror of c/src/replay.c.
Table has fixed capacity; when full, the least-recently-updated entry is evicted (documented weakness: an evicted
origin's old frames can be accepted again; see PROTOCOL.md 8.3). Call only AFTER the MAC has verified."""
NEW, DUP, OLD = 0, 1, 2
W = 64
M64 = (1 << 64) - 1


class ReplayTable:
    def __init__(self, cap=64):
        self.cap = cap; self.ent = {}; self.tick = 0   # key -> [highest, bitmap, last_used]

    def check_and_update(self, origin, cls, ctr):
        self.tick += 1
        key = (origin, cls)
        e = self.ent.get(key)
        if e is None:
            if len(self.ent) >= self.cap:
                victim = min(self.ent, key=lambda k: (self.ent[k][2], k))
                del self.ent[victim]
            self.ent[key] = [ctr, 1, self.tick]
            return NEW
        e[2] = self.tick
        if ctr > e[0]:
            sh = ctr - e[0]
            e[1] = 1 if sh >= W else ((e[1] << sh) & M64) | 1
            e[0] = ctr
            return NEW
        d = e[0] - ctr
        if d >= W:
            return OLD
        if (e[1] >> d) & 1:
            return DUP
        e[1] |= 1 << d
        return NEW
