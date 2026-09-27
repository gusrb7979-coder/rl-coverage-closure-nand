"""Full state diagrams of the NAND read-recovery controller, one per RTL version, same layout:
  docs/fsm_golden.png  (rtl/nand_recovery_golden.v)
  docs/fsm_buggy.png   (rtl/nand_recovery_buggy.v)
They differ only at transition 3 (rewrite, RTL line 88) and at the final commit 4.
Sized for a PDF page: 15.5 in wide, text 12.5-21 pt. Labels: command [NAND result] / effect.
usage: python docs/make_fsm_diagram.py"""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch

HERE = Path(__file__).resolve().parent
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Malgun Gothic", "Segoe UI", "DejaVu Sans"],
                     "axes.unicode_minus": False})

INK, SUB, EDGE = "#111111", "#444444", "#333333"
WARN, HINT, OK, BAD, GRAY, FIX = "#e08a00", "#2a6fd6", "#0f9466", "#d02f2f", "#8a8a8a", "#444444"
W, H = 22, 12                      # box size (1 unit = 0.1 in)
YA, YB = 72, 34                    # rows
XS = [13, 41, 69, 97, 125]         # columns, row A
XB = [25, 55, 97, 125]             # columns, row B: violation, MAP_PENDING, RECOVERED2, ECC_FAIL2
RAIL_TOP, RAIL_BOT, RAIL_OK, RAIL_X = 92, 18, 55, -2.5
LS = 2.6                           # label line spacing


def draw(buggy):
    fig = plt.figure(figsize=(15.5, 10.8), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(-5, 150)
    ax.set_ylim(-2, 106)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    def box(x, y, name, lines, color=EDGE, fill="white", lw=2.2, ls="-"):
        ax.add_patch(FancyBboxPatch((x - W / 2, y - H / 2), W, H, boxstyle="round,pad=0,rounding_size=1.4",
                                    fc=fill, ec=color, lw=lw, ls=ls, zorder=3))
        ax.text(x, y + 2.6, name, ha="center", va="center", fontsize=18, fontweight="bold", color=INK, zorder=4)
        for i, s in enumerate(lines):
            ax.text(x, y - 1.4 - 2.6 * i, s, ha="center", va="center", fontsize=13.5, color=SUB, zorder=4)

    def arrow(p, q, color, ls="-", lw=2.6):
        ax.annotate("", xy=q, xytext=p, zorder=2,
                    arrowprops=dict(arrowstyle="-|>,head_length=0.8,head_width=0.4", color=color, lw=lw, ls=ls,
                                    shrinkA=0, shrinkB=0))

    def line(xs, ys, color, ls="-", lw=2.6):
        ax.plot(xs, ys, color=color, ls=ls, lw=lw, zorder=2, solid_capstyle="butt")

    def label(x, y, lines, ha="center", color=INK, size=14, bold_first=True):
        for i, s in enumerate(lines):
            ax.text(x, y - LS * i, s, ha=ha, va="center", fontsize=size, color=color,
                    fontweight="bold" if (bold_first and i == 0) else "normal", zorder=5)

    # ---- title
    if buggy:
        title, sub = ("버그 DUT (rtl/nand_recovery_buggy.v) — 전체 상태 다이어그램",
                      "정상 DUT와 다른 곳: ③ 재기록 전이(88번 줄)와 그 결과인 ④ 확정. 나머지는 정상 DUT와 같음")
    else:
        title, sub = ("정상 DUT (rtl/nand_recovery_golden.v) — 전체 상태 다이어그램",
                      "스펙: 오류가 몇 번 겹쳐도 확정 1회에 매핑은 정확히 1건")
    ax.text(-3, 103, title, fontsize=21, fontweight="bold", color=BAD if buggy else INK, va="center")
    ax.text(-3, 99, sub + "     |  전이 표기: 명령 [NAND 결과] / 결과, h = 직전 실패에서 받은 실패 정보(hint_o)",
            fontsize=12.5, color=SUB, va="center")

    # ---- states
    box(XS[0], YA, "IDLE", ["state_o = 0"])
    box(XS[1], YA, "ECC_FAIL", ["state_o = 1", "hint_o = h1"])
    box(XS[2], YA, "RECOVERED", ["state_o = 2"])
    box(XS[3], YA, "PGM_FAIL", ["state_o = 3", "hint_o = h2"])
    box(XS[4], YA, "RELOCATED", ["state_o = 4"])
    box(XB[3], YB, "ECC_FAIL2", ["state_o = 5", "hint_o = h3"])
    box(XB[2], YB, "RECOVERED2", ["state_o = 6"])
    box(XB[1], YB, "MAP_PENDING", ["state_o = 7"])
    if buggy:
        box(XB[0], YB, "스펙 위반", ["매핑 2건 기록", "→ 테스트 FAIL"], color=BAD, fill="#fff5f5", lw=2.8, ls="--")

    # ---- reset into IDLE
    ax.add_patch(Circle((6, 86), 1.1, color=INK, zorder=4))
    arrow((6, 84.9), (6, YA + H / 2), INK, "-", 2.2)
    ax.text(8, 86, "리셋", fontsize=13, color=INK, va="center")

    # ---- abort rails (states 1..7 -> IDLE)
    line([RAIL_X, XS[4]], [RAIL_TOP, RAIL_TOP], GRAY, "--", 1.8)
    for x in XS[1:]:
        line([x, x], [YA + H / 2, RAIL_TOP], GRAY, "--", 1.8)
    line([RAIL_X, XB[3]], [RAIL_BOT, RAIL_BOT], GRAY, "--", 1.8)
    for x in XB[1:]:
        line([x, x], [YB - H / 2, RAIL_BOT], GRAY, "--", 1.8)
    line([RAIL_X, RAIL_X], [RAIL_BOT, RAIL_TOP], GRAY, "--", 1.8)
    arrow((RAIL_X, YA), (XS[0] - W / 2, YA), GRAY, "--", 1.8)
    ax.text(75, RAIL_TOP + 2.3, "상태 1~7에서 기대 명령이 아니면 → IDLE  (err_o 1클럭 펄스, 예약 모두 삭제)",
            ha="center", va="center", fontsize=12.5, color=SUB)
    ax.text(75, RAIL_BOT - 2.3, "상태 5~7도 같음: 기대 명령이 아니면 → IDLE", ha="center", va="center",
            fontsize=12.5, color=SUB)

    # ---- IDLE self loop
    ax.annotate("", xy=(XS[0] - 2, YA - H / 2), xytext=(XS[0] - 7, YA - H / 2), zorder=2,
                arrowprops=dict(arrowstyle="-|>,head_length=0.6,head_width=0.3", color=FIX, lw=2,
                                connectionstyle="arc3,rad=1.5"))
    label(10, 58.5, ["READ 0xA [fail=0]", "또는 기타 명령"], size=12.5, bold_first=False)

    # ---- main path, row A
    arrow((XS[0] + W / 2, YA), (XS[1] - W / 2, YA), WARN, "--")
    label(27, 86.5, ["READ 0xA", "[fail=1]", "실패 정보 ← h1"])
    arrow((XS[1] + W / 2, YA), (XS[2] - W / 2, YA), HINT)
    label(55, 85.2, ["RETRY", "retry_table[h1]"])
    arrow((XS[2] + W / 2, YA), (XS[3] - W / 2, YA), WARN, "--")
    label(83, 86.5, ["REMAP 0x3 [fail=1]", "실패 정보 ← h2", "① slot0 예약→취소"])
    arrow((XS[3] + W / 2, YA), (XS[4] - W / 2, YA), HINT)
    label(111, 86.5, ["REMAP", "spare_table[h2]", "② slot1 예약"])

    # ---- RELOCATED -> ECC_FAIL2
    arrow((131, YA - H / 2), (131, YB + H / 2), WARN, "--")
    label(133, 55, ["READ 0x5", "[fail=1]", "실패 정보 ← h3"], ha="left")

    # ---- row B: ECC_FAIL2 -> RECOVERED2
    arrow((XB[3] - W / 2, YB), (XB[2] + W / 2, YB), HINT)
    label(119, 45.5, ["RETRY", "retry_table[h3]"])

    # ---- row B: RECOVERED2 -> MAP_PENDING (transition 3, RTL line 88)
    edge, fill, tag = (BAD, "#fdecec", "버그 코드") if buggy else (HINT, "#eef4fd", "88번 줄")
    ax.add_patch(FancyBboxPatch((67.5, 22.5), 18, 27.5, boxstyle="round,pad=0,rounding_size=1.4",
                                fc=fill, ec=edge, lw=3 if buggy else 2.2, zorder=1))
    arrow((XB[2] - W / 2, YB), (XB[1] + W / 2, YB), FIX)
    ax.text(76.5, 51.8, tag, fontsize=14, fontweight="bold", color=edge, ha="center", va="center")
    label(76.5, 46.5, ["③ STATUS 0x0", "재기록 전이"], color=INK, size=13.5)
    if buggy:
        label(76.5, 30.2, ["rsv_last = rsv_idx", "(-1 누락)", "→ 취소된 slot0 부활"], color=BAD, size=12.5)
    else:
        label(76.5, 30.2, ["rsv_last =", "rsv_idx - 1 = 1", "→ slot1에 덮어씀"], color=HINT, size=12.5)

    # ---- commit paths to IDLE (green rail)
    line([119, 119], [YA - H / 2, RAIL_OK], OK)
    line([76, 76], [YA - H / 2, RAIL_OK], OK)
    line([21, 119], [RAIL_OK, RAIL_OK], OK)
    arrow((21, RAIL_OK), (21, YA - H / 2), OK)
    label(117, 60.5, ["재읽기 성공 [fail=0]", "/ 확정 1건"], ha="right", color=OK)
    label(74.5, 60.5, ["쓰기 성공 [fail=0]", "/ 확정 1건"], ha="right", color=OK)
    if buggy:   # MAP_PENDING -> violation: the commit writes both slots
        arrow((XB[1] - W / 2, YB), (XB[0] + W / 2, YB), BAD, "--")
        label(40, 46.5, ["REMAP 0xF", "④ 확정 2건"], color=BAD)
    else:       # MAP_PENDING -> IDLE: the commit writes slot1 only
        line([60, 60], [YB + H / 2, RAIL_OK], OK)
        label(58.5, 50, ["REMAP 0xF", "/ ④ 확정 1건"], ha="right", color=OK)

    # ---- legend
    items = [(WARN, "--", "NAND 실패(p = 0.5), 실패 정보 무작위"), (HINT, "-", "실패 정보를 보고 반응해야 하는 전이"),
             (FIX, "-", "고정 명령 전이"), (OK, "-", "확정 성공 → IDLE (매핑 1건)"),
             (GRAY, "--", "오답 → IDLE (err_o 펄스)")]
    if buggy:
        items.append((BAD, "--", "버그의 결과: 매핑 2건 → FAIL"))
    for i, (c, ls, s) in enumerate(items):
        x, y = -2 + 51 * (i // 2), 9.5 - 4.2 * (i % 2)
        line([x, x + 6], [y, y], c, ls, 2.6)
        ax.text(x + 8, y, s, fontsize=13, color=INK, va="center")
    ax.add_patch(FancyBboxPatch((-2, -0.4), 6, 2.4, boxstyle="round,pad=0,rounding_size=0.5",
                                fc=fill, ec=edge, lw=2.4))
    ax.text(6, 0.8, "RTL 88번 줄(rsv_last)이 실행되는 유일한 전이" + ("  ← 버그" if buggy else ""),
            fontsize=13, color=INK, va="center")
    ax.add_patch(Circle((64, 0.8), 1.0, color=INK))
    ax.text(67, 0.8, "리셋: 전원 리셋(por_n)·호스트 리셋(rst_n) → IDLE", fontsize=13, color=INK, va="center")

    out = HERE / ("fsm_buggy.png" if buggy else "fsm_golden.png")
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    print(f"saved {out}")


if __name__ == "__main__":
    draw(buggy=False)
    draw(buggy=True)
