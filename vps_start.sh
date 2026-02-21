#!/bin/bash
set -euo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "$0")" && pwd)}"
LOG_FILE="$PROJECT_DIR/logs/system.log"
PID_FILE="$PROJECT_DIR/bot.pid"
ENV_FILE="${ENV_FILE:-/etc/bot_trade/bot_trade.env}"

cd "$PROJECT_DIR"

if [ -f "$PID_FILE" ]; then
  if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "⚠️ BOT already running (PID $(cat "$PID_FILE"))"
    exit 0
  else
    rm -f "$PID_FILE"
  fi
fi

if [ ! -d .venv ]; then
  echo "[ERR] .venv not found. Run: sudo bash ./vps_setup.sh /opt/bot_trade" >&2
  exit 1
fi

# Load env (do NOT print values)
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
  export BOT_ENV_FILE="$ENV_FILE"
elif [ -f "$PROJECT_DIR/.env" ]; then
  # Fallback for old setups (NOT recommended)
  echo "⚠️ [SECURITY] Using $PROJECT_DIR/.env. Prefer /etc/bot_trade/bot_trade.env" >> "$LOG_FILE"
  set -a
  source "$PROJECT_DIR/.env"
  set +a
  export BOT_ENV_FILE="$PROJECT_DIR/.env"
fi

source .venv/bin/activate
mkdir -p logs

echo "🚀 START BOT $(date -u)" >> "$LOG_FILE"

# Run supervisor (runtime loop)
nohup python3 supervisor.py runtime >> "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"
echo "✅ BOT STARTED (PID $(cat "$PID_FILE"))"
echo "📌 Logs: tail -f $LOG_FILE"
