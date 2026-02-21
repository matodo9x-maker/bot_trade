# trade_ai/infrastructure/market/exchange_factory.py
from __future__ import annotations

import os
from typing import Optional

from .ccxt_usdtm_exchange import CcxtUsdtmExchange


def _env_bool(key: str, default: str = "0") -> bool:
    v = os.getenv(key, default)
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def make_exchange_from_env() -> CcxtUsdtmExchange:
    """Factory: build a CCXT USDT-M exchange adapter from environment variables."""

    ex_id = (os.getenv("EXCHANGE") or "binance").lower().strip()
    sandbox = _env_bool("EXCHANGE_TESTNET", "0")
    enable_rl = _env_bool("EXCHANGE_RATE_LIMIT", "1")

    # Per-exchange key names
    if ex_id == "binance":
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")
        password = os.getenv("BINANCE_API_PASSWORD", "")
    elif ex_id == "bybit":
        api_key = os.getenv("BYBIT_API_KEY", "")
        api_secret = os.getenv("BYBIT_API_SECRET", "")
        password = os.getenv("BYBIT_API_PASSWORD", "")
    elif ex_id == "mexc":
        api_key = os.getenv("MEXC_API_KEY", "")
        api_secret = os.getenv("MEXC_API_SECRET", "")
        password = os.getenv("MEXC_API_PASSWORD", "")
    else:
        raise ValueError(f"Unsupported EXCHANGE={ex_id}. Use binance|bybit|mexc")

    ex = CcxtUsdtmExchange(
        exchange_id=ex_id,
        api_key=api_key,
        api_secret=api_secret,
        password=password,
        sandbox=sandbox,
        enable_rate_limit=enable_rl,
        timeout_ms=int(os.getenv("EXCHANGE_TIMEOUT_MS", "30000")),
    )
    ex.connect()
    return ex
