#!/bin/sh
# One-time Lean 4 + Mathlib setup in an unprivileged account. Run as root:  sh scripts/setup_lean.sh
# Needs a few GB of disk and can take 20-60 minutes (it downloads Mathlib's prebuilt cache).
set -e
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
id rsi >/dev/null 2>&1 || useradd -m -s /bin/bash rsi
apt-get install -y git curl >/dev/null
runuser -u rsi -- bash -c '
  set -e
  cd ~
  [ -x ~/.elan/bin/lake ] || (curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain none)
  [ -d formal-conjectures ] || git clone --depth 1 https://github.com/google-deepmind/formal-conjectures
  cd formal-conjectures
  export PATH=$HOME/.elan/bin:$PATH
  lake exe cache get
  lake build FormalConjecturesForMathlib FormalConjecturesUtil
'
echo SETUP_DONE
