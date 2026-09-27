"""Transaction-level model (TLM) of the proposal's auth FSM (Moore machine).

State k (0..depth-1) means "k transactions of the magic sequence matched".
State `depth` is the bug state (Admin Unlocked). Any wrong transaction -> state 0,
exactly as the proposal specifies (this is what makes P(random hit) = 1/4^depth).
"""
import numpy as np

NOP, REQ, CHA, RES = 0, 1, 2, 3
ACTION_NAMES = ["NOP", "REQ", "CHA", "RES"]
PROPOSAL_SEQ = [REQ, RES, CHA, REQ, REQ, RES, CHA, RES]


def make_seq(depth, n_actions=4, seed=0):
    if depth == len(PROPOSAL_SEQ) and n_actions == 4:
        return list(PROPOSAL_SEQ)
    return list(np.random.default_rng(1000 + depth).integers(0, n_actions, depth))


class SeqLockDUT:
    def __init__(self, seq, n_actions=4, perturb_p=0.0, seed=None):
        self.seq = list(seq)
        self.depth = len(seq)
        self.n_states = self.depth + 1
        self.n_actions = n_actions
        # perturb_p: chance per cycle that an asynchronous event (another bus
        # master / session timeout) rewinds the FSM by 2 states. Models a
        # non-deterministic DUT where an open-loop stimulus file can desync.
        self.perturb_p = perturb_p
        self.rng = np.random.default_rng(seed)
        self.state = 0

    def reset(self):
        self.state = 0
        return 0

    def step(self, a):
        s = self.state
        if s == self.depth:  # bug state is absorbing
            return s
        s = s + 1 if a == self.seq[s] else 0
        if self.perturb_p and 0 < s < self.depth and self.rng.random() < self.perturb_p:
            s = max(s - 2, 0)
        self.state = s
        return s
