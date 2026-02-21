# trade_ai/infrastructure/config/env_loader.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


DEFAULT_ENV_FILE = "/etc/bot_trade/bot_trade.env"


def load_env(env_file: Optional[str] = None) -> Optional[str]:
    """Load environment variables from a file (best effort).

    Priority:
      1) explicit arg env_file
      2) BOT_ENV_FILE
      3) /etc/bot_trade/bot_trade.env
      4) ./ .env (project root)  (not recommended, will only load if exists)

    Returns the path used (if loaded), else None.
    """
    if load_dotenv is None:
        return None

    # NOTE:
    # - We intentionally keep this function best-effort and non-throwing.
    # - Some operators start the bot from a different working directory (systemd/Task Scheduler),
    #   so relying on Path.cwd() to find `.env` is fragile.

    candidates = []
    if env_file:
        candidates.append(env_file)

    bot_env = os.getenv("BOT_ENV_FILE")
    if bot_env:
        candidates.append(bot_env)

    candidates.append(DEFAULT_ENV_FILE)

    # Project-root .env (robust even if cwd != repo root)
    try:
        # .../bot_trade/trade_ai/infrastructure/config/env_loader.py -> parents[3] == project root (bot_trade)
        project_root = Path(__file__).resolve().parents[3]
        candidates.append(str(project_root / ".env"))
    except Exception:
        pass

    # Last-resort fallback (dev only)
    candidates.append(str(Path.cwd() / ".env"))

    override = os.getenv("BOT_ENV_OVERRIDE", "0").strip().lower() in ("1", "true", "yes", "y", "on")

    for p in candidates:
        try:
            if p and os.path.isfile(p):
                load_dotenv(p, override=override)
                return p
        except Exception:
            # Do not raise here: env loading should never crash runtime
            continue

    return None
