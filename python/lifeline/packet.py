"""LifeLine-Mesh frame codec (Python reference; the C implementation in c/ must agree byte for byte).
See docs/PROTOCOL.md section 4. All multi-byte fields little-endian. Max frame 32 bytes (nRF24 payload limit).

b0 = ver(7:6) | type(5:4) | class(3:2) | low2     DATA low2 = rsvd(1)=0, FRAG(0);  ACK low2 = status;  BEACON bits 3:0 = flags
DATA   : b0 | ttl<<4|life | origin | prev | next | ctr(4) | payload(0..14) | MAC4 | CRC16        (18..32 bytes)
BEACON : b0 | node | epoch(4) | cost | free | MAC4 | CRC16                                         (15 bytes)
ACK    : b0 | acker | origin | ctr(4) | MAC4 | CRC16                                              (15 bytes)
MAC = first 4 bytes (LE) of SipHash-2-4(K_mac, domain || immutable fields); CRC-16/CCITT-FALSE over everything before it.
Mutable per hop and NOT under the MAC: ttl, life, prev, next (CRC only).
"""
from .siphash import siphash24
from .crc import crc16

VER = 1
T_BEACON, T_DATA, T_ACK = 0, 1, 2
C_SOS, C_STATUS, C_BULK = 0, 1, 2
CLASS_NAMES = ("SOS", "STATUS", "BULK")
MAX_FRAME, HDR, MACLEN, CRCLEN = 32, 12, 4, 2
MAX_PAYLOAD = MAX_FRAME - HDR - MACLEN - CRCLEN  # 14
BCAST = 0xFFFF
ACK_ACCEPTED, ACK_DUPLICATE, ACK_FULL = 0, 1, 2

# decode status codes (same numbering in C)
OK, E_LEN, E_CRC, E_VER, E_TYPE, E_CLASS, E_RSVD, E_MAC, E_ARG = range(9)
STATUS_NAMES = ("OK", "E_LEN", "E_CRC", "E_VER", "E_TYPE", "E_CLASS", "E_RSVD", "E_MAC", "E_ARG")


def _mac(keys, domain: bytes, body: bytes) -> bytes:
    return siphash24(keys.mac, domain + body).to_bytes(8, "little")[:4]




def _finish(frame_wo_crc: bytes) -> bytes:
    return frame_wo_crc + crc16(frame_wo_crc).to_bytes(2, "little")


def encode_data(keys, cls, ttl, life, origin, prev, nxt, ctr, payload=b"", frag=False) -> bytes:
    if not (0 <= cls <= 2 and 0 <= ttl <= 15 and 0 <= life <= 15 and len(payload) <= MAX_PAYLOAD):
        raise ValueError("bad argument")
    b0 = (VER << 6) | (T_DATA << 4) | (cls << 2) | (1 if frag else 0)
    macbody = bytes([b0]) + origin.to_bytes(2, "little") + ctr.to_bytes(4, "little") + bytes([len(payload)]) + payload
    f = (bytes([b0, (ttl << 4) | life]) + origin.to_bytes(2, "little") + prev.to_bytes(2, "little")
         + nxt.to_bytes(2, "little") + ctr.to_bytes(4, "little") + payload + _mac(keys, b"D", macbody))
    return _finish(f)


def encode_beacon(keys, node, epoch, cost, free, flags=0) -> bytes:
    if not (0 <= flags <= 15 and 0 <= cost <= 255 and 0 <= free <= 255):
        raise ValueError("bad argument")
    b0 = (VER << 6) | (T_BEACON << 4) | flags
    body = bytes([b0]) + node.to_bytes(2, "little") + epoch.to_bytes(4, "little") + bytes([cost, free])
    return _finish(body + _mac(keys, b"B", body))


def encode_ack(keys, cls, status, acker, origin, ctr) -> bytes:
    if not (0 <= cls <= 2 and 0 <= status <= 2):
        raise ValueError("bad argument")
    b0 = (VER << 6) | (T_ACK << 4) | (cls << 2) | status
    body = bytes([b0]) + acker.to_bytes(2, "little") + origin.to_bytes(2, "little") + ctr.to_bytes(4, "little")
    return _finish(body + _mac(keys, b"A", body))


def decode(keys, buf: bytes):
    """Returns (status, fields dict or None). Check order: length, CRC, version, type, structure, MAC."""
    n = len(buf)
    if n < 15 or n > MAX_FRAME:
        return E_LEN, None
    if crc16(buf[:-2]) != int.from_bytes(buf[-2:], "little"):
        return E_CRC, None
    b0 = buf[0]
    if (b0 >> 6) != VER:
        return E_VER, None
    t = (b0 >> 4) & 3
    if t == T_DATA:
        if n < 18:
            return E_LEN, None
        cls = (b0 >> 2) & 3
        if cls > 2:
            return E_CLASS, None
        if b0 & 2:
            return E_RSVD, None
        plen = n - 18
        origin = int.from_bytes(buf[2:4], "little"); ctr = int.from_bytes(buf[8:12], "little")
        payload = bytes(buf[12:12 + plen])
        macbody = bytes([b0]) + buf[2:4] + buf[8:12] + bytes([plen]) + payload
        if _mac(keys, b"D", macbody) != bytes(buf[12 + plen:16 + plen]):
            return E_MAC, None
        return OK, dict(type=T_DATA, cls=cls, frag=bool(b0 & 1), ttl=buf[1] >> 4, life=buf[1] & 15, origin=origin,
                        prev=int.from_bytes(buf[4:6], "little"), next=int.from_bytes(buf[6:8], "little"),
                        ctr=ctr, payload=payload)
    if t == T_BEACON:
        if n != 15:
            return E_LEN, None
        if _mac(keys, b"B", bytes(buf[:9])) != bytes(buf[9:13]):
            return E_MAC, None
        return OK, dict(type=T_BEACON, flags=b0 & 15, node=int.from_bytes(buf[1:3], "little"),
                        epoch=int.from_bytes(buf[3:7], "little"), cost=buf[7], free=buf[8])
    if t == T_ACK:
        if n != 15:
            return E_LEN, None
        cls = (b0 >> 2) & 3
        if cls > 2:
            return E_CLASS, None
        if (b0 & 3) > 2:
            return E_RSVD, None
        if _mac(keys, b"A", bytes(buf[:9])) != bytes(buf[9:13]):
            return E_MAC, None
        return OK, dict(type=T_ACK, cls=cls, status=b0 & 3, acker=int.from_bytes(buf[1:3], "little"),
                        origin=int.from_bytes(buf[3:5], "little"), ctr=int.from_bytes(buf[5:9], "little"))
    return E_TYPE, None


def reencode(keys, f) -> bytes:
    """Canonical re-encoding of a decoded frame (used by round-trip / fuzz checks)."""
    if f["type"] == T_DATA:
        return encode_data(keys, f["cls"], f["ttl"], f["life"], f["origin"], f["prev"], f["next"], f["ctr"], f["payload"], f["frag"])
    if f["type"] == T_BEACON:
        return encode_beacon(keys, f["node"], f["epoch"], f["cost"], f["free"], f["flags"])
    return encode_ack(keys, f["cls"], f["status"], f["acker"], f["origin"], f["ctr"])
