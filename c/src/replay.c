#include "lifeline.h"
void ll_replay_init(ll_replay_t *r) {
    uint32_t i; r->tick = 0;
    for (i = 0; i < LL_REPLAY_CAP; i++) { r->e[i].used = 0; r->e[i].origin = 0; r->e[i].cls = 0; r->e[i].highest = 0; r->e[i].bitmap = 0; r->e[i].last_used = 0; }
}
int ll_replay_check_and_update(ll_replay_t *r, uint16_t origin, uint8_t cls, uint32_t ctr) {
    uint32_t i, found = LL_REPLAY_CAP, free_i = LL_REPLAY_CAP, lru = 0; int have_lru = 0;
    ll_rp_entry_t *e;
    r->tick++;
    for (i = 0; i < LL_REPLAY_CAP; i++) {
        if (r->e[i].used) {
            if (r->e[i].origin == origin && r->e[i].cls == cls) { found = i; break; }
            /* LRU victim: smallest last_used, ties broken by smallest (origin, cls) like the Python model */
            if (!have_lru || r->e[i].last_used < r->e[lru].last_used ||
                (r->e[i].last_used == r->e[lru].last_used &&
                 (r->e[i].origin < r->e[lru].origin || (r->e[i].origin == r->e[lru].origin && r->e[i].cls < r->e[lru].cls)))) { lru = i; have_lru = 1; }
        } else if (free_i == LL_REPLAY_CAP) free_i = i;
    }
    if (found == LL_REPLAY_CAP) {
        uint32_t slot = (free_i != LL_REPLAY_CAP) ? free_i : lru;
        e = &r->e[slot];
        e->used = 1; e->origin = origin; e->cls = cls; e->highest = ctr; e->bitmap = 1u; e->last_used = r->tick;
        return LL_RP_NEW;
    }
    e = &r->e[found]; e->last_used = r->tick;
    if (ctr > e->highest) {
        uint32_t sh = ctr - e->highest;
        e->bitmap = (sh >= 64u) ? 1u : ((e->bitmap << sh) | 1u);
        e->highest = ctr; return LL_RP_NEW;
    } else {
        uint32_t d = e->highest - ctr;
        if (d >= 64u) return LL_RP_OLD;
        if ((e->bitmap >> d) & 1u) return LL_RP_DUP;
        e->bitmap |= ((uint64_t)1u << d); return LL_RP_NEW;
    }
}
