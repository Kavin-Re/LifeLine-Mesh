#include <string.h>
#include "lifeline.h"

static void put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24); }
static uint16_t get16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t get32(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }

static void mac4(const ll_keys_t *k, uint8_t domain, const uint8_t *body, size_t n, uint8_t out[4]) {
    uint8_t tmp[1 + 1 + 2 + 4 + 1 + LL_MAX_PAYLOAD + 8];   /* domain + body (<= 23 bytes) */
    uint64_t h; int i;
    tmp[0] = domain; memcpy(tmp + 1, body, n);
    h = ll_siphash24(k->mac, tmp, n + 1);
    for (i = 0; i < 4; i++) out[i] = (uint8_t)(h >> (8 * i));
}
static void seal_crc(uint8_t *f, size_t n_wo_crc) { put16(f + n_wo_crc, ll_crc16(f, n_wo_crc)); }

static void data_macbody(uint8_t b0, uint16_t origin, uint32_t ctr, uint8_t plen, const uint8_t *pl, uint8_t *mb, size_t *n) {
    mb[0] = b0; put16(mb + 1, origin); put32(mb + 3, ctr); mb[7] = plen;
    if (plen) memcpy(mb + 8, pl, plen);
    *n = 8u + plen;
}

int ll_encode_data(const ll_keys_t *k, const ll_data_t *d, uint8_t *out, size_t cap, size_t *outlen) {
    uint8_t b0, mb[8 + LL_MAX_PAYLOAD]; size_t mn, n;
    if (!k || !d || !out || !outlen) return LL_E_ARG;
    if (d->cls > 2 || d->ttl > 15 || d->life > 15 || d->plen > LL_MAX_PAYLOAD || d->frag > 1) return LL_E_ARG;
    n = LL_DATA_OVERHEAD + d->plen;
    if (cap < n) return LL_E_ARG;
    b0 = (uint8_t)((LL_VER << 6) | ((unsigned)LL_T_DATA << 4) | ((unsigned)d->cls << 2) | d->frag);
    out[0] = b0; out[1] = (uint8_t)((d->ttl << 4) | d->life);
    put16(out + 2, d->origin); put16(out + 4, d->prev); put16(out + 6, d->next); put32(out + 8, d->ctr);
    if (d->plen) memcpy(out + 12, d->payload, d->plen);
    data_macbody(b0, d->origin, d->ctr, d->plen, d->payload, mb, &mn);
    mac4(k, 'D', mb, mn, out + 12 + d->plen);
    seal_crc(out, n - 2);
    *outlen = n; return LL_OK;
}

int ll_encode_beacon(const ll_keys_t *k, const ll_beacon_t *b, uint8_t *out, size_t cap, size_t *outlen) {
    if (!k || !b || !out || !outlen || cap < 15 || b->flags > 15) return LL_E_ARG;
    out[0] = (uint8_t)((LL_VER << 6) | ((unsigned)LL_T_BEACON << 4) | b->flags);
    put16(out + 1, b->node); put32(out + 3, b->epoch); out[7] = b->cost; out[8] = b->free_slots;
    mac4(k, 'B', out, 9, out + 9); seal_crc(out, 13); *outlen = 15; return LL_OK;
}

int ll_encode_ack(const ll_keys_t *k, const ll_ack_t *a, uint8_t *out, size_t cap, size_t *outlen) {
    if (!k || !a || !out || !outlen || cap < 15 || a->cls > 2 || a->status > 2) return LL_E_ARG;
    out[0] = (uint8_t)((LL_VER << 6) | ((unsigned)LL_T_ACK << 4) | ((unsigned)a->cls << 2) | a->status);
    put16(out + 1, a->acker); put16(out + 3, a->origin); put32(out + 5, a->ctr);
    mac4(k, 'A', out, 9, out + 9); seal_crc(out, 13); *outlen = 15; return LL_OK;
}

int ll_encode_frame(const ll_keys_t *k, const ll_frame_t *f, uint8_t *out, size_t cap, size_t *outlen) {
    if (!f) return LL_E_ARG;
    switch (f->type) {
    case LL_T_DATA: return ll_encode_data(k, &f->data, out, cap, outlen);
    case LL_T_BEACON: return ll_encode_beacon(k, &f->beacon, out, cap, outlen);
    case LL_T_ACK: return ll_encode_ack(k, &f->ack, out, cap, outlen);
    default: return LL_E_ARG;
    }
}

static int ct_eq4(const uint8_t *a, const uint8_t *b) { return (uint8_t)((a[0] ^ b[0]) | (a[1] ^ b[1]) | (a[2] ^ b[2]) | (a[3] ^ b[3])) == 0; }

int ll_decode(const ll_keys_t *k, const uint8_t *buf, size_t n, ll_frame_t *out) {
    uint8_t b0, t, tag[4];
    if (!k || !buf || !out) return LL_E_ARG;
    if (n < LL_MIN_FRAME || n > LL_MAX_FRAME) return LL_E_LEN;
    if (ll_crc16(buf, n - 2) != get16(buf + n - 2)) return LL_E_CRC;
    b0 = buf[0];
    if ((b0 >> 6) != LL_VER) return LL_E_VER;
    t = (uint8_t)((b0 >> 4) & 3u);
    memset(out, 0, sizeof *out);
    if (t == LL_T_DATA) {
        uint8_t mb[8 + LL_MAX_PAYLOAD]; size_t mn, plen; uint8_t cls = (uint8_t)((b0 >> 2) & 3u);
        if (n < LL_DATA_OVERHEAD) return LL_E_LEN;
        if (cls > 2) return LL_E_CLASS;
        if (b0 & 2u) return LL_E_RSVD;
        plen = n - LL_DATA_OVERHEAD;
        data_macbody(b0, get16(buf + 2), get32(buf + 8), (uint8_t)plen, buf + 12, mb, &mn);
        mac4(k, 'D', mb, mn, tag);
        if (!ct_eq4(tag, buf + 12 + plen)) return LL_E_MAC;
        out->type = LL_T_DATA;
        out->data.cls = cls; out->data.frag = (uint8_t)(b0 & 1u); out->data.ttl = (uint8_t)(buf[1] >> 4); out->data.life = (uint8_t)(buf[1] & 15u);
        out->data.origin = get16(buf + 2); out->data.prev = get16(buf + 4); out->data.next = get16(buf + 6); out->data.ctr = get32(buf + 8);
        out->data.plen = (uint8_t)plen; if (plen) memcpy(out->data.payload, buf + 12, plen);
        return LL_OK;
    }
    if (t == LL_T_BEACON) {
        if (n != 15) return LL_E_LEN;
        mac4(k, 'B', buf, 9, tag);
        if (!ct_eq4(tag, buf + 9)) return LL_E_MAC;
        out->type = LL_T_BEACON; out->beacon.flags = (uint8_t)(b0 & 15u); out->beacon.node = get16(buf + 1);
        out->beacon.epoch = get32(buf + 3); out->beacon.cost = buf[7]; out->beacon.free_slots = buf[8];
        return LL_OK;
    }
    if (t == LL_T_ACK) {
        uint8_t cls = (uint8_t)((b0 >> 2) & 3u);
        if (n != 15) return LL_E_LEN;
        if (cls > 2) return LL_E_CLASS;
        if ((b0 & 3u) > 2u) return LL_E_RSVD;
        mac4(k, 'A', buf, 9, tag);
        if (!ct_eq4(tag, buf + 9)) return LL_E_MAC;
        out->type = LL_T_ACK; out->ack.cls = cls; out->ack.status = (uint8_t)(b0 & 3u); out->ack.acker = get16(buf + 1);
        out->ack.origin = get16(buf + 3); out->ack.ctr = get32(buf + 5);
        return LL_OK;
    }
    return LL_E_TYPE;
}

void ll_keys_derive(ll_keys_t *k, const uint8_t master[16]) {
    static const char *lab[2] = { "LLmac", "LLhop" };
    uint8_t *dst[2]; int l, i, j; uint8_t m[6];
    dst[0] = k->mac; dst[1] = k->hop;
    for (l = 0; l < 2; l++) {
        for (i = 0; i < 5; i++) m[i] = (uint8_t)lab[l][i];
        for (i = 0; i < 2; i++) {
            uint64_t h; m[5] = (uint8_t)i; h = ll_siphash24(master, m, 6);
            for (j = 0; j < 8; j++) dst[l][8 * i + j] = (uint8_t)(h >> (8 * j));
        }
    }
}
