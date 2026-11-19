/* LifeLine-Mesh reference core. Portable C99, no dynamic allocation, no libc beyond <stdint.h>/<stddef.h>/<string.h>.
 * Not field-validated; host-compilable reference of docs/PROTOCOL.md. */
#ifndef LIFELINE_H
#define LIFELINE_H
#include <stddef.h>
#include <stdint.h>

#define LL_VER          1u
#define LL_MAX_FRAME    32u
#define LL_MIN_FRAME    15u
#define LL_DATA_OVERHEAD 18u                 /* 12 header + 4 MAC + 2 CRC */
#define LL_MAX_PAYLOAD  (LL_MAX_FRAME - LL_DATA_OVERHEAD)   /* 14 */
#define LL_BCAST        0xFFFFu

enum { LL_T_BEACON = 0, LL_T_DATA = 1, LL_T_ACK = 2 };
enum { LL_C_SOS = 0, LL_C_STATUS = 1, LL_C_BULK = 2 };
enum { LL_ACK_ACCEPTED = 0, LL_ACK_DUPLICATE = 1, LL_ACK_FULL = 2 };
enum { LL_OK = 0, LL_E_LEN, LL_E_CRC, LL_E_VER, LL_E_TYPE, LL_E_CLASS, LL_E_RSVD, LL_E_MAC, LL_E_ARG };

/* ---- SipHash-2-4, CRC, keys ---- */
uint64_t ll_siphash24(const uint8_t key[16], const uint8_t *in, size_t len);
uint16_t ll_crc16(const uint8_t *data, size_t len);      /* CRC-16/CCITT-FALSE */
uint8_t  ll_crc8(const uint8_t *data, size_t len);       /* poly 0x07 */

typedef struct { uint8_t mac[16]; uint8_t hop[16]; } ll_keys_t;
void ll_keys_derive(ll_keys_t *k, const uint8_t master[16]);

/* ---- frames ---- */
typedef struct {
    uint8_t cls, frag, ttl, life;
    uint16_t origin, prev, next;
    uint32_t ctr;
    uint8_t plen;
    uint8_t payload[LL_MAX_PAYLOAD];
} ll_data_t;
typedef struct { uint8_t flags; uint16_t node; uint32_t epoch; uint8_t cost, free_slots; } ll_beacon_t;
typedef struct { uint8_t cls, status; uint16_t acker, origin; uint32_t ctr; } ll_ack_t;
typedef struct { uint8_t type; ll_data_t data; ll_beacon_t beacon; ll_ack_t ack; } ll_frame_t;

int ll_encode_data(const ll_keys_t *k, const ll_data_t *d, uint8_t *out, size_t cap, size_t *outlen);
int ll_encode_beacon(const ll_keys_t *k, const ll_beacon_t *b, uint8_t *out, size_t cap, size_t *outlen);
int ll_encode_ack(const ll_keys_t *k, const ll_ack_t *a, uint8_t *out, size_t cap, size_t *outlen);
int ll_decode(const ll_keys_t *k, const uint8_t *buf, size_t len, ll_frame_t *out);
int ll_encode_frame(const ll_keys_t *k, const ll_frame_t *f, uint8_t *out, size_t cap, size_t *outlen);

/* ---- keyed hop schedule (superframe = 64 slots: 0 beacon, 1..4 common, 5..63 private) ---- */
#define LL_SLOTS 64u
#define LL_N_COMMON 4u
#define LL_PRIV0 5u
#define LL_N_PRIV 59u
uint64_t ll_uniform(const uint8_t key[16], uint8_t tag, uint8_t slot, uint16_t node, uint32_t epoch, uint32_t n);
uint32_t ll_beacon_channel(const uint8_t hopkey[16], uint32_t epoch, uint32_t M);
uint32_t ll_common_channel(const uint8_t hopkey[16], uint32_t epoch, uint32_t c, uint32_t M);
uint32_t ll_rx_channel(const uint8_t hopkey[16], uint32_t epoch, uint32_t slot, uint16_t node, uint32_t M);
void     ll_listen_slots(const uint8_t hopkey[16], uint16_t node, uint32_t epoch, uint32_t R, uint8_t *out);

/* ---- beacon acceptance / resync (anti-replay of time) ---- */
typedef struct { uint32_t epoch_ref; uint32_t floor_epoch; uint8_t locked; } ll_sync_t;
/* now_epoch: our local epoch estimate (if locked). Returns 1 and updates state if the beacon is acceptable. */
int ll_sync_accept(ll_sync_t *s, uint32_t beacon_epoch, uint32_t now_epoch, uint32_t tolerance);

/* ---- replay window ---- */
#define LL_REPLAY_CAP 64u
enum { LL_RP_NEW = 0, LL_RP_DUP = 1, LL_RP_OLD = 2 };
typedef struct { uint16_t origin; uint8_t cls; uint8_t used; uint32_t highest; uint64_t bitmap; uint32_t last_used; } ll_rp_entry_t;
typedef struct { ll_rp_entry_t e[LL_REPLAY_CAP]; uint32_t tick; } ll_replay_t;
void ll_replay_init(ll_replay_t *r);
int  ll_replay_check_and_update(ll_replay_t *r, uint16_t origin, uint8_t cls, uint32_t ctr);   /* call only after MAC verified */

/* ---- custody queue ---- */
#ifndef LL_QCAP
#define LL_QCAP 32u
#endif
enum { LL_Q_OK = 0, LL_Q_OK_EVICT, LL_Q_DUP, LL_Q_REJ_FULL, LL_Q_REJ_EXPIRED };
typedef struct {
    ll_data_t msg; uint32_t expiry, enq, next_try; uint8_t tries, used;
} ll_qentry_t;
typedef struct { ll_qentry_t e[LL_QCAP]; uint32_t seq, count; } ll_queue_t;
void ll_q_init(ll_queue_t *q);
int  ll_q_push(ll_queue_t *q, const ll_data_t *m, uint32_t expiry, uint32_t now, ll_data_t *evicted);
int  ll_q_select(const ll_queue_t *q, uint32_t now);                 /* index or -1 */
void ll_q_defer(ll_queue_t *q, int idx, uint32_t until);
void ll_q_remove(ll_queue_t *q, int idx);
int  ll_q_remove_id(ll_queue_t *q, uint16_t origin, uint8_t cls, uint32_t ctr);   /* 1 if removed (custody ACK received) */
uint32_t ll_q_expire(ll_queue_t *q, uint32_t now);
#endif
