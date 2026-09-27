"""Shared Python code of the PoC, used by both flows (Python experiments and pyuvm testbench).

nand_dut  transaction-level model of the NAND read-recovery controller (golden / buggy),
          bit-exact with rtl/*.v, plus the 73-bin coverage model
rl_agent  the coverage-driven Q-learning agent
methods   stimulus methods on the model: CRV, coverage fuzzer, BFS, RL, policy replay
"""
