"""Keyed hop schedule and rendezvous (Python reference of c/src/hop.c).

Superframe (SF) = 64 slots: slot 0 beacon, slots 1..4 common (broadcast), slots 5..63 private (59 = prime).
PRF input is one 8-byte block: [tag | retry<<4][slot][node lo][node hi][epoch LE 4 bytes] -> SipHash-2-4(K_hop).
Uniform integer in [0,n) by rejection sampling on the 64-bit output (retry counter in the high nibble of byte 0).
"""
import numpy as np
from .siphash import siphash24, siphash24_u64_vec, M64

SLOTS, N_COMMON, PRIV0, N_PRIV = 64, 4, 5, 59
TAG_BEACON, TAG_COMMON, TAG_RX, TAG_LA, TAG_LB = 1, 2, 3, 4, 5
MAXRETRY = 16


def _msg(tag, retry, slot, node, epoch) -> int:
    return (tag | (retry << 4)) | (slot << 8) | (node << 16) | (epoch << 32)


def uniform(key, tag, slot, node, epoch, n) -> int:
    lim = (M64 // n) * n  # identical to C: UINT64_MAX / n * n
    v = 0
    for r in range(MAXRETRY):
        v = siphash24(key, _msg(tag, r, slot, node, epoch).to_bytes(8, "little"))
        if v < lim:
            break
    return v % n


def uniform_vec(key, tag, slot, node, epoch, n):
    """Vectorised uniform(): slot/node/epoch broadcastable arrays. Values >= lim (prob < n/2^64) fall back to scalar."""
    slot, node, epoch = np.broadcast_arrays(np.asarray(slot, dtype=np.uint64), np.asarray(node, dtype=np.uint64),
                                            np.asarray(epoch, dtype=np.uint64))
    m = np.uint64(tag) | (slot << np.uint64(8)) | (node << np.uint64(16)) | (epoch << np.uint64(32))
    v = siphash24_u64_vec(key, m)
    lim = np.uint64((M64 // n) * n)
    out = (v % np.uint64(n)).astype(np.int64)
    bad = v >= lim
    if bad.any():
        for idx in zip(*np.nonzero(bad)):
            out[idx] = uniform(key, tag, int(slot[idx]), int(node[idx]), int(epoch[idx]), n)
    return out


def beacon_channel(key, epoch, M): return uniform(key, TAG_BEACON, 0, 0, epoch, M)
def common_channel(key, epoch, c, M): return uniform(key, TAG_COMMON, 1 + c, 0, epoch, M)
def rx_channel(key, epoch, slot, node, M): return uniform(key, TAG_RX, slot, node, epoch, M)


def listen_slots(key, node, epoch, R):
    """R distinct private slots node listens in during superframe `epoch`: PRIV0 + (a + j*b) mod 59, b in 1..58."""
    a = uniform(key, TAG_LA, 0, node, epoch, N_PRIV)
    b = 1 + uniform(key, TAG_LB, 0, node, epoch, N_PRIV - 1)
    return [PRIV0 + (a + j * b) % N_PRIV for j in range(R)]


def listen_slots_vec(key, nodes, epoch, R):
    nodes = np.asarray(nodes)
    a = uniform_vec(key, TAG_LA, 0, nodes, epoch, N_PRIV)
    b = 1 + uniform_vec(key, TAG_LB, 0, nodes, epoch, N_PRIV - 1)
    return PRIV0 + (a[:, None] + np.arange(R)[None, :] * b[:, None]) % N_PRIV


def rx_channel_vec(key, epoch, slot, node, M): return uniform_vec(key, TAG_RX, slot, node, epoch, M)
