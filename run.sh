#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
else
  echo "❌ Không tìm thấy virtualenv (.venv/ hoặc venv/). Hãy tạo venv trước."
  exit 1
fi

python3 -m apps.runtime_trader "$@"
