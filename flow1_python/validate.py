"""Flow 1, step 2: validity checks of the comparison.
  reach : an oracle that knows both tables must reach 100% (no unreachable bins)
  budget: CRV / fuzzer / BFS with 10x budget (30M transactions) must still miss the bug
  tables: RL must re-learn to 100% when the retry / spare tables are re-randomized
  golden: on the golden DUT, RL and the oracle must never see a double map write (no false alarm)
usage: python flow1_python/validate.py [reach] [budget] [tables] [golden]   (default: all)
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from nandpoc import methods, nand_dut  # noqa: E402
from nandpoc.nand_dut import BINS, BUG, N_BINS, NandRecoveryDUT, oracle_action  # noqa: E402


def reach(seeds=5):
    """Oracle follows the spec, plus random transactions so abort arcs also get hit."""
    for sd in range(seeds):
        rng = np.random.default_rng(sd)
        t = methods.Tracker(NandRecoveryDUT(seed=0x1000 + 97 * sd))
        while not t.done():
            t.dut.reset()
            for _ in range(64):
                a = oracle_action(t.dut) if rng.random() < 0.8 else int(rng.integers(64))
                t.step(a)
                if t.dut.state == BUG or t.done():
                    break
        print(f"  seed {sd}: oracle coverage {t.dut.coverage():.1f}% at {t.full_at} transactions")


def budget(seeds=3, big=30_000_000):
    saved, methods.BUDGET = methods.BUDGET, big
    try:
        for name in ("CRV", "Fuzzer", "BFS"):
            for sd in range(seeds):
                t0 = time.perf_counter()
                t = methods.Tracker(NandRecoveryDUT(seed=0x1000 + 97 * sd))
                methods.METHODS[name](t, np.random.default_rng(sd))
                print(f"  {name:6s} seed {sd}: {t.steps:,} tx -> coverage {t.dut.coverage():.1f}%, "
                      f"bug {'hit' if t.bug_at else 'never hit'}  ({time.perf_counter() - t0:.0f}s)")
    finally:
        methods.BUDGET = saved


def tables(seeds=3):
    saved = list(nand_dut.RT), list(nand_dut.ST)
    try:
        for sd in range(seeds):
            r = np.random.default_rng(777 + sd)
            nand_dut.RT[:] = r.permutation(16).tolist()
            nand_dut.ST[:] = r.permutation(16).tolist()
            t = methods.Tracker(NandRecoveryDUT(seed=0x2000 + sd))
            policy = methods.rl(t, np.random.default_rng(sd))
            rep = methods.replay_policy(policy, seed=0x9000 + sd)
            print(f"  new tables #{sd}: RL coverage {t.dut.coverage():.1f}%, 100% at {t.full_at}, "
                  f"policy replay {rep:.3f}")
    finally:  # restore the spec tables so later checks in the same run use them
        nand_dut.RT[:], nand_dut.ST[:] = saved


def golden(seeds=3):
    for sd in range(seeds):
        t = methods.Tracker(NandRecoveryDUT(seed=0x1000 + 97 * sd, buggy=False))
        methods.rl(t, np.random.default_rng(sd), polish=False)
        missing = [BINS[i] for i in range(N_BINS) if i not in t.dut.covered]
        d, deep, double = NandRecoveryDUT(seed=0x2000 + sd, buggy=False), 0, 0
        for _ in range(200_000):
            s = d.state
            d.step(oracle_action(d))
            deep += int(s == 7 and d.commit)
            double += int(d.commit and d.wr_cnt == 2)
        print(f"  golden seed {sd}: RL coverage {t.dut.coverage():.1f}%, bug hit {t.bug_at}, missing {missing} | "
              f"oracle deepest commits {deep}, double map writes {double}")


if __name__ == "__main__":
    checks = {"reach": reach, "budget": budget, "tables": tables, "golden": golden}
    for w in sys.argv[1:] or list(checks):
        print(f"[{w}]")
        checks[w]()
