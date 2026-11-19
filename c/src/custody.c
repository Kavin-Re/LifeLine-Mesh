#include <string.h>
#include "lifeline.h"

void ll_q_init(ll_queue_t *q) { memset(q, 0, sizeof *q); }

static int has_id(const ll_queue_t *q, uint16_t o, uint8_t c, uint32_t ctr) {
    uint32_t i;
    for (i = 0; i < LL_QCAP; i++)
        if (q->e[i].used && q->e[i].msg.origin == o && q->e[i].msg.cls == c && q->e[i].msg.ctr == ctr) return 1;
    return 0;
}

int ll_q_push(ll_queue_t *q, const ll_data_t *m, uint32_t expiry, uint32_t now, ll_data_t *evicted) {
    uint32_t i, slot = LL_QCAP; int did_evict = 0;
    if (expiry <= now) return LL_Q_REJ_EXPIRED;
    if (has_id(q, m->origin, m->cls, m->ctr)) return LL_Q_DUP;
    if (q->count >= LL_QCAP) {
        int v = -1;       /* victim: lowest priority class (largest cls), oldest (smallest enq) */
        for (i = 0; i < LL_QCAP; i++) {
            if (!q->e[i].used) continue;
            if (v < 0 || q->e[i].msg.cls > q->e[v].msg.cls || (q->e[i].msg.cls == q->e[v].msg.cls && q->e[i].enq < q->e[v].enq)) v = (int)i;
        }
        if (v < 0 || q->e[v].msg.cls <= m->cls) return LL_Q_REJ_FULL;
        if (evicted) *evicted = q->e[v].msg;
        q->e[v].used = 0; q->count--; slot = (uint32_t)v; did_evict = 1;
    } else {
        for (i = 0; i < LL_QCAP; i++) if (!q->e[i].used) { slot = i; break; }
    }
    if (slot >= LL_QCAP) return LL_Q_REJ_FULL;     /* unreachable; defensive */
    q->seq++;
    q->e[slot].msg = *m; q->e[slot].expiry = expiry; q->e[slot].enq = q->seq; q->e[slot].next_try = 0; q->e[slot].tries = 0; q->e[slot].used = 1;
    q->count++;
    return did_evict ? LL_Q_OK_EVICT : LL_Q_OK;
}

int ll_q_select(const ll_queue_t *q, uint32_t now) {
    int best = -1; uint32_t i;
    for (i = 0; i < LL_QCAP; i++) {
        const ll_qentry_t *x = &q->e[i];
        if (!x->used || x->next_try > now || x->expiry <= now) continue;
        if (best < 0 || x->msg.cls < q->e[best].msg.cls || (x->msg.cls == q->e[best].msg.cls && x->enq < q->e[best].enq)) best = (int)i;
    }
    return best;
}

void ll_q_defer(ll_queue_t *q, int idx, uint32_t until) {
    if (idx < 0 || idx >= (int)LL_QCAP || !q->e[idx].used) return;
    if (q->e[idx].tries < 255) q->e[idx].tries++;
    q->e[idx].next_try = until;
}
void ll_q_remove(ll_queue_t *q, int idx) {
    if (idx < 0 || idx >= (int)LL_QCAP || !q->e[idx].used) return;
    q->e[idx].used = 0; q->count--;
}
int ll_q_remove_id(ll_queue_t *q, uint16_t o, uint8_t c, uint32_t ctr) {
    uint32_t i;
    for (i = 0; i < LL_QCAP; i++)
        if (q->e[i].used && q->e[i].msg.origin == o && q->e[i].msg.cls == c && q->e[i].msg.ctr == ctr) { q->e[i].used = 0; q->count--; return 1; }
    return 0;
}
uint32_t ll_q_expire(ll_queue_t *q, uint32_t now) {
    uint32_t i, n = 0;
    for (i = 0; i < LL_QCAP; i++) if (q->e[i].used && q->e[i].expiry <= now) { q->e[i].used = 0; q->count--; n++; }
    return n;
}
