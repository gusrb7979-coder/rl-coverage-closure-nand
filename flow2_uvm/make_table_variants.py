"""Table re-randomization check on the RTL: write buggy-RTL variants whose retry / spare tables are
replaced by the same random tables as flow1_python/validate.py tables (rng seed 777 + k).
Writes rtl/variants/nand_recovery_buggy_t<k>.v and prints the tables= argument for run_uvm.py.
usage: python flow2_uvm/make_table_variants.py [count=3]"""
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "rtl" / "nand_recovery_buggy.v").read_text()


def case_body(name, table):
    lines = [f"            4'd{h}: {name} = 4'd{v};" for h, v in enumerate(table[:15])]
    lines.append(f"            default: {name} = 4'd{table[15]};")
    return "\n".join(lines)


def variant(rt, st, k):
    v = SRC
    for name, table in (("retry_table", rt), ("spare_table", st)):
        pat = re.compile(rf"(function \[3:0\] {name}\(input \[3:0\] h\);\n\s*case \(h\)\n)(.*?)(\n\s*endcase)", re.S)
        v, n = pat.subn(lambda m: m.group(1) + case_body(name, table) + m.group(3), v)
        assert n == 1, name
    return v.replace("-- BUGGY version (device under verification).",
                     f"-- BUGGY version, table variant t{k} (re-randomized retry/spare tables).", 1)


def main(count=3):
    out = ROOT / "rtl" / "variants"
    out.mkdir(exist_ok=True)
    for k in range(count):
        r = np.random.default_rng(777 + k)
        rt, st = r.permutation(16).tolist(), r.permutation(16).tolist()
        (out / f"nand_recovery_buggy_t{k}.v").write_text(variant(rt, st, k))
        print(f"t{k} tables={','.join(map(str, rt))}:{','.join(map(str, st))}")


if __name__ == "__main__":
    main(int(dict(a.split("=", 1) for a in sys.argv[1:]).get("count", 3)))
