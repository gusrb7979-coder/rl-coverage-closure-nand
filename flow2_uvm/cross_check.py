"""Cross-check: pyuvm results on the RTL (out/uvm_*.json) vs the same runs on the Python model.
Every UVM sequence mirrors a nandpoc.methods function with identical seeds, so every number must
match, and the UVM verdict must be FAIL exactly when the Python model reached the bug.
usage: python flow2_uvm/cross_check.py [pattern ...]   (default: every out/uvm_*.json present)
       with patterns (e.g. "uvm_rlp_*.json") it writes out/cross_check_summary_extra.json instead
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from nandpoc import methods, nand_dut  # noqa: E402
from nandpoc.nand_dut import BUG, N_BINS, N_SPEC_BINS, NandRecoveryDUT, oracle_action, spec_coverage  # noqa: E402

OUT = ROOT / "out"
# compared when the Python run computes them; the later keys exist only in newer result files
KEYS = ["steps", "spec_covered", "violation", "coverage", "covered", "bug_at", "full_at", "policy_ok",
        "max_depth", "depth_at", "curve", "polish_steps", "policy", "deep_commits", "deep_entries", "hint_hist"]


BULKY = ("curve", "policy", "deep_entries", "hint_hist")   # compared, but left out of the summary file


def with_spec(u):
    """Older result files have no spec fields; both violation bins are hit together with bug_at."""
    if "spec_covered" not in u:
        u = dict(u, spec_covered=u["covered"] - (2 if u["bug_at"] is not None else 0),
                 spec_total=N_SPEC_BINS, violation=u["bug_at"] is not None)
    return u


def python_run(u):
    """Same run on the Python model; a table variant (u['tables']) patches the model's tables."""
    saved = list(nand_dut.RT), list(nand_dut.ST)
    if u.get("tables"):
        rt, st = u["tables"].split(":")
        nand_dut.RT[:], nand_dut.ST[:] = [int(x) for x in rt.split(",")], [int(x) for x in st.split(",")]
    try:
        return _python_run(u)
    finally:
        nand_dut.RT[:], nand_dut.ST[:] = saved


def _python_run(u):
    methods.BUDGET = u["budget"]
    t = methods.Tracker(NandRecoveryDUT(seed=u["lfsr_seed"], buggy=u["variant"] == "buggy"))
    rng = np.random.default_rng(u["seed"])
    res = {}
    if u["mode"] in ("crv", "fuzzer", "bfs"):
        getattr(methods, u["mode"])(t, rng)
    elif u["mode"] == "rl":
        methods.rl(t, rng, polish=False)
    elif u["mode"] == "rlp":  # coverage phase + policy polish; polish runs outside the Tracker
        res["policy"] = [int(x) for x in methods.rl(t, rng, polish=True)]
        res["polish_steps"] = t.polish_steps
    elif u["mode"] == "oracle":  # flow1_python/validate.py reach
        while not t.done():
            t.dut.reset()
            for _ in range(64):
                a = oracle_action(t.dut) if rng.random() < 0.8 else int(rng.integers(64))
                t.step(a)
                if t.dut.state == BUG or t.done():
                    break
    elif u["mode"] == "oraclepure":  # flow1_python/validate.py golden: oracle only, no reset
        while not t.done():
            t.step(oracle_action(t.dut))
    elif u["mode"] == "repro":  # the saved episode, replayed from its error-model state
        rep = json.loads((OUT / u.get("repro_file", "uvm_rl_buggy_s0_repro.json")).read_text())
        t.dut.reset()
        for a in rep["txs"]:
            t.step(a)
    else:  # policy replay on a fresh DUT seeded like the RTL run (busy length does not matter)
        policy = json.loads((OUT / u.get("policy_file", "policy_seed0.json")).read_text())["policy"]
        ok = 0
        for _ in range(u["trials"]):
            o = t.dut.reset()
            for _ in range(200):
                t.step(policy[o])
                o = t.dut.obs()
                if t.dut.state == BUG:
                    ok += 1
                    break
        res["policy_ok"] = ok
    spec_cov, _, violation = spec_coverage(t.dut.covered)
    res.update(steps=t.steps, spec_covered=spec_cov, violation=violation, coverage=t.dut.coverage(),
               covered=len(t.dut.covered), bug_at=t.bug_at, full_at=t.full_at)
    if "curve" in u:
        # Tracker samples coverage % every CKPT; both violation bins are hit at bug_at
        curve = []
        for k, v in enumerate(t.curve):
            n = (k + 1) * methods.CKPT
            cov = round(v * N_BINS / 100)
            curve.append([n, cov, cov - (2 if t.bug_at is not None and n >= t.bug_at else 0)])
        res.update(max_depth=t.max_depth, depth_at={str(d): n for d, n in t.depth_at.items()}, curve=curve)
    if "deep_entries" in u and u["mode"] != "rlp":  # rlp: the RTL also counts the polish phase
        res.update(deep_entries=t.deep_entries, hint_hist=t.hint_hist)
        if "deep_commits" in u:
            res["deep_commits"] = t.deep_commits
    return res


def main():
    rows = []
    patterns = sys.argv[1:] or ["uvm_*.json"]
    summary = OUT / ("cross_check_summary.json" if len(sys.argv) == 1 else "cross_check_summary_extra.json")
    for f in sorted({f for p in patterns for f in OUT.glob(p)}):
        if f.stem.endswith(("_repro", "_policy")):
            continue
        u = with_spec(json.loads(f.read_text()))
        p = python_run(u)
        diff = [k for k in KEYS if k in p and u.get(k) != p.get(k)
                and not (isinstance(u.get(k), float) and abs(u[k] - p[k]) < 1e-9)]
        want = "FAIL" if p["bug_at"] is not None else "PASS"
        if u["verdict"] != want:
            diff.append("verdict")
        rows.append((f.stem, u, p, diff))
        print(f"\n{f.stem}  ({u['steps']:,} tx on RTL, busy {u['busy']}, sim {u['sim_ns'] / 1000:,.0f} us, "
              f"{u['tx_per_s']:,.0f} tx/s)  verdict {u['verdict']} (expected {want})  "
              f"spec coverage {u['spec_covered']}/{u['spec_total']}"
              + (" + violation detected" if u["violation"] else ""))
        for k in KEYS:
            if k in p:
                uv, pv = u.get(k), p.get(k)
                if k in ("curve", "policy"):  # too long to print: show the length and the last item
                    uv = f"{len(uv or [])} items, last {(uv or [None])[-1]}"
                    pv = f"{len(pv or [])} items, last {(pv or [None])[-1]}"
                elif k in ("deep_entries", "hint_hist"):
                    uv = {d: (len(v) if k == "deep_entries" else sum(v)) for d, v in (uv or {}).items()}
                    pv = {d: (len(v) if k == "deep_entries" else sum(v)) for d, v in (pv or {}).items()}
                print(f"   {k:10s} RTL/UVM {uv!s:>22}   Python {pv!s:>22}   "
                      f"{'MISMATCH' if k in diff else 'ok'}")
        print(f"   scoreboard: checked {u['sb_checked']:,}, mismatches vs spec {u['sb_mismatch']}, "
              f"commit-rule violations {u['sb_rule_violation']}")
    bad = [r[0] for r in rows if r[3]]
    print(f"\n{len(rows)} runs compared: " + ("ALL MATCH" if not bad else f"MISMATCHED RUNS: {bad}"))
    summary.write_text(json.dumps(
        [{"run": r[0], "verdict": r[1]["verdict"], "match": not r[3],
          "spec_coverage": f"{r[1]['spec_covered']}/{r[1]['spec_total']}", "violation": r[1]["violation"],
          "uvm": {k: r[1].get(k) for k in KEYS if k in r[2] and k not in BULKY},
          "python": {k: r[2].get(k) for k in KEYS if k not in BULKY}} for r in rows], indent=1))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
