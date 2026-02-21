#!/bin/bash
set -euo pipefail

# Prepare folder structure + sanity checks.
# Run from project root.

mkdir -p logs data/runtime/snapshots data/datasets/rl

if [ ! -f .env ] && [ -f .env.example ]; then
  echo "ℹ️ .env not found."
  echo "   - Local dev: you MAY do: cp .env.example .env  (⚠️ do not zip/share .env)"
  echo "   - VPS: use /etc/bot_trade/bot_trade.env (recommended)"
fi

if [ -d .venv ]; then
  source .venv/bin/activate
fi

python3 -m compileall -q .

echo "OK: bootstrap complete"
