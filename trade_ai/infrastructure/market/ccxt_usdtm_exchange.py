# trade_ai/infrastructure/market/ccxt_usdtm_exchange.py
from __future__ import annotations

import os
import time
import math
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger("ccxt_usdtm")


class ExchangeAdapterError(Exception):
    pass


@dataclass(frozen=True)
class OrderIds:
    entry_order_id: Optional[str]
    tp_order_id: Optional[str]
    sl_order_id: Optional[str]

    entry_avg_price: Optional[float] = None
    entry_timestamp_ms: Optional[int] = None


class CcxtUsdtmExchange:
    """CCXT wrapper for USDT-M (linear) futures.

    Supported exchanges (best effort):
    - Binance (USDT-M)
    - Bybit (USDT perpetual)
    - MEXC (USDT perpetual)

    Position mode: One-way (non-hedge) (best-effort)
    Margin mode: Isolated (best-effort)

    IMPORTANT:
    - Exchange APIs differ. This wrapper is conservative and tries multiple
      order-type/param variants.
    - Always test in paper/testnet before live.
    """

    def __init__(
        self,
        exchange_id: str,
        api_key: str = "",
        api_secret: str = "",
        password: str = "",
        sandbox: bool = False,
        enable_rate_limit: bool = True,
        timeout_ms: int = 30000,
    ):
        self.exchange_id = (exchange_id or "").lower().strip()
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.password = password or ""
        self.sandbox = bool(sandbox)
        self.enable_rate_limit = bool(enable_rate_limit)
        self.timeout_ms = int(timeout_ms)

        self._ex = None
        self._markets = None

    # ----------------------------
    # Init
    # ----------------------------
    def connect(self) -> None:
        try:
            import ccxt
        except Exception as e:
            raise ExchangeAdapterError("Missing dependency: ccxt. Install: pip install ccxt") from e

        if not hasattr(ccxt, self.exchange_id):
            raise ExchangeAdapterError(f"ccxt does not support exchange_id={self.exchange_id}")

        klass = getattr(ccxt, self.exchange_id)

        # Default futures type mapping
        default_type = "swap"
        if self.exchange_id in ("binance",):
            default_type = "future"

        self._ex = klass(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "password": self.password,
                "enableRateLimit": self.enable_rate_limit,
                "timeout": self.timeout_ms,
                "options": {
                    "defaultType": default_type,
                },
            }
        )

        # Sandbox/testnet if supported
        try:
            if self.sandbox and hasattr(self._ex, "set_sandbox_mode"):
                self._ex.set_sandbox_mode(True)
        except Exception:
            logger.warning("set_sandbox_mode not supported for %s", self.exchange_id)

        # Load markets
        self._markets = self._ex.load_markets()

    @property
    def ex(self):
        if self._ex is None:
            raise ExchangeAdapterError("Exchange not connected. Call connect() first.")
        return self._ex

    # ----------------------------
    # Symbol helpers
    # ----------------------------
    def resolve_symbol(self, user_symbol: str) -> str:
        """Resolve user symbol like BTCUSDT / BTC/USDT into exchange market symbol."""
        if not user_symbol:
            raise ExchangeAdapterError("symbol required")

        s = user_symbol.strip().upper()
        if "/" in s:
            base, quote = s.split("/", 1)
        else:
            # common USDT suffix
            if s.endswith("USDT") and len(s) > 4:
                base, quote = s[:-4], "USDT"
            else:
                # fallback: treat as already exchange symbol
                base, quote = s, ""

        # Try exact matches in loaded markets
        if self._markets:
            # 1) direct
            if s in self._markets:
                return s
            # 2) common forms
            cand1 = f"{base}/{quote}" if quote else s
            if cand1 in self._markets:
                return cand1
            # 3) linear swap form: BTC/USDT:USDT
            cand2 = f"{base}/{quote}:{quote}" if quote else s
            if cand2 in self._markets:
                return cand2

            # 4) search by base/quote
            for mk, info in self._markets.items():
                try:
                    if info.get("base") == base and info.get("quote") == quote:
                        # Prefer linear swaps/USDT settled if present
                        if ":" in mk:
                            return mk
                        return mk
                except Exception:
                    continue

        return user_symbol

    def list_active_usdtm_user_symbols(self) -> List[str]:
        """Return a list of *user symbols* like BTCUSDT for active USDT-M contracts.

        We normalize market symbols (BTC/USDT:USDT, BTC/USDT, BTCUSDT) into the
        compact user form BASE+QUOTE (no slash).
        """
        if not self._markets:
            try:
                self._markets = self.ex.load_markets()
            except Exception:
                self._markets = {}

        out: List[str] = []
        for _sym, m in (self._markets or {}).items():
            if not isinstance(m, dict):
                continue
            if m.get("active") is False:
                continue
            # futures/swap contract
            if not (m.get("contract") or m.get("swap") or m.get("future")):
                continue
            quote = (m.get("quote") or "").upper()
            base = (m.get("base") or "").upper()
            settle = (m.get("settle") or "").upper() if m.get("settle") else ""

            # USDT-m only
            if quote != "USDT":
                continue
            if settle and settle != "USDT":
                continue

            # avoid inverse/coin-m
            if (m.get("linear") is False) and (m.get("inverse") is True):
                continue

            if not base:
                continue
            out.append(f"{base}USDT")

        # de-dup
        return sorted(list(set(out)))

    def fetch_tickers_many(self, user_symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Best-effort batch ticker fetch.

        Returns mapping user_symbol -> ticker dict.
        """
        res: Dict[str, Dict[str, Any]] = {}
        if not user_symbols:
            return res
        try:
            # Some CCXT exchanges accept list of market symbols
            if hasattr(self.ex, "fetch_tickers"):
                syms = [self.resolve_symbol(s) for s in user_symbols]
                raw = self.ex.fetch_tickers(syms)
                if isinstance(raw, dict):
                    # map back to user symbols
                    for us in user_symbols:
                        ms = self.resolve_symbol(us)
                        tk = raw.get(ms)
                        if isinstance(tk, dict):
                            res[us] = tk
                    if res:
                        return res
        except Exception:
            pass

        # fallback: per symbol
        for s in user_symbols:
            try:
                res[s] = self.fetch_ticker(s)
            except Exception:
                continue
        return res

    # ----------------------------
    # Market data
    # ----------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 200, since_ms: Optional[int] = None) -> List[List[float]]:
        sym = self.resolve_symbol(symbol)
        return self.ex.fetch_ohlcv(sym, timeframe=timeframe, since=since_ms, limit=int(limit))

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        sym = self.resolve_symbol(symbol)
        return self.ex.fetch_ticker(sym)

    def fetch_funding_rate(self, symbol: str) -> float:
        """Best-effort funding rate. If unsupported, returns 0.0."""
        sym = self.resolve_symbol(symbol)
        # CCXT unified method (not always implemented)
        try:
            if hasattr(self.ex, "fetch_funding_rate"):
                fr = self.ex.fetch_funding_rate(sym)
                # common keys: fundingRate
                if isinstance(fr, dict):
                    v = fr.get("fundingRate")
                    return float(v) if v is not None else 0.0
        except Exception:
            pass
        return 0.0

    def fetch_open_interest(self, symbol: str) -> Optional[float]:
        """Best-effort open interest.

        Returns:
            float open interest if available, else None.

        Notes:
        - CCXT unified methods are not consistently supported across exchanges.
        - For Binance USDT-M futures, we also try the public endpoint via raw method.
        """
        sym = self.resolve_symbol(symbol)

        # Unified (best-effort)
        try:
            if hasattr(self.ex, "fetch_open_interest"):
                oi = self.ex.fetch_open_interest(sym)
                if isinstance(oi, dict):
                    v = oi.get("openInterest")
                    if v is None:
                        v = oi.get("openInterestAmount")
                    if v is None:
                        v = oi.get("value")
                    if v is None:
                        v = oi.get("amount")
                    return float(v) if v is not None else None
                if isinstance(oi, (int, float)):
                    return float(oi)
        except Exception:
            pass

        # Exchange-specific (best-effort)
        try:
            if self.exchange_id == "binance":
                # Binance USDT-M open interest endpoint expects symbol like BTCUSDT
                s = symbol.replace("/", "").upper()
                if hasattr(self.ex, "fapiPublicGetOpenInterest"):
                    raw = self.ex.fapiPublicGetOpenInterest({"symbol": s})
                    if isinstance(raw, dict):
                        v = raw.get("openInterest")
                        return float(v) if v is not None else None
        except Exception:
            pass
        return None

    # ----------------------------
    # Account
    # ----------------------------
    def fetch_usdt_balance(self) -> Tuple[float, float]:
        """Return (equity_usdt, free_usdt) best-effort."""
        bal = self.ex.fetch_balance()
        # CCXT balance structure: bal['total']['USDT'], bal['free']['USDT']
        total = None
        free = None
        try:
            total = bal.get("total", {}).get("USDT")
            free = bal.get("free", {}).get("USDT")
        except Exception:
            total = None
            free = None

        # Fallback: search in info
        if total is None or free is None:
            try:
                usdt = bal.get("USDT") or {}
                total = total if total is not None else usdt.get("total")
                free = free if free is not None else usdt.get("free")
            except Exception:
                pass

        equity = float(total) if total is not None else 0.0
        free_u = float(free) if free is not None else 0.0
        return equity, free_u

    def get_market_constraints(self, symbol: str) -> Dict[str, Any]:
        sym = self.resolve_symbol(symbol)
        m = None
        try:
            m = self.ex.market(sym)
        except Exception:
            m = None
        if not isinstance(m, dict):
            return {"min_notional_usdt": 5.0, "min_qty": None, "qty_step": None}

        min_notional = None
        min_qty = None
        qty_step = None
        try:
            min_qty = ((m.get("limits") or {}).get("amount") or {}).get("min")
        except Exception:
            min_qty = None

        try:
            min_notional = ((m.get("limits") or {}).get("cost") or {}).get("min")
        except Exception:
            min_notional = None

        # step from precision.amount
        try:
            prec = (m.get("precision") or {}).get("amount")
            if isinstance(prec, (int, float)) and int(prec) >= 0:
                qty_step = float(10 ** (-int(prec)))
        except Exception:
            qty_step = None

        return {
            "min_notional_usdt": float(min_notional) if min_notional is not None else 5.0,
            "min_qty": float(min_qty) if min_qty is not None else None,
            "qty_step": float(qty_step) if qty_step is not None else None,
        }

    # ----------------------------
    # Futures settings
    # ----------------------------
    def set_oneway_mode(self, symbol: Optional[str] = None) -> None:
        """Best-effort set One-Way (non-hedged) position mode."""
        try:
            if hasattr(self.ex, "set_position_mode"):
                # hedged=False means one-way
                self.ex.set_position_mode(False, symbol=self.resolve_symbol(symbol) if symbol else None)
                return
        except Exception:
            pass
        # ignore if unsupported

    def set_isolated_margin(self, symbol: str) -> None:
        try:
            if hasattr(self.ex, "set_margin_mode"):
                self.ex.set_margin_mode("isolated", self.resolve_symbol(symbol))
                return
        except Exception:
            pass

    def set_leverage(self, symbol: str, leverage: int) -> None:
        lev = int(leverage)
        if lev <= 0:
            return
        try:
            if hasattr(self.ex, "set_leverage"):
                self.ex.set_leverage(lev, self.resolve_symbol(symbol))
                return
        except Exception:
            pass

    # ----------------------------
    # Orders
    # ----------------------------
    def _client_id_param(self, client_id: str) -> Dict[str, Any]:
        if not client_id:
            return {}
        if self.exchange_id in ("binance",):
            return {"newClientOrderId": client_id}
        if self.exchange_id in ("bybit",):
            return {"orderLinkId": client_id}
        # mexc / others
        return {"clientOrderId": client_id}

    def place_entry_and_brackets(
        self,
        symbol: str,
        direction: str,
        qty: float,
        tp_price: float,
        sl_price: float,
        leverage: int,
        client_order_id: str,
    ) -> OrderIds:
        """Open a position (market) then place TP limit + SL stop-market (reduceOnly).

        Returns order ids (best-effort). Some exchanges may reject stop orders;
        in that case sl_order_id may be None (bot must enforce SL by monitoring price).
        """
        sym = self.resolve_symbol(symbol)
        side = "buy" if direction.upper() == "LONG" else "sell"
        exit_side = "sell" if side == "buy" else "buy"

        # Ensure modes
        self.set_oneway_mode(sym)
        self.set_isolated_margin(sym)
        self.set_leverage(sym, leverage)

        params_entry = {}
        params_entry.update(self._client_id_param(client_order_id))

        entry = self.ex.create_order(sym, "market", side, float(qty), None, params_entry)
        entry_id = str(entry.get("id")) if isinstance(entry, dict) and entry.get("id") else None
        entry_avg = None
        entry_ts = None
        try:
            entry_avg = entry.get("average") or entry.get("price")
            entry_avg = float(entry_avg) if entry_avg is not None else None
        except Exception:
            entry_avg = None
        try:
            entry_ts = entry.get("timestamp")
            entry_ts = int(entry_ts) if entry_ts is not None else None
        except Exception:
            entry_ts = None

        # TP limit reduceOnly
        tp_params = {"reduceOnly": True}
        tp_params.update(self._client_id_param(client_order_id + "-TP"))
        try:
            tp = self.ex.create_order(sym, "limit", exit_side, float(qty), float(tp_price), tp_params)
            tp_id = str(tp.get("id")) if isinstance(tp, dict) and tp.get("id") else None
        except Exception as e:
            logger.warning("TP order failed: %s", e)
            tp_id = None

        # SL stop-market reduceOnly (best-effort)
        sl_id = None
        sl_params = {"reduceOnly": True, "stopPrice": float(sl_price)}
        sl_params.update(self._client_id_param(client_order_id + "-SL"))

        # Try a few order types for compatibility
        stop_types = ["stop_market", "STOP_MARKET", "market"]
        for t in stop_types:
            try:
                sl = self.ex.create_order(sym, t, exit_side, float(qty), None, sl_params)
                sl_id = str(sl.get("id")) if isinstance(sl, dict) and sl.get("id") else None
                break
            except Exception:
                continue

        if sl_id is None:
            logger.warning("SL order not supported/failed. Bot must enforce SL by monitoring price.")

        return OrderIds(
            entry_order_id=entry_id,
            tp_order_id=tp_id,
            sl_order_id=sl_id,
            entry_avg_price=entry_avg,
            entry_timestamp_ms=entry_ts,
        )

    def fetch_order(self, symbol: str, order_id: str) -> Optional[Dict[str, Any]]:
        if not order_id:
            return None
        sym = self.resolve_symbol(symbol)
        try:
            return self.ex.fetch_order(order_id, sym)
        except Exception:
            return None

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        if not order_id:
            return False
        sym = self.resolve_symbol(symbol)
        try:
            self.ex.cancel_order(order_id, sym)
            return True
        except Exception:
            return False

    def fetch_position_qty(self, symbol: str) -> float:
        """Return current position size for symbol (signed qty)."""
        sym = self.resolve_symbol(symbol)
        # CCXT unified fetch_positions
        try:
            if hasattr(self.ex, "fetch_positions"):
                pos = self.ex.fetch_positions([sym])
                if isinstance(pos, list) and pos:
                    p0 = pos[0] or {}
                    # common keys: contracts, contractSize, side, info.positionAmt
                    contracts = p0.get("contracts")
                    if contracts is None:
                        # fallback to info
                        info = p0.get("info") or {}
                        contracts = info.get("positionAmt") or info.get("size")
                    q = float(contracts) if contracts is not None else 0.0
                    side = (p0.get("side") or "").lower()
                    if side == "short":
                        q = -abs(q)
                    return float(q)
        except Exception:
            pass
        return 0.0
