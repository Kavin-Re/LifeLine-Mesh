"""SipHash-2-4 (64-bit output). Scalar version for any length, plus a numpy version for
8-byte messages (used to evaluate the keyed hop schedule for many nodes at once)."""
import numpy as np

M64 = (1 << 64) - 1


def _rotl(x, b):
    return ((x << b) | (x >> (64 - b))) & M64


def _round(v0, v1, v2, v3):
    v0 = (v0 + v1) & M64; v1 = _rotl(v1, 13); v1 ^= v0; v0 = _rotl(v0, 32)
    v2 = (v2 + v3) & M64; v3 = _rotl(v3, 16); v3 ^= v2
    v0 = (v0 + v3) & M64; v3 = _rotl(v3, 21); v3 ^= v0
    v2 = (v2 + v1) & M64; v1 = _rotl(v1, 17); v1 ^= v2; v2 = _rotl(v2, 32)
    return v0, v1, v2, v3


def siphash24(key: bytes, data: bytes) -> int:
    assert len(key) == 16
    k0 = int.from_bytes(key[:8], "little"); k1 = int.from_bytes(key[8:], "little")
    v0 = k0 ^ 0x736f6d6570736575; v1 = k1 ^ 0x646f72616e646f6d
    v2 = k0 ^ 0x6c7967656e657261; v3 = k1 ^ 0x7465646279746573
    n = len(data)
    for i in range(0, n - n % 8, 8):
        m = int.from_bytes(data[i:i + 8], "little")
        v3 ^= m
        v0, v1, v2, v3 = _round(v0, v1, v2, v3); v0, v1, v2, v3 = _round(v0, v1, v2, v3)
        v0 ^= m
    b = ((n & 0xFF) << 56) | int.from_bytes(data[n - n % 8:], "little")
    v3 ^= b
    v0, v1, v2, v3 = _round(v0, v1, v2, v3); v0, v1, v2, v3 = _round(v0, v1, v2, v3)
    v0 ^= b; v2 ^= 0xFF
    for _ in range(4):
        v0, v1, v2, v3 = _round(v0, v1, v2, v3)
    return v0 ^ v1 ^ v2 ^ v3


def _vr(v0, v1, v2, v3):
    u = np.uint64
    def rl(x, b): return (x << u(b)) | (x >> u(64 - b))
    v0 = v0 + v1; v1 = rl(v1, 13); v1 = v1 ^ v0; v0 = rl(v0, 32)
    v2 = v2 + v3; v3 = rl(v3, 16); v3 = v3 ^ v2
    v0 = v0 + v3; v3 = rl(v3, 21); v3 = v3 ^ v0
    v2 = v2 + v1; v1 = rl(v1, 17); v1 = v1 ^ v2; v2 = rl(v2, 32)
    return v0, v1, v2, v3


def siphash24_u64_vec(key: bytes, m):
    """SipHash-2-4 of 8-byte little-endian messages given as a uint64 array. Bit-exact with siphash24."""
    m = np.asarray(m, dtype=np.uint64)
    u = np.uint64
    k0 = u(int.from_bytes(key[:8], "little")); k1 = u(int.from_bytes(key[8:], "little"))
    z = np.zeros_like(m)
    v0 = z + (k0 ^ u(0x736f6d6570736575)); v1 = z + (k1 ^ u(0x646f72616e646f6d))
    v2 = z + (k0 ^ u(0x6c7967656e657261)); v3 = z + (k1 ^ u(0x7465646279746573))
    with np.errstate(over="ignore"):
        v3 = v3 ^ m
        v0, v1, v2, v3 = _vr(v0, v1, v2, v3); v0, v1, v2, v3 = _vr(v0, v1, v2, v3)
        v0 = v0 ^ m
        b = u(8 << 56)
        v3 = v3 ^ b
        v0, v1, v2, v3 = _vr(v0, v1, v2, v3); v0, v1, v2, v3 = _vr(v0, v1, v2, v3)
        v0 = v0 ^ b; v2 = v2 ^ u(0xFF)
        for _ in range(4):
            v0, v1, v2, v3 = _vr(v0, v1, v2, v3)
    return v0 ^ v1 ^ v2 ^ v3
