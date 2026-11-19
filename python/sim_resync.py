"""Cold-start beacon acquisition Monte Carlo (PROTOCOL.md 5.3).  A node with no usable epoch parks its receiver on one
channel and re-parks on a random channel every REPARK superframes; it locks when a beacon is transmitted alone (no other
beacon in the same beacon slot), on the parked channel (beacon channel = real keyed hash of the epoch), not lost.
Usage: python3 sim_resync.py [outdir=../results] -> resync.json"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lifeline import hopsched as H
from lifeline.keys import derive_keys
from lifeline.sim import SF_S, V, I_RX

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
M, REPARK, TRIALS, MAXSF = 40, 64, 4000, 20000
hk = derive_keys(bytes(range(16))).hop
bc = H.uniform_vec(hk, H.TAG_BEACON, 0, 0, np.arange(MAXSF + 10000), M)        # real beacon channel per epoch
rng = np.random.default_rng(5); res = {}
for deg in (3, 8, 15):
    for p_jam_ch in (0.0, 0.25):                  # fraction of the 40 channels jammed at the node's location
        times = []
        for t in range(TRIALS):
            e0 = int(rng.integers(0, 10000)); park = int(rng.integers(0, M)); jam = rng.random(M) < p_jam_ch; k = 0
            nb = rng.binomial(deg, 1 / 8, MAXSF)                              # neighbours beaconing in each SF
            while k < MAXSF:
                if k % REPARK == 0: park = int(rng.integers(0, M))
                if bc[e0 + k] == park and nb[k] == 1 and not jam[park] and rng.random() > 0.02: break
                k += 1
            times.append(k + 1 if k < MAXSF else np.nan)
        x = np.array(times) * SF_S
        res[f"deg{deg}_jamfrac{p_jam_ch}"] = dict(locked=float(np.mean(~np.isnan(x))), mean_s=float(np.nanmean(x)),
            median_s=float(np.nanmedian(x)), p95_s=float(np.nanpercentile(x, 95)), p99_s=float(np.nanpercentile(x, 99)),
            mean_rx_charge_mAh=float(np.nanmean(x) * I_RX * 1e3 / 3600))
os.makedirs(out, exist_ok=True); json.dump(res, open(os.path.join(out, "resync.json"), "w"), indent=1); print(json.dumps(res, indent=1))
