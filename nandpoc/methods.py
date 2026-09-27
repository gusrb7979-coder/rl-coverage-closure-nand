"""Stimulus methods on the transaction-level model: CRV, coverage fuzzer, BFS, RL, policy replay.
All methods drive the same model and are charged in DUT transactions; coverage is merged
across resets, as in a regression. The pyuvm sequences in flow2_uvm/tb_nand.py mirror these
functions exactly, so the same seeds give the same numbers on the RTL.
"""
from .nand_dut import BUG, N_BINS, NandRecoveryDUT
from .rl_agent import CoverageQAgent

BUDGET, CKPT = 3_000_000, 20_000   # transactions per run, coverage-curve sample period


class Tracker:
    """Wraps a DUT, counts transactions and samples the coverage curve."""

    def __init__(self, dut):
        self.dut, self.steps, self.curve, self.bug_at, self.full_at = dut, 0, [], None, None
        self.polish_steps = None
        self.max_depth, self.depth_at = 0, {}   # deepest state reached (8 = violation), first tx per depth
        self.deep_entries = {str(d): [] for d in range(5, 9)}   # tx of every entry into states 5..8
        self.hint_hist = {str(d): [0] * 16 for d in (1, 3, 5)}  # hint seen on entering states 1/3/5
        self.deep_commits = 0   # commits made from MAP_PENDING (the deepest step)

    def step(self, a):
        prev = self.dut.state
        new = self.dut.step(a)
        self.steps += 1
        s = self.dut.state
        self.deep_commits += int(prev == 7 and self.dut.commit)
        if s != prev:
            if s >= 5:
                self.deep_entries[str(s)].append(self.steps)
            if s in (1, 3, 5):
                self.hint_hist[str(s)][self.dut.hint] += 1
        if self.dut.state > self.max_depth:
            self.max_depth = self.dut.state
            self.depth_at[self.dut.state] = self.steps
        if self.bug_at is None and self.dut.state == BUG:
            self.bug_at = self.steps
        if self.full_at is None and len(self.dut.covered) == N_BINS:
            self.full_at = self.steps
        if self.steps % CKPT == 0:
            self.curve.append(self.dut.coverage())
        return new

    def done(self):
        return self.steps >= BUDGET or self.full_at is not None


def crv(t, rng, test_len=1000):
    """Constrained-random baseline: tests of test_len random transactions, reset in between."""
    while not t.done():
        t.dut.reset()
        for a in rng.integers(0, 64, test_len).tolist():
            t.step(a)
            if t.done():
                return


def fuzzer(t, rng, max_ext=4):
    """Coverage-guided fuzzer: keep inputs that hit new bins, extend them randomly."""
    corpus = [[]]
    while not t.done():
        inp = corpus[rng.integers(len(corpus))] + rng.integers(0, 64, rng.integers(1, max_ext + 1)).tolist()
        t.dut.reset()
        last_new = -1
        for i, a in enumerate(inp):
            if t.step(a):
                last_new = i
            if t.done():
                return
        if last_new >= 0:
            corpus.append(inp[:last_new + 1])


def bfs(t, rng):
    """Systematic exploration: try every transaction once from each newly found state."""
    while not t.done():
        frontier, known = [[]], {0}
        while frontier and not t.done():
            prefix = frontier.pop(0)
            for a in rng.permutation(64).tolist():
                t.dut.reset()
                for x in prefix:
                    t.step(x)
                t.step(a)
                if t.done():
                    return
                if t.dut.state not in known:
                    known.add(t.dut.state)
                    frontier.append(prefix + [a])


def rl_episode(ag, dut, step, horizon=32):
    o = dut.reset()
    for _ in range(horizon):
        a = ag.act(o)
        new = step(a)
        o2, hit = dut.obs(), dut.state == BUG
        ag.learn(o, a, new, o2, hit)
        if hit:
            return True
        o = o2
    return False


def rl(t, rng, polish=True, max_polish=2_000_000, check_every=50_000):
    """Phase A (coverage closure): Q-learning with coverage reward until 100% or budget.
    Phase B (policy polish, not counted in the closure cost): keep training on the bug bin
    until the greedy policy replays it >= 99% of the time. Returns the policy table."""
    ag = CoverageQAgent(t.dut.n_obs, 64, rng)
    while not t.done():
        rl_episode(ag, t.dut, t.step)
    if polish and t.bug_at is not None:
        extra, counter = 0, [0]

        def step(a):
            counter[0] += 1
            return t.dut.step(a)
        while extra < max_polish:
            while counter[0] - extra < check_every:
                rl_episode(ag, t.dut, step)
            extra = counter[0]
            if replay_policy(ag.Q.argmax(1), seed=0x6000, trials=200) >= 0.99:
                t.polish_steps = extra
                break
    return ag.Q.argmax(1)


def replay_policy(policy, seed, trials=1000, horizon=200, buggy=True):
    """Fraction of fresh episodes in which following the policy table reaches the bug."""
    ok = 0
    dut = NandRecoveryDUT(seed=seed, buggy=buggy)
    for _ in range(trials):
        o = dut.reset()
        for _ in range(horizon):
            dut.step(int(policy[o]))
            o = dut.obs()
            if dut.state == BUG:
                ok += 1
                break
    return ok / trials


METHODS = {"CRV": crv, "Fuzzer": fuzzer, "BFS": bfs, "RL": rl}
