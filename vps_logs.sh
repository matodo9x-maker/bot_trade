#!/bin/bash
set -euo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "$0")" && pwd)}"
LOG_FILE="$PROJECT_DIR/logs/system.log"

tail -n 200 -f "$LOG_FILE"
