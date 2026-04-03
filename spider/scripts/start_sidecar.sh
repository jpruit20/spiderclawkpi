#!/usr/bin/env bash
set -e
cd /home/jpruit20/.openclaw/workspace/spider/sidecar
source .venv/bin/activate
rm -f .sidecar.lock
exec python -u gpt_sidecar.py
