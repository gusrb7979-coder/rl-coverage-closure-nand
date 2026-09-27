"""Flow 1, step 4: coverage-closure chart from out/nand_compare.json -> out/fig_coverage_closure.png"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
R = json.loads((OUT / "nand_compare.json").read_text())
BUDGET, CKPT = R.pop("budget"), R.pop("ckpt")
SEEDS = len(R["RL"])

INK, INK2, MUTED, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
# validated categorical order (blue, yellow, magenta, aqua); line styles as secondary encoding
STYLE = {"CRV": ("#2a78d6", "-"), "Fuzzer": ("#eda100", "--"), "BFS": ("#e87ba4", ":"), "RL": ("#1baf7a", "-")}
LABEL = {"CRV": "CRV", "Fuzzer": "퍼저", "BFS": "BFS", "RL": "RL"}
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Malgun Gothic", "Segoe UI", "DejaVu Sans"],
                     "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.facecolor": SURF, "figure.facecolor": SURF, "axes.unicode_minus": False})

n = BUDGET // CKPT
x = np.arange(1, n + 1) * CKPT / 1e6
fig, ax = plt.subplots(figsize=(8.5, 4.8))
ends = {}
for name, rows in R.items():
    curves = [(r["curve"] + [r["final_cov"]] * (n - len(r["curve"])))[:n] for r in rows]
    med = np.median(np.array(curves), axis=0)
    color, ls = STYLE[name]
    ax.plot(x, med, color=color, ls=ls, lw=2.2 if name == "RL" else 2, label=LABEL[name])
    ends[name] = med[-1]
# end labels, nudged apart when values are close
placed = []
for name in sorted(ends, key=ends.get):
    y = ends[name]
    while any(abs(y - p) < 3.5 for p in placed):
        y += 3.5
    placed.append(y)
    ax.annotate(f"{LABEL[name]} {ends[name]:.0f}%", (x[-1], ends[name]), xytext=(x[-1] * 1.01, y),
                textcoords="data", va="center", color=INK2, fontsize=9)
ax.set_ylim(0, 105)
ax.set_xlim(0, BUDGET / 1e6 * 1.18)
ax.set_xlabel("DUT 트랜잭션 수 (백만)")
ax.set_ylabel("기능 커버리지 (%)")
ax.set_title("CRV·퍼저·BFS는 정체, RL만 스펙 커버리지 71/71 + 위반 검출", loc="left", color=INK, fontsize=13,
             fontweight="bold", pad=22)
ax.text(0, 1.02, f"NAND 읽기 오류 복구 컨트롤러(버그 버전), 빈 73개 = 스펙 커버리지 71 + 스펙 위반 이벤트 2, "
        f"시드 {SEEDS}개 중앙값",
        transform=ax.transAxes, color=INK2, fontsize=9)
ax.grid(True, color=GRID, lw=0.6)
ax.set_axisbelow(True)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
ax.legend(frameon=False, fontsize=9, loc="center right", bbox_to_anchor=(0.86, 0.62), labelcolor=INK2)
fig.tight_layout()
fig.savefig(OUT / "fig_coverage_closure.png", dpi=160)
print(f"saved {OUT / 'fig_coverage_closure.png'}")
