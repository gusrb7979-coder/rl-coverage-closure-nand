"""Build one RTL variant with Icarus and run the pyuvm testbench (flow2_uvm/tb_nand.py). Runs in WSL.
usage: python flow2_uvm/run_uvm.py variant=buggy mode=crv seed=0 budget=300000
         [trials=1000] [lfsr_seed=N] [policy=path] [repro=path] [busy=3] [waves=1]
         [rtl=path] [tables=rt0,..,rt15:st0,..,st15] [suffix=_tag]
  mode: crv | fuzzer | bfs | rl | rlp (RL + policy polish) | oracle | oraclepure | policy | repro
Writes out/uvm_<mode>_<variant>_s<seed>[_busy<N>].json (+ _repro.json on the first failure,
+ .fst waveform when waves=1). Exit code 1 when the test FAILS (spec violation seen).
"""
import shutil
import sys
from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parents[1]


def main(args):
    kv = dict(a.split("=", 1) for a in args)
    variant, mode, seed = kv.get("variant", "buggy"), kv.get("mode", "crv"), kv.get("seed", "0")
    busy, waves = int(kv.get("busy", "3")), kv.get("waves", "0") == "1"
    tag = f"uvm_{mode}_{variant}_s{seed}" + (f"_busy{busy}" if busy != 3 else "") + kv.get("suffix", "")
    out = ROOT / "out" / f"{tag}.json"
    out.parent.mkdir(exist_ok=True)
    env = {"DUT_VARIANT": variant, "MODE": mode, "SEED": seed, "BUDGET": kv.get("budget", "300000"),
           "TRIALS": kv.get("trials", "1000"), "OUT": str(out), "BUSY": str(busy),
           "POLICY": str(ROOT / kv.get("policy", "out/policy_seed0.json")),
           "REPRO": str(ROOT / kv.get("repro", "out/uvm_rl_buggy_s0_repro.json")),
           "TABLES": kv.get("tables", "")}   # retry/spare tables of an rtl= variant (rt,..:st,..)
    if "lfsr_seed" in kv:
        env["LFSR_SEED"] = str(int(kv["lfsr_seed"], 0))
    rtl = ROOT / kv.get("rtl", f"rtl/nand_recovery_{variant}.v")
    build_dir = ROOT / "sim_build" / (f"{rtl.stem}_busy{busy}" + ("_waves" if waves else ""))
    runner = get_runner("icarus")
    runner.build(sources=[rtl], hdl_toplevel="nand_recovery",
                 build_dir=build_dir, always=True, timescale=("1ns", "1ps"),
                 parameters={"BUSY_CYCLES": busy}, waves=waves)
    failed = False
    try:
        results = runner.test(hdl_toplevel="nand_recovery", test_module="tb_nand", test_dir=ROOT / "flow2_uvm",
                              build_dir=build_dir, extra_env=env, waves=waves)
        failed = "<failure" in Path(results).read_text()  # junit failure element, not failures="0"
    except (SystemExit, RuntimeError):
        failed = True
    if waves:
        for f in build_dir.glob("*.fst"):
            shutil.copy(f, ROOT / "out" / f"{tag}.fst")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
