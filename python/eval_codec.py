"""Codec evaluation on the held-out split.  Usage: python3 eval_codec.py [outdir=../results]  -> codec_eval.json + stdout"""
import json, os, random, sys, zlib, heapq
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lifeline.codec import Codec, CodecError, tokenize, pack_sos, unpack_sos
from lifeline.corpus import EN, HI, split_train_test

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
res = {}


def char_huff_bytes(train, test):
    """Baseline: order-0 Huffman over characters (smoothed), trained on the same train split, +END, +CRC-8 byte."""
    cnt = Counter("".join(train)); alpha = sorted(set("".join(train + test)) | {"\0"})
    h = [(cnt.get(c, 0) + 0.5, i, (c,)) for i, c in enumerate(alpha)]; heapq.heapify(h); L = Counter(); nid = len(h)
    while len(h) > 1:
        a = heapq.heappop(h); b = heapq.heappop(h)
        for c in a[2] + b[2]: L[c] += 1
        heapq.heappush(h, (a[0] + b[0], nid, a[2] + b[2])); nid += 1
    return [(-(-(sum(L[c] for c in m.lower()) + L["\0"]) // 8)) + 1 for m in test]


def evaluate(name, codec, train, test, hold_msgs):
    raw = [len(codec.canonical(m).encode()) for m in test]
    enc = [len(codec.encode(m)) for m in test]
    toks = [t for m in test for t in tokenize(m, codec.variants)]
    oov = sum(1 for t in toks if t not in codec.widx and t not in ".,!?;") / len(toks)
    r = dict(n_train=len(train), n_test=len(test), raw_bytes=sum(raw), codec_bytes=sum(enc), ratio=sum(raw) / sum(enc),
             mean_codec_bytes=sum(enc) / len(enc), oov_token_rate_test=oov,
             single_frame_14B=sum(e <= 14 for e in enc) / len(enc), within_2_frames=sum(e <= 28 for e in enc) / len(enc),
             exact_roundtrip=sum(codec.decode(codec.encode(m)) == codec.canonical(m) for m in test) / len(test))
    ch = char_huff_bytes(train, test); r["char_huffman_bytes"] = sum(ch); r["ratio_vs_char_huffman"] = sum(ch) / sum(enc)
    z = [len(zlib.compress(codec.canonical(m).encode(), 9)) for m in test]; r["zlib_bytes"] = sum(z)
    r["train_ratio"] = (sum(len(codec.canonical(m).encode()) for m in train) / sum(len(codec.encode(m)) for m in train))
    # error detection on held-out encodings (decode must raise, or yield different text = undetected)
    rng = random.Random(11); det = {}
    for k in (1, 2, 3, 8):
        n = und = 0
        for m in test:
            b = codec.encode(m); ref = codec.canonical(m)
            for _ in range(300):
                g = bytearray(b)
                for p in rng.sample(range(len(g) * 8), min(k, len(g) * 8)): g[p // 8] ^= 1 << (p % 8)
                n += 1
                try:
                    if codec.decode(bytes(g)) != ref: und += 1        # accepted but wrong text
                except CodecError: pass
        det[f"{k}_bit_flips"] = dict(trials=n, undetected=und, rate=und / n)
    n = und = 0
    for m in test:                                                      # truncation by 1..2 bytes
        b = codec.encode(m)
        for cut in (1, 2):
            if len(b) > cut:
                n += 1
                try: und += codec.decode(b[:-cut]) != codec.canonical(m)
                except CodecError: pass
    det["truncation"] = dict(trials=n, undetected=und, rate=und / max(1, n))
    r["error_detection"] = det
    # same, with the CRC-8 turned OFF, to show how much of the detection is the CRC rather than the Huffman structure
    nc = Codec(codec.profile, train, crc=False); n = und = 0
    for m in test:
        b = nc.encode(m); ref = nc.canonical(m)
        for _ in range(300):
            g = bytearray(b); p = rng.randrange(len(g) * 8); g[p // 8] ^= 1 << (p % 8); n += 1
            try: und += nc.decode(bytes(g)) != ref
            except CodecError: pass
    r["no_crc_single_flip_undetected_rate"] = und / n
    res[name] = r


tr, te = split_train_test(EN); evaluate("en_profile_on_EN", Codec("en", tr), tr, te, EN)
tr2, te2 = split_train_test(EN + HI); evaluate("en+hi_profile_on_EN+HI", Codec("en+hi", tr2), tr2, te2, EN + HI)
c_en_only = Codec("en", split_train_test(EN + HI)[0]); hi_te = [m for m in te2 if m in set(HI)]
res["hindi_subset"] = dict(n=len(hi_te), en_profile_bytes=sum(len(c_en_only.encode(m)) for m in hi_te),
                           enhi_profile_bytes=sum(len(Codec("en+hi", tr2).encode(m)) for m in hi_te))
# sensitivity: shuffle-split 20 times (different 25% hold-outs) to show the ratio is not an artefact of one split
rs = []
for s in range(20):
    rng = random.Random(s); idx = list(range(len(EN))); rng.shuffle(idx); k = len(EN) // 4
    te_ = [EN[i] for i in idx[:k]]; tr_ = [EN[i] for i in idx[k:]]; c = Codec("en", tr_)
    rs.append(sum(len(c.canonical(m).encode()) for m in te_) / sum(len(c.encode(m)) for m in te_))
res["en_random_split_ratio"] = dict(mean=sum(rs) / 20, min=min(rs), max=max(rs))
# SOS record: single-bit detection over all codes of a sample
n = und = 0
for cat in range(16):
    for ppl in (0, 3, 15):
        b = pack_sos(cat, ppl, 40000, 5)
        for p in range(32):
            g = bytearray(b); g[p // 8] ^= 1 << (p % 8); n += 1
            try: unpack_sos(bytes(g)); und += 1
            except CodecError: pass
res["sos_record_4B"] = dict(single_flip_trials=n, undetected=und)
os.makedirs(out, exist_ok=True)
json.dump(res, open(os.path.join(out, "codec_eval.json"), "w"), indent=1)
print(json.dumps(res, indent=1))
