# LifeLine-Mesh results: claims, evidence, caveats

Scope: design, simulation and a host-compilable C99 reference. No hardware, no RF, no field trial. Every number below
comes from the scripts named next to it; nothing is a field measurement. "+-" is a 95 percent t-interval over 8 seeds
(`run_sweeps.py`), so it describes seed-to-seed spread of the simulator, not real-world uncertainty.

Reproduce: `cd c && make test nomalloc san ITERS=1000000`; `cd python && python3 -m pytest -q tests`;
`python3 run_sweeps.py 8` (about 18 min on 2 cores; writes `sweep_raw.csv`, `sweep_summary.csv`);
`python3 eval_codec.py` (`codec_eval.json`); `python3 sim_resync.py` (`resync.json`).

## 1. Implementation and test evidence

| claim | evidence | result |
|---|---|---|
| C99 core builds clean, strict flags | `make` (`-std=c99 -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Werror`) | passes |
| no dynamic allocation | `make nomalloc` (no malloc/calloc/realloc/free symbols in any object) | OK |
| C agrees with Python on frames, keys, hop schedule, replay window, queue | `tools_gen_vectors.py` -> `c/tests/vec_*.txt`, replayed by `make test` (1940 main + 6000 replay + 8000 queue vectors) | 288113 checks, 0 failed |
| memory safety / UB | `make san`: unit tests plus fuzz, 2 x 1,000,000 iterations (seeds 1, 2) under ASan+UBSan | 0 violations; about 1.3 percent of random/mutated inputs decode OK, all re-encode canonically |
| CRC/MAC reject tampering | fuzz: 160k MAC rejects of 1M; re-sealed (CRC fixed) mutations accepted only when they hit the unauthenticated per-hop fields (ttl/life/prev/next) | consistent with the spec; that is a stated weakness, not a pass |
| Python tests | `pytest tests` | 26 passed (core + codec 20, simulator 6) |

Not tested: the C code on a microcontroller (sizes, timing, endianness on a big-endian host), concurrency/ISR use, the
beacon state machine beyond `ll_sync_accept` unit cases, any C implementation of the text codec (Python only).
A passing fuzz run is evidence of no crash on the inputs tried, not a proof.

## 2. Network simulation (PROTOCOL.md section 10 describes the model)

Default scenario: 36 nodes, 1 km square, random geometric graph with mean degree 8 (re-drawn until connected), one gateway
in a corner, 0.4 messages/s for 600 s (mix 10 percent SOS / 30 STATUS / 60 BULK), run to 900 s, 40 channels, 6 listen slots
per SF, queue 32, 2 percent frame loss, 8 seeds. Ratios are fraction of created messages that reached a gateway before expiry.
Flood and gossip are limited by the 4 common slots, so their numbers are for this link design, not for an ideal broadcast medium.

### 2.1 Baseline (claim: custody delivers more, with far fewer transmissions)
| protocol | delivery | median latency s | data frames per delivered msg | mean current uA |
|---|---|---|---|---|
| flooding | 0.69 +- 0.07 | 2.0 | 38 +- 4 | 69 |
| TTL gossip (p 0.3, 4 sends) | 0.78 +- 0.06 | 14.2 | 138 +- 7 | 72 |
| custody | 1.00 +- 0.00 | 1.9 | 4.0 +- 0.5 | 145 |

Custody costs about twice the mean current (it listens in 6 extra private slots per SF); per delivered message it is cheaper
because it sends about a tenth of the frames. Per-message energy is in `sweep_summary.csv` (`energy_per_deliv_J`).
Battery arithmetic, idealised: 2000 mAh / 145 uA is about 575 days, ignoring MCU wake-ups, oscillator start-up, regulator
and self-discharge, so treat it as an upper bound. Radio currents are assumed datasheet-typical values, not measured.

### 2.2 Offered load, priorities, custody occupancy (`load`, `priority_ablation`, `qcap`)
| offered msgs/s | flood | gossip | custody | custody SOS / BULK | custody queue max |
|---|---|---|---|---|---|
| 1 | 0.48 | 0.45 | 1.00 | 1.00 / 1.00 | 3.8 |
| 3 | 0.27 | 0.21 | 0.999 | 1.00 / 1.00 | 15 |
| 6 | 0.17 | 0.14 | 0.66 +- 0.08 | 1.00 / 0.45 | 32 (full) |
| 10 | 0.12 | 0.10 | 0.40 +- 0.05 | 1.00 / 0.10 | 32 (full) |

Priority ablation at 10 msgs/s (custody only): with class priority SOS delivery 0.996 +- 0.009, median latency over all
classes 33 s; with plain FIFO queues SOS delivery drops to 0.68 +- 0.02 and median latency 71 s. Total delivery is similar
(0.40 versus 0.44, FIFO slightly higher because it does not discard BULK in favour of SOS). So priority is a trade: it
sacrifices BULK to protect SOS and does not create capacity. Queue capacity 4..32 at 10 msgs/s barely changes delivery
(0.37-0.40, the bottleneck is the gateway's neighbours' 6 listen slots) but scales queue occupancy and latency: bigger buffers
buy delay, not throughput, at overload. Mean occupancy is below 0.5 frames per node at low load.

### 2.3 Node failures (`failures`; 10-50 percent of non-gateway nodes die at t = 198 s and lose their queues)
Raw delivery of custody falls 1.00 / 0.995 / 0.92 / 0.87 / 0.68 at 0 / 10 / 20 / 30 / 50 percent (wide intervals, +-0.16 to
+-0.24, because some seeds partition the graph). Restricted to messages whose origin still had a path to a gateway
(`ratio_reach`, approximate: uses the beacon cost table at creation time) custody stays at 0.99-1.00 while flooding is about 0.70
and gossip about 0.78 throughout. Interpretation: custody re-routes around dead nodes after the cost table refreshes (up to 8 SFs)
but cannot cross a partition. Messages held by a node when it dies are lost (`lost_failed`: 0-1 for custody, 12-50 for gossip,
because gossip keeps copies queued longer). Because queues are nearly empty at this load, the simulation understates the
custody-loss risk at heavy load; no replication is implemented.

### 2.4 Jamming (`jam_keyed`, `jam_fixed`; disc of 400 m radius at the centre, t = 100..500 s, J of 40 channels blocked)
| J blocked | flood | gossip | custody, keyed hop | custody, fixed channel |
|---|---|---|---|---|
| 0 | 0.69 | 0.78 | 1.00 | 1.00 |
| 10 | 0.60 | 0.74 | 1.00 | 0.73 +- 0.07 |
| 20 | 0.50 | 0.69 | 0.998 | 0.73 |
| 30 | 0.39 | 0.61 | 0.96 +- 0.03 | 0.73 |
The 'static' jammer blocks channels 0..J-1 and the fixed-channel network is placed on channel 0, i.e. the jammer knows the
static plan (a realistic assumption since a fixed plan is observable), so any J >= 1 blocks it, hence identical fixed rows.
Keyed hopping turns that into a loss of about J/40 per attempt, recovered by retries (cost: transmissions per message rise
from 4 to 17 at J = 30 and latency from 1.9 s to 4.4 s). The remaining gap at J = 30 is BULK (0.94); SOS stays 1.00 in all rows.
This does not show resistance to a jammer holding `K_hop`, a wideband jammer, or a follower jammer; none was simulated.

### 2.5 Mobility, sparse network (`mobility_sparse`, mean degree 4, not forced connected)
Fraction of mobile nodes 0 / 0.3 / 0.6: custody 0.36 / 0.70 / 0.71, flood 0.28 / 0.32 / 0.39, gossip 0.35 / 0.42 / 0.45
(intervals +-0.15 to +-0.26, 8 seeds only: the ordering custody > gossip, flood is robust, the exact values are not).
Movement lets custody carry messages across partitions (SOS 0.93-0.97 with mobility); latency median is dominated by waiting for
a path (42 s with an enormous spread). Flood/gossip transmit hundreds to thousands of frames per delivered message here because
copies spread inside partitions that never reach a gateway (numbers inflated by tiny denominators; read the trend).

### 2.6 Topologies (`topology`)
Grid 36 / line 20 / three clusters 36: custody 1.00 in all, flooding 0.82 / 0.68 / 0.55, gossip 0.89 / 0.88 / 0.57.
Line median latency 2.7 s custody versus 2.2 s flood, i.e. custody's advantage there is delivery and cost, not speed.

## 3. Beacon resync (`sim_resync.py`, `resync.json`)
Cold-start Monte Carlo (4000 trials per row; real beacon-channel hash; beacon about once per 8 SFs per neighbour; park on one
channel, re-park every 64 SFs). Locking time with no jamming: median 47 s (degree 8), 61 s (degree 3), 63 s (degree 15); p99
295 / 396 / 415 s. With 25 percent of channels jammed at the node: median 67-90 s, p99 up to 610 s. Receive charge to lock
0.25-0.5 mAh mean. Degree 15 is slower than 8 because simultaneous beacons collide. All trials locked within 20000 SFs.
Not modelled: persistence of `floor_epoch`, attacker replays, drift between beacons, slot-boundary alignment.

## 4. Text codec (`eval_codec.py`, `codec_eval.json`)
Dictionary (320 English + 106 Hindi-in-Roman words) was written before the corpus (author assertion; the repository has no
history to prove ordering). Corpus: 131 English and 40 Hindi-Roman messages, hand-written by one author, synthetic. Split: every
4th message held out (32 EN test, 99 train; combined profile 42 test, 129 train). Code lengths see only the train split.
| measure (held-out) | English profile | English+Hindi profile |
|---|---|---|
| compression vs canonical ASCII text | 2.71x (train 2.76x) | 2.64x (train 2.67x) |
| vs order-0 character Huffman (same train data, +CRC) | 1.65x better | 1.64x better |
| zlib level 9 on the same messages | 1310 B vs 399 B (zlib larger than raw text) | 1703 B vs 532 B |
| mean encoded size | 12.5 B | 12.7 B |
| fits one 14 B frame / within two | 72 percent / 100 percent | 76 percent / 100 percent |
| out-of-dictionary token rate in held-out text | 13.5 percent | 11.9 percent |
| exact round trip to canonical form | 100 percent | 100 percent |
Twenty random 75/25 splits of the English set give 2.40-2.89x (mean 2.70), so the ratio is not an artefact of one split.
Hindi subset (10 held-out): 240 B with the English profile, 124 B with the combined profile.
Error detection on held-out encodings (300 random corruptions per message): 1-bit flips 0 undetected of 9600; 2-bit 1 of 9600
(English; CRC-8 poly 0x07 guarantees 2-bit detection only up to 119 bits, and some messages are longer), 0 of 12600 on the
combined profile; 3-bit and 8-bit 0 undetected; truncation 0 of 64/84. Without the CRC byte a single flip yields a wrong accepted text 36 percent
of the time, so almost all detection comes from the CRC-8, not from the Huffman structure. Random multi-bit errors will pass
CRC-8 about 1 in 256 times in general; the figures above are measurements on 9600-12600 trials, not guarantees. The 4-byte
structured SOS record detects 31 of 32 single-bit flips (1488 of 1536 trials): bit 3 of byte 0 (low bit group of the
people count) is not covered because only 4 bits of CRC-8 are kept.
Caveats: 131 messages is small; dictionary words were chosen with the same disaster vocabulary the corpus uses, so the ratio is
optimistic for traffic in other styles (names, addresses, other languages: 12-14 percent of tokens already fall out of
dictionary at about 5 bits per character plus escape). Lossy: case and unusual characters are dropped by design. No Devanagari.

## 5. Honest limits (summary)
1. Simulator abstractions: unit-disk links, no capture/fading/hidden terminals beyond same-slot-same-channel at the receiver, perfect
   slot sync, beacons abstracted, 1 frame per message, flooding restricted to 4 common slots. Absolute delivery numbers
   depend on those choices; the ordering custody > gossip, flood is the finding, and it is partly a consequence of giving unicast
   access to 59 private slots versus 4 shared ones.
2. 8 seeds per condition, one network size (20-36 nodes), one workload shape. No scaling study beyond that.
3. Energy: assumed radio currents, no MCU/crystal/regulator model.
4. Security: unauthenticated per-hop fields, 4-byte MAC, replay-table eviction, floor-epoch loss, no confidentiality, shared key.
5. Custody stores one copy; a holder that dies loses the message.
6. No hardware, no timing of the C code on a target, no interoperability with any real radio driver.
