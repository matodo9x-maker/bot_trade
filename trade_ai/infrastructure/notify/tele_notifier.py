# trade_ai/infrastructure/notify/tele_notifier.py
from __future__ import annotations

import logging
from typing import Any, Dict

from .message_builder import build_message_from_event
from .telegram_client import TelegramClient

logger = logging.getLogger("tele_notifier")


class TeleNotifier:
    """Event -> Telegram notifier (fail-safe).

    Notes:
    - This class must NEVER raise exception to main loop.
    - It should not leak secrets (token).
    """

    def __init__(self, client: TelegramClient | None = None):
        self.client = client or TelegramClient()

    def handle_event(self, topic_or_type: str | Dict[str, Any], payload: Dict[str, Any] | None = None):
        """Compatible callback for two dispatcher shapes:
          1) (topic, payload) where topic is a string and payload is dict
          2) single arg where arg is dict event
        """
        # Normalize arguments
        if isinstance(topic_or_type, dict) and payload is None:
            event = topic_or_type
        else:
            event = {"type": topic_or_type, "payload": payload}

        try:
            msg = build_message_from_event(event)
            if not msg:
                return None

            res = self.client.send(msg)
            # Don't spam logs; only warn on failure
            if isinstance(res, dict) and res.get("ok") is False:
                logger.warning("Telegram send failed: %s", {k: res.get(k) for k in ("reason", "error")})
            return res
        except Exception:
            # fail-safe: do not raise; just log stacktrace
            logger.exception("TeleNotifier failed")
            return None
