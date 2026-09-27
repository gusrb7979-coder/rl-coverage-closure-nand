"""Synthesizability + gate-level equivalence of both RTL variants (runs on Windows or WSL).

1. Lint and synthesize rtl/nand_recovery_<variant>.v with Yosys (warnings fail the check),
   save the cell statistics to out/synth_<variant>.txt.
2. Write the synthesized netlist as JSON, compile it into a straight-line Python function
   (one clock cycle) and drive it with valid/ready traffic including NAND busy stalls,
   idle cycles and host resets. After every accepted transaction the netlist outputs
   (state, hint, err, map commit, map write count) must equal the Python model.

Yosys: 'yowasp-yosys' from the active Python environment (pip install yowasp-yosys) or a
system 'yosys' on PATH (e.g. apt install yosys in WSL).
usage: python synth/synth_check.py [golden] [buggy] [n_tx=100000]
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from nandpoc.nand_dut import BUG, NandRecoveryDUT, oracle_action  # noqa: E402

OUT = ROOT / "out"
OPS = {"$_AND_": "{A} & {B}", "$_ANDNOT_": "{A} & ({B} ^ 1)", "$_NAND_": "({A} & {B}) ^ 1",
       "$_NOR_": "({A} | {B}) ^ 1", "$_NOT_": "{A} ^ 1", "$_OR_": "{A} | {B}",
       "$_ORNOT_": "{A} | ({B} ^ 1)", "$_XOR_": "{A} ^ {B}", "$_XNOR_": "({A} ^ {B}) ^ 1",
       "$_MUX_": "({B} if {S} else {A})", "$_BUF_": "{A}"}
FFS = {"$_DFFE_PN0P_": 0, "$_DFFE_PN1P_": 1, "$_DFF_PN0_": 0, "$_DFF_PN1_": 1}  # value = async reset value


def find_yosys():
    here = Path(sys.executable).parent
    for cand in (here / "yowasp-yosys", here / "yowasp-yosys.exe"):
        if cand.exists():
            return str(cand)
    for name in ("yowasp-yosys", "yosys"):
        if shutil.which(name):
            return shutil.which(name)
    sys.exit("Yosys not found: pip install yowasp-yosys (or apt install yosys)")


def yosys(script):
    return subprocess.run([find_yosys(), "-q", "-p", script], cwd=ROOT, capture_output=True, text=True)


def lint_and_synth(variant):
    src = f"rtl/nand_recovery_{variant}.v"
    r = yosys(f"read_verilog {src}; hierarchy -check -top nand_recovery; proc; opt; check -assert; "
              f"synth -top nand_recovery; tee -q -o out/synth_{variant}.txt stat")
    warnings = [l for l in (r.stdout + r.stderr).splitlines() if "Warning" in l or "ERROR" in l]
    stat = (OUT / f"synth_{variant}.txt").read_text() if (OUT / f"synth_{variant}.txt").exists() else ""
    # Yosys versions print stat differently ("304 cells" / "Number of cells: 304", "24 $_DFF.." / "$_DFF.. 24")
    num = lambda line: next((int(tok) for tok in line.replace(":", " ").split() if tok.isdigit()), 0)
    cells = next((num(l) for l in stat.splitlines() if l.strip().endswith(" cells") or "Number of cells" in l), "?")
    ffs = sum(num(l) for l in stat.splitlines() if "DFF" in l)
    ok = r.returncode == 0 and not warnings
    print(f"[{variant}] lint/synth {'OK, no warnings' if ok else 'FAILED'}: {cells} cells, {ffs} flip-flops")
    for w in warnings:
        print("   ", w)
    return ok


def compile_netlist(variant):
    r = yosys(f"read_verilog rtl/nand_recovery_{variant}.v; hierarchy -check -top nand_recovery; "
              "synth -top nand_recovery; flatten; opt_clean; write_json out/netlist.json")
    if r.returncode:
        sys.exit(r.stderr)
    netlist = OUT / "netlist.json"   # intermediate, removed once loaded
    mod = json.loads(netlist.read_text())["modules"]["nand_recovery"]
    netlist.unlink()
    net = lambda b: str(b) if b in ("0", "1") else f"n{b}"
    ports = {name: p["bits"] for name, p in mod["ports"].items()}
    comb, ffs = [], []
    for cell in mod["cells"].values():
        t, c = cell["type"], cell["connections"]
        if t in OPS:
            comb.append((c["Y"][0], OPS[t].format(**{k: net(v[0]) for k, v in c.items() if k != "Y"})))
        elif t in FFS:
            enable = net(c["E"][0]) if "E" in c else "1"  # plain DFF: always enabled
            ffs.append((c["Q"][0], net(c["D"][0]), enable, FFS[t]))
        else:
            raise ValueError(f"unsupported cell {t}")
    known = {b for name in ("clk", "por_n", "rst_n", "seed_we", "lfsr_seed", "in_valid", "in_tx")
             for b in ports[name]} | {q for q, *_ in ffs}
    order, pending = [], comb
    while pending:  # topological order of the combinational cells
        ready = [(y, e) for y, e in pending
                 if all(int(tok[1:]) in known for tok in e.replace("(", " ").replace(")", " ").split()
                        if tok.startswith("n") and tok[1:].isdigit())]
        if not ready:
            raise RuntimeError("combinational loop")
        order += ready
        known |= {y for y, _ in ready}
        pending = [p for p in pending if p not in ready]
    lines = ["def cycle(q, rst_n, seed_we, seed, valid, txv):"]
    lines += [f"    n{b} = (seed >> {i}) & 1" for i, b in enumerate(ports["lfsr_seed"])]
    lines += [f"    n{b} = (txv >> {i}) & 1" for i, b in enumerate(ports["in_tx"])]
    lines += [f"    n{ports['rst_n'][0]} = rst_n", f"    n{ports['seed_we'][0]} = seed_we",
              f"    n{ports['in_valid'][0]} = valid", f"    n{ports['por_n'][0]} = 1"]
    lines += [f"    n{qb} = q[{i}]" for i, (qb, *_) in enumerate(ffs)]
    lines += [f"    n{y} = {e}" for y, e in order]
    rd = lambda name: " | ".join(f"({net(b)} << {i})" for i, b in enumerate(ports[name]))
    lines.append(f"    ready = {rd('in_ready')}")
    lines.append("    nq = [" + ", ".join(f"({d} if {e} else n{qb})" for qb, d, e, _ in ffs) + "]")
    lines.append("    return ready, nq")
    env = {}
    exec("\n".join(lines), env)
    q_index = {qb: i for i, (qb, *_) in enumerate(ffs)}

    def read(q, name):
        v = 0
        for i, b in enumerate(ports[name]):
            v |= (int(b) if b in ("0", "1") else q[q_index[b]]) << i
        return v
    return env["cycle"], [r for *_, r in ffs], read


def equivalence(variant, n_tx=100_000, seed=0x5EED):
    cycle, q, read = compile_netlist(variant)
    rng = np.random.default_rng(1)
    _, q = cycle(list(q), 1, 1, seed, 0, 0)          # load the error-model seed
    model = NandRecoveryDUT(seed=seed, buggy=(variant == "buggy"))
    accepted = cycles = stalls = resets = mismatches = double = 0
    seen = set()
    while accepted < n_tx:
        if model.state == BUG or rng.random() < 0.002:   # host reset now and then
            _, q = cycle(q, 0, 0, 0, 0, 0)
            model.reset()
            resets, cycles = resets + 1, cycles + 1
            continue
        if rng.random() < 0.1:                             # idle cycle, valid low
            _, q = cycle(q, 1, 0, 0, 0, 0)
            cycles += 1
            continue
        t = oracle_action(model) if rng.random() < 0.7 else int(rng.integers(64))
        while True:                                        # hold valid until ready (NAND busy)
            ready, q = cycle(q, 1, 0, 0, 1, t)
            cycles += 1
            if ready:
                break
            stalls += 1
        model.step(t)
        accepted += 1
        seen.add(model.state)
        double += int(model.commit and model.wr_cnt == 2)
        # model state 8 = monitor-level bug event; the RTL itself is back in IDLE (state 0)
        want = (0 if model.state == BUG else model.state, model.hint, model.err, model.commit, model.wr_cnt)
        got = (read(q, "state_o"), read(q, "hint_o"), read(q, "err_o"), read(q, "map_commit_o"),
               read(q, "map_wr_cnt_o"))
        if got != want:
            mismatches += 1
            if mismatches <= 5:
                print(f"    MISMATCH at tx {accepted}: netlist {got} model {want}")
    print(f"[{variant}] gate-level equivalence: {accepted:,} tx, {cycles:,} cycles ({stalls:,} busy stalls, "
          f"{resets:,} host resets), states {sorted(seen)}, double map writes {double:,}, mismatches {mismatches}")
    return mismatches == 0


def main(args):
    OUT.mkdir(exist_ok=True)
    kv = dict(a.split("=", 1) for a in args if "=" in a)
    variants = [a for a in args if "=" not in a] or ["golden", "buggy"]
    ok = True
    for v in variants:
        ok &= lint_and_synth(v)
        ok &= equivalence(v, int(kv.get("n_tx", 100_000)))
    print("SYNTH CHECK PASSED" if ok else "SYNTH CHECK FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
