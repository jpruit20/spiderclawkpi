#!/usr/bin/env bash
set -e
cd /home/jpruit20/.openclaw/workspace/spider/sidecar
source .venv/bin/activate
rm -f .sidecar.lock
mkdir -p run
nohup python -u gpt_sidecar.py > run/sidecar.log 2>&1 &
echo $! > run/sidecar.pid
echo "sidecar started pid=$(cat run/sidecar.pid) log=$(pwd)/run/sidecar.log"
