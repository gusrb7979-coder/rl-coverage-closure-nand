"""Flow 1, step 1: CRV vs coverage fuzzer vs BFS vs RL on the Python model of the buggy DUT.
usage: python flow1_python/compare.py [seeds=10] [budget=3000000]
Writes out/nand_compare.json (per-seed results and coverage curves).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from nandpoc import methods  # noqa: E402
from nandpoc.nand_dut import N_SPEC_BINS, NandRecoveryDUT, spec_coverage  # noqa: E402

OUT = ROOT / "out"


def main(seeds=10, budget=3_000_000):
    methods.BUDGET = budget
    results = {m: [] for m in methods.METHODS}
    for sd in range(seeds):
        for name, fn in methods.METHODS.items():
            rng = np.random.default_rng(sd)
            t = methods.Tracker(NandRecoveryDUT(seed=0x1000 + 97 * sd))
            t0 = time.perf_counter()
            policy = fn(t, rng)
            spec_cov, _, violation = spec_coverage(t.dut.covered)
            row = {"final_cov": t.dut.coverage(), "spec_covered": spec_cov, "violation": violation,
                   "bug_at": t.bug_at, "full_at": t.full_at,
                   "steps": t.steps, "sec": time.perf_counter() - t0, "curve": t.curve}
            if name == "RL":
                row["policy_replay"] = methods.replay_policy(policy, seed=0x7000 + sd)
                row["polish_steps"] = t.polish_steps
            results[name].append(row)
            print(f"seed {sd} {name:6s} cov {row['final_cov']:5.1f}%  spec {spec_cov}/{N_SPEC_BINS}"
                  f"{' +violation' if violation else ''}  bug_at {t.bug_at}  100%_at {t.full_at}"
                  + (f"  +polish {t.polish_steps}  policy replay {row['policy_replay']:.3f}" if name == "RL" else "")
                  + f"  ({row['sec']:.1f}s)")
    OUT.mkdir(exist_ok=True)
    (OUT / "nand_compare.json").write_text(json.dumps({"budget": budget, "ckpt": methods.CKPT, **results}))
    print(f"\nsummary (median over {seeds} seeds, budget {budget:,} tx)")
    for name, rows in results.items():
        bug = [r["bug_at"] for r in rows if r["bug_at"]]
        full = [r["full_at"] for r in rows if r["full_at"]]
        print(f"{name:6s} final cov {np.median([r['final_cov'] for r in rows]):5.1f}% (73 bins)  "
              f"spec coverage {np.median([r['spec_covered'] for r in rows]):g}/{N_SPEC_BINS}  "
              f"violation detected {len(bug)}/{len(rows)}  all 73 bins {len(full)}/{len(rows)}"
              + (f" at {np.median(full):,.0f}" if full else ""))


if __name__ == "__main__":
    kv = dict(a.split("=", 1) for a in sys.argv[1:])
    main(int(kv.get("seeds", 10)), int(kv.get("budget", 3_000_000)))
