"""Coverage-closure chart of the UVM matrix on the buggy DUT, from out/matrix_summary.json
(run flow2_uvm/matrix_summary.py first) -> out/fig_uvm_coverage_buggy.png"""
import json
from pathlib import Path

import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parents[1] / "out"
S = json.loads((OUT / "matrix_summary.json").read_text(encoding="utf-8"))
ROWS, DEPTH, SEEDS = S["curve_buggy"], S["depth_buggy"], S["seeds"]

INK, INK2, MUTED, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
STYLE = {"CRV": ("#2a78d6", "-"), "퍼저": ("#eda100", "--"), "BFS": ("#e87ba4", ":"), "RL": ("#1baf7a", "-")}
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Malgun Gothic", "Segoe UI", "DejaVu Sans"],
                     "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.facecolor": SURF, "figure.facecolor": SURF, "axes.unicode_minus": False})

fig, ax = plt.subplots(figsize=(8.5, 4.8))
ends = {}
for name, (color, ls) in STYLE.items():
    pts = [(r["m"], 100 * r["cov"]) for r in ROWS if r["method"] == name]
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, ls=ls, lw=2.2 if name == "RL" else 2, label=name)
    ends[name] = ys[-1]
placed = []
for name in sorted(ends, key=ends.get):  # end labels, nudged apart when close
    y = ends[name]
    while any(abs(y - p) < 3.5 for p in placed):
        y += 3.5
    placed.append(y)
    ax.annotate(f"{name} {ends[name]:.0f}% (최대 깊이 {DEPTH[name]['max']})", (xs[-1], ends[name]),
                xytext=(xs[-1] * 1.01, y), textcoords="data", va="center", color=INK2, fontsize=9)
ax.set_ylim(0, 105)
ax.set_xlim(0, xs[-1] * 1.32)
ax.set_xlabel("DUT 트랜잭션 수 (백만)")
ax.set_ylabel("스펙 커버리지 (빈 71개 중, %)")
ax.set_title("버그 DUT: RL만 스펙 커버리지 71/71 + 버그 검출", loc="left", color=INK, fontsize=13,
             fontweight="bold", pad=22)
ax.text(0, 1.02, f"UVM(Icarus + pyuvm), 시드 {SEEDS}개 중앙값. 버그 = 깊이 8, "
        f"RL 검출 중앙값 {DEPTH['RL']['depth8_at_median']:,.0f}번째 트랜잭션",
        transform=ax.transAxes, color=INK2, fontsize=9)
ax.grid(True, color=GRID, lw=0.6)
ax.set_axisbelow(True)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
ax.legend(frameon=False, fontsize=9, loc="center right", bbox_to_anchor=(0.76, 0.62), labelcolor=INK2)
fig.tight_layout()
fig.savefig(OUT / "fig_uvm_coverage_buggy.png", dpi=160)
print(f"saved {OUT / 'fig_uvm_coverage_buggy.png'}")
