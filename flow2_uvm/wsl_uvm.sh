#!/usr/bin/env bash
# Copy the project into the Linux filesystem (much faster than /mnt/c), run one pyuvm job,
# copy the results back to <project>/out.
# usage (PowerShell): wsl -d Ubuntu-24.04 -u root -- bash <project in /mnt/c>/flow2_uvm/wsl_uvm.sh variant=buggy mode=crv seed=0 budget=300000
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DST=${RLCOV_WORK:-/root/rlcov/nand_v1}
VENV=${RLCOV_VENV:-/root/rlcov/.venv}
rm -rf "$DST/rtl" "$DST/spec" "$DST/nandpoc" "$DST/flow2_uvm" "$DST"/out/uvm_* "$DST"/out/*.fst
mkdir -p "$DST/out"
cp -r "$SRC/rtl" "$SRC/spec" "$SRC/nandpoc" "$SRC/flow2_uvm" "$DST/"
cp "$SRC"/out/policy_seed*.json "$SRC"/out/*_repro.json "$DST/out/" 2>/dev/null
cd "$DST"
. "$VENV/bin/activate"
LOG="$DST/uvm_run.log"   # per work dir, so parallel jobs (RLCOV_WORK) never share a log
python flow2_uvm/run_uvm.py "$@" > "$LOG" 2>&1
status=$?
grep -E "RESULT|SPEC VIOLATION|TESTS=" "$LOG" | head -6 | sed -E 's/^ *[0-9.]+ns (INFO|ERROR) +//'
if grep -q "Traceback" "$LOG" && ! grep -q "RESULT" "$LOG"; then tail -30 "$LOG"; fi
mkdir -p "$SRC/out"
cp "$DST"/out/uvm_*.json "$DST"/out/*.fst "$SRC/out/" 2>/dev/null
echo "exit=$status ($([ $status -eq 0 ] && echo PASS || echo FAIL))"
