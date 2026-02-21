#!/bin/bash
set -euo pipefail

PROJECT_DIR="${1:-/opt/bot_trade}"
SERVICE_NAME="bot_trade"
ENV_FILE="${ENV_FILE:-/etc/bot_trade/bot_trade.env}"

if [ "$(id -u)" -ne 0 ]; then
  echo "[ERR] Please run as root (sudo)." >&2
  exit 1
fi

RUN_USER="${SUDO_USER:-root}"
RUN_GROUP="$RUN_USER"

TEMPLATE="$PROJECT_DIR/systemd/bot_trade.service.template"
OUT="/etc/systemd/system/${SERVICE_NAME}.service"

if [ ! -f "$TEMPLATE" ]; then
  echo "[ERR] Missing template: $TEMPLATE" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "⚠️ Env file not found: $ENV_FILE"
  echo "Create it with:"
  echo "  sudo bash $PROJECT_DIR/deploy/create_env_file.sh $ENV_FILE"
fi

cat "$TEMPLATE"   | sed "s|__PROJECT_DIR__|$PROJECT_DIR|g"   | sed "s|__RUN_USER__|$RUN_USER|g"   | sed "s|__RUN_GROUP__|$RUN_GROUP|g"   | sed "s|__ENV_FILE__|$ENV_FILE|g"   > "$OUT"

systemctl daemon-reload

echo "✅ Installed $OUT"
echo "Next:"
echo "  sudo systemctl enable $SERVICE_NAME"
echo "  sudo systemctl start  $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"
