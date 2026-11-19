# LifeLine-Mesh protocol specification, version 1 (design reference)

Status: design plus host-compilable C reference plus simulation. There is no hardware, no RF measurement and no field
validation behind any statement here. Radio and energy numbers are stated assumptions (section 9), not measurements.
Normative sources: this file; `python/lifeline/*.py` (executable model) and `c/src/*.c` (C99 reference) agree byte for byte
on frames (tested by shared vectors, section 11).

## 1. Goals and non-goals

Goal: short text and status messages between people with phones or small nodes when infrastructure is down, over
a multi-hop ad hoc network of cheap 2.4 GHz packet radios (nRF24-class: 32-byte payload limit, 40 usable 2 MHz-spaced
channels assumed). SOS traffic must get through first, nodes may disappear, messages must survive disconnection.
Non-goals: voice, images, confidentiality (messages are authenticated, not encrypted), routing across partitions that
never heal, protection against an adversary who holds the network key.

## 2. Notation and constants

All multi-byte fields little-endian. `M` = number of channels (40 assumed). Superframe (SF) = 64 slots of 10 ms = 0.64 s.
Epoch = SF counter (uint32), carried in beacons. Network master key `K` (16 random bytes, provisioned out of band)
derives `K_mac` and `K_hop` (keys.py: SipHash-2-4 PRF with labels `LLmac`, `LLhop`; SipHash is a PRF, not a password KDF,
so `K` must be uniformly random).

## 3. Message classes, priority, lifetime

| class | code | priority | default life code | lifetime |
|---|---|---|---|---|
| SOS | 0 | highest | 15 | about 1730 s |
| STATUS | 1 | middle | 11 | about 346 s |
| BULK | 2 | lowest | 8 | about 102 s |

Life code `L` (4 bits, in the header) means a lifetime of `4 * 1.5^L` seconds counted from creation, measured by each
holder in its own SF ticks; `life` is a field of the frame, but the holder converts it to an absolute expiry when it
accepts custody, so lifetime is not extended by relaying. Hop limit `ttl` (4 bits, 0..15) is decremented per
hand-off; a frame with ttl 0 is not forwarded (still delivered if the receiver is a gateway).
Priority rules: transmit order is class then arrival order; on a full queue the eviction rule of
section 7 applies; SOS is never evicted by lower classes.

## 4. Frames

Max frame 32 bytes. `b0 = ver(7:6) | type(5:4) | class(3:2) | low2`. ver = 1. type: 0 BEACON, 1 DATA, 2 ACK.

```
DATA   (18..32 B): b0 | ttl<<4 | life | origin(2) | prev(2) | next(2) | ctr(4) | payload(0..14) | MAC4 | CRC16
BEACON (15 B)    : b0(flags in 3:0) | node(2) | epoch(4) | cost | free_slots | MAC4 | CRC16
ACK    (15 B)    : b0(class, status in 1:0) | acker(2) | origin(2) | ctr(4) | MAC4 | CRC16
```
DATA low2 = reserved(bit 1, must be 0) and FRAG (bit 0, set when the payload is one fragment of a multi-frame message; reassembly is left to the application and is not simulated).
ACK status: 0 ACCEPTED (custody taken), 1 DUPLICATE (already held or seen), 2 FULL (refused, retry later).

MAC: first 4 bytes of SipHash-2-4(`K_mac`, domain || immutable fields) with domain byte `D`/`B`/`A`.
For DATA the MAC input is `b0 | origin | ctr | payload_len | payload`. The fields that change per hop
(`ttl`, `life`, `prev`, `next`) are NOT under the MAC, only under the CRC. Consequence (accepted, section 12): an on-path
attacker without the key cannot forge or alter payload, class, origin or counter, but can rewrite ttl/prev/next of a captured
frame (for example to stop it propagating); a 32-bit MAC gives 2^-32 forgery probability per attempt and is the size the
32-byte budget allows. CRC-16/CCITT-FALSE covers the whole frame before it. Decode order: length, CRC, version, type,
structure (class 3 and reserved bit rejected), MAC. Decode never reads outside the buffer (fuzzed, section 11).

## 5. Link layer: keyed hopping, slots, rendezvous, beacons

### 5.1 Superframe layout
64 slots: slot 0 beacon; slots 1..4 common (broadcast); slots 5..63 private (59 slots, prime).

### 5.2 Hop schedule
`uniform(K_hop, tag, slot, node, epoch, n)` = SipHash-2-4 of the 8-byte block
`[tag | retry<<4][slot][node lo][node hi][epoch LE4]`, rejection-sampled to remove modulo bias (up to 16 retries).
- beacon channel for epoch e: `uniform(tag 1, slot 0, node 0, e, M)`
- common slot c (1..4) channel: `uniform(tag 2, slot c, node 0, e, M)`
- receive channel of node n in slot s: `uniform(tag 3, s, n, e, M)`
- listen slots: node n listens in `R` private slots `5 + (a + j*b) mod 59`, j = 0..R-1, with `a = uniform(tag 4, ..., 59)`,
  `b = 1 + uniform(tag 5, ..., 58)`; because 59 is prime the R slots are distinct for R <= 59.
Every node can compute any other node's listen slots and channels (same key). A sender picks one of the receiver's R
slots (random, not already used by itself), tunes to `rx_channel(slot, receiver)` and transmits; the receiver is already
there. The link ACK is sent in slot+1 on `rx_channel(slot+1, sender)` (the sender listens there). A node transmitting
cannot receive in the same slot (half duplex).
Why: a jammer without `K_hop` cannot predict the channel of a slot, so a narrowband or sweep jammer hits a transmission with
probability about J/M (J channels blocked), not 1; a fixed-channel network is blocked completely if the jammer covers
its channel (compare in simulation, results.md). What it does NOT do: protect against a jammer that holds `K_hop`, against
a wideband jammer covering all M channels, or against a jammer that senses and follows within a 10 ms slot.

### 5.3 Beacons, time, resync
Each node transmits a beacon about once per 8 SFs (random), in slot 0 on the beacon channel of the current epoch.
It carries the sender's epoch, `cost` (hops to nearest gateway, 255 = none) and `free_slots` (queue space).
Locked node acceptance (`ll_sync_accept`): accept a beacon only if `|beacon_epoch - local_epoch| <= tolerance`; this prevents
a replayed or far-future beacon from moving a locked node's clock. Unlocked node: accept only beacons with epoch greater
than a persisted `floor_epoch` (monotonic, stored in non-volatile memory), so a recorded old beacon is rejected.
Cold start (no usable epoch): the beacon channel cannot be computed, so the node parks its receiver on one channel and
re-parks on a random channel every 64 SFs until a beacon lands there (Monte Carlo, results.md: median about 1 minute,
p99 about 5-10 minutes, tens of microamp-hours). Known weakness: a node that lost its `floor_epoch` can be set back by
an attacker replaying a recorded valid beacon; mitigation (not implemented): require two beacons from different node
ids with epochs within tolerance.
Clock drift: with 20 ppm crystals the offset grows by about 13 us per SF; each beacon heard resets it. Slot guard time is
a hardware parameter outside the scope of this reference.

## 6. Counters, anti-replay, duplicate suppression

Each origin keeps a 32-bit counter per class, incremented per new message (persisted across reboot: a node must not
reuse a counter, so it stores `ctr + 2^k` ahead; implementation detail left to the target). Message identity =
(origin, class, ctr). Every receiver keeps, per (origin, class), a sliding window of 64 counters (highest seen plus a 64-bit
bitmap): `NEW` (higher, or within window and unseen), `DUP` (seen), `OLD` (more than 63 behind the highest). The
check runs only after the MAC verifies. The table has fixed capacity (64 entries); when full the least recently updated
entry is evicted. Known weakness (tested, `test_eviction_weakness_documented`): an evicted origin's old frames can be
accepted again, which causes duplicates, not forgery; custody keeps duplicates cheap because the receiver answers
DUPLICATE and the sender drops its copy. A frame refused with FULL must not be remembered as seen (the simulator
rolls back the window bit so it can be accepted on retry).

## 7. Store-and-forward and custody transfer

Fixed-capacity queue (`LL_QCAP` = 32 entries, one frame each). Rules (queue.py = custody.c):
1. push of an expired message is rejected; an id already stored is `DUP`.
2. free slot: stored.
3. full: if the lowest-priority stored class is strictly lower than the new message, evict the oldest entry of that class
   (new message stored, result OK_EVICT), else reject FULL.
4. select(now): best-class, oldest, entry that is not deferred and not expired.
Custody: a holder transmits to a next hop and keeps its copy until it receives an ACK with status ACCEPTED or DUPLICATE
matching (origin, class, ctr); then it deletes its copy (responsibility moves on). ACK FULL, or no ACK (frame or ACK lost,
or neighbour dead): exponential backoff `min(2^tries, 16)` SFs and retry, possibly with a different neighbour after 2 tries.
Lost-ACK case produces a harmless duplicate that is answered DUPLICATE. Gateways (sinks) accept everything and hand it to
the application; they do not forward. Expired entries are dropped. Custody is lost, by design, if a holder fails while
holding (counted in simulation as `lost_failed`); there is no replication.
Next hop: among neighbours (from beacons) with `cost < own cost`, the lowest cost (random tie-break); no such neighbour:
hold and wait (store-carry-forward; mobility or repair may create one). Cost is a hop count computed from beacons by
distance-vector relaxation (simulated by BFS refreshed every 8 SFs, so failures are noticed with delay).

## 8. Application layer

### 8.1 Text codec (codec.py)
Hand-written word dictionary (320 English and 106 Hindi-in-Roman words, fixed before the corpus was written),
static canonical Huffman code over {dictionary words, punctuation, literal characters, ESC, END-LIT, END}, trailing CRC-8.
Out-of-dictionary words are spelled with ESC ... END-LIT. Lossy normalisation: lowercase, characters outside
`[a-z0-9 '-/:.,!?;]` dropped, known spelling variants merged: `decode(encode(t)) == canonical(t)`. The code lengths depend on
the training split only through symbol frequencies (smoothed so every symbol is codable). Fragmentation: greedy split at
token boundaries into independently decodable chunks of at most 14 bytes (`encode_frames`).
### 8.2 Structured SOS record (4 bytes)
`[category(4)|people(4)] [cell lo] [cell hi] [flags(4)|check(4)]`, cell = index in a pre-agreed grid, check = low 4 bits of
CRC-8 over the first three bytes and flags. 14 payload bytes hold a record plus 10 bytes of text.

## 9. Energy budget (model, not measurement)

Assumed nRF24L01+-class values (recalled datasheet-typical, unverified here): 3.0 V; 11.3 mA TX at 0 dBm; 13.5 mA RX; 5 uA sleep including an
MCU in deep sleep; 32 B TX burst 0.33 ms including settling; 15 B 0.20 ms; empty RX listen window 0.6 ms.
Per superframe a custody node opens `R + 4 + 1 = 11` listen windows (R = 6): 11 x 0.6 ms x 13.5 mA = 89 mA-ms per SF, about 139 uA
average, plus sleep, plus 1/8 beacon, plus 0.33 ms TX + one ACK window per sent frame and one 0.20 ms ACK TX per received frame.
Flood/gossip nodes need only the 5 common/beacon windows. Flood/gossip idle is about 63 uA of RX average. results.md gives the simulated means (about 70 uA flood/gossip versus
about 145 uA custody including traffic) and battery-life arithmetic; it ignores MCU wake-up cost, oscillator start-up, regulator quiescent current and self-discharge, all of
which matter on real boards.

## 10. Simulator model and limits (python/lifeline/sim.py)

Superframe-level time step; within an SF every transmission is resolved per slot with the real keyed hash functions,
real `CustodyQueue`, real `ReplayTable`. Unit-disk connectivity (no fading, no capture effect, no hidden-terminal
modelling beyond same-slot-same-channel interference at the receiver), p_loss = 2 percent per frame for residual
fading, perfect slot synchronisation once locked, beacon content abstracted (cost table refreshed every 8 SFs, failed
nodes noticed with that lag). One frame per message. Failure = a random fraction of non-gateway nodes dies at a time and
loses its queue. Jammer = disc, window in time, J of M channels blocked per slot ('static' set, which a fixed-channel
network is assumed to sit inside, or 'random' per slot). Mobility = random waypoint on a subset of nodes. Flooding and
gossip use the 4 common slots only (that is what the link layer provides for broadcast), so their limited capacity is
a property of the design, not a strawman parameter; both share queue capacity, duplicate suppression and per-node
transmit budget (2 frames per SF) with custody. See results.md for caveats.

## 11. Verification map

| item | check |
|---|---|
| C99 core: no dynamic allocation | `make nomalloc` (no allocator symbols in objects), C99 `-Wall -Wextra -Wpedantic -Wshadow -Wconversion -Werror` |
| Python = C on frames, queue, replay | `c/tests/vec_*.txt` generated by `python/tools_gen_vectors.py`, replayed by `make test` |
| SipHash-2-4 official vectors, CRC, MAC tamper | `tests/test_core.py`, `c/tests/test_main.c` |
| robustness | `make san` (ASan+UBSan unit tests and fuzz); fuzz invariants: decode never crashes, OK implies canonical re-encode |
| simulator sanity | `tests/test_sim.py` |
| codec | `tests/test_codec.py`, `eval_codec.py` |

## 12. Threat model and known weaknesses

Forgery of payload/class/origin/counter needs the key (2^-32 per try). Replay: counters plus window, beacon floor.
Weaknesses: ttl/prev/next unauthenticated; 4-byte MAC; replay-table eviction; floor-epoch loss; a keyholder or
wideband jammer defeats hopping; no confidentiality; traffic analysis (origin ids are in clear); a captured node leaks the
network key (no per-node keys or revocation).
