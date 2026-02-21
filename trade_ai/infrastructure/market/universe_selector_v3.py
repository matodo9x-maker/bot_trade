# trade_ai/infrastructure/market/universe_selector_v3.py
from __future__ import annotations

"""Universe selector v3 (dynamic symbol universe, richer signals).

V3 adds more ranking signals (best-effort):
- Open Interest (OI) level + acceleration
- Volume acceleration (quoteVolume change since last refresh)
- Volatility burst (ATR% change since last refresh / median)
- Funding z-score (computed from cached history)

It also supports emitting per-symbol rows for AI training (handled by runtime/repo).

Important:
- This module never requires private endpoints.
- When a metric endpoint is unavailable, we degrade gracefully.
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


def _clamp(x: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, x)))


def _zscore(series: List[float], x: float) -> Optional[float]:
    if not series or len(series) < 8:
        return None
    m = sum(series) / float(len(series))
    v = sum((t - m) ** 2 for t in series) / float(max(1, len(series) - 1))
    if v <= 1e-18:
        return None
    return float((x - m) / math.sqrt(v))


def _atr_pct_from_ohlcv(ohlcv: List[List[float]], period: int) -> Optional[float]:
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
class UniverseConfigV3:
    # selection size & refresh
    target_symbols: int = 8
    refresh_min: int = 180

    # liquidity filter
    min_quote_vol_usdt: float = 20_000_000
    max_candidates_by_liquidity: int = 160

    # market quality filters
    max_spread_pct: float = 0.0030
    max_abs_funding: float = 0.0030
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

    # anti-thrashing (sticky)
    sticky_enabled: bool = True
    sticky_keep: int = 2

    # history window for zscores / acceleration (from cached logs)
    history_points: int = 64

    # ranking weights (raw score)
    w_liq: float = 1.0
    w_atr: float = 2.0
    w_vol_burst: float = 0.7
    w_vol_accel: float = 0.8
    w_oi: float = 0.7
    w_oi_accel: float = 0.6
    w_fund_abs_pen: float = 1.2
    w_fund_z_pen: float = 0.7
    w_spread_pen: float = 1.0

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


class UniverseSelectorV3:
    """Universe selection v3 with richer metrics."""

    def __init__(self, cfg: UniverseConfigV3):
        self.cfg = cfg

    def select(
        self,
        ex,
        prev_selected: Optional[List[str]] = None,
        history_by_symbol: Optional[Dict[str, Dict[str, List[float]]]] = None,
        prev_metrics_by_symbol: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Dict[str, Any]:
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

            liq_rows.append(
                {
                    "symbol": sym,
                    "quote_vol_usdt": float(qv),
                    "last": float(last),
                    "spread_pct": float(spread_pct) if spread_pct is not None else None,
                }
            )

        liq_rows.sort(key=lambda x: float(x.get("quote_vol_usdt") or 0.0), reverse=True)
        top = liq_rows[: max(10, int(self.cfg.max_candidates_by_liquidity))]

        # force include
        for s in include:
            if s and all(r["symbol"] != s for r in top):
                top.append({"symbol": s, "quote_vol_usdt": 0.0, "last": None, "spread_pct": None, "_forced": True})

        # --- compute metrics and score on top set
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

            # Open interest (best-effort)
            oi = None
            try:
                if hasattr(ex, "fetch_open_interest"):
                    oi = ex.fetch_open_interest(sym)
            except Exception:
                oi = None

            # History-based features (acceleration / zscores) from cached logs
            h = (history_by_symbol or {}).get(sym) or {}
            prevm = (prev_metrics_by_symbol or {}).get(sym) or {}

            # Funding zscore from cached history
            fr_hist = [float(x) for x in (h.get("funding_rate") or []) if isinstance(x, (int, float))]
            fund_z = _zscore(fr_hist[-int(self.cfg.history_points):], float(funding))

            # Volume accel vs previous refresh
            prev_qv = _safe_float(prevm.get("quote_vol_usdt"))
            vol_accel = None
            if prev_qv is not None and prev_qv > 0:
                vol_accel = float((qv - float(prev_qv)) / float(prev_qv))

            # Volatility burst vs previous ATR% or median
            prev_atr = _safe_float(prevm.get("atr_pct"))
            atr_burst = None
            if prev_atr is not None and prev_atr > 1e-12:
                atr_burst = float(atr_pct / float(prev_atr))
            else:
                atr_hist = [float(x) for x in (h.get("atr_pct") or []) if isinstance(x, (int, float))]
                if len(atr_hist) >= 8:
                    med = sorted(atr_hist[-int(self.cfg.history_points):])[len(atr_hist[-int(self.cfg.history_points):]) // 2]
                    if med and med > 1e-12:
                        atr_burst = float(atr_pct / float(med))

            # OI accel
            prev_oi = _safe_float(prevm.get("open_interest"))
            oi_accel = None
            if oi is not None and prev_oi is not None and prev_oi > 0:
                oi_accel = float((float(oi) - float(prev_oi)) / float(prev_oi))

            # Score (raw, best-effort)
            liq_term = math.log10(float(max(qv, 1.0)))
            oi_term = math.log10(float(max(float(oi or 0.0), 1.0))) if oi is not None else 0.0

            # penalties
            spread_pen = float(spread_pct) if spread_pct is not None else 0.0
            fund_abs = abs(float(funding))
            fund_z_abs = abs(float(fund_z)) if fund_z is not None else 0.0

            # clamp accel/burst to avoid score explosions
            v_acc = _clamp(float(vol_accel) if vol_accel is not None else 0.0, -0.7, 3.0)
            v_burst = _clamp(float(atr_burst) if atr_burst is not None else 1.0, 0.3, 5.0)
            oi_a = _clamp(float(oi_accel) if oi_accel is not None else 0.0, -0.7, 3.0)

            score = (
                float(self.cfg.w_liq) * float(liq_term)
                + float(self.cfg.w_atr) * float(atr_pct)
                + float(self.cfg.w_vol_burst) * float(v_burst)
                + float(self.cfg.w_vol_accel) * float(v_acc)
                + float(self.cfg.w_oi) * float(oi_term)
                + float(self.cfg.w_oi_accel) * float(oi_a)
                - float(self.cfg.w_spread_pen) * float(spread_pen) * 100.0
                - float(self.cfg.w_fund_abs_pen) * float(fund_abs) * 400.0
                - float(self.cfg.w_fund_z_pen) * float(fund_z_abs) * 0.5
            )

            scored.append(
                {
                    "symbol": sym,
                    "quote_vol_usdt": float(qv),
                    "atr_tf": str(self.cfg.atr_tf),
                    "atr_pct": float(atr_pct),
                    "atr_burst": float(v_burst) if atr_burst is not None else None,
                    "spread_pct": float(spread_pct) if spread_pct is not None else None,
                    "funding_rate": float(funding),
                    "funding_z": float(fund_z) if fund_z is not None else None,
                    "vol_accel": float(v_acc) if vol_accel is not None else None,
                    "open_interest": float(oi) if oi is not None else None,
                    "oi_accel": float(oi_a) if oi_accel is not None else None,
                    "score": float(score),
                }
            )

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

        sticky_pool: List[str] = []
        if self.cfg.sticky_enabled and prev:
            scored_set = {r["symbol"] for r in scored}
            sticky_pool = [s for s in prev if s in scored_set][: max(0, int(self.cfg.sticky_keep))]

        for s in sticky_pool:
            row = next((r for r in scored if r["symbol"] == s), None)
            if row:
                selected.append(row)

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

            selected.append(row)

        # compact selected rows
        selected_compact = [
            {
                k: r.get(k)
                for k in (
                    "symbol",
                    "quote_vol_usdt",
                    "atr_tf",
                    "atr_pct",
                    "atr_burst",
                    "spread_pct",
                    "funding_rate",
                    "funding_z",
                    "vol_accel",
                    "open_interest",
                    "oi_accel",
                    "score",
                )
            }
            for r in selected
        ]

        return {
            "schema_version": "universe_v3",
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
                "sticky_enabled": bool(self.cfg.sticky_enabled),
                "sticky_keep": int(self.cfg.sticky_keep),
                "history_points": int(self.cfg.history_points),
                "weights": {
                    "w_liq": float(self.cfg.w_liq),
                    "w_atr": float(self.cfg.w_atr),
                    "w_vol_burst": float(self.cfg.w_vol_burst),
                    "w_vol_accel": float(self.cfg.w_vol_accel),
                    "w_oi": float(self.cfg.w_oi),
                    "w_oi_accel": float(self.cfg.w_oi_accel),
                    "w_fund_abs_pen": float(self.cfg.w_fund_abs_pen),
                    "w_fund_z_pen": float(self.cfg.w_fund_z_pen),
                    "w_spread_pen": float(self.cfg.w_spread_pen),
                },
                "include_symbols": list(include),
                "exclude_symbols": list(exclude),
                "exclude_bases": list(stable_bases),
                "prev_selected": prev,
            },
            "selected": selected_compact,
            "candidates_scored": [
                {
                    k: r.get(k)
                    for k in (
                        "symbol",
                        "quote_vol_usdt",
                        "atr_tf",
                        "atr_pct",
                        "atr_burst",
                        "spread_pct",
                        "funding_rate",
                        "funding_z",
                        "vol_accel",
                        "open_interest",
                        "oi_accel",
                        "score",
                    )
                }
                for r in scored[: max(50, int(self.cfg.target_symbols) * 20)]
            ],
            "excluded": excluded[:400],
        }


def universe_config_v3_from_env(os_env) -> UniverseConfigV3:
    """Build UniverseConfigV3 from os.environ-like mapping."""

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
        bases = UniverseConfigV3().exclude_bases

    return UniverseConfigV3(
        target_symbols=_get_int("UNIVERSE_TARGET_SYMBOLS", "8"),
        refresh_min=_get_int("UNIVERSE_REFRESH_MIN", "180"),
        min_quote_vol_usdt=_get_float("UNIVERSE_MIN_QUOTE_VOL_USDT", "20000000"),
        max_candidates_by_liquidity=_get_int("UNIVERSE_MAX_CANDIDATES_BY_LIQ", "160"),
        max_spread_pct=_get_float("UNIVERSE_MAX_SPREAD_PCT", "0.0030"),
        max_abs_funding=_get_float("UNIVERSE_MAX_ABS_FUNDING", "0.0030"),
        min_last_price=_get_float("UNIVERSE_MIN_LAST_PRICE", "0"),
        atr_tf=str(os_env.get("UNIVERSE_ATR_TF", "1h") or "1h"),
        atr_period=_get_int("UNIVERSE_ATR_PERIOD", "14"),
        atr_limit=_get_int("UNIVERSE_ATR_LIMIT", "200"),
        min_atr_pct=_get_float("UNIVERSE_MIN_ATR_PCT", "0.004"),
        max_corr=_get_float("UNIVERSE_MAX_CORR", "0.85"),
        corr_tf=str(os_env.get("UNIVERSE_CORR_TF", "1h") or "1h"),
        corr_limit=_get_int("UNIVERSE_CORR_LIMIT", "250"),
        sticky_enabled=_get_bool("UNIVERSE_STICKY_ENABLED", "1"),
        sticky_keep=_get_int("UNIVERSE_STICKY_KEEP", "2"),
        history_points=_get_int("UNIVERSE_HISTORY_POINTS", "64"),
        w_liq=_get_float("UNIVERSE_W_LIQ", "1.0"),
        w_atr=_get_float("UNIVERSE_W_ATR", "2.0"),
        w_vol_burst=_get_float("UNIVERSE_W_VOL_BURST", "0.7"),
        w_vol_accel=_get_float("UNIVERSE_W_VOL_ACCEL", "0.8"),
        w_oi=_get_float("UNIVERSE_W_OI", "0.7"),
        w_oi_accel=_get_float("UNIVERSE_W_OI_ACCEL", "0.6"),
        w_fund_abs_pen=_get_float("UNIVERSE_W_FUND_ABS_PEN", "1.2"),
        w_fund_z_pen=_get_float("UNIVERSE_W_FUND_Z_PEN", "0.7"),
        w_spread_pen=_get_float("UNIVERSE_W_SPREAD_PEN", "1.0"),
        exclude_bases=bases,
        include_symbols=include,
        exclude_symbols=exclude,
    )
