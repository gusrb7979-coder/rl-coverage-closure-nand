#!/usr/bin/env bash
# pyuvm regression on both RTL variants (runs in WSL).
# usage (PowerShell): wsl -d Ubuntu-24.04 -u root -- bash <project in /mnt/c>/flow2_uvm/uvm_suite.sh [part]
# part: base (CRV/fuzzer/BFS/policy on both), rl (RL seed 0 on both), rl10 (RL seeds 0-9 on buggy),
#       busy (policy replay with BUSY 0 and 10), repro (replay the RL reproducer with waveforms),
#       synth (Yosys synthesizability + gate-level equivalence), all (base rl busy repro)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
R="$HERE/wsl_uvm.sh"
PART=${1:-all}
run() { echo "== $*"; bash "$R" "$@"; }
if [[ $PART == synth ]]; then
  . "${RLCOV_VENV:-/root/rlcov/.venv}/bin/activate" && python "$HERE/../synth/synth_check.py"
fi
if [[ $PART == base || $PART == all ]]; then
  for v in buggy golden; do
    for m in crv fuzzer bfs; do run variant=$v mode=$m seed=0 budget=300000; done
    run variant=$v mode=policy seed=0 lfsr_seed=0x7000 trials=1000 budget=100000000
  done
fi
if [[ $PART == rl || $PART == all ]]; then
  run variant=buggy mode=rl seed=0 budget=3000000
  run variant=golden mode=rl seed=0 budget=1000000
fi
if [[ $PART == rl10 ]]; then
  for s in 0 1 2 3 4 5 6 7 8 9; do run variant=buggy mode=rl seed=$s budget=3000000; done
fi
if [[ $PART == busy || $PART == all ]]; then
  for b in 0 10; do run variant=buggy mode=policy seed=0 lfsr_seed=0x7000 trials=1000 budget=100000000 busy=$b; done
fi
if [[ $PART == repro || $PART == all ]]; then
  for v in buggy golden; do run variant=$v mode=repro seed=0 repro=out/uvm_rl_buggy_s0_repro.json waves=1; done
fi
