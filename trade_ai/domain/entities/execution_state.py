# trade_ai/domain/entities/execution_state.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


class ExecutionStateError(Exception):
    pass


@dataclass
class ExecutionState:
    status: str  # "OPEN" or "CLOSED"
    entry_time_utc: Optional[int] = None
    entry_fill_price: Optional[float] = None
    exit_time_utc: Optional[int] = None
    exit_fill_price: Optional[float] = None
    exit_type: Optional[str] = None
    fees_total: float = 0.0
    funding_paid: float = 0.0

    # --- Futures/runtime metadata (optional; backward compatible) ---
    exchange: Optional[str] = None          # binance | bybit | mexc
    account_type: Optional[str] = None      # e.g. "USDT-M" (linear)
    margin_mode: Optional[str] = None       # isolated
    position_mode: Optional[str] = None     # oneway
    leverage: Optional[int] = None
    qty: Optional[float] = None             # position size in base asset
    notional: Optional[float] = None        # qty * entry_price (USDT)
    entry_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    client_order_id: Optional[str] = None

    def validate(self):
        if self.status not in ("OPEN", "CLOSED"):
            raise ExecutionStateError("status must be 'OPEN' or 'CLOSED'")
        if self.status == "CLOSED":
            if self.entry_time_utc is None or self.entry_fill_price is None:
                raise ExecutionStateError("Closed execution must have entry fill info")
            if self.exit_time_utc is None or self.exit_fill_price is None:
                raise ExecutionStateError("Closed execution must have exit fill info")
