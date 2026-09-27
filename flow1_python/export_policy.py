"""Flow 1, step 3: train RL on the buggy model (coverage closure + policy polish) and export the
policy table used by the pyuvm policy-replay sequence: one transaction (opcode*16 + param)
per observation (state*16 + hint), 144 entries.
usage: python flow1_python/export_policy.py [seed]      -> out/policy_seed<seed>.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from nandpoc import methods  # noqa: E402
from nandpoc.nand_dut import NandRecoveryDUT  # noqa: E402


def main(seed=0):
    t = methods.Tracker(NandRecoveryDUT(seed=0x1000 + 97 * seed))
    policy = methods.rl(t, np.random.default_rng(seed))
    out = ROOT / "out" / f"policy_seed{seed}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"seed": seed, "trained_tx": t.steps, "polish_tx": t.polish_steps,
                               "policy": [int(a) for a in policy]}))
    print(f"policy exported to {out} (coverage phase {t.steps:,} tx, polish {t.polish_steps} tx)")


if __name__ == "__main__":
    main(*map(int, sys.argv[1:]))
