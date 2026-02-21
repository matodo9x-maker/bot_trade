# trade_ai/infrastructure/market/universe_selector_v1.py
from __future__ import annotations

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
    """Compute ATR(period) / close_last from OHLCV (ms, o, h, l, c, v?)."""
    if not ohlcv or len(ohlcv) < max(3, period + 1):
        return None
    # Use last (period) true ranges
    trs: List[float] = []
    prev_close = None
    for row in ohlcv:
        if not row or len(row) < 5:
            continue
        _c = float(row[4])
        _h = float(row[2])
        _l = float(row[3])
        if prev_close is None:
            tr = _h - _l
        else:
            tr = max(_h - _l, abs(_h - prev_close), abs(_l - prev_close))
        trs.append(float(tr))
        prev_close = _c

    if len(trs) < period + 1:
        return None

    # ATR: SMA of last `period` TR values (skip first which may be unstable)
    last_trs = trs[-period:]
    atr = sum(last_trs) / float(period)
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
    return rets if len(rets) >= 5 else None


def _corr(a: List[float], b: List[float]) -> Optional[float]:
    if not a or not b:
        return None
    n = min(len(a), len(b))
    if n < 10:
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
class UniverseConfig:
    target_symbols: int = 3
    refresh_min: int = 360
    min_quote_vol_usdt: float = 20_000_000
    min_daily_atr_pct: float = 0.01
    max_corr: float = 0.85
    lookback_days: int = 30
    atr_period: int = 14
    max_candidates_by_liquidity: int = 80
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


class UniverseSelectorV1:
    """Select tradable USDT-M symbols for small-cap bot.

    Goals:
    - Exclude stablecoin bases (USDCUSDT, BUSDUSDT, ...)
    - Filter low liquidity (quote volume) and low volatility (daily ATR%)
    - Prefer low correlation among selected symbols
    """

    def __init__(self, cfg: UniverseConfig):
        self.cfg = cfg

    def select(self, ex) -> Dict[str, Any]:
        now = int(time.time())

        markets = []
        try:
            markets = ex.list_active_usdtm_user_symbols()
        except Exception:
            markets = []

        include = {s.upper().strip() for s in self.cfg.include_symbols if s}
        exclude = {s.upper().strip() for s in self.cfg.exclude_symbols if s}
        stable_bases = {s.upper().strip() for s in self.cfg.exclude_bases if s}

        # Always include explicit include list (if exists)
        candidates = set([m.upper().strip() for m in markets if m])
        candidates |= include
        candidates -= exclude

        excluded: List[Dict[str, Any]] = []
        scored: List[Dict[str, Any]] = []

        # 1) Ticker scan (liquidity first) — avoid fetching OHLCV for hundreds of symbols
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
            # fallback: best-effort batch (may still be per-symbol on some exchanges)
            try:
                tickers = ex.fetch_tickers_many(sorted(candidates))
            except Exception:
                tickers = {}

        # Build liquidity-ranked list (filter stable bases early)
        liq_rows: List[Dict[str, Any]] = []
        for sym in sorted(candidates):
            base = sym[:-4] if sym.endswith("USDT") and len(sym) > 4 else sym
            if base in stable_bases:
                excluded.append({"symbol": sym, "reason": "stablecoin_base"})
                continue

            t = tickers.get(sym)
            if not isinstance(t, dict):
                excluded.append({"symbol": sym, "reason": "ticker_unavailable"})
                continue

            qv = _safe_float(t.get("quoteVolume"))
            if qv is None:
                bv = _safe_float(t.get("baseVolume"))
                last = _safe_float(t.get("last") or t.get("close"))
                if bv is not None and last is not None:
                    qv = float(bv) * float(last)

            if qv is None:
                excluded.append({"symbol": sym, "reason": "missing_quote_volume"})
                continue

            liq_rows.append({"symbol": sym, "quote_vol_usdt": float(qv)})

        liq_rows.sort(key=lambda x: float(x.get("quote_vol_usdt") or 0.0), reverse=True)
        top = liq_rows[: max(10, int(self.cfg.max_candidates_by_liquidity))]

        # Make sure included symbols are not accidentally dropped
        for s in include:
            if s and all(r["symbol"] != s for r in top):
                # keep included even if low liquidity, but still apply filters later
                qv = None
                t = tickers.get(s)
                if isinstance(t, dict):
                    qv = _safe_float(t.get("quoteVolume"))
                top.append({"symbol": s, "quote_vol_usdt": float(qv) if qv is not None else 0.0, "_forced": True})

        # 2) Liquidity threshold + OHLCV volatility checks on top candidates only
        for row0 in top:
            sym = row0["symbol"]
            qv = float(row0.get("quote_vol_usdt") or 0.0)
            if qv < float(self.cfg.min_quote_vol_usdt) and not row0.get("_forced"):
                excluded.append({"symbol": sym, "reason": "low_liquidity", "quote_vol_usdt": float(qv)})
                continue

            try:
                ohlcv_d = ex.fetch_ohlcv(sym, timeframe="1d", limit=int(max(self.cfg.lookback_days + 5, self.cfg.atr_period + 5)))
            except Exception as e:
                excluded.append({"symbol": sym, "reason": f"ohlcv_failed: {type(e).__name__}", "quote_vol_usdt": float(qv)})
                continue

            atr_pct = _atr_pct_from_ohlcv(ohlcv_d, int(self.cfg.atr_period))
            if atr_pct is None:
                excluded.append({"symbol": sym, "reason": "atr_unavailable", "quote_vol_usdt": float(qv)})
                continue
            if float(atr_pct) < float(self.cfg.min_daily_atr_pct) and not row0.get("_forced"):
                excluded.append({"symbol": sym, "reason": "low_volatility", "quote_vol_usdt": float(qv), "daily_atr_pct": float(atr_pct)})
                continue

            score = math.log10(float(max(qv, 1.0))) * float(atr_pct)
            scored.append({"symbol": sym, "quote_vol_usdt": float(qv), "daily_atr_pct": float(atr_pct), "score": float(score), "ohlcv_d": ohlcv_d})

        scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

        # 2) Correlation-aware greedy selection
        selected: List[Dict[str, Any]] = []
        ret_cache: Dict[str, List[float]] = {}

        for row in scored:
            if len(selected) >= int(self.cfg.target_symbols):
                break
            sym = row["symbol"]
            # build returns series from daily ohlcv
            if sym not in ret_cache:
                ret = _log_returns_from_ohlcv(row.get("ohlcv_d") or [])
                if ret is None:
                    excluded.append({"symbol": sym, "reason": "returns_unavailable"})
                    continue
                ret_cache[sym] = ret

            ok = True
            corr_with = {}
            for s2 in selected:
                sym2 = s2["symbol"]
                if sym2 not in ret_cache:
                    continue
                c = _corr(ret_cache[sym], ret_cache[sym2])
                if c is not None:
                    corr_with[sym2] = float(c)
                    if abs(float(c)) > float(self.cfg.max_corr):
                        ok = False
                        break
            if not ok:
                excluded.append({"symbol": sym, "reason": "high_correlation", "corr_with": corr_with})
                continue

            selected.append({k: row[k] for k in ("symbol", "quote_vol_usdt", "daily_atr_pct", "score")})

        # cleanup heavy fields
        for r in scored:
            r.pop("ohlcv_d", None)

        return {
            "schema_version": "universe_v1",
            "timestamp_utc": now,
            "exchange": getattr(ex, "exchange_id", None),
            "config": {
                "target_symbols": int(self.cfg.target_symbols),
                "min_quote_vol_usdt": float(self.cfg.min_quote_vol_usdt),
                "min_daily_atr_pct": float(self.cfg.min_daily_atr_pct),
                "max_corr": float(self.cfg.max_corr),
                "lookback_days": int(self.cfg.lookback_days),
                "atr_period": int(self.cfg.atr_period),
                "max_candidates_by_liquidity": int(self.cfg.max_candidates_by_liquidity),
                "exclude_bases": list(stable_bases),
                "include_symbols": list(include),
                "exclude_symbols": list(exclude),
            },
            "selected": selected,
            "candidates_scored": [{k: r[k] for k in ("symbol", "quote_vol_usdt", "daily_atr_pct", "score")} for r in scored[:50]],
            "excluded": excluded[:200],
        }


def universe_config_from_env(os_env) -> UniverseConfig:
    """Helper to build UniverseConfig from os.environ-like mapping."""
    target = int(float(os_env.get("UNIVERSE_TARGET_SYMBOLS", "3") or 3))
    refresh = int(float(os_env.get("UNIVERSE_REFRESH_MIN", "360") or 360))
    min_qv = float(os_env.get("UNIVERSE_MIN_QUOTE_VOL_USDT", "20000000") or 20000000)
    min_atr = float(os_env.get("UNIVERSE_MIN_DAILY_ATR_PCT", "0.01") or 0.01)
    max_corr = float(os_env.get("UNIVERSE_MAX_CORR", "0.85") or 0.85)
    lookback = int(float(os_env.get("UNIVERSE_LOOKBACK_DAYS", "30") or 30))
    atr_period = int(float(os_env.get("UNIVERSE_ATR_PERIOD", "14") or 14))
    max_cand = int(float(os_env.get("UNIVERSE_MAX_CANDIDATES_BY_LIQ", "80") or 80))

    include = tuple([s.upper().replace("/", "").strip() for s in _split_csv(os_env.get("UNIVERSE_INCLUDE_SYMBOLS", ""))])
    exclude = tuple([s.upper().replace("/", "").strip() for s in _split_csv(os_env.get("UNIVERSE_EXCLUDE_SYMBOLS", ""))])
    bases = tuple([s.upper().strip() for s in _split_csv(os_env.get("UNIVERSE_EXCLUDE_BASES", ""))])
    if not bases:
        bases = UniverseConfig().exclude_bases

    return UniverseConfig(
        target_symbols=target,
        refresh_min=refresh,
        min_quote_vol_usdt=min_qv,
        min_daily_atr_pct=min_atr,
        max_corr=max_corr,
        lookback_days=lookback,
        atr_period=atr_period,
        max_candidates_by_liquidity=max_cand,
        exclude_bases=bases,
        include_symbols=include,
        exclude_symbols=exclude,
    )
