#!/bin/sh
# Copy this tree into your clone of chnetinc77/RSISolutions, commit, push.
set -e
git clone https://github.com/chnetinc77/RSISolutions.git ../RSISolutions-clone 2>/dev/null || true
cp -r ./* .gitignore ../RSISolutions-clone/ && cd ../RSISolutions-clone
git add -A && git commit -m "Build RSI scientific discovery system with Hou-Zeng (PPL 013) as first target" && git push
