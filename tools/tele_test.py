"""Quick Telegram connectivity test.

Works on Windows/Linux.

Usage:
  # Option A: use BOT_ENV_FILE
  BOT_ENV_FILE=/etc/bot_trade/bot_trade.env python tools/tele_test.py

  # Option B: use project-root .env
  python tools/tele_test.py

This script:
- loads env best-effort (via trade_ai.infrastructure.config.env_loader)
- sends a test message
"""

from __future__ import annotations

import sys
from pathlib import Path
import time


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    try:
        from trade_ai.infrastructure.config.env_loader import load_env

        used = load_env()
        print(f"[tele_test] env_loaded={used or '(none)'}")
    except Exception as e:
        print(f"[tele_test] env_loader_error={e}")

    from trade_ai.infrastructure.notify.telegram_client import TelegramClient

    c = TelegramClient()
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    res = c.send(f"✅ Telegram OK: bot_trade tele_test at {ts} UTC")
    print(res)


if __name__ == "__main__":
    main()
