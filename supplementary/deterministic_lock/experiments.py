"""Validity check of the proposal's claims.

Exp1  Proposal FSM as specified (depth 8, 4 actions): Random vs Fuzzer vs RL.
Exp2  Depth sweep: where does random actually hit the "coverage wall"?
Exp3  Non-deterministic DUT: open-loop .txt replay vs closed-loop policy ROM.
"""
import json
import time
from pathlib import Path

import numpy as np

from agents import (coverage_fuzzer, coverage_fuzzer_smart, random_crv, systematic_bfs, random_crv_expected, replay_open_loop,
                    replay_policy, rl_finetune, rl_search)
from dut import ACTION_NAMES, PROPOSAL_SEQ, SeqLockDUT, make_seq

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
MAX_STEPS = 3_000_000


def stats(xs):
    xs = np.array([x for x in xs if x is not None], dtype=float)
    if len(xs) == 0:
        return None
    return {"median": float(np.median(xs)), "p10": float(np.percentile(xs, 10)),
            "p90": float(np.percentile(xs, 90)), "n": int(len(xs))}


def timed(fn):
    t = time.perf_counter()
    r = fn()
    return r, time.perf_counter() - t


def exp1(seeds=30):
    print("\n=== Exp1: proposal FSM (depth 8, seq = REQ RES CHA REQ REQ RES CHA RES) ===")
    seq = PROPOSAL_SEQ
    methods = ["random", "fuzzer", "fuzzer_smart", "rl", "bfs"]
    res = {k: [] for k in methods + ["t_" + m for m in methods] + ["rl_episodes"]}
    for sd in range(seeds):
        rng = np.random.default_rng(sd)
        r, t = timed(lambda: random_crv(SeqLockDUT(seq), MAX_STEPS, rng))
        res["random"].append(r); res["t_random"].append(t)
        (f, _), t = timed(lambda: coverage_fuzzer(SeqLockDUT(seq), MAX_STEPS, rng))
        res["fuzzer"].append(f); res["t_fuzzer"].append(t)
        (f, _), t = timed(lambda: coverage_fuzzer_smart(SeqLockDUT(seq), MAX_STEPS, rng))
        res["fuzzer_smart"].append(f); res["t_fuzzer_smart"].append(t)
        (q, ep, _, _), t = timed(lambda: rl_search(SeqLockDUT(seq), MAX_STEPS, rng))
        res["rl"].append(q); res["rl_episodes"].append(ep); res["t_rl"].append(t)
        b, t = timed(lambda: systematic_bfs(SeqLockDUT(seq), rng))
        res["bfs"].append(b); res["t_bfs"].append(t)

    summary = {k: stats(v) for k, v in res.items()}
    summary["random_expected_closed_form"] = random_crv_expected(8)
    for k in methods:
        s, t = summary[k], summary["t_" + k]
        print(f"{k:12s} cycles-to-bug median {s['median']:>9.0f}  (p10 {s['p10']:.0f}, p90 {s['p90']:.0f})"
              f"  wall {t['median']*1e3:7.1f} ms   found {s['n']}/{seeds}")
    print(f"rl episodes-to-bug median {summary['rl_episodes']['median']:.0f} "
          f"(p10 {summary['rl_episodes']['p10']:.0f}, p90 {summary['rl_episodes']['p90']:.0f})")
    print(f"closed-form E[random cycles] = {summary['random_expected_closed_form']}")

    # Full Phase-1 pipeline once: discover -> fine-tune -> export artifacts.
    rng = np.random.default_rng(123)
    t0 = time.perf_counter()
    dut = SeqLockDUT(seq)
    _, _, agent, _ = rl_search(dut, MAX_STEPS, rng)
    rl_finetune(agent, dut, episodes=300, horizon=16)
    policy = agent.Q.argmax(1)
    dut.reset(); golden = []
    s = 0
    while s != dut.depth and len(golden) < 32:
        a = int(policy[s]); golden.append(a); s = dut.step(a)
    t_pipeline = time.perf_counter() - t0
    (OUT / "stimulus.txt").write_text("".join(f"{a:x}\n" for a in golden))
    (OUT / "policy_rom.mem").write_text("".join(f"{int(a):x}\n" for a in policy))
    print(f"Phase-1 pipeline (search+finetune+export) wall time: {t_pipeline:.2f} s")
    print("exported stimulus:", " ".join(ACTION_NAMES[a] for a in golden))
    summary["pipeline_seconds"] = t_pipeline
    summary["exported_stimulus"] = [ACTION_NAMES[a] for a in golden]
    return summary


def exp2(depths=(4, 6, 8, 10, 12, 16, 20, 24), seeds=20):
    print("\n=== Exp2: depth sweep (cycles to first bug hit, median of seeds) ===")
    rows = []
    for d in depths:
        seq = make_seq(d)
        row = {"depth": d, "random_expected": random_crv_expected(d)}
        rnd_seeds = {4: 20, 6: 20, 8: 20, 10: 5}.get(d, 0)  # beyond 10: closed form only
        if rnd_seeds:
            row["random_sim"] = stats([random_crv(SeqLockDUT(seq), 10 * MAX_STEPS,
                                                  np.random.default_rng(s)) for s in range(rnd_seeds)])
        fz, fzs, rl, rl_ep, bfs = [], [], [], [], []
        for s in range(seeds):
            rng = np.random.default_rng(s)
            fz.append(coverage_fuzzer(SeqLockDUT(seq), MAX_STEPS, rng)[0])
            fzs.append(coverage_fuzzer_smart(SeqLockDUT(seq), MAX_STEPS, rng)[0])
            q, ep, _, _ = rl_search(SeqLockDUT(seq), MAX_STEPS, rng)
            rl.append(q); rl_ep.append(ep)
            bfs.append(systematic_bfs(SeqLockDUT(seq), rng))
        row.update(fuzzer=stats(fz), fuzzer_smart=stats(fzs), rl=stats(rl),
                   rl_episodes=stats(rl_ep), bfs=stats(bfs))
        rows.append(row)
        rs = row.get("random_sim")
        print(f"d={d:2d}  random E={row['random_expected']:>20,.0f}"
              f"  sim={'%.0f' % rs['median'] if rs else '-':>8}"
              f"  fuzzer={row['fuzzer']['median']:>8.0f}  fuzzer_smart={row['fuzzer_smart']['median']:>6.0f}"
              f"  rl={row['rl']['median']:>6.0f} ({row['rl_episodes']['median']:.0f} ep)"
              f"  bfs={row['bfs']['median']:>5.0f}")
    return rows


def exp3(ps=(0.0, 0.05, 0.1, 0.2, 0.3), trials=2000, seeds=10):
    print("\n=== Exp3: non-deterministic DUT (async rewind w.p. p per cycle) ===")
    seq, d = PROPOSAL_SEQ, len(PROPOSAL_SEQ)
    rows = []
    for p in ps:
        ol, cl, fz, rl = [], [], [], []
        for sd in range(seeds):
            rng = np.random.default_rng(sd)
            fz.append(coverage_fuzzer_smart(SeqLockDUT(seq, perturb_p=p, seed=sd), MAX_STEPS, rng)[0])
            dut = SeqLockDUT(seq, perturb_p=p, seed=sd)
            q, _, agent, _ = rl_search(dut, MAX_STEPS, rng, horizon=4 * d)
            rl.append(q)
            rl_finetune(agent, dut, episodes=500, horizon=4 * d)
            policy = agent.Q.argmax(1)
            test = SeqLockDUT(seq, perturb_p=p, seed=10_000 + sd)
            ol.append(np.mean([replay_open_loop(test, seq) for _ in range(trials)]))
            cl.append(np.mean([replay_policy(test, policy, 4 * d) for _ in range(trials)]))
        row = {"p": p, "open_loop_success": float(np.mean(ol)), "policy_success": float(np.mean(cl)),
               "fuzzer": stats(fz), "rl": stats(rl)}
        rows.append(row)
        print(f"p={p:.2f}  open-loop .txt success {row['open_loop_success']*100:5.1f}%   "
              f"policy-ROM success {row['policy_success']*100:5.1f}%   "
              f"discovery cycles: fuzzer_smart {row['fuzzer']['median']:.0f}, rl {row['rl']['median']:.0f}")
    return rows


if __name__ == "__main__":
    t = time.perf_counter()
    results = {"exp1": exp1(), "exp2": exp2(), "exp3": exp3()}
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    print(f"\ntotal {time.perf_counter() - t:.1f} s -> {OUT / 'results.json'}")
