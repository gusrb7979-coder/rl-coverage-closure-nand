"""The coverage-driven Q-learning agent, shared by the Python experiments (nandpoc.methods)
and the pyuvm RL sequence (flow2_uvm/tb_nand.py) so both always run the same algorithm."""
import numpy as np


class CoverageQAgent:
    """Tabular Q-learning. Observation = (state, hint) as state*16 + hint, action = one of
    64 transactions (opcode*16 + param).
    Reward = new coverage bins + curiosity 1/sqrt(N(obs)), +10 when the spec-violation event is seen.
    Everything in it comes from the spec and the monitor/scoreboard: no RTL code, no table, no bug location.
    Optimistic initialization (Q0 = 10) makes untried actions look better than tried ones.
    After the first violation it switches to exploitation: gamma 0.99, alpha 0.2, no curiosity."""

    def __init__(self, n_obs, n_actions, rng, alpha=0.5, gamma=0.9, eps=0.1, beta=1.0, q_init=10.0):
        self.Q = np.full((n_obs, n_actions), q_init)
        self.N = np.zeros(n_obs)
        self.rng, self.alpha, self.gamma, self.eps, self.beta = rng, alpha, gamma, eps, beta

    def act(self, o, greedy=False):
        if not greedy and self.rng.random() < self.eps:
            return int(self.rng.integers(self.Q.shape[1]))
        q = self.Q[o]
        return int(self.rng.choice(np.flatnonzero(q == q.max())))

    def learn(self, o, a, new_bins, o2, hit):
        self.N[o2] += 1
        r = new_bins + self.beta / np.sqrt(self.N[o2]) + (10.0 if hit else 0.0)
        target = r if hit else r + self.gamma * self.Q[o2].max()
        self.Q[o, a] += self.alpha * (target - self.Q[o, a])
        if hit and self.gamma < 0.99:
            self.gamma, self.alpha, self.beta = 0.99, 0.2, 0.0
