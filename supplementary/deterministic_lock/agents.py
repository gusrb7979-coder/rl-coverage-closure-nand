"""Stimulus generators. Every method is charged in the same currency:
DUT cycles (= transactions driven) until the bug state is first reached.
"""
import numpy as np


def random_crv(dut, max_steps, rng, chunk=1 << 16):
    """Constrained-random baseline, given its BEST case: one endless stream,
    no per-test reset overhead."""
    dut.reset()
    steps = 0
    while steps < max_steps:
        for a in rng.integers(0, dut.n_actions, chunk).tolist():
            steps += 1
            if dut.step(a) == dut.depth:
                return steps
            if steps >= max_steps:
                break
    return None


def random_crv_expected(depth, n_actions=4):
    """Closed form for strict-reset lock: T_k = n*(T_{k-1}+1) -> sum_{k=1..d} n^k."""
    return sum(n_actions ** k for k in range(1, depth + 1))


def coverage_fuzzer(dut, max_steps, rng, max_ext=4):
    """AFL-style coverage-guided fuzzer: keep any input that hit a new
    (state, action, next_state) bin, then mutate by appending random tokens."""
    corpus, seen, steps = [[]], set(), 0
    while steps < max_steps:
        seed = corpus[rng.integers(len(corpus))]
        inp = seed + rng.integers(0, dut.n_actions, rng.integers(1, max_ext + 1)).tolist()
        s, new = dut.reset(), False
        for a in inp:
            s2 = dut.step(a)
            steps += 1
            if s2 == dut.depth:
                return steps, inp
            if (s, a, s2) not in seen:
                seen.add((s, a, s2))
                new = True
            s = s2
        if new:
            corpus.append(inp)
    return None, None


def coverage_fuzzer_smart(dut, max_steps, rng, max_ext=4):
    """Stronger fuzzer: coverage bins = FSM states only, and each saved seed is
    truncated right where it first reached the new state (no dead-end tails)."""
    corpus, seen, steps = [[]], {0}, 0
    while steps < max_steps:
        seed = corpus[rng.integers(len(corpus))]
        inp = seed + rng.integers(0, dut.n_actions, rng.integers(1, max_ext + 1)).tolist()
        dut.reset()
        for i, a in enumerate(inp):
            s2 = dut.step(a)
            steps += 1
            if s2 == dut.depth:
                return steps, inp[:i + 1]
            if s2 not in seen:
                seen.add(s2)
                corpus.append(inp[:i + 1])
    return None, None


def systematic_bfs(dut, rng):
    """Graph exploration of a deterministic DUT with reset: for each newly
    discovered state, try every action once from it. This is what a formal /
    exhaustive explorer does and is the practical lower bound here."""
    frontier, known, steps = [[]], {0}, 0
    while frontier:
        prefix = frontier.pop(0)
        for a in rng.permutation(dut.n_actions).tolist():
            dut.reset()
            for x in prefix:
                dut.step(x)
            s2 = dut.step(a)
            steps += len(prefix) + 1
            if s2 == dut.depth:
                return steps
            if s2 not in known:
                known.add(s2)
                frontier.append(prefix + [a])
    return None


class QLearnCDV:
    """Tabular Q-learning with a count-based curiosity reward r = beta/sqrt(N(s')).
    Observation = FSM state (grey-box coverage), like a coverage monitor gives."""

    def __init__(self, n_states, n_actions, rng, alpha=0.5, gamma=0.9, eps=0.1, beta=1.0):
        self.Q = np.zeros((n_states, n_actions))
        self.N = np.zeros(n_states)
        self.rng, self.alpha, self.gamma, self.eps, self.beta = rng, alpha, gamma, eps, beta

    def act(self, s, greedy=False):
        if not greedy and self.rng.random() < self.eps:
            return int(self.rng.integers(self.Q.shape[1]))
        q = self.Q[s]
        return int(self.rng.choice(np.flatnonzero(q == q.max())))

    def update(self, s, a, r, s2, terminal):
        target = r if terminal else r + self.gamma * self.Q[s2].max()
        self.Q[s, a] += self.alpha * (target - self.Q[s, a])

    def run_episode(self, dut, horizon, bug_reward=0.0):
        s, trace = dut.reset(), []
        for _ in range(horizon):
            a = self.act(s)
            s2 = dut.step(a)
            trace.append(a)
            self.N[s2] += 1
            hit = s2 == dut.depth
            r = self.beta / np.sqrt(self.N[s2]) + (bug_reward if hit else 0.0)
            self.update(s, a, r, s2, hit)
            if hit:
                return len(trace), trace, True
            s = s2
        return len(trace), trace, False


def rl_search(dut, max_steps, rng, horizon=None, **kw):
    """Curiosity-only search until first bug hit. Returns (steps, episodes, agent, trace)."""
    horizon = horizon or 2 * dut.depth
    agent = QLearnCDV(dut.n_states, dut.n_actions, rng, **kw)
    steps = eps_count = 0
    while steps < max_steps:
        n, trace, hit = agent.run_episode(dut, horizon)
        steps += n
        eps_count += 1
        if hit:
            return steps, eps_count, agent, trace
    return None, eps_count, agent, None


def rl_finetune(agent, dut, episodes, horizon, bug_reward=10.0):
    """After discovery, the bug bin becomes a known coverage target: add an
    extrinsic reward so the greedy policy reliably drives the DUT there."""
    for _ in range(episodes):
        agent.run_episode(dut, horizon, bug_reward=bug_reward)
    return agent


def replay_open_loop(dut, seq):
    """Phase-2 as proposed: driver replays a fixed .txt transaction list."""
    dut.reset()
    for a in seq:
        if dut.step(a) == dut.depth:
            return True
    return False


def replay_policy(dut, policy, horizon):
    """Reactive driver: reads DUT state each cycle and looks up the action
    in an exported policy ROM (state -> action)."""
    s = dut.reset()
    for _ in range(horizon):
        s = dut.step(int(policy[s]))
        if s == dut.depth:
            return True
    return False
