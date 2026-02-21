#!/bin/bash
set -euo pipefail

# Usage:
#   sudo bash ./vps_setup.sh /opt/bot_trade
#
# Notes:
# - Script idempotent: run again after `git pull` to update deps.
# - Secrets are stored OUTSIDE project dir at /etc/bot_trade/bot_trade.env

PROJECT_DIR="${1:-/opt/bot_trade}"
INSTALL_ML="${INSTALL_ML:-0}"   # set 1 to install xgboost/lightgbm
ENV_FILE="${ENV_FILE:-/etc/bot_trade/bot_trade.env}"

if [ "$(id -u)" -ne 0 ]; then
  echo "[ERR] Please run as root (sudo)." >&2
  exit 1
fi

echo "🚀 VPS SETUP START"

echo "✅ apt update/upgrade"
apt update -y
apt upgrade -y

echo "✅ install system packages"
apt install -y   python3 python3-pip python3-venv   git tmux htop curl jq rsync   build-essential gcc g++ make   libffi-dev libssl-dev pkg-config

# Create dir
mkdir -p "$PROJECT_DIR"
chown -R "${SUDO_USER:-root}:${SUDO_USER:-root}" "$PROJECT_DIR"

# If running from a different folder, copy code into PROJECT_DIR
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ "$SCRIPT_DIR" != "$PROJECT_DIR" ]; then
  echo "📦 Sync source -> $PROJECT_DIR"
  rsync -a     --exclude '.venv' --exclude 'venv'     --exclude 'data/runtime' --exclude 'data/datasets'     --exclude 'logs'     "$SCRIPT_DIR/" "$PROJECT_DIR/"
fi

cd "$PROJECT_DIR"

# Create venv
if [ ! -d .venv ]; then
  echo "🐍 create venv .venv"
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip wheel

echo "📦 install requirements"
pip install -r requirements.txt

if [ "$INSTALL_ML" = "1" ] && [ -f requirements_ml.txt ]; then
  echo "📦 install ML stack (xgboost/lightgbm)"
  pip install -r requirements_ml.txt
fi

echo "📁 create dirs"
mkdir -p \
  logs \
  data/runtime/snapshots \
  data/runtime \
  data/datasets/rl \
  data/datasets/market \
  data/datasets/supervised \
  data/models

# Create env file outside project
if [ -f "$PROJECT_DIR/deploy/create_env_file.sh" ]; then
  bash "$PROJECT_DIR/deploy/create_env_file.sh" "$ENV_FILE" || true
else
  echo "⚠️ Missing deploy/create_env_file.sh"
fi

echo "✅ VPS SETUP DONE"
echo "Next:"
echo "  1) Edit env: nano $ENV_FILE"
echo "  2) Start:    bash ./vps_start.sh $PROJECT_DIR"
