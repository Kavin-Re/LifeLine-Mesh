#include "lifeline.h"
uint16_t ll_crc16(const uint8_t *d, size_t n) {
    unsigned int c = 0xFFFFu; size_t i; int j;
    for (i = 0; i < n; i++) {
        c ^= (unsigned int)d[i] << 8;
        for (j = 0; j < 8; j++) c = ((c & 0x8000u) ? ((c << 1) ^ 0x1021u) : (c << 1)) & 0xFFFFu;
    }
    return (uint16_t)c;
}
uint8_t ll_crc8(const uint8_t *d, size_t n) {
    unsigned int c = 0; size_t i; int j;
    for (i = 0; i < n; i++) {
        c ^= d[i];
        for (j = 0; j < 8; j++) c = ((c & 0x80u) ? ((c << 1) ^ 0x07u) : (c << 1)) & 0xFFu;
    }
    return (uint8_t)c;
}
