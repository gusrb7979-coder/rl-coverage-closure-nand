"""Summary of the extra UVM checks (flow2_uvm/uvm_jobs.sh extra ...), read from out/:
  policy   : RL with policy polish on the buggy RTL (uvm_rlp_buggy_s<N>), then 1,000-episode replay of the
             saved policy on a fresh error-model seed, on the buggy and the golden RTL (uvm_policy_*)
  oracle   : an oracle that knows both tables must reach 100% (uvm_oracle_buggy_s<N>)
  golden   : oracle-only traffic on the golden RTL: deepest commits and double map writes (uvm_oraclepure_*)
  tables   : RL on buggy-RTL variants with re-randomized tables (uvm_rlp_buggy_s<K>_t<K>, uvm_policy_buggy_s<K>_t<K>)
  budget   : fuzzer seed 7 with 10x budget (uvm_fuzzer_buggy_s7_b30m): deep-state entries at 3M and 30M tx
  hints    : hint distribution on entering ECC_FAIL2 over the RL runs
Prints and writes out/extra_summary.json.  usage: python flow2_uvm/extra_summary.py"""
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "out"


def load(name):
    f = OUT / f"{name}.json"
    return json.loads(f.read_text()) if f.exists() else None


def main():
    s, missing = {}, []

    def need(name):
        r = load(name)
        if r is None:
            missing.append(name)
        return r

    rows = []
    for k in range(10):
        rl, pb, pg = need(f"uvm_rlp_buggy_s{k}"), need(f"uvm_policy_buggy_s{k}"), need(f"uvm_policy_golden_s{k}")
        rows.append({"seed": k, "bug_at": rl and rl["bug_at"], "polish_steps": rl and rl["polish_steps"],
                     "replay_buggy": pb and pb["policy_ok"] / pb["trials"], "verdict_buggy": pb and pb["verdict"],
                     "replay_golden": pg and pg["policy_ok"] / pg["trials"], "verdict_golden": pg and pg["verdict"]})
    s["policy"] = rows
    ok = [r for r in rows if r["polish_steps"] is not None]
    rb = [r["replay_buggy"] for r in rows if r["replay_buggy"] is not None]
    print("policy: polish median", f"{np.median([r['polish_steps'] for r in ok]):,.0f}" if ok else "-",
          "| replay on buggy", f"{min(rb):.3f}-{max(rb):.3f}" if rb else "-",
          "| golden replays", [r["replay_golden"] for r in rows], [r["verdict_golden"] for r in rows])

    s["oracle"] = [{"seed": k, "full_at": r and r["full_at"], "verdict": r and r["verdict"]}
                   for k, r in ((k, need(f"uvm_oracle_buggy_s{k}")) for k in range(5))]
    print("oracle full_at:", [o["full_at"] for o in s["oracle"]])

    s["golden_oracle"] = [{"seed": k, "steps": r and r["steps"], "deep_commits": r and r["deep_commits"],
                           "double_writes": r and r["sb_rule_violation"], "verdict": r and r["verdict"]}
                          for k, r in ((k, need(f"uvm_oraclepure_golden_s{k}")) for k in range(3))]
    print("golden oracle:", [(g["deep_commits"], g["double_writes"], g["verdict"]) for g in s["golden_oracle"]])

    s["tables"] = []
    for k in range(3):
        rl, pb = need(f"uvm_rlp_buggy_s{k}_t{k}"), need(f"uvm_policy_buggy_s{k}_t{k}")
        s["tables"].append({"variant": f"t{k}", "coverage": rl and rl["coverage"], "full_at": rl and rl["full_at"],
                            "polish_steps": rl and rl["polish_steps"],
                            "replay": pb and pb["policy_ok"] / pb["trials"], "tables": rl and rl.get("tables")})
    print("tables:", [(t["variant"], t["coverage"], t["full_at"], t["replay"]) for t in s["tables"]])

    fz = need("uvm_fuzzer_buggy_s7_b30m")
    if fz:
        entries = {d: {"to_3M": sum(t <= 3_000_000 for t in v), "to_30M": len(v), "first": v[0] if v else None}
                   for d, v in fz["deep_entries"].items()}
        s["budget"] = {"steps": fz["steps"], "verdict": fz["verdict"], "bug_at": fz["bug_at"],
                       "spec_covered": fz["spec_covered"], "coverage": fz["coverage"],
                       "max_depth": fz["max_depth"], "depth_at": fz["depth_at"], "entries": entries}
        print("fuzzer s7 30M:", fz["verdict"], "bug_at", fz["bug_at"], "spec", fz["spec_covered"],
              "max depth", fz["max_depth"], "entries", entries)

    hist = np.zeros(16, int)
    for k in range(10):
        r = load(f"uvm_rlp_buggy_s{k}")
        if r:
            hist += np.array(r["hint_hist"]["5"])
    if hist.sum():
        s["hints_ecc_fail2"] = {"counts": hist.tolist(), "total": int(hist.sum()),
                                "min_max_ratio": round(float(hist.min() / hist.max()), 3)}
        print("hints on entering ECC_FAIL2:", hist.tolist(), "min/max", s["hints_ecc_fail2"]["min_max_ratio"])

    s["missing"] = missing
    print("missing:", missing or "none")
    (OUT / "extra_summary.json").write_text(json.dumps(s, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
