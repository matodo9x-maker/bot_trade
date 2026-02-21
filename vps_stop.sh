#!/bin/bash
set -euo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "$0")" && pwd)}"
PID_FILE="$PROJECT_DIR/bot.pid"

cd "$PROJECT_DIR"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "🛑 BOT STOPPED (PID $PID)"
  else
    echo "⚠️ PID file exists but process not running. Cleaning..."
  fi
  rm -f "$PID_FILE"
else
  echo "⚠️ BOT NOT RUNNING"
fi
