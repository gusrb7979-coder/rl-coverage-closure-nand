#!/usr/bin/env bash
# One-time setup of the flow-2 environment inside WSL Ubuntu 24.04 (run as root):
#   wsl -d Ubuntu-24.04 -u root -- bash <project in /mnt/c>/flow2_uvm/setup_wsl.sh
# Installs Icarus Verilog (apt), Yosys (apt, optional synthesis check) and a Python venv
# with cocotb + pyuvm + numpy. Tested with: Ubuntu 24.04.5, Python 3.12.3, Icarus 12.0,
# cocotb 2.1.0, pyuvm 5.0.0 (pyuvm requires cocotb >=1.6,<3.0; cocotb requires Icarus >= 11).
set -e
VENV=${RLCOV_VENV:-/root/rlcov/.venv}
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq iverilog python3-venv make yosys
mkdir -p "$(dirname "$VENV")"
[ -d "$VENV" ] || python3 -m venv "$VENV"
. "$VENV/bin/activate"
pip install -q --upgrade pip
pip install -q "cocotb==2.1.0" "pyuvm==5.0.0" numpy
pip check
iverilog -V 2>&1 | head -1
yosys -V
python -c "import cocotb, pyuvm; print('cocotb', cocotb.__version__, '| pyuvm OK')"
