/* Host unit tests + cross-implementation vector replay for the LifeLine-Mesh C reference.
 * Usage: test_main <vector_dir>      (vector files produced by python/tools_gen_vectors.py) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lifeline.h"

static int g_fail = 0, g_checks = 0;
#define CHECK(c) do { g_checks++; if (!(c)) { g_fail++; if (g_fail < 30) printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #c); } } while (0)

static int hexval(char c) { return (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10 : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : -1; }
static size_t unhex(const char *s, uint8_t *out, size_t cap) {   /* "-" = empty */
    size_t n = 0;
    if (s[0] == '-' && s[1] == 0) return 0;
    while (s[0] && s[1] && n < cap) { out[n++] = (uint8_t)(hexval(s[0]) * 16 + hexval(s[1])); s += 2; }
    return n;
}

static void test_known_answers(void) {
    uint8_t key[16], msg[16]; int i; ll_keys_t K; uint8_t master[16];
    for (i = 0; i < 16; i++) key[i] = (uint8_t)i;
    for (i = 0; i < 16; i++) msg[i] = (uint8_t)i;
    CHECK(ll_siphash24(key, msg, 0) == 0x726fdb47dd0e0e31ULL);       /* official SipHash-2-4 vectors */
    CHECK(ll_siphash24(key, msg, 15) == 0xa129ca6149be45e5ULL);
    CHECK(ll_crc16((const uint8_t *)"123456789", 9) == 0x29B1);
    CHECK(ll_crc8((const uint8_t *)"123456789", 9) == 0xF4);
    memset(master, 7, 16); ll_keys_derive(&K, master);
    CHECK(memcmp(K.mac, K.hop, 16) != 0);
}

static void test_frames(void) {
    ll_keys_t K; uint8_t master[16], buf[LL_MAX_FRAME], bad[LL_MAX_FRAME]; size_t n, i; ll_data_t d; ll_frame_t f; int b;
    memset(master, 3, 16); ll_keys_derive(&K, master);
    memset(&d, 0, sizeof d); d.cls = LL_C_SOS; d.ttl = 15; d.life = 9; d.origin = 0x1234; d.prev = 5; d.next = LL_BCAST; d.ctr = 0xDEADBEEFu; d.plen = 14;
    for (i = 0; i < 14; i++) d.payload[i] = (uint8_t)(0xA0 + i);
    CHECK(ll_encode_data(&K, &d, buf, sizeof buf, &n) == LL_OK && n == 32);
    CHECK(ll_decode(&K, buf, n, &f) == LL_OK && f.type == LL_T_DATA && f.data.ctr == 0xDEADBEEFu && f.data.plen == 14 && f.data.origin == 0x1234);
    /* every single-bit flip is rejected (CRC-16 detects all single-bit errors) */
    for (i = 0; i < n * 8; i++) { memcpy(bad, buf, n); bad[i / 8] ^= (uint8_t)(1u << (i % 8)); CHECK(ll_decode(&K, bad, n, &f) != LL_OK); }
    /* re-sealed CRC after flipping an immutable byte -> MAC failure; mutable bytes (1,4..7) -> still OK (documented) */
    for (b = 0; b < (int)n - 2; b++) {
        int mutable_byte = (b == 1 || (b >= 4 && b <= 7)); uint16_t c; int r;
        memcpy(bad, buf, n); bad[b] ^= 0x10; c = ll_crc16(bad, n - 2); bad[n - 2] = (uint8_t)c; bad[n - 1] = (uint8_t)(c >> 8);
        r = ll_decode(&K, bad, n, &f);
        if (mutable_byte) CHECK(r == LL_OK); else CHECK(r != LL_OK);
    }
    /* wrong key */
    { ll_keys_t K2; uint8_t m2[16]; memset(m2, 4, 16); ll_keys_derive(&K2, m2); CHECK(ll_decode(&K2, buf, n, &f) == LL_E_MAC); }
    /* length handling */
    CHECK(ll_decode(&K, buf, 14, &f) == LL_E_LEN); CHECK(ll_decode(&K, buf, 33, &f) == LL_E_LEN); CHECK(ll_decode(&K, buf, 0, &f) == LL_E_LEN);
    d.plen = 15; CHECK(ll_encode_data(&K, &d, buf, sizeof buf, &n) == LL_E_ARG);
    d.plen = 0; CHECK(ll_encode_data(&K, &d, buf, sizeof buf, &n) == LL_OK && n == 18);
    CHECK(ll_encode_data(&K, &d, buf, 10, &n) == LL_E_ARG);
    { ll_beacon_t bc; ll_ack_t a; memset(&bc, 0, sizeof bc); bc.node = 9; bc.epoch = 0xFFFFFFFFu; bc.cost = 3; bc.free_slots = 17; bc.flags = 5;
      CHECK(ll_encode_beacon(&K, &bc, buf, sizeof buf, &n) == LL_OK && n == 15);
      CHECK(ll_decode(&K, buf, n, &f) == LL_OK && f.type == LL_T_BEACON && f.beacon.epoch == 0xFFFFFFFFu && f.beacon.free_slots == 17);
      memset(&a, 0, sizeof a); a.cls = 1; a.status = LL_ACK_DUPLICATE; a.acker = 7; a.origin = 8; a.ctr = 99;
      CHECK(ll_encode_ack(&K, &a, buf, sizeof buf, &n) == LL_OK && n == 15);
      CHECK(ll_decode(&K, buf, n, &f) == LL_OK && f.type == LL_T_ACK && f.ack.ctr == 99 && f.ack.status == LL_ACK_DUPLICATE); }
}

static void test_replay(void) {
    ll_replay_t r; uint32_t i; static uint8_t seen[3][4096]; uint32_t hi[3] = {0, 0, 0}; int init[3] = {0, 0, 0}; uint32_t s = 12345;
    ll_replay_init(&r);
    CHECK(ll_replay_check_and_update(&r, 1, 0, 100) == LL_RP_NEW);
    CHECK(ll_replay_check_and_update(&r, 1, 0, 100) == LL_RP_DUP);
    CHECK(ll_replay_check_and_update(&r, 1, 0, 99) == LL_RP_NEW);       /* out of order inside window */
    CHECK(ll_replay_check_and_update(&r, 1, 0, 99) == LL_RP_DUP);
    CHECK(ll_replay_check_and_update(&r, 1, 1, 100) == LL_RP_NEW);       /* classes have independent windows */
    CHECK(ll_replay_check_and_update(&r, 1, 0, 164) == LL_RP_NEW);
    CHECK(ll_replay_check_and_update(&r, 1, 0, 100) == LL_RP_OLD);       /* 164-100 = 64 -> outside window */
    CHECK(ll_replay_check_and_update(&r, 1, 0, 101) == LL_RP_NEW);
    /* oracle comparison on 3 keys with counters < 4096 (no eviction possible) */
    ll_replay_init(&r);
    for (i = 0; i < 200000; i++) {
        uint32_t k, ctr; int exp, got;
        s = s * 1664525u + 1013904223u; k = (s >> 24) % 3u;
        s = s * 1664525u + 1013904223u; ctr = init[k] ? (hi[k] + ((s >> 16) % 90u)) - 40u : (s >> 16) % 4000u;
        if (ctr >= 4096u) continue;
        if (!init[k]) exp = LL_RP_NEW;
        else if (ctr > hi[k]) exp = LL_RP_NEW;
        else if (hi[k] - ctr >= 64u) exp = LL_RP_OLD;
        else exp = seen[k][ctr] ? LL_RP_DUP : LL_RP_NEW;
        got = ll_replay_check_and_update(&r, (uint16_t)(k + 1), (uint8_t)k, ctr);
        CHECK(got == exp);
        if (!init[k] || ctr > hi[k]) { init[k] = 1; hi[k] = ctr; }
        if (exp == LL_RP_NEW) seen[k][ctr] = 1;
    }
}

static ll_data_t mk(uint8_t cls, uint16_t o, uint32_t ctr) { ll_data_t m; memset(&m, 0, sizeof m); m.cls = cls; m.origin = o; m.ctr = ctr; return m; }

static void test_queue(void) {
    static ll_queue_t q; uint32_t i; ll_data_t m, ev; int idx;
    ll_q_init(&q);
    m = mk(LL_C_BULK, 1, 1); CHECK(ll_q_push(&q, &m, 100, 0, NULL) == LL_Q_OK);
    CHECK(ll_q_push(&q, &m, 100, 0, NULL) == LL_Q_DUP);
    m = mk(LL_C_SOS, 1, 2); CHECK(ll_q_push(&q, &m, 100, 0, NULL) == LL_Q_OK);
    m = mk(LL_C_STATUS, 1, 3); CHECK(ll_q_push(&q, &m, 100, 0, NULL) == LL_Q_OK);
    idx = ll_q_select(&q, 1); CHECK(idx >= 0 && q.e[idx].msg.cls == LL_C_SOS);
    ll_q_defer(&q, idx, 50); idx = ll_q_select(&q, 1); CHECK(idx >= 0 && q.e[idx].msg.cls == LL_C_STATUS);   /* SOS deferred */
    idx = ll_q_select(&q, 60); CHECK(idx >= 0 && q.e[idx].msg.cls == LL_C_SOS);
    CHECK(ll_q_remove_id(&q, 1, LL_C_SOS, 2) == 1 && ll_q_remove_id(&q, 1, LL_C_SOS, 2) == 0);
    m = mk(LL_C_SOS, 2, 1); CHECK(ll_q_push(&q, &m, 5, 10, NULL) == LL_Q_REJ_EXPIRED);
    CHECK(ll_q_expire(&q, 100) == 2 && q.count == 0);
    /* fill with BULK, then SOS evicts the oldest BULK; BULK cannot evict anything */
    ll_q_init(&q);
    for (i = 0; i < LL_QCAP; i++) { m = mk(LL_C_BULK, 3, i + 1); CHECK(ll_q_push(&q, &m, 1000, 0, NULL) == LL_Q_OK); }
    m = mk(LL_C_BULK, 3, 999); CHECK(ll_q_push(&q, &m, 1000, 0, NULL) == LL_Q_REJ_FULL);
    m = mk(LL_C_SOS, 4, 1); CHECK(ll_q_push(&q, &m, 1000, 0, &ev) == LL_Q_OK_EVICT && ev.ctr == 1 && ev.cls == LL_C_BULK);
    CHECK(q.count == LL_QCAP);
    for (i = 0; i < LL_QCAP; i++) { m = mk(LL_C_SOS, 5, i + 1); (void)ll_q_push(&q, &m, 1000, 0, NULL); }
    m = mk(LL_C_SOS, 6, 1); CHECK(ll_q_push(&q, &m, 1000, 0, NULL) == LL_Q_REJ_FULL);   /* all SOS: no eviction among equals */
}

static void test_hop(void) {
    uint8_t k[16], sl[8]; uint32_t cnt[40], e, i, M = 40; int j, bad = 0;
    for (i = 0; i < 16; i++) k[i] = (uint8_t)(i * 7 + 1);
    memset(cnt, 0, sizeof cnt);
    for (e = 0; e < 40000; e++) cnt[ll_beacon_channel(k, e, M)]++;
    for (i = 0; i < M; i++) if (cnt[i] < 800 || cnt[i] > 1200) bad++;      /* mean 1000, sd ~31 */
    CHECK(bad == 0);
    for (e = 0; e < 5000; e++) {
        ll_listen_slots(k, (uint16_t)(e % 300), e, 8, sl);
        for (j = 0; j < 8; j++) { int jj; CHECK(sl[j] >= LL_PRIV0 && sl[j] < LL_SLOTS); for (jj = 0; jj < j; jj++) CHECK(sl[jj] != sl[j]); }
    }
}

static void test_sync(void) {
    ll_sync_t s; memset(&s, 0, sizeof s); s.floor_epoch = 1000;
    CHECK(ll_sync_accept(&s, 900, 0, 2) == 0);          /* searching: replayed old beacon rejected */
    CHECK(ll_sync_accept(&s, 1001, 0, 2) == 1 && s.locked);
    CHECK(ll_sync_accept(&s, 5000, 1002, 2) == 0);      /* locked: far-future beacon rejected (no clock hijack) */
    CHECK(ll_sync_accept(&s, 1003, 1002, 2) == 1);
    CHECK(ll_sync_accept(&s, 990, 1003, 2) == 0);       /* locked: stale beacon rejected */
}

/* ---------- vector replay ---------- */
static int run_vec_main(const char *path) {
    FILE *fp = fopen(path, "r"); char line[1024]; int n = 0;
    if (!fp) { printf("cannot open %s\n", path); return 1; }
    while (fgets(line, sizeof line, fp)) {
        char *tok[16]; int nt = 0; char *p = strtok(line, " \r\n");
        while (p && nt < 16) { tok[nt++] = p; p = strtok(NULL, " \r\n"); }
        if (nt == 0) continue;
        n++;
        if (!strcmp(tok[0], "SIP")) {
            uint8_t k[16], m[128], exp[8]; size_t ml; uint64_t want = 0; int i;
            unhex(tok[1], k, 16); ml = unhex(tok[2], m, sizeof m); unhex(tok[3], exp, 8);
            for (i = 0; i < 8; i++) want = (want << 8) | exp[i];
            CHECK(ll_siphash24(k, m, ml) == want);
        } else if (!strcmp(tok[0], "CRC16") || !strcmp(tok[0], "CRC8")) {
            uint8_t m[128], e[2]; size_t ml = unhex(tok[1], m, sizeof m);
            unhex(tok[2], e, 2);
            if (tok[0][3] == '1') CHECK(ll_crc16(m, ml) == (uint16_t)((e[0] << 8) | e[1])); else CHECK(ll_crc8(m, ml) == e[0]);
        } else if (!strcmp(tok[0], "KEY")) {
            uint8_t m[16], a[16], b[16]; ll_keys_t K; unhex(tok[1], m, 16); unhex(tok[2], a, 16); unhex(tok[3], b, 16);
            ll_keys_derive(&K, m); CHECK(!memcmp(K.mac, a, 16) && !memcmp(K.hop, b, 16));
        } else if (!strcmp(tok[0], "ENCD")) {
            uint8_t m[16], want[40], got[40]; ll_keys_t K; ll_data_t d; size_t gl, wl;
            unhex(tok[1], m, 16); ll_keys_derive(&K, m); memset(&d, 0, sizeof d);
            d.cls = (uint8_t)atoi(tok[2]); d.ttl = (uint8_t)atoi(tok[3]); d.life = (uint8_t)atoi(tok[4]);
            d.origin = (uint16_t)strtoul(tok[5], 0, 10); d.prev = (uint16_t)strtoul(tok[6], 0, 10); d.next = (uint16_t)strtoul(tok[7], 0, 10);
            d.ctr = (uint32_t)strtoul(tok[8], 0, 10); d.frag = (uint8_t)atoi(tok[9]); d.plen = (uint8_t)unhex(tok[10], d.payload, 14);
            wl = unhex(tok[11], want, 40);
            CHECK(ll_encode_data(&K, &d, got, sizeof got, &gl) == LL_OK && gl == wl && !memcmp(got, want, wl));
        } else if (!strcmp(tok[0], "ENCB")) {
            uint8_t m[16], want[40], got[40]; ll_keys_t K; ll_beacon_t b; size_t gl, wl;
            unhex(tok[1], m, 16); ll_keys_derive(&K, m);
            b.flags = (uint8_t)atoi(tok[2]); b.node = (uint16_t)strtoul(tok[3], 0, 10); b.epoch = (uint32_t)strtoul(tok[4], 0, 10); b.cost = (uint8_t)atoi(tok[5]); b.free_slots = (uint8_t)atoi(tok[6]);
            wl = unhex(tok[7], want, 40);
            CHECK(ll_encode_beacon(&K, &b, got, sizeof got, &gl) == LL_OK && gl == wl && !memcmp(got, want, wl));
        } else if (!strcmp(tok[0], "ENCA")) {
            uint8_t m[16], want[40], got[40]; ll_keys_t K; ll_ack_t a; size_t gl, wl;
            unhex(tok[1], m, 16); ll_keys_derive(&K, m);
            a.cls = (uint8_t)atoi(tok[2]); a.status = (uint8_t)atoi(tok[3]); a.acker = (uint16_t)strtoul(tok[4], 0, 10); a.origin = (uint16_t)strtoul(tok[5], 0, 10); a.ctr = (uint32_t)strtoul(tok[6], 0, 10);
            wl = unhex(tok[7], want, 40);
            CHECK(ll_encode_ack(&K, &a, got, sizeof got, &gl) == LL_OK && gl == wl && !memcmp(got, want, wl));
        } else if (!strcmp(tok[0], "DEC")) {
            uint8_t m[16], buf[64]; ll_keys_t K; ll_frame_t f; size_t bl; int st, want;
            unhex(tok[1], m, 16); ll_keys_derive(&K, m); bl = unhex(tok[2], buf, sizeof buf); want = atoi(tok[3]);
            st = ll_decode(&K, buf, bl, &f);
            CHECK(st == want);
            if (st == LL_OK) { uint8_t re[40]; size_t rl; CHECK(ll_encode_frame(&K, &f, re, sizeof re, &rl) == LL_OK && rl == bl && !memcmp(re, buf, bl)); }
        } else if (!strcmp(tok[0], "HOPB") || !strcmp(tok[0], "HOPC") || !strcmp(tok[0], "HOPR")) {
            uint8_t k[16]; uint32_t e, M, got, want; unhex(tok[1], k, 16); e = (uint32_t)strtoul(tok[2], 0, 10);
            if (tok[0][3] == 'B') { M = (uint32_t)atoi(tok[3]); want = (uint32_t)atoi(tok[4]); got = ll_beacon_channel(k, e, M); }
            else if (tok[0][3] == 'C') { M = (uint32_t)atoi(tok[4]); want = (uint32_t)atoi(tok[5]); got = ll_common_channel(k, e, (uint32_t)atoi(tok[3]), M); }
            else { M = (uint32_t)atoi(tok[5]); want = (uint32_t)atoi(tok[6]); got = ll_rx_channel(k, e, (uint32_t)atoi(tok[3]), (uint16_t)atoi(tok[4]), M); }
            CHECK(got == want);
        } else if (!strcmp(tok[0], "LST")) {
            uint8_t k[16], out[8]; uint32_t R, e, j; uint16_t node; char *q;
            unhex(tok[1], k, 16); node = (uint16_t)atoi(tok[2]); e = (uint32_t)strtoul(tok[3], 0, 10); R = (uint32_t)atoi(tok[4]);
            ll_listen_slots(k, node, e, R, out); q = tok[5];
            for (j = 0; j < R; j++) { CHECK(out[j] == (uint8_t)strtoul(q, &q, 10)); if (*q == ',') q++; }
        }
    }
    fclose(fp); return n;
}

static int run_vec_replay(const char *path) {
    FILE *fp = fopen(path, "r"); static ll_replay_t r; unsigned o, c; unsigned long ctr; int res, n = 0; char tag[8];
    if (!fp) { printf("cannot open %s\n", path); return 1; }
    ll_replay_init(&r);
    while (fscanf(fp, "%7s %u %u %lu %d", tag, &o, &c, &ctr, &res) == 5) { n++; CHECK(ll_replay_check_and_update(&r, (uint16_t)o, (uint8_t)c, (uint32_t)ctr) == res); }
    fclose(fp); return n;
}

static int run_vec_queue(const char *path) {
    FILE *fp = fopen(path, "r"); static ll_queue_t q; char line[256]; int n = 0;
    if (!fp) { printf("cannot open %s\n", path); return 1; }
    ll_q_init(&q);
    while (fgets(line, sizeof line, fp)) {
        char op[16]; n++;
        if (sscanf(line, "%15s", op) != 1) continue;
        if (!strcmp(op, "PUSH")) {
            unsigned cls, o; unsigned long ctr, exp, now; int st; char evs[64]; ll_data_t m, ev; int got;
            if (sscanf(line, "%*s %u %u %lu %lu %lu %d %63s", &cls, &o, &ctr, &exp, &now, &st, evs) != 7) { CHECK(0); continue; }
            memset(&m, 0, sizeof m); memset(&ev, 0, sizeof ev); m.cls = (uint8_t)cls; m.origin = (uint16_t)o; m.ctr = (uint32_t)ctr;
            got = ll_q_push(&q, &m, (uint32_t)exp, (uint32_t)now, &ev); CHECK(got == st);
            if (st == LL_Q_OK_EVICT) { unsigned eo, ec; unsigned long ek; if (sscanf(evs, "%u,%u,%lu", &eo, &ec, &ek) == 3) CHECK(ev.origin == eo && ev.cls == ec && ev.ctr == ek); }
        } else if (!strcmp(op, "SELDEF") || !strcmp(op, "SELREM")) {
            unsigned long now, until = 0; char ids[64]; int idx; int isdef = (op[3] == 'D');
            if (isdef) { if (sscanf(line, "%*s %lu %lu %63s", &now, &until, ids) != 3) { CHECK(0); continue; } }
            else if (sscanf(line, "%*s %lu %63s", &now, ids) != 2) { CHECK(0); continue; }
            idx = ll_q_select(&q, (uint32_t)now);
            if (ids[0] == '-') CHECK(idx < 0);
            else {
                unsigned o, c; unsigned long k; sscanf(ids, "%u,%u,%lu", &o, &c, &k);
                CHECK(idx >= 0 && q.e[idx].msg.origin == o && q.e[idx].msg.cls == c && q.e[idx].msg.ctr == k);
                if (idx >= 0) { if (isdef) ll_q_defer(&q, idx, (uint32_t)until); else ll_q_remove(&q, idx); }
            }
        } else if (!strcmp(op, "REMID")) {
            unsigned o, c; unsigned long k; int want;
            if (sscanf(line, "%*s %u %u %lu %d", &o, &c, &k, &want) != 4) { CHECK(0); continue; }
            CHECK(ll_q_remove_id(&q, (uint16_t)o, (uint8_t)c, (uint32_t)k) == want);
        } else if (!strcmp(op, "EXP")) {
            unsigned long now; int want; if (sscanf(line, "%*s %lu %d", &now, &want) != 2) { CHECK(0); continue; }
            CHECK((int)ll_q_expire(&q, (uint32_t)now) == want);
        } else if (!strcmp(op, "CNT")) {
            int want; if (sscanf(line, "%*s %d", &want) != 1) { CHECK(0); continue; }
            CHECK((int)q.count == want);
        }
    }
    fclose(fp); return n;
}

int main(int argc, char **argv) {
    char p[512]; const char *dir = argc > 1 ? argv[1] : "tests"; int a, b, c;
    test_known_answers(); test_frames(); test_replay(); test_queue(); test_hop(); test_sync();
    snprintf(p, sizeof p, "%s/vec_main.txt", dir); a = run_vec_main(p);
    snprintf(p, sizeof p, "%s/vec_replay.txt", dir); b = run_vec_replay(p);
    snprintf(p, sizeof p, "%s/vec_queue.txt", dir); c = run_vec_queue(p);
    printf("vectors replayed: main=%d replay=%d queue=%d\n", a, b, c);
    printf("%d checks, %d failed\n", g_checks, g_fail);
    return g_fail ? 1 : 0;
}
