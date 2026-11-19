"""Key derivation. Master (16 random bytes) -> K_mac, K_hop, each 16 bytes, via SipHash-2-4 used as a PRF with domain
separation: K = SipHash(master, label || 0x00) || SipHash(master, label || 0x01), each half as 8 little-endian bytes.
SipHash is a PRF/MAC, not a password-stretching KDF: the master must be uniformly random."""
from collections import namedtuple
from .siphash import siphash24

Keys = namedtuple("Keys", "mac hop")


def _expand(master: bytes, label: bytes) -> bytes:
    return b"".join(siphash24(master, label + bytes([i])).to_bytes(8, "little") for i in (0, 1))


def derive_keys(master: bytes) -> Keys:
    assert len(master) == 16
    return Keys(mac=_expand(master, b"LLmac"), hop=_expand(master, b"LLhop"))
