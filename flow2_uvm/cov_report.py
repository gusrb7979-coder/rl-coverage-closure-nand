"""Per-group coverage report of pyuvm runs.
usage: python flow2_uvm/cov_report.py uvm_crv_buggy_s0 uvm_rl_buggy_s0 ...   (names of out/*.json)"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "out"

for run in sys.argv[1:]:
    r = json.loads((OUT / f"{run}.json").read_text())
    spec = (f"spec coverage {r['spec_covered']}/{r['spec_total']}"
            + (" + violation detected" if r["violation"] else "")) if "spec_covered" in r else ""
    print(f"{run}: {r['coverage']:.1f}% ({r['covered']}/73 bins) {spec}, verdict {r['verdict']}")
    for group, v in r["coverage_by_group"].items():
        miss = ", ".join(v["missing"][:6]) + (" ..." if len(v["missing"]) > 6 else "")
        print(f"   {group:14s} {v['covered']:2d}/{v['total']:2d}   missing: {miss or '-'}")
