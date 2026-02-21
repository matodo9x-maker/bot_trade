# trade_ai/infrastructure/market/universe_selector_v2.py
from __future__ import annotations

"""Universe selector v2 (dynamic symbol universe).

Design goals (AI-ready):
1) Pick a *small* set of USDT-M perpetual symbols that are liquid and volatile.
2) Avoid unstable bases (stablecoins) and obvious bad markets (wide spread, extreme funding).
3) Diversify by correlation (greedy selection).
4) Emit a rich report for audit + future AI training.

This module is intentionally conservative and best-effort:
- If an exchange endpoint is unavailable, we degrade gracefully.
- We never assume private endpoints; public data is enough.
"""

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def _split_csv(v: str) -> List[str]:
    if not v:
        return []
    return [x.strip() for x in str(v).split(",") if x.strip()]


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _atr_pct_from_ohlcv(ohlcv: List[List[float]], period: int) -> Optional[float]:
    """Compute ATR(period) / close_last from OHLCV rows (ms, o, h, l, c, v?)."""
    if not ohlcv or len(ohlcv) < max(3, period + 1):
        return None
    trs: List[float] = []
    prev_close = None
    for row in ohlcv:
        if not row or len(row) < 5:
            continue
        c = float(row[4])
        h = float(row[2])
        l = float(row[3])
        if prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(float(tr))
        prev_close = c
    if len(trs) < period + 1:
        return None
    atr = sum(trs[-period:]) / float(period)
    close_last = float(ohlcv[-1][4])
    if close_last <= 0:
        return None
    return float(atr) / float(close_last)


def _log_returns_from_ohlcv(ohlcv: List[List[float]]) -> Optional[List[float]]:
    if not ohlcv or len(ohlcv) < 5:
        return None
    closes: List[float] = []
    for row in ohlcv:
        if not row or len(row) < 5:
            continue
        closes.append(float(row[4]))
    if len(closes) < 5:
        return None
    rets: List[float] = []
    for i in range(1, len(closes)):
        a = closes[i - 1]
        b = closes[i]
        if a <= 0 or b <= 0:
            continue
        rets.append(math.log(b / a))
    return rets if len(rets) >= 10 else None


def _corr(a: List[float], b: List[float]) -> Optional[float]:
    if not a or not b:
        return None
    n = min(len(a), len(b))
    if n < 12:
        return None
    a2 = a[-n:]
    b2 = b[-n:]
    ma = sum(a2) / n
    mb = sum(b2) / n
    va = sum((x - ma) ** 2 for x in a2)
    vb = sum((x - mb) ** 2 for x in b2)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((a2[i] - ma) * (b2[i] - mb) for i in range(n))
    return float(cov / math.sqrt(va * vb))


@dataclass(frozen=True)
class UniverseConfigV2:
    # selection size & refresh
    target_symbols: int = 5
    refresh_min: int = 360

    # liquidity filter
    min_quote_vol_usdt: float = 15_000_000
    max_candidates_by_liquidity: int = 120

    # market quality filters
    max_spread_pct: float = 0.0025
    max_abs_funding: float = 0.0020
    min_last_price: float = 0.0

    # volatility filter
    atr_tf: str = "1h"
    atr_period: int = 14
    atr_limit: int = 200
    min_atr_pct: float = 0.004

    # correlation diversification
    max_corr: float = 0.85
    corr_tf: str = "1h"
    corr_limit: int = 250

    # allow manual overrides
    exclude_bases: Tuple[str, ...] = (
        "USDC",
        "BUSD",
        "TUSD",
        "FDUSD",
        "DAI",
        "USDP",
        "USDE",
        "USTC",
    )
    include_symbols: Tuple[str, ...] = ()
    exclude_symbols: Tuple[str, ...] = ()

    # anti-thrashing (sticky)
    sticky_enabled: bool = True
    sticky_keep: int = 2


class UniverseSelectorV2:
    """Universe selection v2.

    Compared to v1:
    - Adds funding-rate and spread filters (best-effort from ticker/funding endpoints)
    - Uses configurable ATR timeframe (default 1h) for more responsive selection
    - Emits more metrics per selected symbol
    - Optional sticky keep of previous selections to reduce thrashing
    """

    def __init__(self, cfg: UniverseConfigV2):
        self.cfg = cfg

    def select(self, ex, prev_selected: Optional[List[str]] = None) -> Dict[str, Any]:
        now = int(time.time())

        markets: List[str] = []
        try:
            markets = ex.list_active_usdtm_user_symbols()
        except Exception:
            markets = []

        include = {s.upper().strip().replace("/", "") for s in self.cfg.include_symbols if s}
        exclude = {s.upper().strip().replace("/", "") for s in self.cfg.exclude_symbols if s}
        stable_bases = {s.upper().strip() for s in self.cfg.exclude_bases if s}
        prev = [s.upper().strip().replace("/", "") for s in (prev_selected or []) if s]

        candidates = set([m.upper().strip().replace("/", "") for m in markets if m])
        candidates |= include
        candidates -= exclude

        excluded: List[Dict[str, Any]] = []
        scored: List[Dict[str, Any]] = []

        # --- Ticker scan (liquidity + spread + price)
        tickers: Dict[str, Dict[str, Any]] = {}
        try:
            if hasattr(ex, "ex") and hasattr(ex.ex, "fetch_tickers"):
                raw_all = ex.ex.fetch_tickers()  # type: ignore[attr-defined]
                if isinstance(raw_all, dict):
                    for sym in candidates:
                        ms = ex.resolve_symbol(sym)
                        tk = raw_all.get(ms)
                        if isinstance(tk, dict):
                            tickers[sym] = tk
        except Exception:
            tickers = {}

        if not tickers:
            try:
                tickers = ex.fetch_tickers_many(sorted(candidates))
            except Exception:
                tickers = {}

        liq_rows: List[Dict[str, Any]] = []
        for sym in sorted(candidates):
            base = sym[:-4] if sym.endswith("USDT") and len(sym) > 4 else sym
            if base in stable_bases:
                excluded.append({"symbol": sym, "reason": "stablecoin_base"})
                continue

            tk = tickers.get(sym)
            if not isinstance(tk, dict):
                excluded.append({"symbol": sym, "reason": "ticker_unavailable"})
                continue

            last = _safe_float(tk.get("last") or tk.get("close"))
            if last is None or last <= 0:
                excluded.append({"symbol": sym, "reason": "bad_last_price"})
                continue
            if float(last) < float(self.cfg.min_last_price) and sym not in include:
                excluded.append({"symbol": sym, "reason": "min_last_price", "last": float(last)})
                continue

            qv = _safe_float(tk.get("quoteVolume"))
            if qv is None:
                bv = _safe_float(tk.get("baseVolume"))
                if bv is not None:
                    qv = float(bv) * float(last)
            if qv is None:
                excluded.append({"symbol": sym, "reason": "missing_quote_volume"})
                continue

            bid = _safe_float(tk.get("bid"))
            ask = _safe_float(tk.get("ask"))
            spread_pct = None
            if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
                mid = (bid + ask) / 2.0
                if mid > 0:
                    spread_pct = float((ask - bid) / mid)

            liq_rows.append({
                "symbol": sym,
                "quote_vol_usdt": float(qv),
                "last": float(last),
                "spread_pct": float(spread_pct) if spread_pct is not None else None,
            })

        liq_rows.sort(key=lambda x: float(x.get("quote_vol_usdt") or 0.0), reverse=True)
        top = liq_rows[: max(10, int(self.cfg.max_candidates_by_liquidity))]

        # force include
        for s in include:
            if s and all(r["symbol"] != s for r in top):
                top.append({"symbol": s, "quote_vol_usdt": 0.0, "last": None, "spread_pct": None, "_forced": True})

        # --- volatility + funding filters on top set only
        for row0 in top:
            sym = row0["symbol"]
            qv = float(row0.get("quote_vol_usdt") or 0.0)
            if qv < float(self.cfg.min_quote_vol_usdt) and not row0.get("_forced"):
                excluded.append({"symbol": sym, "reason": "low_liquidity", "quote_vol_usdt": float(qv)})
                continue

            spread_pct = row0.get("spread_pct")
            if spread_pct is not None and float(spread_pct) > float(self.cfg.max_spread_pct) and not row0.get("_forced"):
                excluded.append({"symbol": sym, "reason": "wide_spread", "spread_pct": float(spread_pct)})
                continue

            # funding rate (best-effort)
            funding = 0.0
            try:
                funding = float(ex.fetch_funding_rate(sym))
            except Exception:
                funding = 0.0
            if float(self.cfg.max_abs_funding) > 0 and abs(float(funding)) > float(self.cfg.max_abs_funding) and not row0.get("_forced"):
                excluded.append({"symbol": sym, "reason": "extreme_funding", "funding_rate": float(funding)})
                continue

            # ATR% (responsive timeframe)
            try:
                ohlcv = ex.fetch_ohlcv(sym, timeframe=str(self.cfg.atr_tf), limit=int(self.cfg.atr_limit))
            except Exception as e:
                excluded.append({"symbol": sym, "reason": f"ohlcv_failed: {type(e).__name__}"})
                continue
            atr_pct = _atr_pct_from_ohlcv(ohlcv, int(self.cfg.atr_period))
            if atr_pct is None:
                excluded.append({"symbol": sym, "reason": "atr_unavailable"})
                continue
            if float(atr_pct) < float(self.cfg.min_atr_pct) and not row0.get("_forced"):
                excluded.append({"symbol": sym, "reason": "low_volatility", "atr_pct": float(atr_pct)})
                continue

            # Score: liquidity * volatility with penalties
            liq_term = math.log10(float(max(qv, 1.0)))
            spread_pen = 1.0
            if spread_pct is not None:
                spread_pen = 1.0 / (1.0 + float(spread_pct) * 200.0)
            fund_pen = 1.0
            if float(self.cfg.max_abs_funding) > 0:
                fund_pen = max(0.1, 1.0 - abs(float(funding)) / float(self.cfg.max_abs_funding))

            score = liq_term * float(atr_pct) * float(spread_pen) * float(fund_pen)
            scored.append({
                "symbol": sym,
                "quote_vol_usdt": float(qv),
                "atr_tf": str(self.cfg.atr_tf),
                "atr_pct": float(atr_pct),
                "spread_pct": float(spread_pct) if spread_pct is not None else None,
                "funding_rate": float(funding),
                "score": float(score),
                "ohlcv_for_corr": None,  # fill lazily
            })

        scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

        # --- correlation-aware greedy selection
        selected: List[Dict[str, Any]] = []
        ret_cache: Dict[str, List[float]] = {}

        def _get_rets(sym: str) -> Optional[List[float]]:
            if sym in ret_cache:
                return ret_cache[sym]
            try:
                o = ex.fetch_ohlcv(sym, timeframe=str(self.cfg.corr_tf), limit=int(self.cfg.corr_limit))
            except Exception:
                return None
            rets = _log_returns_from_ohlcv(o)
            if rets is None:
                return None
            ret_cache[sym] = rets
            return rets

        # Sticky keep: attempt to keep some previous symbols that still qualify
        sticky_pool: List[str] = []
        if self.cfg.sticky_enabled and prev:
            ok_prev = []
            scored_set = {r["symbol"] for r in scored}
            for s in prev:
                if s in scored_set:
                    ok_prev.append(s)
            sticky_pool = ok_prev[: max(0, int(self.cfg.sticky_keep))]

        for s in sticky_pool:
            row = next((r for r in scored if r["symbol"] == s), None)
            if not row:
                continue
            # add without correlation check among sticky themselves (still check vs selected)
            selected.append({k: row.get(k) for k in ("symbol", "quote_vol_usdt", "atr_tf", "atr_pct", "spread_pct", "funding_rate", "score")})

        for row in scored:
            if len(selected) >= int(self.cfg.target_symbols):
                break
            sym = row["symbol"]
            if any(x.get("symbol") == sym for x in selected):
                continue

            rets = _get_rets(sym)
            if rets is None:
                excluded.append({"symbol": sym, "reason": "returns_unavailable"})
                continue

            ok = True
            corr_with: Dict[str, float] = {}
            for s2 in selected:
                sym2 = str(s2.get("symbol") or "")
                if not sym2:
                    continue
                rets2 = _get_rets(sym2)
                if rets2 is None:
                    continue
                c = _corr(rets, rets2)
                if c is not None:
                    corr_with[sym2] = float(c)
                    if abs(float(c)) > float(self.cfg.max_corr):
                        ok = False
                        break
            if not ok:
                excluded.append({"symbol": sym, "reason": "high_correlation", "corr_with": corr_with})
                continue

            selected.append({k: row.get(k) for k in ("symbol", "quote_vol_usdt", "atr_tf", "atr_pct", "spread_pct", "funding_rate", "score")})

        return {
            "schema_version": "universe_v2",
            "timestamp_utc": now,
            "exchange": getattr(ex, "exchange_id", None),
            "config": {
                "target_symbols": int(self.cfg.target_symbols),
                "refresh_min": int(self.cfg.refresh_min),
                "min_quote_vol_usdt": float(self.cfg.min_quote_vol_usdt),
                "max_candidates_by_liquidity": int(self.cfg.max_candidates_by_liquidity),
                "max_spread_pct": float(self.cfg.max_spread_pct),
                "max_abs_funding": float(self.cfg.max_abs_funding),
                "min_last_price": float(self.cfg.min_last_price),
                "atr_tf": str(self.cfg.atr_tf),
                "atr_period": int(self.cfg.atr_period),
                "atr_limit": int(self.cfg.atr_limit),
                "min_atr_pct": float(self.cfg.min_atr_pct),
                "max_corr": float(self.cfg.max_corr),
                "corr_tf": str(self.cfg.corr_tf),
                "corr_limit": int(self.cfg.corr_limit),
                "exclude_bases": list(stable_bases),
                "include_symbols": list(include),
                "exclude_symbols": list(exclude),
                "sticky_enabled": bool(self.cfg.sticky_enabled),
                "sticky_keep": int(self.cfg.sticky_keep),
                "prev_selected": prev,
            },
            "selected": selected,
            "candidates_scored": [
                {k: r.get(k) for k in ("symbol", "quote_vol_usdt", "atr_tf", "atr_pct", "spread_pct", "funding_rate", "score")}
                for r in scored[:50]
            ],
            "excluded": excluded[:250],
        }


def universe_config_v2_from_env(os_env) -> UniverseConfigV2:
    """Build UniverseConfigV2 from os.environ-like mapping."""
    def _get_float(k: str, d: str) -> float:
        try:
            return float(os_env.get(k, d) or d)
        except Exception:
            return float(d)

    def _get_int(k: str, d: str) -> int:
        try:
            return int(float(os_env.get(k, d) or d))
        except Exception:
            return int(float(d))

    def _get_bool(k: str, d: str) -> bool:
        v = str(os_env.get(k, d) or d).strip().lower()
        return v in ("1", "true", "yes", "y", "on")

    include = tuple([s.upper().replace("/", "").strip() for s in _split_csv(os_env.get("UNIVERSE_INCLUDE_SYMBOLS", ""))])
    exclude = tuple([s.upper().replace("/", "").strip() for s in _split_csv(os_env.get("UNIVERSE_EXCLUDE_SYMBOLS", ""))])
    bases = tuple([s.upper().strip() for s in _split_csv(os_env.get("UNIVERSE_EXCLUDE_BASES", ""))])
    if not bases:
        bases = UniverseConfigV2().exclude_bases

    return UniverseConfigV2(
        target_symbols=_get_int("UNIVERSE_TARGET_SYMBOLS", "5"),
        refresh_min=_get_int("UNIVERSE_REFRESH_MIN", "360"),
        min_quote_vol_usdt=_get_float("UNIVERSE_MIN_QUOTE_VOL_USDT", "15000000"),
        max_candidates_by_liquidity=_get_int("UNIVERSE_MAX_CANDIDATES_BY_LIQ", "120"),
        max_spread_pct=_get_float("UNIVERSE_MAX_SPREAD_PCT", "0.0025"),
        max_abs_funding=_get_float("UNIVERSE_MAX_ABS_FUNDING", "0.0020"),
        min_last_price=_get_float("UNIVERSE_MIN_LAST_PRICE", "0"),
        atr_tf=str(os_env.get("UNIVERSE_ATR_TF", "1h") or "1h"),
        atr_period=_get_int("UNIVERSE_ATR_PERIOD", "14"),
        atr_limit=_get_int("UNIVERSE_ATR_LIMIT", "200"),
        min_atr_pct=_get_float("UNIVERSE_MIN_ATR_PCT", "0.004"),
        max_corr=_get_float("UNIVERSE_MAX_CORR", "0.85"),
        corr_tf=str(os_env.get("UNIVERSE_CORR_TF", "1h") or "1h"),
        corr_limit=_get_int("UNIVERSE_CORR_LIMIT", "250"),
        exclude_bases=bases,
        include_symbols=include,
        exclude_symbols=exclude,
        sticky_enabled=_get_bool("UNIVERSE_STICKY_ENABLED", "1"),
        sticky_keep=_get_int("UNIVERSE_STICKY_KEEP", "2"),
    )
