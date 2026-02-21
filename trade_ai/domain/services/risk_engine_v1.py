# trade_ai/domain/services/risk_engine_v1.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
import math

from ..entities.trade_decision import TradeDecision


def _floor_to_step(x: float, step: Optional[float]) -> float:
    if step is None or step <= 0:
        return float(x)
    return math.floor(float(x) / float(step)) * float(step)


def _ceil_to_step(x: float, step: Optional[float]) -> float:
    if step is None or step <= 0:
        return float(x)
    return math.ceil(float(x) / float(step)) * float(step)


@dataclass(frozen=True)
class AccountState:
    equity_usdt: float
    free_usdt: float


@dataclass(frozen=True)
class MarketConstraints:
    min_notional_usdt: float = 5.0
    min_qty: Optional[float] = None
    qty_step: Optional[float] = None


@dataclass(frozen=True)
class RiskConfig:
    # Risk budget
    risk_per_trade_pct: float = 0.25   # percent (%) of equity
    risk_per_trade_usdt: Optional[float] = None

    # Leverage / margin
    default_leverage: int = 3
    max_leverage: int = 10
    margin_utilization: float = 0.30   # only use up to 30% of free USDT as initial margin

    # Constraints
    max_notional_usdt: Optional[float] = None
    max_exposure_pct_per_symbol: Optional[float] = None  # cap initial margin per symbol as % of equity

    # Min notional policy
    min_notional_policy: str = "skip"  # skip | override_with_cap
    max_risk_multiplier_on_override: float = 2.0
    max_risk_override_usdt: Optional[float] = None

    # Safety gates
    min_confidence: float = 0.55


@dataclass(frozen=True)
class RiskPlan:
    ok: bool
    reason: str

    qty: Optional[float] = None
    notional_usdt: Optional[float] = None
    leverage: Optional[int] = None
    risk_usdt: Optional[float] = None
    risk_pct: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "qty": self.qty,
            "notional_usdt": self.notional_usdt,
            "leverage": self.leverage,
            "risk_usdt": self.risk_usdt,
            "risk_pct": self.risk_pct,
        }


class RiskEngineV1:
    """Risk engine for USDT-M linear futures.

    Design goals:
    - Works with *small capital* (micro sizing, but respects min notional).
    - Deterministic sizing from (account_state, decision, constraints).
    - Keeps RR/SL/TP generation inside the policy; this module only sizes.

    Notes:
    - qty is in *base asset* units (e.g., BTC).
    - notional_usdt = qty * entry_price.
    - risk_usdt = qty * abs(entry - sl).
    """

    def __init__(self, cfg: Optional[RiskConfig] = None):
        self.cfg = cfg or RiskConfig()

    def build_plan(
        self,
        account: AccountState,
        constraints: MarketConstraints,
        decision: TradeDecision,
    ) -> RiskPlan:
        # Confidence gate (hybrid rule -> ML scorer)
        conf = decision.confidence if decision.confidence is not None else 1.0
        if float(conf) < float(self.cfg.min_confidence):
            return RiskPlan(ok=False, reason=f"confidence<{self.cfg.min_confidence}")

        equity = float(account.equity_usdt)
        free = float(account.free_usdt)
        if not (equity > 0 and free > 0):
            return RiskPlan(ok=False, reason="account_balance_invalid")

        # Risk budget
        if self.cfg.risk_per_trade_usdt is not None and self.cfg.risk_per_trade_usdt > 0:
            risk_budget = float(self.cfg.risk_per_trade_usdt)
        else:
            risk_budget = equity * (float(self.cfg.risk_per_trade_pct) / 100.0)
        if not (risk_budget > 0):
            return RiskPlan(ok=False, reason="risk_budget_invalid")

        entry = float(decision.entry_price)
        sl = float(decision.sl_price)
        stop_dist = abs(entry - sl)
        if not (stop_dist > 0):
            return RiskPlan(ok=False, reason="stop_distance_invalid")

        # Initial qty from risk budget
        raw_qty = risk_budget / stop_dist
        qty = _floor_to_step(raw_qty, constraints.qty_step)

        if constraints.min_qty is not None:
            qty = max(float(constraints.min_qty), float(qty))
            # ensure step compliance when min_qty bumps size
            qty = _ceil_to_step(qty, constraints.qty_step)

        if not (qty > 0):
            return RiskPlan(ok=False, reason="qty_invalid")

        # Constraints
        min_notional = float(constraints.min_notional_usdt or 0.0)
        if not (min_notional > 0):
            min_notional = 5.0

        # Apply max notional cap (optional)
        if self.cfg.max_notional_usdt is not None and self.cfg.max_notional_usdt > 0:
            max_notional = float(self.cfg.max_notional_usdt)
            cap_qty = max_notional / entry
            qty = min(float(qty), _floor_to_step(cap_qty, constraints.qty_step))
            if constraints.min_qty is not None:
                qty = max(float(constraints.min_qty), float(qty))
                qty = _ceil_to_step(qty, constraints.qty_step)

        notional = float(qty) * entry

        # Choose leverage to satisfy margin utilization
        lev = int(self.cfg.default_leverage)
        lev = max(1, min(int(self.cfg.max_leverage), lev))

        margin_limit = max(0.0, float(self.cfg.margin_utilization) * free)

        # Optional exposure cap per symbol (initial margin <= equity * pct)
        if self.cfg.max_exposure_pct_per_symbol is not None and float(self.cfg.max_exposure_pct_per_symbol) > 0:
            symbol_margin_cap = equity * (float(self.cfg.max_exposure_pct_per_symbol) / 100.0)
            margin_limit = min(margin_limit, float(symbol_margin_cap))
        if margin_limit <= 0:
            return RiskPlan(ok=False, reason="margin_limit_invalid")

        margin_req = notional / float(lev)
        if margin_req > margin_limit:
            # Try to increase leverage up to max
            needed_lev = int(math.ceil(notional / margin_limit))
            lev = max(lev, min(int(self.cfg.max_leverage), max(1, needed_lev)))
            margin_req = notional / float(lev)

        if margin_req > margin_limit:
            # Still too large: scale down qty
            qty_max = (margin_limit * float(lev)) / entry
            qty = min(float(qty), _floor_to_step(qty_max, constraints.qty_step))
            if constraints.min_qty is not None:
                qty = max(float(constraints.min_qty), float(qty))
                qty = _ceil_to_step(qty, constraints.qty_step)
            notional = float(qty) * entry
            margin_req = notional / float(lev)

        if margin_req > margin_limit:
            return RiskPlan(ok=False, reason="margin_too_high")

        if not (qty > 0):
            return RiskPlan(ok=False, reason="qty_too_small_after_margin")

        # Min notional policy
        if notional < min_notional:
            if (self.cfg.min_notional_policy or "skip").lower() != "override_with_cap":
                return RiskPlan(ok=False, reason=f"notional<{min_notional}")

            # Override: bump qty up to min_notional (round UP to step)
            qty2 = _ceil_to_step(min_notional / entry, constraints.qty_step)
            if constraints.min_qty is not None:
                qty2 = max(float(constraints.min_qty), float(qty2))
                qty2 = _ceil_to_step(qty2, constraints.qty_step)
            notional2 = float(qty2) * entry
            risk2 = float(qty2) * stop_dist

            # cap override risk
            if risk2 > (risk_budget * float(self.cfg.max_risk_multiplier_on_override)):
                return RiskPlan(ok=False, reason="min_notional_override_risk_too_high")
            if self.cfg.max_risk_override_usdt is not None and risk2 > float(self.cfg.max_risk_override_usdt):
                return RiskPlan(ok=False, reason="min_notional_override_cap_exceeded")

            # re-check margin with existing leverage (and possibly max)
            margin_req2 = notional2 / float(lev)
            if margin_req2 > margin_limit:
                needed_lev2 = int(math.ceil(notional2 / margin_limit))
                lev2 = min(int(self.cfg.max_leverage), max(lev, needed_lev2))
                margin_req2 = notional2 / float(lev2)
                if margin_req2 > margin_limit:
                    return RiskPlan(ok=False, reason="min_notional_override_margin_too_high")
                lev = lev2

            qty = float(qty2)
            notional = float(notional2)

        # Final risk
        risk_usdt = float(qty) * stop_dist
        risk_pct = (risk_usdt / equity) * 100.0 if equity > 0 else None

        return RiskPlan(
            ok=True,
            reason="ok",
            qty=float(qty),
            notional_usdt=float(notional),
            leverage=int(lev),
            risk_usdt=float(risk_usdt),
            risk_pct=float(risk_pct) if risk_pct is not None else None,
        )
