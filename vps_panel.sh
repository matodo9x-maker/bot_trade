#!/bin/bash
set -euo pipefail

# Simple control panel for VPS usage.
# Works with env file outside project: /etc/bot_trade/bot_trade.env (chmod 600)
#
# Examples:
#   bash ./vps_panel.sh help
#   sudo bash ./vps_panel.sh setup /opt/bot_trade
#   bash ./vps_panel.sh start
#   bash ./vps_panel.sh logs
#   sudo bash ./vps_panel.sh apply-profile demo
#   sudo bash ./vps_panel.sh set BOT_MODE paper
#   sudo bash ./vps_panel.sh tele-test

PROJECT_DIR="${2:-$(cd "$(dirname "$0")" && pwd)}"
ENV_FILE="${ENV_FILE:-/etc/bot_trade/bot_trade.env}"
PROFILE_DIR="$PROJECT_DIR/config/profiles"

cmd="${1:-help}"

_die() { echo "[ERR] $*" >&2; exit 1; }

_need_root_for_env() {
  if [ "$(id -u)" -ne 0 ]; then
    _die "This command needs root to edit $ENV_FILE. Run with: sudo bash ./vps_panel.sh $cmd"
  fi
}

_python_edit_env() {
  # args: KEY VALUE
  local key="$1"
  local val="$2"
  python3 - <<'PY' "$ENV_FILE" "$key" "$val"
import sys, re
env_path, key, val = sys.argv[1], sys.argv[2], sys.argv[3]
key_re = re.compile(rf"^\s*{re.escape(key)}\s*=.*$")
lines = []
try:
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
except FileNotFoundError:
    lines = []

out = []
replaced = False
for line in lines:
    if line.strip().startswith("#") or not line.strip():
        out.append(line)
        continue
    if key_re.match(line):
        out.append(f"{key}={val}")
        replaced = True
    else:
        out.append(line)

if not replaced:
    # ensure a blank line before appending for readability
    if out and out[-1].strip():
        out.append("")
    out.append(f"{key}={val}")

with open(env_path, "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")
PY
}

_apply_profile_file() {
  local profile_path="$1"
  [ -f "$profile_path" ] || _die "Profile not found: $profile_path"

  # Apply each KEY=VALUE line (skip comments/blank)
  while IFS= read -r line; do
    # strip CR
    line="${line%$'\r'}"
    # skip comments/blank
    [[ -z "${line// }" ]] && continue
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    # only KEY=VALUE
    if [[ "$line" != *"="* ]]; then
      continue
    fi
    key="${line%%=*}"
    val="${line#*=}"
    key="$(echo "$key" | tr -d ' ')"
    _python_edit_env "$key" "$val"
  done < "$profile_path"
}

case "$cmd" in
  help)
    cat <<EOF
Usage: bash ./vps_panel.sh <command>

Runtime:
  start                Start bot (nohup recall)
  stop                 Stop bot
  restart              Restart bot
  status               Show status
  logs                 Tail logs

Setup:
  setup [PROJECT_DIR]  Install deps + venv + create env file (needs sudo)
  systemd [PROJECT_DIR]Install systemd service (needs sudo)

Config:
  show-env             Print env file path + non-secret keys
  set KEY VALUE        Set a single key in env file (needs sudo)
  apply-profile NAME   Apply preset in config/profiles/NAME.env (needs sudo)

Telegram:
  tele-test            Send a test message to Telegram (needs sudo to read env)

Notes:
- Secrets should be stored in: $ENV_FILE (chmod 600)
- BOT_MODE: demo | data | paper | live  (live needs LIVE_CONFIRM=1)
- Multi-symbol:
    * BOT_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT
    * or BOT_SYMBOLS=AUTO (use UNIVERSE_* filters)
EOF
    ;;
  setup)
    _need_root_for_env
    sudo bash "$PROJECT_DIR/vps_setup.sh" "$PROJECT_DIR"
    ;;
  systemd)
    _need_root_for_env
    sudo bash "$PROJECT_DIR/deploy/install_systemd.sh" "$PROJECT_DIR"
    ;;
  start)
    bash "$PROJECT_DIR/vps_start.sh" "$PROJECT_DIR"
    ;;
  stop)
    bash "$PROJECT_DIR/vps_stop.sh" "$PROJECT_DIR"
    ;;
  restart)
    bash "$PROJECT_DIR/vps_restart.sh" "$PROJECT_DIR"
    ;;
  status)
    bash "$PROJECT_DIR/vps_status.sh" "$PROJECT_DIR"
    ;;
  logs)
    bash "$PROJECT_DIR/vps_logs.sh" "$PROJECT_DIR"
    ;;
  show-env)
    echo "ENV_FILE=$ENV_FILE"
    if [ ! -f "$ENV_FILE" ]; then
      echo "(missing) create with: sudo bash $PROJECT_DIR/deploy/create_env_file.sh $ENV_FILE"
      exit 0
    fi
    # Show only non-secret-ish lines
    grep -Ev '(_KEY=|_SECRET=|_PASSWORD=|TELEGRAM_BOT_TOKEN=)' "$ENV_FILE" || true
    ;;
  set)
    _need_root_for_env
    key="${2:-}"; val="${3:-}"
    [ -n "$key" ] || _die "Missing KEY"
    _python_edit_env "$key" "$val"
    echo "✅ Updated $key in $ENV_FILE"
    ;;
  apply-profile)
    _need_root_for_env
    name="${2:-}"
    [ -n "$name" ] || _die "Missing profile name. Available: $(ls -1 "$PROFILE_DIR" 2>/dev/null | sed 's/\.env$//' | tr '\n' ' ')"
    profile_path="$PROFILE_DIR/$name.env"
    _apply_profile_file "$profile_path"
    echo "✅ Applied profile: $name -> $ENV_FILE"
    ;;
  tele-test)
    _need_root_for_env
    [ -f "$ENV_FILE" ] || _die "Env file not found: $ENV_FILE"
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    export BOT_ENV_FILE="$ENV_FILE"
    python3 - <<'PY'
from trade_ai.infrastructure.notify.telegram_client import TelegramClient
c = TelegramClient()
res = c.send("✅ Telegram OK: bot_trade panel test")
print(res)
PY
    ;;
  *)
    _die "Unknown command: $cmd (run: bash ./vps_panel.sh help)"
    ;;
esac
