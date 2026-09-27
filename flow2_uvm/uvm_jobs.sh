#!/usr/bin/env bash
# Run lists of UVM jobs in parallel (runs in WSL). Each argument after the name is a job file with
# one wsl_uvm.sh argument line per job; the files run one after another (stage 2 can use the
# policies written by stage 1), the lines of one file run in parallel.
# Progress: out/<name>_status.txt, per-job logs in out/<name>_logs/.
# usage (PowerShell): wsl -d Ubuntu-24.04 -u root -- bash <project in /mnt/c>/flow2_uvm/uvm_jobs.sh <name> <jobs1.txt> [<jobs2.txt> ...]
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC=$(cd "$HERE/.." && pwd)
NAME=$1; shift
export R="$HERE/wsl_uvm.sh"
export LOGDIR="$SRC/out/${NAME}_logs"
export STATUS="$SRC/out/${NAME}_status.txt"
export WORKROOT=${RLCOV_ROOT:-/root/rlcov}
unset BUDGET   # the testbench reads BUDGET from the environment; jobs pass budget=...
note() { echo "$(date '+%F %T') $*" >> "$STATUS"; }
mkdir -p "$LOGDIR"
: > "$STATUS"
note "START $NAME"

cores=$(nproc)
load=$(awk '{printf "%d", $1 + 0.5}' /proc/loadavg)
mem_gb=$(awk '/MemAvailable/ {printf "%d", $2 / 1048576}' /proc/meminfo)
N=$(( cores - 2 - load ))
(( N > 10 )) && N=10
(( N > mem_gb * 2 )) && N=$(( mem_gb * 2 ))
(( N < 1 )) && N=1
note "parallel jobs: $N (cores $cores, load $load, free memory ${mem_gb} GB)"

for jobs in "$@"; do
  [[ $jobs = /* ]] || jobs="$HERE/$jobs"
  note "stage $(basename "$jobs"): $(grep -c . "$jobs") jobs"
  grep . "$jobs" | xargs -P "$N" -L 1 --process-slot-var=SLOT bash -c '
    m= v= s= x=
    for a in "$@"; do
      case $a in mode=*) m=${a#mode=};; variant=*) v=${a#variant=};; seed=*) s=${a#seed=};; suffix=*) x=${a#suffix=};; esac
    done
    tag="${m}_${v}_s${s}${x}"
    RLCOV_WORK="$WORKROOT/j$SLOT" bash "$R" "$@" > "$LOGDIR/$tag.log" 2>&1
    res=$(grep -o "exit=[0-9]* ([A-Z]*)" "$LOGDIR/$tag.log" | tail -1)
    grep -q Traceback "$LOGDIR/$tag.log" && res="$res TRACEBACK"
    echo "$(date "+%F %T") done $tag ${res:-NO_RESULT}" >> "$STATUS"
  ' _
done
note "ALL DONE"
rm -rf "$WORKROOT"/j[0-9]*
