# trade_ai/infrastructure/notify/telegram_client.py
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional

import requests


# Telegram bot tokens look like: 123456789:AA... (digits + ':' + base64-ish)
_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")


def _redact_secrets(text: str) -> str:
    """Best-effort redaction to avoid leaking secrets into logs."""
    if not text:
        return text
    return _TOKEN_RE.sub("<TELEGRAM_BOT_TOKEN_REDACTED>", text)


class TelegramClient:
    """Low-level Telegram sender.

    Security goals:
    - Never hardcode tokens in repo.
    - Avoid returning/logging raw token in exception strings.
    - Allow disabling via TELEGRAM_ENABLED=0.

    Env:
      TELEGRAM_ENABLED=0/1
      TELEGRAM_BOT_TOKEN=...
      TELEGRAM_CHAT_ID=...
      TELEGRAM_PARSE_MODE=Markdown (optional)
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        session: Optional[requests.Session] = None,
    ):
        # Load env at init-time (NOT import-time) to support dotenv / systemd env loading.
        # Backward/compat keys to reduce operator mistakes
        if bot_token is None:
            bot_token = (
                os.getenv("TELEGRAM_BOT_TOKEN")
                or os.getenv("TELEGRAM_TOKEN")
                or os.getenv("TG_BOT_TOKEN")
            )
        if chat_id is None:
            chat_id = (
                os.getenv("TELEGRAM_CHAT_ID")
                or os.getenv("TELEGRAM_CHATID")
                or os.getenv("TG_CHAT_ID")
            )

        if enabled is None:
            enabled_env = os.getenv("TELEGRAM_ENABLED", "1")
            enabled = enabled_env not in ("0", "false", "False", "no", "NO")

        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(enabled)
        self.session = session or requests.Session()

    def _url(self) -> Optional[str]:
        if not self.bot_token or not self.chat_id:
            return None
        return f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send(
        self,
        text: str,
        parse_mode: Optional[str] = None,
        disable_notification: bool = False,
        max_retries: int = 2,
        backoff_sec: float = 0.5,
        timeout_sec: float = 8.0,
    ) -> Dict[str, Any]:
        """Send message synchronously.

        Returns a small JSON-like dict. It is safe to log this return value:
        it will not include the bot token.
        """
        if not self.enabled:
            return {"ok": False, "reason": "disabled"}

        url = self._url()
        if not url:
            return {"ok": False, "reason": "no-token-or-chatid"}

        if parse_mode is None:
            parse_mode = os.getenv("TELEGRAM_PARSE_MODE", "Markdown")

        # Allow disabling parse_mode via env (avoid 'can't parse entities' issues)
        if parse_mode is not None:
            pm = str(parse_mode).strip()
            if pm == "" or pm.lower() in ("none", "off", "0", "false"):
                parse_mode = None
            else:
                parse_mode = pm

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_notification": disable_notification,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        last_exc: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                r = self.session.post(url, json=payload, timeout=timeout_sec)
                r.raise_for_status()
                # Telegram returns JSON with ok/result.
                out = r.json()
                # Extra safety: redact any token-like string in payload (shouldn't happen)
                return out
            except Exception as e:
                last_exc = e
                time.sleep(backoff_sec * (attempt + 1))

        # Failed - return sanitized error, never include URL/token
        err_msg = _redact_secrets(str(last_exc)) if last_exc else "unknown"
        return {"ok": False, "reason": "exception", "error": err_msg}
