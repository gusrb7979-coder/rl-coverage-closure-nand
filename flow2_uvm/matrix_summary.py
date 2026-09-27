"""Summary of the UVM control-group matrix (flow2_uvm/uvm_matrix.sh): golden and buggy DUT x
CRV, fuzzer, BFS, RL x seeds 0-9, read from out/uvm_<mode>_<variant>_s<seed>.json.
Prints and writes out/matrix_summary.json with
  table        : one row per (DUT, method): verdicts, spec coverage, 73-bin coverage, violations
  curve_buggy  : buggy DUT, median spec coverage (fraction of 71) per method every 100k tx
  depth_buggy  : buggy DUT, deepest state reached per seed (8 = spec violation) per method
usage: python flow2_uvm/matrix_summary.py [seeds=10] [budget=3000000]"""
import json
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "out"
METHODS = [("crv", "CRV"), ("fuzzer", "퍼저"), ("bfs", "BFS"), ("rl", "RL")]
kv = dict(a.split("=", 1) for a in sys.argv[1:])
SEEDS, BUDGET = int(kv.get("seeds", 10)), int(kv.get("budget", 3_000_000))
STEP = 100_000


def load(variant, mode):
    runs = []
    for s in range(SEEDS):
        f = OUT / f"uvm_{mode}_{variant}_s{s}.json"
        runs.append(json.loads(f.read_text()) if f.exists() else None)
    return runs


def spec_at(run, n):
    """Spec bins covered after n tx; after a run ended (RL stops at 100%) its final value."""
    if n >= run["steps"]:
        return run["spec_covered"]
    last = 0
    for t, _, spec in run["curve"]:
        if t > n:
            break
        last = spec
    return last


def main():
    table, curve_rows, depth = [], [], {}
    missing = []
    for variant in ("golden", "buggy"):
        for mode, label in METHODS:
            runs = load(variant, mode)
            missing += [f"{mode}_{variant}_s{s}" for s, r in enumerate(runs) if r is None]
            ok = [r for r in runs if r is not None]
            if not ok:
                continue
            full = [r["full_at"] for r in ok if r["full_at"]]
            row = {"dut": variant, "method": label, "runs": len(ok),
                   "pass": sum(r["verdict"] == "PASS" for r in ok), "fail": sum(r["verdict"] == "FAIL" for r in ok),
                   "spec_median": float(np.median([r["spec_covered"] for r in ok])),
                   "cov73_median": float(np.median([r["coverage"] for r in ok])),
                   "cov73_full": len(full), "violation": sum(bool(r["violation"]) for r in ok),
                   "full_at_median": float(np.median(full)) if full else None,
                   "tx_per_s_median": float(np.median([r["tx_per_s"] for r in ok]))}
            table.append(row)
            if variant == "buggy":
                for n in range(STEP, BUDGET + 1, STEP):
                    med = np.median([spec_at(r, n) for r in ok]) / 71
                    curve_rows.append({"m": round(n / 1e6, 1), "method": label, "cov": round(float(med), 4)})
                per_seed = [r["max_depth"] if r else None for r in runs]
                vals = [d for d in per_seed if d is not None]
                bug_at = [r["depth_at"].get("8") for r in ok if r["depth_at"].get("8")]
                depth[label] = {"per_seed": per_seed, "median": float(np.median(vals)), "max": max(vals),
                                "depth8_at_median": float(np.median(bug_at)) if bug_at else None}

    print(f"{'DUT':6s} {'method':6s} | runs | PASS FAIL | spec cov (median) | 73-bin cov (median) | "
          f"100% runs | violations")
    for r in table:
        print(f"{r['dut']:6s} {r['method']:6s} | {r['runs']:4d} | {r['pass']:4d} {r['fail']:4d} | "
              f"{r['spec_median']:>12g}/71 | {r['cov73_median']:>18.1f}% | {r['cov73_full']:6d}/{r['runs']} | "
              f"{r['violation']:4d}/{r['runs']}")
    print("\nbuggy DUT, deepest state reached per seed (8 = spec violation)")
    for label, d in depth.items():
        print(f"  {label:6s} {d['per_seed']}  median {d['median']:g}  max {d['max']}"
              + (f"  depth 8 at median {d['depth8_at_median']:,.0f} tx" if d["depth8_at_median"] else ""))
    golden = [r for r in table if r["dut"] == "golden"]
    buggy_rl = [r for r in table if r["dut"] == "buggy" and r["method"] == "RL"]
    ok = (not missing and all(r["fail"] == 0 for r in golden)
          and buggy_rl and buggy_rl[0]["cov73_full"] == buggy_rl[0]["runs"] == SEEDS)
    print(f"\nmissing runs: {missing or 'none'}")
    print("CRITERIA MET: golden all PASS, buggy RL 100% on every seed" if ok else "CRITERIA NOT MET")
    (OUT / "matrix_summary.json").write_text(json.dumps(
        {"budget": BUDGET, "seeds": SEEDS, "table": table, "curve_buggy": curve_rows, "depth_buggy": depth,
         "missing": missing, "criteria_met": bool(ok)}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
