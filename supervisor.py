#!/usr/bin/env python3
"""Process supervisor / entrypoint router.

- `python supervisor.py demo`     -> run demo once (same as main.py demo)
- `python supervisor.py runtime`  -> run apps/runtime_trader (loop)

Bạn có thể gắn supervisor vào systemd để auto-restart.

Security note:
- Secrets (Telegram/API keys) nên nằm ở: /etc/bot_trade/bot_trade.env (chmod 600)
- Tránh để `.env` trong thư mục project rồi zip/share.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _maybe_load_env() -> None:
    """Best-effort env loading; NEVER crash runtime."""
    try:
        from trade_ai.infrastructure.config.env_loader import load_env

        used = load_env()
        # Warn if project-root .env exists (easy to leak when zipping)
        proj_env = str(Path.cwd() / ".env")
        if os.path.isfile(proj_env):
            if used == proj_env:
                print(
                    "[SECURITY] Loaded .env from project directory. "
                    "Prefer /etc/bot_trade/bot_trade.env to avoid accidental leaks.",
                    file=sys.stderr,
                )
            else:
                print(
                    "[SECURITY] Found .env in project directory. "
                    "Prefer /etc/bot_trade/bot_trade.env and remove .env to avoid accidental leaks.",
                    file=sys.stderr,
                )
    except Exception:
        return


def main() -> None:
    parser = argparse.ArgumentParser(prog="bot_trade supervisor")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("demo")
    sub.add_parser("runtime")

    args = parser.parse_args()
    cmd = args.cmd or "runtime"

    # ensure repo root in sys.path
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    _maybe_load_env()

    if cmd == "demo":
        from main import demo_flow

        demo_flow()
        return

    if cmd == "runtime":
        from apps.runtime_trader import main as runtime_main

        runtime_main()
        return

    raise SystemExit(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
