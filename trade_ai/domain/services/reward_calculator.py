# trade_ai/domain/services/reward_calculator.py
from __future__ import annotations
from typing import List, Dict
from ..entities.reward_state import RewardState
from ..entities.execution_state import ExecutionState
from ..entities.trade_decision import TradeDecision
from .mfe_mae_calculator import calculate_mfe_mae_from_ohlc


def calculate_reward(decision: TradeDecision, execution: ExecutionState, ohlc_bars: List[Dict]) -> RewardState:
    if execution.status != "CLOSED":
        raise ValueError("execution must be CLOSED")

    entry_price = float(execution.entry_fill_price)
    exit_price = float(execution.exit_fill_price)
    fees = float(execution.fees_total or 0.0)
    funding = float(execution.funding_paid or 0.0)
    holding_seconds = int(execution.exit_time_utc - execution.entry_time_utc)

    dir_sign = 1.0 if decision.direction.upper() == "LONG" else -1.0
    price_delta = (exit_price - entry_price) * dir_sign
    # If we know qty (linear futures), we can expose pnl_usdt while keeping
    # the legacy "pnl_raw" semantics (per-1-unit price delta adjusted by per-unit fees).
    qty = getattr(execution, "qty", None)
    pnl_usdt = None
    risk_usdt = None
    fees_unit = fees
    funding_unit = funding
    if isinstance(qty, (int, float)) and float(qty) > 0:
        q = float(qty)
        fees_unit = fees / q
        funding_unit = funding / q
        pnl_usdt = (q * price_delta) - fees - funding
        risk_usdt = q * float(decision.risk_unit)

    pnl_raw = price_delta - (fees_unit + funding_unit)

    risk_unit = float(decision.risk_unit)
    if risk_unit <= 0:
        raise ValueError("decision.risk_unit must be >0")
    pnl_r = pnl_raw / risk_unit

    mfe, mae = calculate_mfe_mae_from_ohlc(entry_price, decision.direction, ohlc_bars)

    return RewardState(
        pnl_raw=float(pnl_raw),
        pnl_r=float(pnl_r),
        mfe=float(mfe),
        mae=float(mae),
        holding_seconds=int(holding_seconds),
        reward_version="v1",
        pnl_usdt=(float(pnl_usdt) if pnl_usdt is not None else None),
        risk_usdt=(float(risk_usdt) if risk_usdt is not None else None),
        qty=(float(qty) if isinstance(qty, (int, float)) else None),
        fees_usdt=float(fees) if fees is not None else None,
        funding_usdt=float(funding) if funding is not None else None,
    )
