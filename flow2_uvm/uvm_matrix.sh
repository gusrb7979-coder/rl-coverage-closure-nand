#!/usr/bin/env bash
# UVM control-group matrix (runs in WSL): golden and buggy DUT x CRV, fuzzer, BFS, RL x seeds 0-9
# = 80 runs, 3,000,000 tx each (RL stops early once all 73 bins are covered).
#   1. archive the previous out/uvm_* results to out/archive_uvm/
#   2. smoke test: two short runs, check the result files carry the curve and max-depth fields
#   3. pick the parallel job count from the idle cores and free memory (max 10)
#   4. run the 80 jobs in parallel, longest first, one work dir per job slot
# Progress: out/matrix_status.txt (one line per event), per-job logs in out/matrix_logs/.
# usage (PowerShell): wsl -d Ubuntu-24.04 -u root -- bash <project in /mnt/c>/flow2_uvm/uvm_matrix.sh
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC=$(cd "$HERE/.." && pwd)
export R="$HERE/wsl_uvm.sh"
export LOGDIR="$SRC/out/matrix_logs"
export STATUS="$SRC/out/matrix_status.txt"
# not called BUDGET: the testbench reads BUDGET from the environment, which would override budget=...
export MATRIX_BUDGET=${MATRIX_BUDGET:-3000000}
unset BUDGET
WORKROOT=${RLCOV_ROOT:-/root/rlcov}
VENV=${RLCOV_VENV:-/root/rlcov/.venv}
note() { echo "$(date '+%F %T') $*" >> "$STATUS"; }

mkdir -p "$SRC/out/archive_uvm" "$LOGDIR"
: > "$STATUS"
note "START matrix (budget $MATRIX_BUDGET)"

# 1. archive previous results so out/ only holds this matrix
shopt -s nullglob
old=("$SRC"/out/uvm_* "$SRC"/out/cross_check_summary.json)
if (( ${#old[@]} )); then mv -n "${old[@]}" "$SRC/out/archive_uvm/"; rm -f "${old[@]}"; fi   # keep the first archived copy
shopt -u nullglob
note "archived ${#old[@]} previous files to out/archive_uvm/"

# 2. smoke test (short budget), then remove its outputs
for job in "buggy rl 0" "golden crv 0"; do
  set -- $job
  RLCOV_WORK="$WORKROOT/smoke" bash "$R" variant=$1 mode=$2 seed=$3 budget=20000 > "$LOGDIR/smoke_$2_$1.log" 2>&1
done
. "$VENV/bin/activate"
if python - "$SRC/out" <<'EOF'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
for name in ("uvm_rl_buggy_s0.json", "uvm_crv_golden_s0.json"):
    r = json.loads((out / name).read_text())
    # RL finishes its last episode, so it can stop a few tx past the budget
    assert 20000 <= r["steps"] < 20100 and "curve" in r and "max_depth" in r and len(r["curve"]) == 1, name
    assert r["verdict"] == "PASS", name
EOF
then
  note "SMOKE OK"
  rm -f "$SRC"/out/uvm_*
else
  note "SMOKE FAILED - matrix not started (see out/matrix_logs/smoke_*.log)"
  exit 1
fi

# 3. parallel job count: idle cores - 2, at most 10, at least 1; ~0.5 GB per job
cores=$(nproc)
load=$(awk '{printf "%d", $1 + 0.5}' /proc/loadavg)
mem_gb=$(awk '/MemAvailable/ {printf "%d", $2 / 1048576}' /proc/meminfo)
N=$(( cores - 2 - load ))
(( N > 10 )) && N=10
(( N > mem_gb * 2 )) && N=$(( mem_gb * 2 ))
(( N < 1 )) && N=1
note "parallel jobs: $N (cores $cores, load $load, free memory ${mem_gb} GB)"

# 4. jobs, longest first: golden RL and BFS/fuzzer/CRV run the full budget, buggy RL stops near 0.9M
jobs=()
for m in rl bfs fuzzer crv; do
  for v in golden buggy; do
    [[ $m == rl && $v == buggy ]] && continue
    for s in 0 1 2 3 4 5 6 7 8 9; do jobs+=("$v $m $s"); done
  done
done
for s in 0 1 2 3 4 5 6 7 8 9; do jobs+=("buggy rl $s"); done
note "jobs: ${#jobs[@]}"

printf '%s\n' "${jobs[@]}" | xargs -P "$N" -L 1 --process-slot-var=SLOT bash -c '
  tag="$2_$1_s$3"
  RLCOV_WORK="'"$WORKROOT"'/w$SLOT" bash "$R" variant=$1 mode=$2 seed=$3 budget=$MATRIX_BUDGET > "$LOGDIR/$tag.log" 2>&1
  res=$(grep -o "exit=[0-9]* ([A-Z]*)" "$LOGDIR/$tag.log" | tail -1)
  grep -q Traceback "$LOGDIR/$tag.log" && res="$res TRACEBACK"
  echo "$(date "+%F %T") done $tag ${res:-NO_RESULT}" >> "$STATUS"
' _

n=$(ls "$SRC"/out/uvm_*_s[0-9].json 2>/dev/null | wc -l)
note "ALL DONE: $n result files"
rm -rf "$WORKROOT"/w[0-9]* "$WORKROOT/smoke"
