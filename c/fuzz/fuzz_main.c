/* Fuzz / robustness harness for the LifeLine-Mesh C core (random + mutated frames, random queue/replay ops).
 * Standalone deterministic driver:  fuzz_main [iterations] [seed]
 * Build with -fsanitize=address,undefined to turn memory errors / UB into failures.
 * Also exports LLVMFuzzerTestOneInput when compiled with -DLL_LIBFUZZER (clang -fsanitize=fuzzer). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lifeline.h"

static uint64_t s_state = 88172645463325252ULL;
static uint32_t rnd(void) { s_state ^= s_state << 13; s_state ^= s_state >> 7; s_state ^= s_state << 17; return (uint32_t)(s_state >> 11); }
static uint32_t rn(uint32_t n) { return n ? rnd() % n : 0; }

static ll_keys_t K;
static unsigned long n_ok, n_rej[9], n_resealed_ok, n_resealed_total, n_bad;
#define BAD(msg) do { n_bad++; if (n_bad < 20) printf("INVARIANT VIOLATED: %s (line %d)\n", msg, __LINE__); } while (0)

static void reseal(uint8_t *b, size_t n) { if (n >= 3) { uint16_t c = ll_crc16(b, n - 2); b[n - 2] = (uint8_t)c; b[n - 1] = (uint8_t)(c >> 8); } }

/* Invariant 1: decode never crashes; if it returns OK the frame re-encodes to the identical bytes (canonical form). */
static int check_decode(const uint8_t *buf, size_t n) {
    ll_frame_t f; int st = ll_decode(&K, buf, n, &f);
    if (st < 0 || st > LL_E_ARG) BAD("status out of range"); else n_rej[st]++;
    if (st == LL_OK) {
        uint8_t re[LL_MAX_FRAME + 8]; size_t rl = 0; n_ok++;
        if (ll_encode_frame(&K, &f, re, sizeof re, &rl) != LL_OK || rl != n || memcmp(re, buf, n)) BAD("re-encode mismatch");
        if (f.type == LL_T_DATA && f.data.plen > LL_MAX_PAYLOAD) BAD("plen > max");
    }
    return st;
}

#ifdef LL_LIBFUZZER
int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n) {
    static int init = 0; if (!init) { uint8_t m[16] = {1}; ll_keys_derive(&K, m); init = 1; }
    (void)check_decode(d, n > 64 ? 64 : n); return 0;
}
#else
static void valid_frame(uint8_t *b, size_t *n) {
    ll_data_t d; ll_beacon_t bc; ll_ack_t a; uint32_t t = rn(3), i; memset(&d, 0, sizeof d);
    if (t == 0) {
        d.cls = (uint8_t)rn(3); d.ttl = (uint8_t)rn(16); d.life = (uint8_t)rn(16); d.origin = (uint16_t)rnd(); d.prev = (uint16_t)rnd(); d.next = (uint16_t)rnd(); d.ctr = rnd(); d.frag = (uint8_t)rn(2);
        d.plen = (uint8_t)rn(LL_MAX_PAYLOAD + 1); for (i = 0; i < d.plen; i++) d.payload[i] = (uint8_t)rnd();
        (void)ll_encode_data(&K, &d, b, LL_MAX_FRAME, n);
    } else if (t == 1) {
        bc.flags = (uint8_t)rn(16); bc.node = (uint16_t)rnd(); bc.epoch = rnd(); bc.cost = (uint8_t)rnd(); bc.free_slots = (uint8_t)rnd();
        (void)ll_encode_beacon(&K, &bc, b, LL_MAX_FRAME, n);
    } else {
        a.cls = (uint8_t)rn(3); a.status = (uint8_t)rn(3); a.acker = (uint16_t)rnd(); a.origin = (uint16_t)rnd(); a.ctr = rnd();
        (void)ll_encode_ack(&K, &a, b, LL_MAX_FRAME, n);
    }
}

int main(int argc, char **argv) {
    unsigned long iters = argc > 1 ? strtoul(argv[1], 0, 10) : 1000000UL, it;
    static ll_replay_t rp; static ll_queue_t q; uint8_t master[16]; uint32_t now = 1000, ctr = 0, i;
    if (argc > 2) s_state ^= strtoull(argv[2], 0, 10) * 0x9E3779B97F4A7C15ULL;
    for (i = 0; i < 16; i++) master[i] = (uint8_t)(i * 13 + 5);
    ll_keys_derive(&K, master); ll_replay_init(&rp); ll_q_init(&q);
    for (it = 0; it < iters; it++) {
        uint8_t b[LL_MAX_FRAME + 16]; size_t n = 0; uint32_t mode = rn(6);
        if (mode == 0) {                       /* pure random bytes, random length 0..40 */
            n = rn(41); for (i = 0; i < n; i++) b[i] = (uint8_t)rnd(); check_decode(b, n);
        } else if (mode == 1) {                /* random bytes with a valid CRC (reaches structural + MAC checks) */
            n = 15 + rn(18); for (i = 0; i < n; i++) b[i] = (uint8_t)rnd(); b[0] = (uint8_t)((b[0] & 0x3F) | 0x40); reseal(b, n); check_decode(b, n);
        } else if (mode == 2) {                /* valid frame, bit flips / truncation / extension, CRC left broken */
            valid_frame(b, &n); if (n == 0) { BAD("valid_frame failed"); continue; }
            for (i = 0; i < 1 + rn(4); i++) b[rn((uint32_t)n)] ^= (uint8_t)(1u << rn(8));
            if (rn(3) == 0) n = rn((uint32_t)n + 1); else if (rn(3) == 0 && n < LL_MAX_FRAME + 8) { b[n] = (uint8_t)rnd(); n++; }
            check_decode(b, n);
        } else if (mode == 3) {                /* valid frame, mutate, re-seal CRC: must fail unless only mutable DATA bytes changed */
            uint8_t o[LL_MAX_FRAME]; size_t pos; int st, only_mutable;
            valid_frame(b, &n); memcpy(o, b, n);
            pos = rn((uint32_t)n - 2); b[pos] ^= (uint8_t)(1u + rn(255)); reseal(b, n);
            st = check_decode(b, n); n_resealed_total++;
            only_mutable = ((b[0] >> 4 & 3) == LL_T_DATA && (b[0] == o[0]) && (pos == 1 || (pos >= 4 && pos <= 7)));
            if (st == LL_OK) { n_resealed_ok++; if (!only_mutable) BAD("immutable-field tamper accepted (MAC bypass)"); }
        } else if (mode == 4) {                /* untampered frame: must decode OK and feed replay/queue */
            ll_frame_t f; valid_frame(b, &n);
            if (ll_decode(&K, b, n, &f) != LL_OK) BAD("valid frame rejected");
            else if (f.type == LL_T_DATA) {
                int r = ll_replay_check_and_update(&rp, f.data.origin, f.data.cls, f.data.ctr); (void)r;
                (void)ll_q_push(&q, &f.data, now + rn(500) + 1, now, NULL);
            }
        } else {                               /* random queue operations */
            uint32_t k = rn(5); now += rn(30);
            if (k == 0) { ll_data_t m; memset(&m, 0, sizeof m); m.cls = (uint8_t)rn(3); m.origin = (uint16_t)rn(8); m.ctr = ++ctr; (void)ll_q_push(&q, &m, now + rn(300), now, NULL); }
            else if (k == 1) { int idx = ll_q_select(&q, now); if (idx >= 0) { if (!q.e[idx].used || q.e[idx].expiry <= now || q.e[idx].next_try > now) BAD("select returned ineligible"); ll_q_defer(&q, idx, now + rn(40)); } }
            else if (k == 2) { int idx = ll_q_select(&q, now); if (idx >= 0) ll_q_remove(&q, idx); }
            else if (k == 3) (void)ll_q_expire(&q, now);
            else { ll_q_remove(&q, (int)rn(LL_QCAP + 3) - 1); (void)ll_q_remove_id(&q, (uint16_t)rn(8), (uint8_t)rn(3), rn(ctr + 2)); }
            { uint32_t c = 0; for (i = 0; i < LL_QCAP; i++) c += q.e[i].used; if (c != q.count || c > LL_QCAP) BAD("queue count inconsistent"); }
        }
    }
    printf("fuzz iterations=%lu decoded_ok=%lu  rejects: len=%lu crc=%lu ver=%lu type=%lu class=%lu rsvd=%lu mac=%lu arg=%lu\n",
           iters, n_ok, n_rej[1], n_rej[2], n_rej[3], n_rej[4], n_rej[5], n_rej[6], n_rej[7], n_rej[8]);
    printf("re-sealed mutations: %lu, accepted: %lu (all in mutable header fields), invariant violations: %lu\n", n_resealed_total, n_resealed_ok, n_bad);
    return n_bad ? 1 : 0;
}
#endif
