"""Custody queue reference model (priority store-and-forward buffer). Mirror of c/src/custody.c.
Priority: class SOS(0) > STATUS(1) > BULK(2); FIFO (enq order) within class. Fixed capacity.
push(): expired -> REJ_EXPIRED; id already stored -> DUP; free slot -> OK; else evict the OLDEST entry of the LOWEST class
if that class is strictly lower priority than the new entry (OK_EVICT) otherwise REJ_FULL.
select(now): best entry with next_try <= now and expiry > now.  Times are abstract uint32 ticks (sim: seconds*1000)."""
Q_OK, Q_OK_EVICT, Q_DUP, Q_REJ_FULL, Q_REJ_EXPIRED = range(5)
Q_NAMES = ("OK", "OK_EVICT", "DUP", "REJ_FULL", "REJ_EXPIRED")


class Entry:
    __slots__ = ("cls", "origin", "ctr", "expiry", "ttl", "enq", "next_try", "tries", "meta")

    def __init__(self, cls, origin, ctr, expiry, ttl=0, meta=None):
        self.cls, self.origin, self.ctr, self.expiry, self.ttl, self.meta = cls, origin, ctr, expiry, ttl, meta
        self.enq = 0; self.next_try = 0; self.tries = 0

    @property
    def key(self): return (self.origin, self.cls, self.ctr)


class CustodyQueue:
    def __init__(self, cap, prio=True):
        self.cap, self.items, self.seq, self.prio = cap, [], 0, prio   # prio=False -> pure FIFO (ablation only)
        self.keys = set()

    def __len__(self): return len(self.items)

    def has(self, key): return key in self.keys

    def _rank(self, e): return (e.cls if self.prio else 0, e.enq)

    def push(self, e, now):
        if e.expiry <= now:
            return Q_REJ_EXPIRED, None
        if e.key in self.keys:
            return Q_DUP, None
        evicted = None
        if len(self.items) >= self.cap:
            v = max(self.items, key=lambda x: ((x.cls if self.prio else 0), -x.enq))
            if self.prio and v.cls > e.cls:
                self.items.remove(v); self.keys.discard(v.key); evicted = v
            else:
                return Q_REJ_FULL, None
        self.seq += 1
        e.enq = self.seq; e.next_try = 0; e.tries = 0
        self.items.append(e); self.keys.add(e.key)
        return (Q_OK_EVICT if evicted else Q_OK), evicted

    def select(self, now):
        best = None
        for x in self.items:
            if x.next_try <= now and x.expiry > now and (best is None or self._rank(x) < self._rank(best)):
                best = x
        return best

    def defer(self, e, until): e.tries = min(e.tries + 1, 255); e.next_try = until

    def remove(self, e): self.items.remove(e); self.keys.discard(e.key)

    def remove_key(self, key):
        for x in self.items:
            if x.key == key:
                self.remove(x); return True
        return False

    def expire(self, now):
        dead = [x for x in self.items if x.expiry <= now]
        for x in dead: self.remove(x)
        return dead
