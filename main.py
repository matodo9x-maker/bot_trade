#!/usr/bin/env python3
"""
main.py -- bootstrap / demo runner for bot_trade

Usage:
    # Run demo end-to-end (no real Telegram unless env set)
    TELEGRAM_ENABLED=0 python main.py demo

Notes:
    - This script uses an in-memory TradeRepo for the demo to avoid storage deserialization caveats.
    - In production, replace InMemoryTradeRepo with trade_ai.infrastructure.storage.trade_repo_csv.TradeRepoCSV
"""
from __future__ import annotations
import sys
from pathlib import Path
import logging
import uuid
import time
import datetime
import os
import json

# ensure project root on sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bot_trade")

# Imports from project
from trade_ai.infrastructure.storage.snapshot_repo_fs_json import SnapshotRepoFSJson
from trade_ai.infrastructure.storage.dataset_repo_parquet import DatasetRepoParquet
from trade_ai.infrastructure.notify.telegram_client import TelegramClient
from trade_ai.infrastructure.notify.tele_notifier import TeleNotifier
from trade_ai.infrastructure.events.event_dispatcher import EventDispatcher

from trade_ai.application.usecases.observer_usecase import ObserverUsecase
from trade_ai.application.usecases.open_trade_usecase import OpenTradeUsecase
from trade_ai.application.usecases.resolve_trade_usecase import ResolveTradeUsecase
from trade_ai.application.usecases.dataset_build_usecase import DatasetBuildUsecase

# Policies
try:
    from trade_ai.domain.policies.risk_aware_policy_v1 import RiskAwarePolicyV1
except Exception:
    # fallback if file not present
    from trade_ai.domain.policies.rule_policy_v1 import RulePolicyV1 as RiskAwarePolicyV1

# Domain objects
from trade_ai.domain.entities.execution_state import ExecutionState

# Type imports
from trade_ai.application.ports.trade_repository import TradeRepositoryPort


# -------------------------
# In-memory TradeRepo (for demo)
# -------------------------
class InMemoryTradeRepo(TradeRepositoryPort):
    """
    Simple in-memory Trade repository used for bootstrap/demo.
    Keeps full TradeAggregate objects in memory (no serialization).
    Replace with persistent repo in production.
    """
    def __init__(self):
        self._open: dict[str, object] = {}
        self._closed: list[object] = []

    def save_open(self, trade):
        self._open[trade.trade_id] = trade
        logger.info("InMemoryTradeRepo: save_open %s", trade.trade_id)

    def update_closed(self, trade):
        if trade.trade_id in self._open:
            self._open.pop(trade.trade_id, None)
        self._closed.append(trade)
        logger.info("InMemoryTradeRepo: update_closed %s", trade.trade_id)

    def list_closed(self):
        return list(self._closed)

    def list_open(self):
        return list(self._open.values())

    def get_open(self, trade_id: str):
        return self._open.get(trade_id)


# -------------------------
# Utility: build synthetic snapshot
# -------------------------
def make_synthetic_snapshot(symbol: str, ts: int, price: float, atr_pct: float = 0.001):
    """
    Construct a minimal SnapshotV3 dict for demo.
    Must satisfy SnapshotV3.from_dict expectations.
    """
    snapshot_id = str(uuid.uuid4())
    return {
        "schema_version": "v3",
        "snapshot_id": snapshot_id,
        "snapshot_time_utc": int(ts),
        "observer_time_utc": int(ts + 5),
        "symbol": symbol,
        "ltf": {
            "tf": "1m",
            "timestamp": int(ts),
            "price": {
                "close": float(price),
                "range_pct": 0.005,
                "atr_pct": float(atr_pct),
                "volatility_regime": "normal",
            },
            "micro_structure": {
                "bos": True,
                "hh_ll_state": "HH",
                "distance_to_structure": 0.1
            }
        },
        "htf": {
            "1h": {"trend": "up", "market_regime": "trend", "volatility_regime": "normal"},
            "4h": {"trend": "up", "market_regime": "trend", "volatility_regime": "normal"}
        },
        "context": {
            "session": "asia",
            "funding_rate": 0.0,
            "funding_zscore": 0.0
        }
    }


# -------------------------
# Demo flow (end-to-end)
# -------------------------
def demo_flow():
    logger.info("Starting demo flow")

    # Repos and infra
    snapshot_repo = SnapshotRepoFSJson(base_path="data/runtime/snapshots")
    dataset_repo = DatasetRepoParquet(out_path="data/datasets/rl/rl_dataset_v1.parquet")
    trade_repo = InMemoryTradeRepo()

    # Event system & notifier
    event_dispatcher = EventDispatcher()
    tg_client = TelegramClient()  # reads env if present
    tele_notifier = TeleNotifier(client=tg_client)

    # Subscribe notifier to our topics
    event_dispatcher.subscribe("trade.open", lambda topic, payload: tele_notifier.handle_event({"type": "trade.entry", "trade": payload}))
    event_dispatcher.subscribe("trade.closed", lambda topic, payload: tele_notifier.handle_event({"type": "trade.exit", "payload": payload}))

    # Usecases & policy
    policy = RiskAwarePolicyV1() if "RiskAwarePolicyV1" in globals() else RiskAwarePolicyV1()
    observer_uc = ObserverUsecase(snapshot_repo)
    open_uc = OpenTradeUsecase(snapshot_repo, trade_repo, policy, event_bus=event_dispatcher)
    resolve_uc = ResolveTradeUsecase(trade_repo, event_bus=event_dispatcher)
    # feature_spec file location (must exist)
    feature_spec_path = "trade_ai/feature_engineering/feature_spec_v1.yaml"
    dataset_uc = DatasetBuildUsecase(trade_repo, snapshot_repo, dataset_repo, feature_spec_path)

    # 1) create entry snapshot
    now = int(time.time())
    entry_price = 100.0
    snap_entry_dict = make_synthetic_snapshot("BTCUSD", now, entry_price, atr_pct=0.002)
    snap_entry = observer_uc.create_snapshot(snap_entry_dict)
    logger.info("Saved entry snapshot %s", snap_entry.snapshot_id)

    # 2) open trade
    policy_info = {"policy_name": getattr(policy, "__class__").__name__, "policy_version": "v1", "policy_type": "rule"}
    ta = open_uc.open_trade(snap_entry.snapshot_id, policy_info)
    logger.info("Opened trade %s decision rr=%.3f risk_unit=%.6f", ta.trade_id, ta.decision.rr, ta.decision.risk_unit)

    # 3) create exit snapshot (simulate hitting TP)
    # Use a later timestamp and set ltf close to tp_price
    exit_ts = now + 60  # after 1 minute
    tp_price = ta.decision.tp_price
    snap_exit_dict = make_synthetic_snapshot("BTCUSD", exit_ts, tp_price, atr_pct=0.002)
    snap_exit = observer_uc.create_snapshot(snap_exit_dict)
    logger.info("Saved exit snapshot %s", snap_exit.snapshot_id)

    # 4) create execution state (closed)
    exec_state = ExecutionState(
        status="CLOSED",
        entry_time_utc=int(now + 1),
        entry_fill_price=float(ta.decision.entry_price),
        exit_time_utc=int(exit_ts + 1),
        exit_fill_price=float(ta.decision.tp_price),
        exit_type="TP",
        fees_total=0.0005,
        funding_paid=0.0,
    )

    # 5) synthetic OHLC bars covering entry->exit (for mfe/mae)
    ohlc_bars = [
        {"timestamp": now, "open": entry_price, "high": max(entry_price, ta.decision.tp_price), "low": min(entry_price, ta.decision.sl_price), "close": entry_price},
        {"timestamp": exit_ts, "open": entry_price, "high": max(entry_price, ta.decision.tp_price), "low": min(entry_price, ta.decision.sl_price), "close": float(ta.decision.tp_price)},
    ]

    # 6) resolve trade
    resolve_uc.resolve_trade(ta.trade_id, exec_state, ohlc_bars, snap_exit.snapshot_id, snap_exit.snapshot_time_utc)
    logger.info("Resolved trade %s", ta.trade_id)

    # 7) build dataset
    n = dataset_uc.build_and_save()
    logger.info("Dataset build produced %d rows (appended)", n)

    # print closed trades and dataset path
    closed = trade_repo.list_closed()
    logger.info("Closed trades count: %d", len(closed))
    ds_path = Path("data/datasets/rl/rl_dataset_v1.parquet")
    logger.info("Dataset file exists: %s (size=%s)", ds_path.exists(), ds_path.stat().st_size if ds_path.exists() else "n/a")

    # Optionally print last row (for manual inspection)
    if ds_path.exists():
        try:
            import pandas as pd
            df = pd.read_parquet(ds_path)
            print("=== LAST DATASET ROW ===")
            print(df.tail(1).to_dict(orient="records")[0])
        except Exception as e:
            logger.warning("Could not pretty print dataset: %s", e)

    logger.info("Demo finished")


# -------------------------
# Entry point
# -------------------------
if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "demo":
        try:
            demo_flow()
        except Exception as e:
            logger.exception("Demo failed: %s", e)
            raise
    else:
        print("Usage: python main.py demo")
        print("Example: TELEGRAM_ENABLED=0 python main.py demo")
