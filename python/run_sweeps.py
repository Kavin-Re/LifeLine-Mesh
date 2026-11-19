"""Parameter sweeps for the LifeLine-Mesh simulator.  Usage: python3 run_sweeps.py [seeds=8] [outdir=../results]
Writes sweep_raw.csv (one row per run) and sweep_summary.csv (mean and 95% t-interval over seeds, per condition)."""
import csv, itertools, os, sys, time
from multiprocessing import Pool
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lifeline.sim import Cfg, run

PROTOS = ("flood", "gossip", "custody")
JAM = lambda J: ((500, 500, 400, 100.0, 500.0, J, "static"),)      # centre jammer, 400 m radius, t = 100..500 s
T975 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23, 11: 2.20, 12: 2.18,
        15: 2.13, 19: 2.09, 29: 2.05}


def tcrit(df): return T975.get(df) or T975[min((k for k in T975 if k >= df), default=29)]


def conditions():
    C = []
    for p in PROTOS: C.append(("baseline", "-", dict(proto=p)))
    for rate in (1.0, 3.0, 6.0, 10.0):
        for p in PROTOS: C.append(("load", rate, dict(proto=p, rate=rate)))
    for ff in (0.0, 0.1, 0.2, 0.3, 0.5):
        for p in PROTOS: C.append(("failures", ff, dict(proto=p, fail_frac=ff)))
    for J in (0, 10, 20, 30):
        for p in PROTOS: C.append(("jam_keyed", J, dict(proto=p, jam=JAM(J))))
        C.append(("jam_fixed", J, dict(proto="custody", hop="fixed", jam=JAM(J))))
    for mf in (0.0, 0.3, 0.6):
        for p in PROTOS: C.append(("mobility_sparse", mf, dict(proto=p, deg=4.0, connected=False, mobile_frac=mf)))
    for topo, n in (("grid", 36), ("line", 20), ("clusters", 36)):
        for p in PROTOS: C.append(("topology", topo, dict(proto=p, topo=topo, n=n)))
    for prio in (True, False): C.append(("priority_ablation", prio, dict(proto="custody", prio=prio, rate=10.0)))
    for q in (4, 8, 16, 32): C.append(("qcap", q, dict(proto="custody", qcap=q, rate=10.0)))
    return C


def work(a):
    sweep, val, kw, seed = a
    r = run(Cfg(seed=seed, **kw)); r.update(sweep=sweep, value=val, proto=kw.get("proto", "custody"),
                                           hop=kw.get("hop", "keyed"), seed=seed)
    if sweep == "priority_ablation": r["proto"] = "custody_prio" if val else "custody_fifo"
    return r


def main():
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
    os.makedirs(out, exist_ok=True)
    jobs = [(s, v, kw, 1000 + k) for (s, v, kw) in conditions() for k in range(seeds)]
    t0 = time.time(); print(len(jobs), "runs", flush=True)
    with Pool(2) as P: rows = P.map(work, jobs, chunksize=4)
    keys = list(rows[0].keys())
    with open(os.path.join(out, "sweep_raw.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, keys); w.writeheader(); w.writerows(rows)
    metrics = [k for k in keys if k not in ("sweep", "value", "proto", "hop", "seed")]
    groups = {}
    for r in rows: groups.setdefault((r["sweep"], str(r["value"]), r["proto"], r["hop"]), []).append(r)
    with open(os.path.join(out, "sweep_summary.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["sweep", "value", "proto", "hop", "n"] + [f"{m}_{s}" for m in metrics for s in ("mean", "ci95")])
        for g, rs in groups.items():
            row = list(g) + [len(rs)]
            for m in metrics:
                x = np.array([r[m] for r in rs], float); x = x[~np.isnan(x)]
                mu = x.mean() if len(x) else float("nan")
                ci = tcrit(len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else float("nan")
                row += [f"{mu:.4g}", f"{ci:.3g}"]
            w.writerow(row)
    print("done in", round(time.time() - t0), "s", flush=True)


if __name__ == "__main__":
    main()
