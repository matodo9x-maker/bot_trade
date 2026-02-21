# trade_ai/domain/services/risk_guard_v1.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import datetime

from ..entities.trade_aggregate import TradeAggregate


@dataclass(frozen=True)
class RiskGuardConfig:
    max_daily_loss_usdt: Optional[float] = None
    max_daily_loss_pct: Optional[float] = None  # % of equity
    max_consecutive_losses: int = 3
    cooldown_sec: int = 0
    max_trades_per_day: Optional[int] = None


@dataclass(frozen=True)
class RiskGuardResult:
    ok: bool
    reason: str
    metrics: Dict[str, Any]


def _trade_pnl_usdt(t: TradeAggregate) -> float:
    if not t.reward_state:
        return 0.0
    pu = getattr(t.reward_state, "pnl_usdt", None)
    if isinstance(pu, (int, float)):
        return float(pu)
    # fallback: approximate using qty if present
    qty = getattr(t.execution_state, "qty", None)
    if isinstance(qty, (int, float)):
        return float(qty) * float(t.reward_state.pnl_raw)
    return float(t.reward_state.pnl_raw)


class RiskGuardV1:
    """Runtime risk guard (daily loss, streak, cooldown, trades/day).

    This is intentionally simple and deterministic.
    """

    def __init__(self, cfg: Optional[RiskGuardConfig] = None):
        self.cfg = cfg or RiskGuardConfig()

    def check(self, closed_trades: List[TradeAggregate], now_utc: int, equity_usdt: float) -> RiskGuardResult:
        eq = float(equity_usdt)
        now_dt = datetime.datetime.utcfromtimestamp(int(now_utc))
        day_start = datetime.datetime(now_dt.year, now_dt.month, now_dt.day)
        day_start_ts = int(day_start.replace(tzinfo=datetime.timezone.utc).timestamp())

        closed_sorted = sorted(
            [t for t in closed_trades if t.execution_state and t.execution_state.exit_time_utc],
            key=lambda x: int(x.execution_state.exit_time_utc or 0),
        )

        # today stats
        today = [t for t in closed_sorted if int(t.execution_state.exit_time_utc or 0) >= day_start_ts]
        pnl_today = sum(_trade_pnl_usdt(t) for t in today)
        n_today = len(today)

        # cooldown
        if self.cfg.cooldown_sec and closed_sorted:
            last_exit = int(closed_sorted[-1].execution_state.exit_time_utc or 0)
            if last_exit and (now_utc - last_exit) < int(self.cfg.cooldown_sec):
                return RiskGuardResult(
                    ok=False,
                    reason="cooldown",
                    metrics={"cooldown_sec": int(self.cfg.cooldown_sec), "seconds_since_last_exit": int(now_utc - last_exit)},
                )

        # max trades/day
        if self.cfg.max_trades_per_day is not None and n_today >= int(self.cfg.max_trades_per_day):
            return RiskGuardResult(
                ok=False,
                reason="max_trades_per_day",
                metrics={"trades_today": n_today, "max_trades_per_day": int(self.cfg.max_trades_per_day)},
            )

        # daily loss cap
        if self.cfg.max_daily_loss_usdt is not None and self.cfg.max_daily_loss_usdt > 0:
            if pnl_today <= -abs(float(self.cfg.max_daily_loss_usdt)):
                return RiskGuardResult(
                    ok=False,
                    reason="max_daily_loss_usdt",
                    metrics={"pnl_today_usdt": float(pnl_today), "max_daily_loss_usdt": float(self.cfg.max_daily_loss_usdt)},
                )

        if self.cfg.max_daily_loss_pct is not None and self.cfg.max_daily_loss_pct > 0 and eq > 0:
            cap = eq * (float(self.cfg.max_daily_loss_pct) / 100.0)
            if pnl_today <= -abs(cap):
                return RiskGuardResult(
                    ok=False,
                    reason="max_daily_loss_pct",
                    metrics={"pnl_today_usdt": float(pnl_today), "cap_usdt": float(cap), "max_daily_loss_pct": float(self.cfg.max_daily_loss_pct)},
                )

        # consecutive losses
        max_streak = int(self.cfg.max_consecutive_losses)
        if max_streak > 0 and closed_sorted:
            streak = 0
            for t in reversed(closed_sorted):
                pnl = _trade_pnl_usdt(t)
                if pnl < 0:
                    streak += 1
                    if streak >= max_streak:
                        return RiskGuardResult(
                            ok=False,
                            reason="max_consecutive_losses",
                            metrics={"loss_streak": streak, "max_consecutive_losses": max_streak},
                        )
                else:
                    break

        return RiskGuardResult(
            ok=True,
            reason="ok",
            metrics={"pnl_today_usdt": float(pnl_today), "trades_today": n_today},
        )

    def ok(self, trade_repo, account, now_utc: int) -> bool:
        """Compatibility helper used by runtime loops.

        Returns True when trading is allowed under the configured guard.
        Stores the last RiskGuardResult in `self.last_result` for debugging.
        """
        try:
            closed = trade_repo.list_closed() if trade_repo is not None else []
        except Exception:
            closed = []
        try:
            equity = float(getattr(account, 'equity_usdt', 0.0) or 0.0)
        except Exception:
            equity = 0.0
        res = self.check(closed_trades=closed, now_utc=int(now_utc), equity_usdt=equity)
        self.last_result = res
        return bool(getattr(res, 'ok', False))

