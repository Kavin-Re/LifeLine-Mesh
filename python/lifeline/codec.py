"""Compact text codec for short emergency messages: small word dictionary + static (canonical) Huffman coding.

Pipeline:  text -> normalise (lowercase, drop chars outside the literal set, spelling variants) -> tokens
           (dictionary word | punctuation | literal word spelled char-by-char between ESC and END_LIT) -> Huffman bits
           -> END symbol -> zero-pad -> optional CRC-8 byte.
Lossy by design: case and characters outside [a-z0-9 '-/:.,!?;] are not preserved. decode(encode(t)) == canonical(t).
Profiles: "en" (English dictionary) and "en+hi" (adds Hindi in Roman transliteration; ~spelling variants mapped to one form).
The Huffman table is a pure function of (dictionary, training messages); only the code lengths define it (canonical codes).
"""
import heapq, re
from collections import Counter
from .crc import crc8

DICT_EN = """
help urgent emergency sos trapped injured hurt bleeding unconscious dead missing alive safe stranded sick fever pregnant
elderly children child baby infant woman women man men people person family patient patients survivors volunteers team
rescue rescued doctor nurse medic ambulance police army fire firefighters brigade boat helicopter bus car lift
need needs needed require send bring request requesting water food medicine medicines insulin oxygen blood bandage
first aid kit blankets blanket tents tent shelter clothes fuel diesel petrol battery batteries charger generator torch
torches radio rope ladder stretcher tools cutter tanker packets milk saline sheets airdrop
building house home school hospital clinic camp bridge road highway street lane market temple church station village
town city river canal dam hill roof floor basement ground top north south east west near behind opposite beside towards
gate jetty tunnel colony sector district crossing hall gym
flood flooded rising level collapsed collapse debris rubble landslide earthquake aftershock smoke gas leak electric
wires power blocked closed damaged unsafe danger dangerous cut off down cracks contaminated clear cleared open
is are was were have has had we i you they it at in on of to from with and or no not the a an there here this that
all some more many few please now today tonight morning evening hours hour minutes days day since until after before
still again can cannot will come coming reach reached arrived arriving moving move going left right ok okay yes thanks thank
status update report well evacuated evacuate evacuating location grid gps total number count supply supplies relief
distribution age name last seen looking searching for by via but only if when where who how which my our your
free full empty hungry thirsty cold wet heavy rain light vehicles key
0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 24 30 40 50 60 100
""".split()

DICT_HI = """
madad bachao pani khana dawai ghayal zakhmi phanse phanse hue log bachche buzurg mahila aurat aadmi aag baadh malba sadak
band jaldi yahan wahan ghar imarat doctor aspatal khoon saans bijli raasta pul gir gaya gayi gaye andar bahar paas hain hai
mein se ko ka ki ke nahi chahiye zaroorat bhejo bhej do abhi kal aaj raat subah ghante din mil mila milega sab theek
surakshit bimar bukhar garbhwati kambal tambu naav fauj raahat chhat manzil pehli doosri teesri upar neeche ped mareez
behosh gum nadi gaon kat toot bhar aa jao aao karo le pahunch pahunchao shukriya hum mera mere kya aur par tak liye
""".split()

HI_VARIANTS = {"paani": "pani", "madat": "madad", "bachaao": "bachao", "bacche": "bachche", "bachhe": "bachche", "dawa": "dawai",
               "davai": "dawai", "khaana": "khana", "aspataal": "aspatal", "hospital": "hospital", "zaruri": "zaroorat",
               "jarurat": "zaroorat", "zarurat": "zaroorat", "sadaq": "sadak", "bijlee": "bijli", "bukhaar": "bukhar",
               "ghaayal": "ghayal", "baad": "baadh", "chhath": "chhat", "chat": "chat", "kambl": "kambal", "theik": "theek"}

PUNCT = [".", ",", "!", "?", ";"]
CHARS = list("abcdefghijklmnopqrstuvwxyz0123456789'-/:.")
TOKEN_RE = re.compile(r"[a-z0-9]+(?:['\-/:.][a-z0-9]+)*|[.,!?;]")


class CodecError(ValueError):
    pass


def tokenize(text: str, variants=None):
    toks = TOKEN_RE.findall(text.lower())
    if variants:
        toks = [variants.get(t, t) for t in toks]
    return toks


def detokenize(toks):
    out = ""
    for t in toks:
        if t in PUNCT:
            out += t
        else:
            out += (" " if out else "") + t
    return out


class Codec:
    """profile: 'en' or 'en+hi'. train: iterable of messages used to set symbol frequencies (smoothed, so every symbol is codable)."""

    def __init__(self, profile="en", train=(), crc=True):
        if profile not in ("en", "en+hi"):
            raise ValueError("profile")
        self.profile, self.crc = profile, crc
        words = list(dict.fromkeys(DICT_EN + (DICT_HI if profile == "en+hi" else [])))
        self.variants = HI_VARIANTS if profile == "en+hi" else {}
        self.words = words; self.widx = {w: i for i, w in enumerate(words)}
        D = len(words)
        self.sym_word = lambda i: i
        self.S_PUNCT = D; self.S_CHAR = D + len(PUNCT); self.S_ESC = self.S_CHAR + len(CHARS)
        self.S_ENDLIT = self.S_ESC + 1; self.S_END = self.S_ENDLIT + 1; self.nsym = self.S_END + 1
        self.cidx = {c: i for i, c in enumerate(CHARS)}
        cnt = Counter()
        for m in train:
            for s in self._symbols(m): cnt[s] += 1
        freq = [cnt.get(s, 0) + (0.4 if s < D else 0.15) for s in range(self.nsym)]
        freq[self.S_END] += 0.0
        self.lengths = self._huff_lengths(freq)
        self._canon()

    # ---- tokens / symbols ----
    def canonical(self, text):
        return detokenize(tokenize(text, self.variants))

    def _symbols(self, text):
        syms = []
        for t in tokenize(text, self.variants):
            if t in self.widx: syms.append(self.widx[t])
            elif t in PUNCT: syms.append(self.S_PUNCT + PUNCT.index(t))
            else:
                syms.append(self.S_ESC); syms += [self.S_CHAR + self.cidx[c] for c in t]; syms.append(self.S_ENDLIT)
        return syms

    # ---- Huffman ----
    @staticmethod
    def _huff_lengths(freq):
        h = [(f, i, (i,)) for i, f in enumerate(freq)]; heapq.heapify(h); nid = len(freq)
        L = [0] * len(freq)
        while len(h) > 1:
            f1, _, s1 = heapq.heappop(h); f2, _, s2 = heapq.heappop(h)
            for s in s1 + s2: L[s] += 1
            heapq.heappush(h, (f1 + f2, nid, s1 + s2)); nid += 1
        return L

    def _canon(self):
        order = sorted(range(self.nsym), key=lambda s: (self.lengths[s], s))
        code, prev = 0, 0; self.code = {}; self.decode_map = {}
        for i, s in enumerate(order):
            l = self.lengths[s]
            if i: code = (code + 1) << (l - prev)
            prev = l; self.code[s] = (code, l); self.decode_map[(code, l)] = s
        self.maxlen = max(self.lengths)

    # ---- encode / decode ----
    def _bits(self, syms):
        v, n = 0, 0
        for s in syms:
            c, l = self.code[s]; v = (v << l) | c; n += l
        return v, n

    def encode_tokens(self, toks):
        syms = []
        for t in toks:
            if t in self.widx: syms.append(self.widx[t])
            elif t in PUNCT: syms.append(self.S_PUNCT + PUNCT.index(t))
            else: syms.append(self.S_ESC); syms += [self.S_CHAR + self.cidx[c] for c in t]; syms.append(self.S_ENDLIT)
        syms.append(self.S_END)
        v, n = self._bits(syms); pad = (-n) % 8
        data = (v << pad).to_bytes((n + pad) // 8, "big")
        return data + bytes([self._crc(data)]) if self.crc else data

    def _crc(self, data): return crc8(bytes([0x5A if self.profile == "en" else 0xA5]) + data)

    def encode(self, text: str) -> bytes:
        return self.encode_tokens(tokenize(text, self.variants))

    def decode_tokens(self, blob: bytes):
        data = blob
        if self.crc:
            if len(blob) < 2: raise CodecError("too short")
            data, c = blob[:-1], blob[-1]
            if self._crc(data) != c: raise CodecError("crc mismatch")
        if not data: raise CodecError("empty")
        bits = "".join(f"{b:08b}" for b in data); pos, cur, ln, toks, lit = 0, 0, 0, [], None
        while True:
            if pos >= len(bits): raise CodecError("truncated (no END symbol)")
            cur = (cur << 1) | int(bits[pos]); ln += 1; pos += 1
            s = self.decode_map.get((cur, ln))
            if s is None:
                if ln >= self.maxlen: raise CodecError("invalid code")
                continue
            cur, ln = 0, 0
            if lit is not None:
                if s == self.S_ENDLIT:
                    if not lit: raise CodecError("empty literal")
                    toks.append("".join(lit)); lit = None
                elif self.S_CHAR <= s < self.S_ESC: lit.append(CHARS[s - self.S_CHAR])
                else: raise CodecError("bad symbol inside literal")
            elif s == self.S_END: break
            elif s < len(self.words): toks.append(self.words[s])
            elif s < self.S_CHAR: toks.append(PUNCT[s - self.S_PUNCT])
            elif s == self.S_ESC: lit = []
            else: raise CodecError("unexpected symbol")
        if lit is not None: raise CodecError("unterminated literal")
        rest = bits[pos:]
        if len(rest) >= 8 or "1" in rest: raise CodecError("bad padding")
        return toks

    def decode(self, blob: bytes) -> str:
        return detokenize(self.decode_tokens(blob))

    # ---- fragmentation into link-layer payloads ----
    def encode_frames(self, text: str, capacity: int = 14):
        """Greedy split at token boundaries; every fragment is independently decodable and fits in `capacity` bytes."""
        toks, frames, cur = tokenize(text, self.variants), [], []
        for t in toks:
            if len(self.encode_tokens(cur + [t])) <= capacity: cur.append(t)
            else:
                if not cur: raise CodecError(f"token {t!r} does not fit in {capacity} bytes")
                frames.append(self.encode_tokens(cur)); cur = [t]
                if len(self.encode_tokens(cur)) > capacity: raise CodecError(f"token {t!r} does not fit in {capacity} bytes")
        frames.append(self.encode_tokens(cur))
        return frames

    def decode_frames(self, frames) -> str:
        toks = []
        for f in frames: toks += self.decode_tokens(f)
        return detokenize(toks)


# ---------------- 4-byte structured SOS record ----------------
SOS_CATEGORIES = ["trapped", "injured", "medical", "water", "food", "shelter", "fire", "flood", "collapse", "missing", "safe",
                  "hazard", "road-blocked", "transport", "supplies-offer", "other"]


def pack_sos(category: int, people: int, cell: int, flags: int = 0) -> bytes:
    """[cat(4)|people(4, 15 = 15 or more)] [cell lo] [cell hi] [flags(4)|check(4)]. `cell` = index in a pre-agreed grid
    (deployment config, e.g. 256x256 cells of 100 m). check = low 4 bits of CRC-8 over the first 3 bytes + flags."""
    if not (0 <= category < 16 and 0 <= people and 0 <= cell < 65536 and 0 <= flags < 16): raise ValueError
    b = bytes([(category << 4) | min(people, 15), cell & 255, cell >> 8])
    return b + bytes([(flags << 4) | (crc8(b + bytes([flags])) & 15)])


def unpack_sos(blob: bytes):
    if len(blob) != 4: raise CodecError("length")
    flags = blob[3] >> 4
    if (crc8(blob[:3] + bytes([flags])) & 15) != (blob[3] & 15): raise CodecError("check mismatch")
    return dict(category=blob[0] >> 4, people=blob[0] & 15, cell=blob[1] | (blob[2] << 8), flags=flags)
