"""Transaction-level model of the NAND read-recovery controller + NAND error model.
Reads spec/nand_recovery.json so the RTL and this model share one source of truth.
buggy=True is bit-exact with rtl/nand_recovery_buggy.v, buggy=False with rtl/nand_recovery_golden.v
(same LFSR, same transition rules, same map-reservation logic).
"""
import json
from pathlib import Path

SPEC = json.loads((Path(__file__).resolve().parents[1] / "spec" / "nand_recovery.json").read_text())
STATUS, READ, RETRY, REMAP = 0, 1, 2, 3
C = SPEC["constants"]
RT, ST = SPEC["retry_table"], SPEC["spare_table"]
ARCS = [tuple(a) for a in SPEC["coverage"]["arcs"]]
N_STATES = len(SPEC["states"]) + 1   # the 8 RTL states + the spec-violation event (index 8)
BUG = N_STATES - 1

# coverage bin ids: states | arcs | recovery (stage, hint)
BINS = ([("state", s) for s in range(N_STATES)] + [("arc", a) for a in ARCS]
        + [("rec", s, h) for s in (1, 3, 5) for h in range(16)])
BIN_ID = {b: i for i, b in enumerate(BINS)}
N_BINS = len(BINS)
VIOLATION_BINS = {BIN_ID[("state", BUG)], BIN_ID[("arc", (7, BUG))]}   # a commit wrote > 1 map entry
N_SPEC_BINS = N_BINS - len(VIOLATION_BINS)                              # 71 spec-coverage bins


def spec_coverage(covered):
    """(spec bins covered, spec bins total, spec violation seen) from a set of covered bin ids."""
    return len(covered - VIOLATION_BINS), N_SPEC_BINS, bool(covered & VIOLATION_BINS)


def tx(op, param):
    return op * 16 + param


LEAP = 7  # LFSR steps per transaction: consecutive operations use disjoint bits


def lfsr_step(x):
    bit = (x ^ (x >> 2) ^ (x >> 3) ^ (x >> 5)) & 1
    return (x >> 1) | (bit << 15)


def lfsr_advance(x):
    for _ in range(LEAP):
        x = lfsr_step(x)
    return x


def oracle_action(dut):
    """The spec-correct next transaction for the deepest path (knows both tables).
    Used only for validity checks and equivalence traffic, never by the compared methods."""
    s, h = dut.state, dut.hint
    return [tx(READ, C["WEAK_PAGE"]), tx(RETRY, RT[h]), tx(REMAP, C["SPARE_BLK"]), tx(REMAP, ST[h]),
            tx(READ, C["VERIFY_PAGE"]), tx(RETRY, RT[h]), tx(STATUS, 0), tx(REMAP, C["COMMIT"]), 0][s]


class NandRecoveryDUT:
    """The RTL has 8 states (0-7). State 8 exists only in this model: it marks the moment a
    monitor sees a commit that wrote more than one map entry (the bug), and ends the episode."""
    n_actions, n_hint, depth = 64, 16, BUG
    n_obs = N_STATES * 16

    def __init__(self, seed=0xACE1, buggy=True):
        self.lfsr = (seed & 0xFFFF) or 0xACE1
        self.buggy = buggy
        self.covered = set()
        self.reset()

    def reset(self):  # host reset: controller state only, the NAND error model keeps running
        self.state, self.hint, self.err = 0, 0, 0
        self.commit, self.wr_cnt = 0, 0
        self.pend_v, self.pend_blk, self.rsv_idx = [0, 0], [0, 0], 0
        return self.obs()

    def obs(self):
        return self.state * 16 + self.hint

    def _hit(self, b):
        i = BIN_ID[b]
        new = i not in self.covered
        self.covered.add(i)
        return new

    def step(self, a):
        """Apply one accepted transaction. Returns the number of new coverage bins."""
        s, h = self.state, self.hint
        if s == BUG:
            return 0
        self.lfsr = lfsr_advance(self.lfsr)
        fail, rnd_hint = self.lfsr & 1, (self.lfsr >> 1) & 0xF
        ns, nh, ok = 0, 0, True
        rsv = cancel = rearm = commit = 0
        rsv_blk = 0
        if s == 0 and a == tx(READ, C["WEAK_PAGE"]):
            ns, nh = (1, rnd_hint) if fail else (0, 0)
        elif s == 1 and a == tx(RETRY, RT[h]):
            ns = 2
        elif s == 2 and a == tx(REMAP, C["SPARE_BLK"]):
            ns, nh = (3, rnd_hint) if fail else (0, 0)
            rsv, rsv_blk, cancel, commit = 1, C["SPARE_BLK"], fail, 1 - fail
        elif s == 3 and a == tx(REMAP, ST[h]):
            ns, rsv, rsv_blk = 4, 1, ST[h]
        elif s == 4 and a == tx(READ, C["VERIFY_PAGE"]):
            ns, nh = (5, rnd_hint) if fail else (0, 0)
            commit = 1 - fail
        elif s == 5 and a == tx(RETRY, RT[h]):
            ns = 6
        elif s == 6 and a == tx(STATUS, 0):
            ns, rearm = 7, 1
        elif s == 7 and a == tx(REMAP, C["COMMIT"]):
            ns, commit = 0, 1
        else:
            ok = False  # unexpected command: abort to IDLE

        # map update, same order as the RTL
        wr_cnt = (self.pend_v[0] + self.pend_v[1] + (rsv and not cancel)) if commit else 0
        if ns == 0:                                   # flow finished or aborted
            self.pend_v, self.rsv_idx = [0, 0], 0
        else:
            if rsv:
                slot = self.rsv_idx & 1
                self.pend_v[slot], self.pend_blk[slot] = int(not cancel), rsv_blk
                self.rsv_idx = (self.rsv_idx + 1) & 3
            if rearm:
                # golden: most recent slot, rsv_last = rsv_idx - 1
                # buggy RTL forgot the -1 (rsv_last = rsv_idx): off-by-one, revives the cancelled slot
                slot = (self.rsv_idx & 1) if self.buggy else ((self.rsv_idx - 1) & 1)
                self.pend_v[slot], self.pend_blk[slot] = 1, (self.pend_blk[1] + 1) & 0xF
        self.commit, self.wr_cnt = commit, wr_cnt
        if wr_cnt > 1:
            ns = BUG                                  # monitor view: a commit wrote 2 map entries

        new = self._hit(("state", ns)) + self._hit(("arc", (s, ns)))
        if s in (1, 3, 5) and ns == s + 1:
            new += self._hit(("rec", s, h))
        # err_o pulses when an abort happens in the middle of a recovery (not in IDLE)
        self.state, self.hint, self.err = ns, nh, int(not ok and s != 0)
        return new

    def coverage(self):
        return 100.0 * len(self.covered) / N_BINS
