#!/bin/bash
set -euo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "$0")" && pwd)}"
PID_FILE="$PROJECT_DIR/bot.pid"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "✅ RUNNING (PID $PID)"
    exit 0
  fi
fi

echo "🟥 NOT RUNNING"
exit 1
