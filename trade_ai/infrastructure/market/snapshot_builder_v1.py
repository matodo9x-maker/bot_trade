# trade_ai/infrastructure/market/snapshot_builder_v1.py
from __future__ import annotations

import time
import uuid
import math
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _utc_session(ts_utc: int) -> str:
    """Rough session bucket from UTC hour."""
    h = int(time.gmtime(int(ts_utc)).tm_hour)
    if 0 <= h < 8:
        return "asia"
    if 8 <= h < 16:
        return "london"
    return "ny"


def _tf_to_sec(tf: str) -> int:
    """Parse timeframe like '5m','15m','1h','4h','1d' into seconds."""
    tf = (tf or "").strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 60 * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 60 * 60 * 24
    return 60


def _atr(ohlcv: List[List[float]], period: int = 14) -> float:
    """Compute ATR on OHLCV list [[ts, o, h, l, c, v], ...]."""
    if not ohlcv or len(ohlcv) < period + 1:
        return 0.0
    trs: List[float] = []
    for i in range(1, len(ohlcv)):
        _, _o, h, l, _c, _v = ohlcv[i]
        prev_c = float(ohlcv[i - 1][4])
        tr = max(float(h) - float(l), abs(float(h) - prev_c), abs(float(l) - prev_c))
        trs.append(float(tr))
    tail = trs[-period:]
    return float(sum(tail) / max(1, len(tail)))


def _sma(xs: List[float], n: int) -> float:
    if not xs:
        return 0.0
    if len(xs) < n:
        return float(xs[-1])
    return float(sum(xs[-n:]) / n)


def _hh_ll_state(closes: List[float]) -> str:
    """Very simple HH/LL state from recent closes."""
    if not closes or len(closes) < 3:
        return "HL"
    prev = closes[:-1]
    last = float(closes[-1])
    if last >= max(prev):
        return "HH"
    if last <= min(prev):
        return "LL"
    # inside range -> infer bias from last delta
    return "HL" if last >= float(prev[-1]) else "LH"


@dataclass
class SnapshotBuilderConfig:
    ltf_tf: str = "5m"
    htf_tfs: Optional[List[str]] = None

    atr_period: int = 14
    vol_threshold_atr_pct: float = 0.003  # 0.3%

    ms_lookback: int = 20
    ma_fast: int = 20
    ma_slow: int = 50

    htf_vol_threshold_atr_pct: float = 0.01  # 1%

    def __post_init__(self):
        if self.htf_tfs is None:
            self.htf_tfs = ["15m", "1h", "4h"]

        # Hard lock: decision timeframe must be 5m and HTF must include 15m,1h,4h.
        # This prevents silent drift / look-ahead mistakes in production.
        req_ltf = "5m"
        req_htf = {"15m", "1h", "4h"}

        if (self.ltf_tf or "").strip().lower() != req_ltf:
            raise ValueError(
                f"SnapshotBuilderConfig.ltf_tf must be '{req_ltf}' (got {self.ltf_tf!r})"
            )
        if (not self.htf_tfs) or (not req_htf.issubset({x.strip().lower() for x in self.htf_tfs if x})):
            raise ValueError(
                f"SnapshotBuilderConfig.htf_tfs must include {sorted(req_htf)} (got {self.htf_tfs!r})"
            )


class SnapshotBuilderV1:
    """Build SnapshotV3 dicts from an exchange adapter."""

    def __init__(self, exchange, cfg: Optional[SnapshotBuilderConfig] = None):
        self.exchange = exchange
        self.cfg = cfg or SnapshotBuilderConfig()
        self._daily_cache: Dict[str, Dict[str, float]] = {}
        self._funding_hist: Dict[str, List[float]] = {}

    def build(self, symbol: str) -> Dict[str, Any]:
        now_utc = int(time.time())
        now_ms = int(time.time() * 1000)

        # ---------- LTF candles ----------
        ltf_tf = self.cfg.ltf_tf
        tf_sec = _tf_to_sec(ltf_tf)
        tf_ms = tf_sec * 1000

        ltf_ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=ltf_tf, limit=220)

        # Ensure we use the *last closed* candle to avoid look-ahead leakage
        if ltf_ohlcv:
            last_open_ms = int(ltf_ohlcv[-1][0])
            if now_ms < (last_open_ms + tf_ms) and len(ltf_ohlcv) >= 2:
                ltf_ohlcv = ltf_ohlcv[:-1]

        if not ltf_ohlcv:
            snap_time = now_utc
            snap_id = str(uuid.uuid4())
            return {
                "schema_version": "v3",
                "snapshot_id": snap_id,
                "snapshot_time_utc": snap_time,
                "observer_time_utc": now_utc,
                "symbol": str(symbol),
                "ltf": {"tf": ltf_tf, "timestamp": int(snap_time), "price": {"close": 0.0}, "micro_structure": {}, "indicators": {}},
                "htf": {},
                "context": {"session": _utc_session(snap_time), "exchange": getattr(self.exchange, "exchange_id", None)},
            }

        last = ltf_ohlcv[-1]
        ltf_open_ms = int(last[0])
        ltf_close_time_utc = int((ltf_open_ms + tf_ms) / 1000)

        ex_id = getattr(self.exchange, "exchange_id", "unknown")
        snap_key = f"{ex_id}|{symbol}|{ltf_tf}|{ltf_close_time_utc}|v3"
        snap_id = hashlib.sha1(snap_key.encode("utf-8")).hexdigest()

        o, h, l, c, v = float(last[1]), float(last[2]), float(last[3]), float(last[4]), float(last[5] or 0.0)
        rng_pct = ((h - l) / c) if c else 0.0

        atr_val = _atr(ltf_ohlcv, period=int(self.cfg.atr_period))
        atr_pct = (atr_val / c) if c else 0.0

        thr = float(self.cfg.vol_threshold_atr_pct or 0.0)
        if thr <= 0:
            vol_regime = "normal"
        else:
            if atr_pct < (0.5 * thr):
                vol_regime = "dead"
            elif atr_pct < (1.5 * thr):
                vol_regime = "normal"
            else:
                vol_regime = "expansion"

        closes = [float(x[4]) for x in ltf_ohlcv[-max(5, int(self.cfg.ms_lookback or 20)) :]]
        hhll = _hh_ll_state(closes)
        bos = bool(hhll in ("HH", "LL"))

        dist_to_struct = 0.0
        if closes and c:
            recent_hi = max(closes)
            recent_lo = min(closes)
            dist_to_struct = min(abs(c - recent_hi), abs(c - recent_lo)) / c

        # ---------- HTF ----------
        htf: Dict[str, Any] = {}
        for tf in (self.cfg.htf_tfs or []):
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=tf, limit=220)
            except Exception:
                ohlcv = []
            if not ohlcv:
                continue
            # Ensure HTF uses last closed candle too (avoid leakage)
            tf_sec_h = _tf_to_sec(tf)
            tf_ms_h = tf_sec_h * 1000
            last_open_ms_h = int(ohlcv[-1][0])
            if now_ms < (last_open_ms_h + tf_ms_h) and len(ohlcv) >= 2:
                ohlcv = ohlcv[:-1]
            if not ohlcv:
                continue

            closes_h = [float(x[4]) for x in ohlcv]
            last_c = float(closes_h[-1])
            ma_f = _sma(closes_h, int(self.cfg.ma_fast))
            ma_s = _sma(closes_h, int(self.cfg.ma_slow))

            trend = "flat"
            if last_c > ma_s and ma_f >= ma_s:
                trend = "up"
            elif last_c < ma_s and ma_f <= ma_s:
                trend = "down"

            ma_spread = abs(ma_f - ma_s) / last_c if last_c else 0.0
            market_regime = "trend" if ma_spread >= 0.0015 else "range"

            atr_h = _atr(ohlcv, period=int(self.cfg.atr_period))
            atr_pct_h = (atr_h / last_c) if last_c else 0.0
            vol_h = "high" if atr_pct_h >= float(self.cfg.htf_vol_threshold_atr_pct) else "normal"

            hhll_h = _hh_ll_state(closes_h[-max(5, int(self.cfg.ms_lookback or 20)) :])
            bos_h = bool(hhll_h in ("HH", "LL"))
            htf[tf] = {
                "trend": trend,
                "bos": bos_h,
                "liquidity_state": None,
                "market_regime": market_regime,
                "volatility_regime": vol_h,
            }

        # ---------- Funding + Z-score (in-memory history) ----------
        funding = 0.0
        try:
            funding = float(self.exchange.fetch_funding_rate(symbol))
        except Exception:
            funding = 0.0

        hist = self._funding_hist.get(symbol, [])
        hist.append(float(funding))
        hist = hist[-200:]
        self._funding_hist[symbol] = hist

        funding_z = 0.0
        if len(hist) >= 20:
            mu = sum(hist) / len(hist)
            var = sum((x - mu) ** 2 for x in hist) / max(1, (len(hist) - 1))
            sd = math.sqrt(var)
            if sd > 1e-12:
                funding_z = (funding - mu) / sd

        # ---------- Bid/Ask spread ----------
        bid = ask = mid = None
        spread_pct = 0.0
        try:
            tkr = self.exchange.fetch_ticker(symbol) or {}
            bid = tkr.get("bid")
            ask = tkr.get("ask")
            last_px = tkr.get("last") or tkr.get("close")
            if bid is None and last_px is not None:
                bid = float(last_px)
            if ask is None and last_px is not None:
                ask = float(last_px)
            if bid is not None and ask is not None:
                bid = float(bid)
                ask = float(ask)
                mid = (bid + ask) / 2.0 if (bid + ask) else float(c)
                spread_pct = abs(ask - bid) / mid if mid else 0.0
        except Exception:
            pass

        # ---------- Daily ATR metrics (cached) ----------
        daily_atr_pct = 0.0
        daily_atr_ratio_30 = 0.0
        try:
            cache = self._daily_cache.get(symbol, {})
            refresh_sec = 6 * 60 * 60
            if not cache or (now_utc - int(cache.get("ts", 0))) > refresh_sec:
                d = self.exchange.fetch_ohlcv(symbol, timeframe="1d", limit=70)
                if d and len(d) >= 20:
                    trs = []
                    for i in range(1, len(d)):
                        _ts, _o, _h, _l, _c, _v = d[i]
                        prev_c = float(d[i - 1][4])
                        tr = max(float(_h) - float(_l), abs(float(_h) - prev_c), abs(float(_l) - prev_c))
                        trs.append(float(tr))
                    atr14 = []
                    for i in range(len(trs)):
                        if i + 1 >= int(self.cfg.atr_period):
                            window = trs[i + 1 - int(self.cfg.atr_period) : i + 1]
                            atr14.append(sum(window) / len(window))
                    if atr14:
                        cur_atr = float(atr14[-1])
                        mean_30 = sum(atr14[-30:]) / max(1, len(atr14[-30:]))
                        close_d = float(d[-1][4]) if float(d[-1][4]) else 0.0
                        daily_atr_pct = (cur_atr / close_d) if close_d else 0.0
                        daily_atr_ratio_30 = (cur_atr / mean_30) if mean_30 else 0.0
                self._daily_cache[symbol] = {
                    "ts": float(now_utc),
                    "daily_atr_pct": float(daily_atr_pct),
                    "daily_atr_ratio_30": float(daily_atr_ratio_30),
                }
            else:
                daily_atr_pct = float(cache.get("daily_atr_pct", 0.0))
                daily_atr_ratio_30 = float(cache.get("daily_atr_ratio_30", 0.0))
        except Exception:
            pass

        return {
            "schema_version": "v3",
            "snapshot_id": snap_id,
            "snapshot_time_utc": int(ltf_close_time_utc),
            "observer_time_utc": int(now_utc),
            "symbol": str(symbol),
            "ltf": {
                "tf": ltf_tf,
                "timestamp": int(ltf_close_time_utc),
                "price": {
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                    "range_pct": float(rng_pct),
                    "atr_pct": float(atr_pct),
                    "volatility_regime": vol_regime,
                },
                "micro_structure": {
                    "hh_ll_state": hhll,
                    "bos": bool(bos),
                    "distance_to_structure": float(dist_to_struct),
                },
                "indicators": {},
            },
            "htf": htf,
            "context": {
                "session": _utc_session(int(ltf_close_time_utc)),
                "exchange": ex_id,
                "funding_rate": float(funding),
                "funding_zscore": float(funding_z),
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread_pct": float(spread_pct),
                "daily_atr_pct": float(daily_atr_pct),
                "daily_atr_ratio_30": float(daily_atr_ratio_30),
            },
        }
