"""Where RL beats coverage-guided fuzzing and BFS: a DUT-generated nonce.

Challenge-response auth: at some states the DUT emits a random nonce (TRNG/LFSR),
visible on its output bus. The only accepted next transaction is f(state, nonce),
and f is unknown to every agent. An open-loop input sequence (fuzzer corpus entry,
BFS prefix, stimulus.txt) reproduces its path only if every nonce repeats, so
replay-based methods lose their foothold. A state-conditioned policy does not.
Everything is at transaction level: no clocks, only order and data.
"""
import json
import time
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


class NonceLockDUT:
    def __init__(self, depth=8, k_nonce=2, n_actions=16, n_nonce=16, seed=None, seq_seed=0):
        self.depth, self.n_actions, self.n_nonce = depth, n_actions, n_nonce
        self.seq = np.random.default_rng(seq_seed).integers(0, n_actions, depth).tolist()
        self.nonce_states = (set(np.linspace(1, depth - 1, k_nonce).round().astype(int).tolist())
                             if k_nonce else set())
        self.n_obs = (depth + 1) * n_nonce
        self.rng = np.random.default_rng(seed)
        self.reset()

    def _enter(self, s):
        self.state = s
        self.nonce = int(self.rng.integers(self.n_nonce)) if s in self.nonce_states else 0
        return self.obs()

    def obs(self):
        return self.state * self.n_nonce + self.nonce

    def reset(self):
        return self._enter(0)

    def step(self, a):
        if self.state == self.depth:
            return self.obs()
        ok = a == (self.seq[self.state] + self.nonce) % self.n_actions
        return self._enter(self.state + 1 if ok else 0)


def fuzzer_smart(dut, max_steps, rng, max_ext=4):
    corpus, seen, steps = [[]], {0}, 0
    while steps < max_steps:
        seed = corpus[rng.integers(len(corpus))]
        inp = seed + rng.integers(0, dut.n_actions, rng.integers(1, max_ext + 1)).tolist()
        dut.reset()
        for i, a in enumerate(inp):
            dut.step(a)
            steps += 1
            if dut.state == dut.depth:
                return steps, inp[:i + 1]
            if dut.state not in seen:
                seen.add(dut.state)
                corpus.append(inp[:i + 1])
    return None, None


def bfs_restarts(dut, max_steps, rng):
    """Deterministic graph exploration, restarted whenever its frontier runs dry."""
    steps = 0
    while steps < max_steps:
        frontier, known = [[]], {0}
        while frontier and steps < max_steps:
            prefix = frontier.pop(0)
            for a in rng.permutation(dut.n_actions).tolist():
                dut.reset()
                for x in prefix:
                    dut.step(x)
                dut.step(a)
                steps += len(prefix) + 1
                if dut.state == dut.depth:
                    return steps
                if dut.state not in known:
                    known.add(dut.state)
                    frontier.append(prefix + [a])
    return None


class QAgent:
    def __init__(self, n_obs, n_actions, rng, alpha=0.5, gamma=0.9, eps=0.1, beta=1.0, q_init=0.0):
        # q_init > 0 = optimistic initialization: untried actions look better than
        # tried ones, so the agent does not settle on a known-wrong action whose
        # abort-to-IDLE target already has a high value.
        self.Q = np.full((n_obs, n_actions), q_init)
        self.N = np.zeros(n_obs)
        self.rng, self.alpha, self.gamma, self.eps, self.beta = rng, alpha, gamma, eps, beta

    def act(self, o, greedy=False):
        if not greedy and self.rng.random() < self.eps:
            return int(self.rng.integers(self.Q.shape[1]))
        q = self.Q[o]
        return int(self.rng.choice(np.flatnonzero(q == q.max())))

    def episode(self, dut, horizon, bug_reward=0.0):
        o, n = dut.reset(), 0
        for _ in range(horizon):
            a = self.act(o)
            o2 = dut.step(a)
            n += 1
            self.N[o2] += 1
            hit = dut.state == dut.depth
            r = self.beta / np.sqrt(self.N[o2]) + (bug_reward if hit else 0.0)
            target = r if hit else r + self.gamma * self.Q[o2].max()
            self.Q[o, a] += self.alpha * (target - self.Q[o, a])
            if hit:
                return n, True
            o = o2
        return n, False


def rl_search(dut, max_steps, rng):
    agent, steps = QAgent(dut.n_obs, dut.n_actions, rng), 0
    while steps < max_steps:
        n, hit = agent.episode(dut, 2 * dut.depth)
        steps += n
        if hit:
            return steps, agent
    return None, agent


def replay_seq(dut, seq):
    dut.reset()
    for a in seq:
        dut.step(a)
        if dut.state == dut.depth:
            return True
    return False


def replay_policy(dut, policy, horizon):
    o = dut.reset()
    for _ in range(horizon):
        o = dut.step(int(policy[o]))
        if dut.state == dut.depth:
            return True
    return False


def main(ks=(0, 1, 2, 3, 4), seeds=8, max_steps=2_000_000, trials=1000, n_actions=16):
    rows = []
    for k in ks:
        fz, bf, rl, fz_rep, rl_rep, t_rl, rl_train = [], [], [], [], [], [], []
        for sd in range(seeds):
            rng = np.random.default_rng(sd)
            f, seq = fuzzer_smart(NonceLockDUT(k_nonce=k, n_actions=n_actions, seed=sd), max_steps, rng)
            fz.append(f)
            bf.append(bfs_restarts(NonceLockDUT(k_nonce=k, n_actions=n_actions, seed=100 + sd), max_steps, rng))
            t0 = time.perf_counter()
            dut = NonceLockDUT(k_nonce=k, n_actions=n_actions, seed=200 + sd)
            q, agent = rl_search(dut, max_steps, rng)
            rl.append(q)
            t_rl.append(time.perf_counter() - t0)
            test = NonceLockDUT(k_nonce=k, n_actions=n_actions, seed=9000 + sd)
            if seq is not None:
                fz_rep.append(np.mean([replay_seq(test, seq) for _ in range(trials)]))
            if q is not None:
                # keep training until the greedy policy closes the bug bin >= 99% of the time
                extra = 0
                while extra < max_steps:
                    for _ in range(500):
                        extra += agent.episode(dut, 2 * dut.depth, bug_reward=10.0)[0]
                    policy = agent.Q.argmax(1)
                    if np.mean([replay_policy(test, policy, 2 * dut.depth) for _ in range(200)]) >= 0.99:
                        break
                rl_train.append(q + extra)
                rl_rep.append(np.mean([replay_policy(NonceLockDUT(k_nonce=k, n_actions=n_actions, seed=7000 + sd),
                                                      policy, 2 * dut.depth) for _ in range(trials)]))

        def med(xs):
            ok = [x for x in xs if x is not None]
            return {"median": float(np.median(ok)) if len(ok) == len(xs) else None,
                    "found": f"{len(ok)}/{len(xs)}"}
        row = {"k_nonce": k, "n_actions": n_actions, "seeds": seeds, "fuzzer": med(fz), "bfs": med(bf), "rl": med(rl),
               "fuzzer_replay": float(np.mean(fz_rep)) if fz_rep else None,
               "rl_policy_replay": float(np.mean(rl_rep)) if rl_rep else None,
               "rl_cycles_to_99pct_policy": med(rl_train),
               "rl_seconds": float(np.median(t_rl))}
        rows.append(row)
        fmt = lambda m: f"{m['median']:>9.0f}" if m["median"] is not None else f"  >{max_steps:.0e}"
        print(f"K={k}  fuzzer {fmt(row['fuzzer'])} ({row['fuzzer']['found']})"
              f"  bfs {fmt(row['bfs'])} ({row['bfs']['found']})"
              f"  rl {fmt(row['rl'])} ({row['rl']['found']}, {row['rl_seconds']:.1f}s)"
              f"  rl->99% policy {fmt(row['rl_cycles_to_99pct_policy'])}"
              f"  | replay: fuzzer seq {row['fuzzer_replay'] if row['fuzzer_replay'] is None else round(100 * row['fuzzer_replay'], 1)}%"
              f"  rl policy {row['rl_policy_replay'] if row['rl_policy_replay'] is None else round(100 * row['rl_policy_replay'], 1)}%")
    (OUT / "nonce_results.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    # results/supplementary/nonce_results.json: python supplementary/nonce/nonce_exp.py n_actions=64 seeds=5
    import sys
    kv = dict(a.split("=", 1) for a in sys.argv[1:])
    na, sds = int(kv.get("n_actions", 16)), int(kv.get("seeds", 8))
    print(f"depth 8, {na} actions, 16-value nonce, {sds} seeds; K = number of nonce rounds on the bug path")
    main(seeds=sds, n_actions=na)
