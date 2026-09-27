"""pyuvm testbench for the NAND read-recovery controller (Icarus + cocotb + pyuvm).

Components: sequencer, driver (valid/ready handshake), monitor (accepted transactions and
host resets -> analysis port), coverage collector (the 73 bins of spec/nand_recovery.json =
71 spec-coverage bins + 2 spec-violation bins, with a per-group report), scoreboard (golden
reference model + "one commit writes exactly one map entry" rule; saves a reproducer of the
first failure).
Sequences: CRV, coverage fuzzer, BFS, RL learning in the loop, policy replay, reproducer replay.

Pass/fail: the test FAILS when the scoreboard saw any spec violation, so the buggy DUT fails
exactly when a method reaches the bug, and the golden DUT must always pass.

Run settings come from environment variables (set by flow2_uvm/run_uvm.py):
  DUT_VARIANT golden|buggy   MODE crv|fuzzer|bfs|rl|policy|repro   SEED   LFSR_SEED   BUDGET
  TRIALS (policy)   POLICY / REPRO (json paths)   OUT (result json path)   BUSY (for the record)
Every sequence mirrors the pure-Python experiment with the same seeds, so the numbers
should match the Python results exactly (flow2_uvm/cross_check.py).
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cocotb
import numpy as np
import pyuvm
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from pyuvm import (uvm_analysis_port, uvm_driver, uvm_env, uvm_monitor, uvm_sequence,
                   uvm_sequence_item, uvm_sequencer, uvm_subscriber, uvm_test)

from types import SimpleNamespace  # noqa: E402

from nandpoc import nand_dut  # noqa: E402
from nandpoc.nand_dut import (BIN_ID, BINS, BUG, N_BINS, VIOLATION_BINS, NandRecoveryDUT,  # noqa: E402
                              oracle_action, spec_coverage)
from nandpoc.methods import CKPT, replay_policy  # noqa: E402
from nandpoc.rl_agent import CoverageQAgent  # noqa: E402

# TABLES="rt0,..,rt15:st0,..,st15": the RTL variant was built with these retry/spare tables,
# so the reference model (and the oracle) must use them too
if os.environ.get("TABLES"):
    _rt, _st = os.environ["TABLES"].split(":")
    nand_dut.RT[:] = [int(x) for x in _rt.split(",")]
    nand_dut.ST[:] = [int(x) for x in _st.split(",")]

VARIANT = os.environ.get("DUT_VARIANT", "buggy")
MODE = os.environ.get("MODE", "crv")
SEED = int(os.environ.get("SEED", "0"))
LFSR_SEED = int(os.environ.get("LFSR_SEED", str(0x1000 + 97 * SEED)))
BUDGET = int(os.environ.get("BUDGET", "300000"))
TRIALS = int(os.environ.get("TRIALS", "1000"))
OUT = Path(os.environ.get("OUT", "uvm_result.json"))


class NandItem(uvm_sequence_item):
    """Request: one transaction or a host reset. Response fields are filled by the driver."""

    def __init__(self, name="nand_item", tx=0, reset=False):
        super().__init__(name)
        self.tx, self.reset = tx, reset
        self.state = self.hint = self.err = self.commit = self.cnt = 0


class NandObs:
    """What the monitor saw at one clock edge. On a reset it also records the NAND error-model
    state, which is what a reproducer needs to replay the episode that follows."""

    def __init__(self, reset, tx=0, state=0, hint=0, err=0, commit=0, cnt=0, lfsr=0):
        self.reset, self.tx, self.lfsr = reset, tx, lfsr
        self.state, self.hint, self.err, self.commit, self.cnt = state, hint, err, commit, cnt


class NandDriver(uvm_driver):
    async def run_phase(self):
        dut = cocotb.top
        while True:
            item = await self.seq_item_port.get_next_item()
            if item.reset:
                dut.rst_n.value = 0
                await FallingEdge(dut.clk)
                dut.rst_n.value = 1
            else:
                dut.in_valid.value, dut.in_tx.value = 1, item.tx
                while True:  # hold valid until the rising edge that accepts it (NAND busy)
                    ready = bool(dut.in_ready.value)
                    await FallingEdge(dut.clk)
                    if ready:
                        break
                dut.in_valid.value = 0
                item.state, item.hint = dut.state_o.value.to_unsigned(), dut.hint_o.value.to_unsigned()
                item.err, item.commit = int(bool(dut.err_o.value)), int(bool(dut.map_commit_o.value))
                item.cnt = dut.map_wr_cnt_o.value.to_unsigned()
            self.seq_item_port.item_done()


class NandMonitor(uvm_monitor):
    def build_phase(self):
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self):
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk)  # inputs as sampled by this edge
            live = bool(dut.por_n.value) and not bool(dut.seed_we.value)
            reset = live and not bool(dut.rst_n.value)
            accept = live and not reset and bool(dut.in_valid.value) and bool(dut.in_ready.value)
            if not (reset or accept):
                continue
            tx = dut.in_tx.value.to_unsigned() if accept else 0
            await ReadOnly()           # outputs after this edge
            self.ap.write(NandObs(reset, tx, dut.state_o.value.to_unsigned(), dut.hint_o.value.to_unsigned(),
                                  int(bool(dut.err_o.value)), int(bool(dut.map_commit_o.value)),
                                  dut.map_wr_cnt_o.value.to_unsigned(),
                                  dut.lfsr.value.to_unsigned() if reset else 0))


class NandCoverage(uvm_subscriber):
    """Same bins as nand_dut.py. A commit that wrote 2 map entries is the spec-violation event
    (state 8, arc 7->8): it is counted in the 73 bins but reported apart from the 71 spec bins."""

    def build_phase(self):
        self.covered, self.prev, self.new_last = set(), (0, 0), 0
        self.steps, self.bug_at, self.full_at = 0, None, None
        # coverage curve every CKPT tx: [tx, bins covered of 73, spec bins covered of 71]
        self.curve = []
        # deepest state reached (8 = spec violation) and the tx at which each depth was first reached
        self.max_depth, self.depth_at = 0, {}
        # tx index of every entry into a deep state (5..8), and the hint seen on entering 1/3/5
        self.deep_entries = {str(d): [] for d in range(5, 9)}
        self.hint_hist = {str(d): [0] * 16 for d in (1, 3, 5)}
        self.deep_commits = 0   # commits made from MAP_PENDING (the deepest step)

    def _hit(self, b):
        i = BIN_ID[b]
        new = i not in self.covered
        self.covered.add(i)
        return new

    def write(self, obs):
        if obs.reset:
            self.prev = (0, 0)
            return
        s, h = self.prev
        self.steps += 1
        ns = BUG if (obs.commit and obs.cnt > 1) else obs.state
        self.deep_commits += int(s == 7 and obs.commit)
        new = self._hit(("state", ns)) + self._hit(("arc", (s, ns)))
        if s in (1, 3, 5) and ns == s + 1:
            new += self._hit(("rec", s, h))
        self.new_last, self.prev = new, (ns, 0 if ns == BUG else obs.hint)
        if ns != s:
            if ns >= 5:
                self.deep_entries[str(ns)].append(self.steps)
            if ns in (1, 3, 5):
                self.hint_hist[str(ns)][obs.hint] += 1
        if ns == BUG and self.bug_at is None:
            self.bug_at = self.steps
        if ns > self.max_depth:
            self.max_depth = ns
            self.depth_at[ns] = self.steps
        if self.full_at is None and len(self.covered) == N_BINS:
            self.full_at = self.steps
        if self.steps % CKPT == 0:
            self.curve.append([self.steps, len(self.covered), spec_coverage(self.covered)[0]])

    def done(self):
        return self.steps >= BUDGET or len(self.covered) == N_BINS

    def obs(self):
        return self.prev[0] * 16 + self.prev[1]

    def report(self):
        """Per-group coverage: covered/total and the missing bins (violation bins in their own group)."""
        groups = {"state": [], "arc": [], "rec@ECC_FAIL": [], "rec@PGM_FAIL": [], "rec@ECC_FAIL2": [],
                  "violation": []}
        for i, b in enumerate(BINS):
            key = ("violation" if i in VIOLATION_BINS else b[0] if b[0] != "rec"
                   else {1: "rec@ECC_FAIL", 3: "rec@PGM_FAIL", 5: "rec@ECC_FAIL2"}[b[1]])
            groups[key].append((b, i in self.covered))
        return {g: {"covered": sum(c for _, c in v), "total": len(v),
                    "missing": [str(b[1:] if len(b) > 2 else b[1]) for b, c in v if not c]}
                for g, v in groups.items()}


class NandScoreboard(uvm_subscriber):
    """Checks the DUT against the SPEC: a golden reference model fed with the same
    transactions (and the same NAND error-model seed), plus the map-commit rule.
    On the first violation it saves a reproducer: the error-model state at the start of
    the failing episode and the transactions of that episode."""

    def build_phase(self):
        self.ref = NandRecoveryDUT(seed=LFSR_SEED, buggy=False)
        self.checked = self.mismatch = self.rule_violation = 0
        self.first, self.episode_lfsr, self.episode = [], LFSR_SEED, []
        self.reproducer = None

    def write(self, obs):
        if obs.reset:
            self.ref.reset()
            self.episode_lfsr, self.episode = obs.lfsr, []
            return
        self.ref.step(obs.tx)
        self.episode.append(obs.tx)
        self.checked += 1
        exp = (self.ref.state, self.ref.hint, self.ref.err, self.ref.commit, self.ref.wr_cnt)
        got = (obs.state, obs.hint, obs.err, obs.commit, obs.cnt)
        if obs.commit and obs.cnt != 1:
            self.rule_violation += 1
            if self.rule_violation <= 3:
                self.logger.error(f"SPEC VIOLATION at tx {self.checked}: one commit wrote {obs.cnt} map entries")
        if got != exp:
            self.mismatch += 1
            if len(self.first) < 3:
                self.first.append({"tx_index": self.checked, "expected": exp, "got": got})
            if self.reproducer is None:
                self.reproducer = {"variant": VARIANT, "lfsr_state": self.episode_lfsr,
                                   "txs": list(self.episode), "found_at_tx": self.checked}


class NandEnv(uvm_env):
    def build_phase(self):
        self.seqr = uvm_sequencer("seqr", self)
        self.driver = NandDriver("driver", self)
        self.monitor = NandMonitor("monitor", self)
        self.cov = NandCoverage("cov", self)
        self.sb = NandScoreboard("sb", self)

    def connect_phase(self):
        self.driver.seq_item_port.connect(self.seqr.seq_item_export)
        self.monitor.ap.connect(self.cov.analysis_export)
        self.monitor.ap.connect(self.sb.analysis_export)


class BaseSeq(uvm_sequence):
    cov = None

    async def do(self, **kw):
        item = NandItem(**kw)
        await self.start_item(item)
        await self.finish_item(item)
        return item


class CrvSeq(BaseSeq):
    """Mirrors nandpoc.methods.crv: tests of 1000 random transactions, host reset in between."""

    async def body(self):
        rng = np.random.default_rng(SEED)
        while not self.cov.done():
            await self.do(reset=True)
            for a in rng.integers(0, 64, 1000).tolist():
                await self.do(tx=a)
                if self.cov.done():
                    return


class FuzzerSeq(BaseSeq):
    """Mirrors nandpoc.methods.fuzzer: keep inputs that hit new bins, extend them randomly."""

    async def body(self, max_ext=4):
        rng, corpus = np.random.default_rng(SEED), [[]]
        while not self.cov.done():
            inp = corpus[rng.integers(len(corpus))] + rng.integers(0, 64, rng.integers(1, max_ext + 1)).tolist()
            await self.do(reset=True)
            last_new = -1
            for i, a in enumerate(inp):
                await self.do(tx=a)
                if self.cov.new_last:
                    last_new = i
                if self.cov.done():
                    return
            if last_new >= 0:
                corpus.append(inp[:last_new + 1])


class BfsSeq(BaseSeq):
    """Mirrors nandpoc.methods.bfs: try every transaction once from each newly found state."""

    async def body(self):
        rng = np.random.default_rng(SEED)
        while not self.cov.done():
            frontier, known = [[]], {0}
            while frontier and not self.cov.done():
                prefix = frontier.pop(0)
                for a in rng.permutation(64).tolist():
                    await self.do(reset=True)
                    for x in prefix:
                        await self.do(tx=x)
                    await self.do(tx=a)
                    if self.cov.done():
                        return
                    if self.cov.prev[0] not in known:
                        known.add(self.cov.prev[0])
                        frontier.append(prefix + [a])


class RlSeq(BaseSeq):
    """Mirrors nandpoc.methods.rl (coverage phase): the shared CoverageQAgent learns in the
    loop with the RTL; reward comes from the coverage collector."""

    async def body(self):
        ag = CoverageQAgent(9 * 16, 64, np.random.default_rng(SEED))
        while not self.cov.done():
            await self.do(reset=True)
            o = 0
            for _ in range(32):
                a = ag.act(o)
                await self.do(tx=a)
                o2, hit = self.cov.obs(), self.cov.prev[0] == BUG
                ag.learn(o, a, self.cov.new_last, o2, hit)
                if hit:
                    break
                o = o2


class RlPolishSeq(BaseSeq):
    """Mirrors nandpoc.methods.rl with the policy polish: after the coverage phase, keep training
    in the loop with the RTL until the greedy policy reaches the bug in >= 99% of 200 episodes.
    That stop check is an evaluation of the table, done on the reference model with the same
    seed as the Python experiment (0x6000); every training transaction runs on the RTL.
    The final policy is saved and replayed on the RTL by PolicySeq."""
    closure_steps = polish_steps = policy = None

    async def episode(self, ag):
        await self.do(reset=True)
        o = 0
        for _ in range(32):
            a = ag.act(o)
            await self.do(tx=a)
            o2, hit = self.cov.obs(), self.cov.prev[0] == BUG
            ag.learn(o, a, self.cov.new_last, o2, hit)
            if hit:
                return
            o = o2

    async def body(self, max_polish=2_000_000, check_every=50_000):
        ag = CoverageQAgent(9 * 16, 64, np.random.default_rng(SEED))
        while not self.cov.done():
            await self.episode(ag)
        self.closure_steps = self.cov.steps
        if self.cov.bug_at is not None:
            extra = 0
            while extra < max_polish:
                while self.cov.steps - self.closure_steps - extra < check_every:
                    await self.episode(ag)
                extra = self.cov.steps - self.closure_steps
                if replay_policy(ag.Q.argmax(1), seed=0x6000, trials=200) >= 0.99:
                    self.polish_steps = extra
                    break
        self.policy = ag.Q.argmax(1).tolist()


class OracleSeq(BaseSeq):
    """Mirrors flow1_python/validate.py reach: episodes of 64 tx, 80% the spec-correct
    transaction (the oracle knows both tables), 20% random so abort arcs get hit too."""

    async def body(self):
        rng = np.random.default_rng(SEED)
        while not self.cov.done():
            await self.do(reset=True)
            for _ in range(64):
                s, h = self.cov.prev
                a = oracle_action(SimpleNamespace(state=s, hint=h)) if rng.random() < 0.8 else int(rng.integers(64))
                await self.do(tx=a)
                if self.cov.prev[0] == BUG or self.cov.done():
                    break


class OraclePureSeq(BaseSeq):
    """Mirrors flow1_python/validate.py golden: only spec-correct transactions, no host reset,
    so every deep path ends in a commit from MAP_PENDING."""

    async def body(self):
        while not self.cov.done():
            s, h = self.cov.prev
            await self.do(tx=oracle_action(SimpleNamespace(state=s, hint=h)))


class PolicySeq(BaseSeq):
    """Replay of an exported policy table: reset, then follow it for up to 200 tx."""
    ok = 0

    async def body(self):
        policy = json.loads(Path(os.environ["POLICY"]).read_text())["policy"]
        for _ in range(TRIALS):
            await self.do(reset=True)
            o = 0
            for _ in range(200):
                await self.do(tx=policy[o])
                o = self.cov.obs()
                if self.cov.prev[0] == BUG:
                    self.ok += 1
                    break


class ReproSeq(BaseSeq):
    """Replays a saved reproducer: one reset, then the recorded transactions."""

    async def body(self):
        rep = json.loads(Path(os.environ["REPRO"]).read_text())
        await self.do(reset=True)
        for a in rep["txs"]:
            await self.do(tx=a)


async def bring_up(dut, lfsr_seed):
    Clock(dut.clk, 10, unit="ns").start()
    dut.por_n.value, dut.rst_n.value, dut.seed_we.value = 0, 1, 0
    dut.in_valid.value, dut.in_tx.value, dut.lfsr_seed.value = 0, 0, 0
    await FallingEdge(dut.clk)
    dut.por_n.value = 1
    await FallingEdge(dut.clk)
    dut.seed_we.value, dut.lfsr_seed.value = 1, lfsr_seed
    await FallingEdge(dut.clk)
    dut.seed_we.value = 0


SEQS = {"crv": CrvSeq, "fuzzer": FuzzerSeq, "bfs": BfsSeq, "rl": RlSeq, "rlp": RlPolishSeq, "oracle": OracleSeq,
        "oraclepure": OraclePureSeq, "policy": PolicySeq, "repro": ReproSeq}


@pyuvm.test()
class NandTest(uvm_test):
    def build_phase(self):
        self.env = NandEnv("env", self)

    async def run_phase(self):
        self.raise_objection()
        lfsr_seed = LFSR_SEED
        if MODE == "repro":  # start the error model where the failing episode started
            lfsr_seed = json.loads(Path(os.environ["REPRO"]).read_text())["lfsr_state"]
            self.env.sb.ref = NandRecoveryDUT(seed=lfsr_seed, buggy=False)
        await bring_up(cocotb.top, lfsr_seed)
        seq = SEQS[MODE]("seq")
        seq.cov = self.env.cov
        t0, ns0 = time.perf_counter(), get_sim_time("ns")
        await seq.start(self.env.seqr)
        dt, sim_ns = time.perf_counter() - t0, get_sim_time("ns") - ns0
        cov, sb = self.env.cov, self.env.sb
        verdict = "FAIL" if (sb.mismatch or sb.rule_violation) else "PASS"
        spec_cov, spec_total, violation = spec_coverage(cov.covered)
        res = {"variant": VARIANT, "mode": MODE, "seed": SEED, "lfsr_seed": lfsr_seed, "budget": BUDGET,
               "busy": int(os.environ.get("BUSY", "3")), "verdict": verdict,
               "steps": cov.steps, "coverage": 100.0 * len(cov.covered) / N_BINS,
               "covered": len(cov.covered), "spec_covered": spec_cov, "spec_total": spec_total,
               "violation": violation, "bug_at": cov.bug_at, "full_at": cov.full_at,
               "max_depth": cov.max_depth, "depth_at": {str(d): t for d, t in cov.depth_at.items()},
               "ckpt": CKPT, "curve": cov.curve,
               "deep_entries": cov.deep_entries, "hint_hist": cov.hint_hist,
               "coverage_by_group": cov.report(),
               "sb_checked": sb.checked, "sb_mismatch": sb.mismatch, "sb_rule_violation": sb.rule_violation,
               "sb_first": sb.first, "seconds": dt, "sim_ns": sim_ns,
               "tx_per_s": cov.steps / dt if dt else None}
        res["deep_commits"] = cov.deep_commits
        if os.environ.get("TABLES"):
            res["tables"] = os.environ["TABLES"]
        if MODE == "rlp":  # steps = coverage-phase cost, as in the Python experiment; polish reported apart
            res.update(steps=seq.closure_steps, polish_steps=seq.polish_steps, total_steps=cov.steps,
                       curve=[c for c in cov.curve if c[0] <= seq.closure_steps], policy=seq.policy)
            OUT.with_name(OUT.stem + "_policy.json").write_text(json.dumps({"policy": seq.policy}))
        if MODE == "policy":
            res.update(trials=TRIALS, policy_ok=seq.ok, policy_file=Path(os.environ["POLICY"]).name)
        if MODE == "repro":
            res.update(repro_file=Path(os.environ["REPRO"]).name)
        OUT.write_text(json.dumps(res))
        if sb.reproducer is not None and MODE != "repro":
            OUT.with_name(OUT.stem + "_repro.json").write_text(json.dumps(sb.reproducer))
        self.logger.info("RESULT " + json.dumps({k: v for k, v in res.items()
                                                  if k not in ("sb_first", "coverage_by_group", "curve",
                                                               "deep_entries", "hint_hist")}))
        self.drop_objection()
        assert verdict == "PASS", (f"{sb.rule_violation} spec violation(s): a commit wrote more than one "
                                   f"map entry (first at tx {sb.first[0]['tx_index'] if sb.first else '?'})")
