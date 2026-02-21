#!/bin/bash
set -euo pipefail

# Create a secure environment file OUTSIDE project dir.
#
# Usage:
#   sudo bash ./deploy/create_env_file.sh              # default /etc/bot_trade/bot_trade.env
#   sudo bash ./deploy/create_env_file.sh /etc/bot_trade/bot_trade.env
#
# Notes:
# - File will be chmod 600
# - Owner will be set to the invoking sudo user (so you can edit without root).

ENV_FILE="${1:-/etc/bot_trade/bot_trade.env}"
ENV_DIR="$(dirname "$ENV_FILE")"

if [ "$(id -u)" -ne 0 ]; then
  echo "[ERR] Please run as root (sudo)." >&2
  exit 1
fi

RUN_USER="${SUDO_USER:-root}"
RUN_GROUP="${SUDO_USER:-root}"

mkdir -p "$ENV_DIR"

if [ -f "$ENV_FILE" ]; then
  echo "✅ Env file already exists: $ENV_FILE"
  echo "Edit it with: nano $ENV_FILE"
  exit 0
fi

cat > "$ENV_FILE" <<'EOF'
# =========================
# TELEGRAM (optional)
# =========================
TELEGRAM_ENABLED=0
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# =========================
# RUNTIME
# =========================
ENV=prod
BOT_MODE=paper  # demo | data | paper | live
DEV_ENABLE_DEMO_DATA=0
LOG_LEVEL=INFO

# =========================
# EXCHANGE KEYS (future)
# =========================
BINANCE_API_KEY=
BINANCE_API_SECRET=
BYBIT_API_KEY=
BYBIT_API_SECRET=
MEXC_API_KEY=
MEXC_API_SECRET=
EOF

chown "$RUN_USER":"$RUN_GROUP" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "✅ Created env file: $ENV_FILE"
echo "👉 Edit it: nano $ENV_FILE"
echo "⚠️ Do NOT commit/share this file."
