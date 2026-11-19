#include <string.h>
#include "lifeline.h"

#define LL_MAXRETRY 16u

uint64_t ll_uniform(const uint8_t key[16], uint8_t tag, uint8_t slot, uint16_t node, uint32_t epoch, uint32_t n) {
    uint8_t m[8]; uint64_t v = 0, lim; uint32_t r;
    if (n == 0) return 0;
    lim = (UINT64_MAX / n) * n;
    for (r = 0; r < LL_MAXRETRY; r++) {
        m[0] = (uint8_t)((tag & 15u) | (r << 4)); m[1] = slot; m[2] = (uint8_t)node; m[3] = (uint8_t)(node >> 8);
        m[4] = (uint8_t)epoch; m[5] = (uint8_t)(epoch >> 8); m[6] = (uint8_t)(epoch >> 16); m[7] = (uint8_t)(epoch >> 24);
        v = ll_siphash24(key, m, 8);
        if (v < lim) break;
    }
    return v % n;
}
uint32_t ll_beacon_channel(const uint8_t k[16], uint32_t e, uint32_t M) { return (uint32_t)ll_uniform(k, 1, 0, 0, e, M); }
uint32_t ll_common_channel(const uint8_t k[16], uint32_t e, uint32_t c, uint32_t M) { return (uint32_t)ll_uniform(k, 2, (uint8_t)(1u + c), 0, e, M); }
uint32_t ll_rx_channel(const uint8_t k[16], uint32_t e, uint32_t slot, uint16_t node, uint32_t M) { return (uint32_t)ll_uniform(k, 3, (uint8_t)slot, node, e, M); }

void ll_listen_slots(const uint8_t k[16], uint16_t node, uint32_t epoch, uint32_t R, uint8_t *out) {
    uint32_t a = (uint32_t)ll_uniform(k, 4, 0, node, epoch, LL_N_PRIV);
    uint32_t b = 1u + (uint32_t)ll_uniform(k, 5, 0, node, epoch, LL_N_PRIV - 1u), j;
    for (j = 0; j < R; j++) out[j] = (uint8_t)(LL_PRIV0 + (a + j * b) % LL_N_PRIV);
}

int ll_sync_accept(ll_sync_t *s, uint32_t be, uint32_t now, uint32_t tol) {
    if (s->locked) {
        uint32_t d = (be > now) ? be - now : now - be;
        if (d > tol) return 0;
    } else if (be <= s->floor_epoch) {
        return 0;      /* replayed/old beacon while searching */
    }
    s->locked = 1; s->epoch_ref = be; if (be > s->floor_epoch) s->floor_epoch = be;
    return 1;
}
