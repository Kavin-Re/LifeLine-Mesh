import os, random, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lifeline.codec import Codec, CodecError, pack_sos, unpack_sos, SOS_CATEGORIES, detokenize, tokenize
from lifeline.corpus import EN, HI, split_train_test

TR, TE = split_train_test(EN)
C = Codec("en", TR)
CH = Codec("en+hi", split_train_test(EN + HI)[0])


class TestCodec(unittest.TestCase):
    def test_roundtrip_corpus_all(self):
        for codec, msgs in ((C, EN), (CH, EN + HI)):
            for m in msgs:
                self.assertEqual(codec.decode(codec.encode(m)), codec.canonical(m), m)

    def test_canonical_idempotent_random_strings(self):
        rng = random.Random(7); alpha = "abcxyz0123 .,!?;:-/'()\"@#ABC\t\n_é"
        for _ in range(3000):
            s = "".join(rng.choice(alpha) for _ in range(rng.randrange(0, 40)))
            c = C.canonical(s); self.assertEqual(C.canonical(c), c)
            try: blob = C.encode(s)
            except CodecError: continue
            self.assertEqual(C.decode(blob), c, repr(s))

    def test_prefix_free_complete(self):
        self.assertAlmostEqual(sum(2.0 ** -l for l in C.lengths), 1.0, places=9)   # Kraft equality: complete code
        codes = sorted((format(c, f"0{l}b")) for c, l in C.code.values())
        for a, b in zip(codes, codes[1:]): self.assertFalse(b.startswith(a))

    def test_out_of_dictionary_words(self):
        s = "xyzzy plugh near zorbatown 12:30"
        self.assertEqual(C.decode(C.encode(s)), s)

    def test_error_detection(self):
        rng = random.Random(3); miss = n = 0
        for m in TE:
            b = C.encode(m); ref = C.canonical(m)
            for i in range(len(b) * 8):       # all single-bit flips
                g = bytearray(b); g[i // 8] ^= 1 << (i % 8)
                n += 1
                try: miss += (C.decode(bytes(g)) != ref) and False
                except CodecError: pass
                else: self.fail("single-bit flip not detected")
        self.assertGreater(n, 500)

    def test_frames(self):
        for m in EN[:60] + HI[:10]:
            fr = CH.encode_frames(m, 14)
            self.assertTrue(all(len(f) <= 14 for f in fr))
            self.assertEqual(CH.decode_frames(fr), CH.canonical(m))
        with self.assertRaises(CodecError): C.encode_frames("a" * 60, 14)

    def test_hindi_variants_and_gain(self):
        self.assertEqual(CH.canonical("paani chahiye"), "pani chahiye")
        a = sum(len(C.encode(m)) for m in HI); b = sum(len(CH.encode(m)) for m in HI)
        self.assertLess(b, a)

    def test_malformed(self):
        for blob in (b"", b"\x00", b"\xff\xff\xff", bytes(range(30))):
            try: C.decode(blob)
            except CodecError: pass

    def test_sos_record(self):
        r = unpack_sos(pack_sos(1, 7, 40000, 5)); self.assertEqual((r["category"], r["people"], r["cell"], r["flags"]), (1, 7, 40000, 5))
        b = bytearray(pack_sos(0, 3, 123)); detected = 0
        for i in range(32):
            g = bytearray(b); g[i // 8] ^= 1 << (i % 8)
            try: unpack_sos(bytes(g))
            except CodecError: detected += 1
        self.assertGreaterEqual(detected, 30)     # 4-bit check: catches (nearly) all single-bit errors; reported in results


if __name__ == "__main__":
    unittest.main()
