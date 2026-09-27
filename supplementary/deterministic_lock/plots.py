import json
from pathlib import Path

import matplotlib.pyplot as plt

OUT = Path(__file__).parent / "out"
R = json.loads((OUT / "results.json").read_text())

INK, INK2, MUTED, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
S = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "Malgun Gothic", "DejaVu Sans"],
                     "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.facecolor": SURF, "figure.facecolor": SURF})


def style(ax, title, subtitle):
    ax.set_title(title, loc="left", color=INK, fontsize=13, fontweight="bold", pad=22)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=INK2, fontsize=9)
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)


def end_label(ax, x, y, text, dy=0):
    ax.annotate(text, (x, y), xytext=(6, dy), textcoords="offset points", va="center",
                color=INK2, fontsize=9)


# Fig 1: depth scaling
rows = R["exp2"]
d = [r["depth"] for r in rows]
fig, ax = plt.subplots(figsize=(8.5, 5))
series = [
    ("Random CRV (closed form)", [r["random_expected"] for r in rows], S[0], "o"),
    ("Coverage fuzzer (basic)", [r["fuzzer"]["median"] for r in rows], S[1], "s"),
    ("RL curiosity (Q-learning)", [r["rl"]["median"] for r in rows], S[2], "D"),
    ("Coverage fuzzer (smart)", [r["fuzzer_smart"]["median"] for r in rows], S[3], "^"),
    ("Systematic BFS (lower bound)", [r["bfs"]["median"] for r in rows], S[4], "v"),
]
for name, ys, c, m in series:
    ax.plot(d, ys, color=c, lw=2, marker=m, ms=8, mec=SURF, mew=2, label=name)
    end_label(ax, d[-1], ys[-1], name.split(" (")[0] if "fuzzer" not in name else name)
sim = [(r["depth"], r["random_sim"]["median"]) for r in rows if "random_sim" in r]
ax.scatter(*zip(*sim), s=90, facecolors="none", edgecolors=S[0], lw=1.5, zorder=5,
           label="Random CRV (simulated)")
ax.axvline(8, color=AXIS, lw=1, ls="--")
ax.text(7.8, 1e8, "proposal\n(depth 8)", color=MUTED, fontsize=9, ha="right")
ax.set_yscale("log")
ax.set_xlabel("Sequence depth (transactions to reach bug state)")
ax.set_ylabel("DUT cycles to first bug hit (median)")
ax.set_xlim(3, 31)
ax.set_xticks(d)
style(ax, "Cycles needed to hit the bug, by sequence depth",
      "Random grows like 4^d; every coverage-feedback method grows polynomially. 20 seeds per point.")
ax.legend(frameon=False, fontsize=8.5, loc="upper left", labelcolor=INK2)
fig.tight_layout()
fig.savefig(OUT / "fig1_depth_scaling.png", dpi=160)

# Fig 2: robustness under non-determinism
rows = R["exp3"]
p = [r["p"] for r in rows]
fig, ax = plt.subplots(figsize=(7.5, 4.5))
ol = [100 * r["open_loop_success"] for r in rows]
cl = [100 * r["policy_success"] for r in rows]
ax.plot(p, cl, color=S[0], lw=2, marker="o", ms=8, mec=SURF, mew=2, label="Closed-loop policy ROM (state → action)")
ax.plot(p, ol, color=S[1], lw=2, marker="s", ms=8, mec=SURF, mew=2, label="Open-loop stimulus.txt replay")
end_label(ax, p[-1], cl[-1], f"Policy ROM {cl[-1]:.0f}%")
end_label(ax, p[-1], ol[-1], f"Open-loop .txt {ol[-1]:.0f}%")
ax.set_ylim(0, 105)
ax.set_xlim(-0.01, 0.4)
ax.set_xlabel("p = probability per cycle of an async rewind (other master / timeout)")
ax.set_ylabel("Replay success rate (%)")
style(ax, "Replay success on a non-deterministic DUT",
      "Depth-8 proposal FSM, 2,000 replays × 10 trained agents per point")
ax.legend(frameon=False, fontsize=9, loc="lower left", labelcolor=INK2)
fig.tight_layout()
fig.savefig(OUT / "fig2_closed_loop.png", dpi=160)
print("saved")
