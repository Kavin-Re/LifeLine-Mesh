"""CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no xorout). check('123456789') = 0x29B1.
CRC-8 (poly 0x07, init 0) is the same one used by the FHSS-Link serial protocol; used by the text codec."""

def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def crc8(data: bytes, poly: int = 0x07) -> int:
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ poly) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c
