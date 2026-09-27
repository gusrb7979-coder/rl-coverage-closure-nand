"""RL in the loop on the buggy RTL (pyuvm, out/uvm_rl_buggy_s<N>.json) vs the Python results of
flow1_python/compare.py (out/nand_compare.json) for the same seeds.
usage: python flow2_uvm/rl10_summary.py [seeds=10]"""
import json
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "out"
seeds = int(dict(a.split("=", 1) for a in sys.argv[1:]).get("seeds", 10))
py = json.loads((OUT / "nand_compare.json").read_text())["RL"]

rows, ok = [], True
print(f"{'seed':>4} | {'UVM bug_at':>10} {'Python':>10} | {'UVM 100%':>10} {'Python':>10} | {'spec':>5} | "
      f"verdict | sb violations | tx/s")
for s in range(seeds):
    f = OUT / f"uvm_rl_buggy_s{s}.json"
    if not f.exists() or s >= len(py):
        print(f"{s:>4} | missing")
        ok = False
        continue
    u, p = json.loads(f.read_text()), py[s]
    u.setdefault("spec_covered", u["covered"] - (2 if u["bug_at"] is not None else 0))  # older result files
    u.setdefault("spec_total", 71)
    match = u["bug_at"] == p["bug_at"] and u["full_at"] == p["full_at"] and u["verdict"] == "FAIL"
    ok &= match
    rows.append(u)
    print(f"{s:>4} | {u['bug_at']:>10,} {p['bug_at']:>10,} | {u['full_at']:>10,} {p['full_at']:>10,} | "
          f"{u['spec_covered']:>2}/{u['spec_total']} | {u['verdict']:>7} | {u['sb_rule_violation']:>13} | "
          f"{u['tx_per_s']:,.0f}" + ("" if match else "   <-- MISMATCH"))
if rows:
    full = [u["full_at"] for u in rows if u["full_at"]]
    spec_full = sum(u["spec_covered"] == u["spec_total"] for u in rows)
    print(f"\nUVM: spec coverage 71/71 in {spec_full}/{len(rows)}, violation detected (bug found) "
          f"{sum(u['bug_at'] is not None for u in rows)}/{len(rows)}; all 73 bins at median {np.median(full):,.0f} tx, "
          f"RTL sim wall time "
          f"{sum(u['seconds'] for u in rows) / 60:.1f} min")
print(f"ALL {seeds} SEEDS MATCH" if ok and len(rows) == seeds else "NOT ALL MATCH")
