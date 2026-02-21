"""Runtime trader (demo | data | paper | live).

Mục tiêu file này:
- Là entrypoint chạy trên VPS (nohup/tmux/systemd).
- Hỗ trợ 4 chế độ (2 chế độ runtime chính thức + 2 chế độ dev):

BOT_MODE:
- demo  : mô phỏng pipeline end-to-end (synthetic snapshots)  [DEV]
- data  : kết nối Futures thật (CCXT) -> tạo SnapshotV3 -> lưu + xuất dataset market features  [DEV]
- paper : chạy policy + risk engine trên dữ liệu Futures thật, nhưng KHÔNG đặt lệnh (giả lập fill) → phù hợp để lấy data an toàn
- live  : đặt lệnh Futures tiền thật (USDT-M), One-Way + Isolated (best-effort)

Ghi chú:
- demo/data chỉ bật khi DEV_ENABLE_DEMO_DATA=1 để tránh operator set nhầm.

⚠️ Cảnh báo:
- Đây là code kỹ thuật/phần mềm. Không phải lời khuyên đầu tư.
- Luôn test paper/testnet trước khi bật live.
"""


from __future__ import annotations

# NOTE (Telegram):
# Nhiều bạn chạy `python -m apps.runtime_trader` trực tiếp (Windows/VPS),
# trong khi Telegram token/chat_id lại nằm trong file env (.env hoặc /etc/bot_trade/bot_trade.env).
# Nếu không load env trước khi khởi tạo TelegramClient thì bot sẽ báo:
#   Telegram send failed: {'reason': 'no-token-or-chatid', ...}
# Vì vậy file này tự bootstrap env best-effort ngay khi start.

import sys

import os
import time
import uuid
import hashlib
import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any, List


# ---------------------------------------------------------------------------
# Bootstrap (sys.path + env) BEFORE wiring TelegramClient / Exchange
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Stabilize working directory so relative paths (logs/, data/, .env) behave consistently.
# Set BOT_CHDIR_ROOT=0 to disable.
if str(os.getenv("BOT_CHDIR_ROOT", "1")).strip().lower() in ("1", "true", "yes", "y", "on"):
    try:
        os.chdir(_PROJECT_ROOT)
    except Exception:
        pass

_ENV_FILE_USED: str | None = None
try:
    from trade_ai.infrastructure.config.env_loader import load_env

    _ENV_FILE_USED = load_env()
except Exception:
    _ENV_FILE_USED = None

from trade_ai.infrastructure.storage.snapshot_repo_fs_json import SnapshotRepoFSJson
from trade_ai.infrastructure.storage.trade_repo_csv import TradeRepoCSV
from trade_ai.infrastructure.storage.dataset_repo_parquet import DatasetRepoParquet
from trade_ai.infrastructure.storage.decision_cycle_repo_jsonl import DecisionCycleRepoJsonl
from trade_ai.infrastructure.storage.order_event_repo_jsonl import OrderEventRepoJsonl
from trade_ai.infrastructure.storage.execution_event_repo_jsonl import ExecutionEventRepoJsonl

from trade_ai.infrastructure.events.event_dispatcher import EventDispatcher
from trade_ai.infrastructure.notify.telegram_client import TelegramClient
from trade_ai.infrastructure.notify.tele_notifier import TeleNotifier

from trade_ai.application.usecases.observer_usecase import ObserverUsecase
from trade_ai.application.usecases.open_trade_usecase import OpenTradeUsecase
from trade_ai.application.usecases.resolve_trade_usecase import ResolveTradeUsecase
from trade_ai.application.usecases.dataset_build_usecase import DatasetBuildUsecase
from trade_ai.application.usecases.scorer_dataset_build_usecase import ScorerDatasetBuildUsecase

from trade_ai.domain.entities.execution_state import ExecutionState

try:
    from trade_ai.domain.policies.risk_aware_policy_v1 import RiskAwarePolicyV1
except Exception:
    from trade_ai.domain.policies.rule_policy_v1 import RulePolicyV1 as RiskAwarePolicyV1

from trade_ai.domain.policies.hybrid_policy_v1 import HybridPolicyV1
from trade_ai.domain.services.risk_engine_v1 import RiskEngineV1, RiskConfig, AccountState, MarketConstraints
from trade_ai.domain.services.risk_guard_v1 import RiskGuardV1, RiskGuardConfig

from trade_ai.feature_engineering.feature_mapper_v1 import FeatureMapperV1

from trade_ai.infrastructure.market.exchange_factory import make_exchange_from_env
from trade_ai.infrastructure.market.snapshot_builder_v1 import SnapshotBuilderV1, SnapshotBuilderConfig
from trade_ai.infrastructure.market.universe_selector_v1 import UniverseSelectorV1, universe_config_from_env
from trade_ai.infrastructure.market.universe_selector_v2 import UniverseSelectorV2, universe_config_v2_from_env
from trade_ai.infrastructure.market.universe_selector_v3 import UniverseSelectorV3, universe_config_v3_from_env
from trade_ai.infrastructure.storage.universe_selection_repo_jsonl import UniverseSelectionRepoJsonl
from trade_ai.infrastructure.storage.universe_cycle_repo_jsonl import UniverseCycleRepoJsonl


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("runtime_trader")


def _ensure_dirs() -> None:
    for p in (
        "logs",
        "data/runtime",
        "data/runtime/snapshots",
        "data/datasets/rl",
        "data/datasets/market",
        "data/datasets/supervised",
        "data/models",
    ):
        Path(p).mkdir(parents=True, exist_ok=True)


def _parse_symbols_from_env() -> List[str]:
    """Resolve symbols list from env.

    Priority:
      1) BOT_SYMBOLS (comma separated) or BOT_SYMBOLS=AUTO
      2) BOT_SYMBOL
    """
    raw = (os.getenv("BOT_SYMBOLS") or "").strip()
    if raw and raw.upper() != "AUTO":
        return [x.strip().upper().replace("/", "") for x in raw.split(",") if x.strip()]
    sym = (os.getenv("BOT_SYMBOL") or "BTCUSDT").strip().upper().replace("/", "")
    return [sym]


def _select_symbols_auto(ex) -> List[str]:
    # Selector version (v1/v2/v3)
    ver = str(os.getenv("UNIVERSE_SELECTOR_VERSION", "3") or "3").strip().lower()

    # Best-effort load last selected universe (for sticky keep)
    prev_selected: List[str] = []
    try:
        last_path = Path(os.getenv("BOT_UNIVERSE_LAST_PATH", "data/runtime/universe_last.json"))
        if last_path.exists():
            prev = json.loads(last_path.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                prev_selected = [str(x).upper().replace("/", "") for x in (prev.get("symbols") or []) if x]
    except Exception:
        prev_selected = []

    # Load cached history for richer v3 signals (best-effort)
    history_by_symbol: dict[str, dict[str, list[float]]] = {}
    prev_metrics_by_symbol: dict[str, dict[str, float]] = {}
    try:
        cycles_repo = UniverseCycleRepoJsonl(path=os.getenv("BOT_UNIVERSE_CYCLES_PATH", "data/runtime/universe_cycles.jsonl"))
        rows = list(cycles_repo.iter())
        # keep only last N rows to limit memory
        max_rows = int(float(os.getenv("UNIVERSE_CYCLES_HISTORY_MAX_ROWS", "5000")))
        if len(rows) > max_rows:
            rows = rows[-max_rows:]
        for r in rows:
            if not isinstance(r, dict):
                continue
            sym = str(r.get("symbol") or "").upper().replace("/", "")
            if not sym:
                continue
            hb = history_by_symbol.setdefault(sym, {})
            for k in ("funding_rate", "atr_pct", "quote_vol_usdt", "open_interest"):
                v = r.get(k)
                if isinstance(v, (int, float)):
                    hb.setdefault(k, []).append(float(v))
        # prev metrics: last row per symbol
        for r in reversed(rows):
            sym = str(r.get("symbol") or "").upper().replace("/", "")
            if sym and sym not in prev_metrics_by_symbol:
                pm = {}
                for k in ("funding_rate", "atr_pct", "quote_vol_usdt", "open_interest"):
                    v = r.get(k)
                    if isinstance(v, (int, float)):
                        pm[k] = float(v)
                prev_metrics_by_symbol[sym] = pm
    except Exception:
        history_by_symbol = {}
        prev_metrics_by_symbol = {}

    if ver in ("1", "v1"):
        cfg = universe_config_from_env(os.environ)
        report = UniverseSelectorV1(cfg).select(ex)
    elif ver in ("2", "v2"):
        cfg2 = universe_config_v2_from_env(os.environ)
        report = UniverseSelectorV2(cfg2).select(ex, prev_selected=prev_selected)
    else:
        cfg3 = universe_config_v3_from_env(os.environ)
        report = UniverseSelectorV3(cfg3).select(
            ex,
            prev_selected=prev_selected,
            history_by_symbol=history_by_symbol,
            prev_metrics_by_symbol=prev_metrics_by_symbol,
        )

    # Persist selection report for audit / AI training
    try:
        Path("data/runtime").mkdir(parents=True, exist_ok=True)
        with open("data/runtime/universe_selection.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # Append selection report to JSONL log (AI-ready)
    try:
        repo = UniverseSelectionRepoJsonl(path=os.getenv("BOT_UNIVERSE_LOG_PATH", "data/runtime/universe_selection.jsonl"))
        repo.append(report)
    except Exception:
        pass

    # Append per-symbol universe cycle rows for AI training (negative samples)
    try:
        cycles_repo = UniverseCycleRepoJsonl(path=os.getenv("BOT_UNIVERSE_CYCLES_PATH", "data/runtime/universe_cycles.jsonl"))
        sel_syms = {str(x.get("symbol") or "").upper().replace("/", "") for x in (report.get("selected") or []) if isinstance(x, dict)}
        cand = report.get("candidates_scored") or []
        if isinstance(cand, list):
            # rank based on provided order
            for idx, it in enumerate(cand, start=1):
                if not isinstance(it, dict) or not it.get("symbol"):
                    continue
                sym = str(it.get("symbol")).upper().replace("/", "")
                row = {
                    "schema_version": "universe_cycle_v1",
                    "timestamp_utc": int(report.get("timestamp_utc") or int(time.time())),
                    "exchange": report.get("exchange"),
                    "selector_version": str(report.get("schema_version") or ""),
                    "symbol": sym,
                    "selected": 1 if sym in sel_syms else 0,
                    "rank": int(idx),
                    "target_symbols": int((report.get("config") or {}).get("target_symbols") or 0),
                }
                # copy common metrics if present
                for k in (
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
                ):
                    if k in it:
                        row[k] = it.get(k)
                cycles_repo.append(row)
    except Exception:
        pass

    # Save last selected universe for sticky keep
    try:
        last_path = Path(os.getenv("BOT_UNIVERSE_LAST_PATH", "data/runtime/universe_last.json"))
        last_path.parent.mkdir(parents=True, exist_ok=True)
        last_path.write_text(
            json.dumps(
                {
                    "timestamp_utc": int(time.time()),
                    "symbols": [x.get("symbol") for x in (report.get("selected") or []) if isinstance(x, dict) and x.get("symbol")],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    selected = [x.get("symbol") for x in (report.get("selected") or []) if isinstance(x, dict) and x.get("symbol")]
    # fallback to BTCUSDT if selection empty
    return [s.upper().replace("/", "") for s in selected] if selected else ["BTCUSDT"]


def _env_bool(key: str, default: str = "0") -> bool:
    v = os.getenv(key, default)
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_float(key: str, default: str) -> float:
    try:
        return float(os.getenv(key, default))
    except Exception:
        return float(default)


def _env_int(key: str, default: str) -> int:
    try:
        return int(float(os.getenv(key, default)))
    except Exception:
        return int(float(default))


def _make_synthetic_snapshot(symbol: str, ts: int, price: float, atr_pct: float = 0.002) -> dict:
    """Minimal SnapshotV3 dict for demo."""
    return {
        "schema_version": "v3",
        "snapshot_id": str(uuid.uuid4()),
        "snapshot_time_utc": int(ts),
        "observer_time_utc": int(ts + 2),
        "symbol": symbol,
        "ltf": {
            "tf": "5m",
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
                "distance_to_structure": 0.1,
            },
        },
        "htf": {
            "15m": {"trend": "up", "bos": True, "liquidity_state": None, "market_regime": "trend", "volatility_regime": "normal"},
            "1h": {"trend": "up", "bos": True, "liquidity_state": None, "market_regime": "trend", "volatility_regime": "normal"},
            "4h": {"trend": "up", "bos": True, "liquidity_state": None, "market_regime": "trend", "volatility_regime": "normal"},
        },
        "context": {
            "session": "asia",
            "funding_rate": 0.0,
            "funding_zscore": 0.0,
            "exchange": "synthetic",
        },
    }


def build_pipeline(feature_spec_path: str):
    """Wire repositories + usecases."""
    snapshot_repo = SnapshotRepoFSJson(base_path=os.getenv("BOT_SNAPSHOT_DIR", "data/runtime/snapshots"))
    trade_repo = TradeRepoCSV(
        open_path=os.getenv("BOT_TRADES_OPEN", "data/runtime/trades_open.csv"),
        closed_path=os.getenv("BOT_TRADES_CLOSED", "data/runtime/trades_closed.csv"),
    )

    rl_dataset_repo = DatasetRepoParquet(out_path=os.getenv("BOT_RL_DATASET_PATH", "data/datasets/rl/rl_dataset_v2.parquet"))
    scorer_dataset_repo = DatasetRepoParquet(out_path=os.getenv("BOT_SCORER_DATASET_PATH", "data/datasets/supervised/scorer_dataset_v1.parquet"))
    market_dataset_repo = DatasetRepoParquet(out_path=os.getenv("BOT_MARKET_DATASET_PATH", "data/datasets/market/market_features_v1.parquet"))

    # Runtime append-only logs (JSONL)
    decision_cycle_repo = DecisionCycleRepoJsonl(path=(os.getenv("BOT_DECISION_CYCLES_PATH") or os.getenv("BOT_DECISION_LOG_PATH") or "data/runtime/decision_cycles.jsonl"))
    orders_repo = OrderEventRepoJsonl(path=os.getenv("BOT_ORDERS_LOG_PATH", "data/runtime/orders.jsonl"))
    executions_repo = ExecutionEventRepoJsonl(path=os.getenv("BOT_EXECUTIONS_LOG_PATH", "data/runtime/executions.jsonl"))

    event_dispatcher = EventDispatcher()
    tele = TeleNotifier(client=TelegramClient())

    event_dispatcher.subscribe(
        "trade.open",
        lambda topic, payload: tele.handle_event({"type": "trade.entry", "trade": payload}),
    )
    event_dispatcher.subscribe(
        "trade.closed",
        lambda topic, payload: tele.handle_event({"type": "trade.closed", "payload": payload}),
    )

    # Notify bot start (optional)
    # Safe: will be ignored if TELEGRAM is disabled or not configured.
    try:
        tele.handle_event({"type": "bot.start"})
    except Exception:
        pass


    # Policy selection: rule vs hybrid
    policy_name = (os.getenv("BOT_POLICY", "hybrid").lower().strip())
    base_policy = RiskAwarePolicyV1()
    if policy_name == "hybrid":
        base_policy = HybridPolicyV1(
            rule_policy=base_policy,
            feature_spec_path=feature_spec_path,
            model_path=os.getenv("SCORER_MODEL_PATH"),
            model_type=os.getenv("SCORER_MODEL_TYPE", "auto"),
        )

    observer_uc = ObserverUsecase(snapshot_repo)
    open_uc = OpenTradeUsecase(snapshot_repo, trade_repo, base_policy, event_bus=event_dispatcher)
    resolve_uc = ResolveTradeUsecase(trade_repo, event_bus=event_dispatcher)
    rl_dataset_uc = DatasetBuildUsecase(trade_repo, snapshot_repo, rl_dataset_repo, feature_spec_path)
    scorer_dataset_uc = ScorerDatasetBuildUsecase(trade_repo, snapshot_repo, scorer_dataset_repo, feature_spec_path)
    feature_mapper = FeatureMapperV1(feature_spec_path)

    return {
        "snapshot_repo": snapshot_repo,
        "trade_repo": trade_repo,
        "market_dataset_repo": market_dataset_repo,
        "decision_cycle_repo": decision_cycle_repo,
        "orders_repo": orders_repo,
        "executions_repo": executions_repo,
        "observer_uc": observer_uc,
        "open_uc": open_uc,
        "resolve_uc": resolve_uc,
        "rl_dataset_uc": rl_dataset_uc,
        "scorer_dataset_uc": scorer_dataset_uc,
        "feature_mapper": feature_mapper,
        "policy": base_policy,
    }


def _make_risk_engine_from_env() -> RiskEngineV1:
    cfg = RiskConfig(
        risk_per_trade_pct=_env_float("RISK_PER_TRADE_PCT", "0.25"),
        risk_per_trade_usdt=(
            _env_float("RISK_PER_TRADE_USDT", "0") if _env_float("RISK_PER_TRADE_USDT", "0") > 0 else None
        ),
        default_leverage=_env_int("LEVERAGE", "3"),
        max_leverage=_env_int("MAX_LEVERAGE", "10"),
        margin_utilization=_env_float("MARGIN_UTILIZATION", "0.30"),
        max_notional_usdt=(
            _env_float("MAX_NOTIONAL_USDT", "0") if _env_float("MAX_NOTIONAL_USDT", "0") > 0 else None
        ),
        max_exposure_pct_per_symbol=(
            _env_float("MAX_EXPOSURE_PCT_PER_SYMBOL", "0") if _env_float("MAX_EXPOSURE_PCT_PER_SYMBOL", "0") > 0 else None
        ),
        min_notional_policy=(os.getenv("MIN_NOTIONAL_POLICY", "skip") or "skip"),
        max_risk_multiplier_on_override=_env_float("MAX_RISK_MULTIPLIER_ON_OVERRIDE", "2.0"),
        max_risk_override_usdt=(
            _env_float("MAX_RISK_OVERRIDE_USDT", "0") if _env_float("MAX_RISK_OVERRIDE_USDT", "0") > 0 else None
        ),
        min_confidence=_env_float("MIN_CONFIDENCE", "0.55"),
    )
    return RiskEngineV1(cfg)


def _make_risk_guard_from_env() -> RiskGuardV1:
    cfg = RiskGuardConfig(
        max_daily_loss_usdt=(
            _env_float("MAX_DAILY_LOSS_USDT", "0") if _env_float("MAX_DAILY_LOSS_USDT", "0") > 0 else None
        ),
        max_daily_loss_pct=(
            _env_float("MAX_DAILY_LOSS_PCT", "0") if _env_float("MAX_DAILY_LOSS_PCT", "0") > 0 else None
        ),
        max_consecutive_losses=_env_int("MAX_CONSECUTIVE_LOSSES", "3"),
        cooldown_sec=_env_int("COOLDOWN_SEC", "0"),
        max_trades_per_day=(
            _env_int("MAX_TRADES_PER_DAY", "0") if _env_int("MAX_TRADES_PER_DAY", "0") > 0 else None
        ),
    )
    return RiskGuardV1(cfg)


def _paper_account_state() -> AccountState:
    equity = _env_float("PAPER_EQUITY_USDT", "100")
    free = _env_float("PAPER_FREE_USDT", str(equity))
    return AccountState(equity_usdt=float(equity), free_usdt=float(free))



def _decision_id(exchange_id: str, symbol: str, snapshot_id: str, snapshot_time_utc: int) -> str:
    base = f"{exchange_id}|{symbol}|{snapshot_id}|{snapshot_time_utc}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


def _hybrid_conf_components(policy, snap) -> tuple[float | None, float | None, float | None]:
    """Return (rule_conf, model_score, final_conf) if possible."""
    try:
        rule_conf = None
        model_score = None

        # HybridPolicyV1 exposes rule_policy + mapper + scorer
        if hasattr(policy, "rule_policy") and hasattr(policy, "mapper") and hasattr(policy, "scorer"):
            try:
                rd = policy.rule_policy.decide(snap)
                rule_conf = float(rd.confidence) if rd.confidence is not None else 1.0
            except Exception:
                rule_conf = 0.0

            try:
                feats = policy.mapper.map(snap.to_dict())
                model_score = float(policy.scorer.score(feats.features))
            except Exception:
                model_score = None

        if rule_conf is None and hasattr(snap, "decision"):
            # not expected; keep None
            pass

        if rule_conf is None and model_score is None:
            return (None, None, None)

        if rule_conf is None:
            final = model_score
        elif model_score is None:
            final = rule_conf
        else:
            final = max(0.0, min(1.0, float(rule_conf) * float(model_score)))

        return (rule_conf, model_score, final)
    except Exception:
        return (None, None, None)

def _to_ohlc_bars(ohlcv: List[List[float]]) -> List[Dict[str, Any]]:
    out = []
    for row in ohlcv:
        if not row or len(row) < 5:
            continue
        ts_ms, o, h, l, c = row[0], row[1], row[2], row[3], row[4]
        out.append({"timestamp": int(ts_ms / 1000), "open": float(o), "high": float(h), "low": float(l), "close": float(c)})
    return out


def run_demo_loop(symbol: str, cycle_sec: int, feature_spec_path: str) -> None:
    pipe = build_pipeline(feature_spec_path)
    observer_uc = pipe["observer_uc"]
    open_uc = pipe["open_uc"]
    resolve_uc = pipe["resolve_uc"]
    rl_dataset_uc = pipe["rl_dataset_uc"]
    scorer_dataset_uc = pipe["scorer_dataset_uc"]

    while True:
        try:
            now = int(time.time())
            entry_price = 100.0
            snap_entry = observer_uc.create_snapshot(_make_synthetic_snapshot(symbol, now, entry_price, atr_pct=0.002))

            policy_info = {"policy_name": pipe["policy"].__class__.__name__, "policy_version": "v1", "policy_type": "rule"}
            ta = open_uc.open_trade(snap_entry.snapshot_id, policy_info)

            # simulate TP
            exit_ts = now + 60
            tp_price = ta.decision.tp_price
            snap_exit = observer_uc.create_snapshot(_make_synthetic_snapshot(symbol, exit_ts, tp_price, atr_pct=0.002))

            exec_state = ExecutionState(
                status="CLOSED",
                entry_time_utc=int(now + 1),
                entry_fill_price=float(ta.decision.entry_price),
                exit_time_utc=int(exit_ts + 1),
                exit_fill_price=float(tp_price),
                exit_type="TP",
                fees_total=0.0005,
                funding_paid=0.0,
            )
            ohlc_bars = [
                {"timestamp": now, "open": entry_price, "high": max(entry_price, tp_price), "low": min(entry_price, ta.decision.sl_price), "close": entry_price},
                {"timestamp": exit_ts, "open": entry_price, "high": max(entry_price, tp_price), "low": min(entry_price, ta.decision.sl_price), "close": float(tp_price)},
            ]
            resolve_uc.resolve_trade(ta.trade_id, exec_state, ohlc_bars, snap_exit.snapshot_id, snap_exit.snapshot_time_utc)

            n1 = rl_dataset_uc.build_and_save()
            n2 = scorer_dataset_uc.build_and_save()
            logger.info("DEMO cycle ok. rl_appended=%s scorer_appended=%s", n1, n2)
        except Exception as e:
            logger.exception("DEMO cycle failed: %s", e)

        time.sleep(max(5, int(cycle_sec)))


def run_data_loop(symbols: List[str], cycle_sec: int, feature_spec_path: str) -> None:
    pipe = build_pipeline(feature_spec_path)
    observer_uc = pipe["observer_uc"]
    feature_mapper = pipe["feature_mapper"]
    market_repo = pipe["market_dataset_repo"]

    ex = make_exchange_from_env()
    sb_cfg = SnapshotBuilderConfig(
        ltf_tf=os.getenv("BOT_LTF", "5m"),
        htf_tfs=[x.strip() for x in (os.getenv("BOT_HTF_LIST", "15m,1h,4h") or "15m,1h,4h").split(",") if x.strip()],
        atr_period=_env_int("ATR_PERIOD", "14"),
        vol_threshold_atr_pct=_env_float("VOL_THRESHOLD_ATR_PCT", "0.003"),
        ms_lookback=_env_int("MS_LOOKBACK", "20"),
        ma_fast=_env_int("MA_FAST", "20"),
        ma_slow=_env_int("MA_SLOW", "50"),
        htf_vol_threshold_atr_pct=_env_float("HTF_VOL_THRESHOLD_ATR_PCT", "0.01"),
    )
    builder = SnapshotBuilderV1(ex, sb_cfg)

    logger.info("DATA mode: exchange=%s symbols=%s", getattr(ex, "exchange_id", "unknown"), ",".join(symbols))

    while True:
        try:
            for symbol in symbols:
                snap_dict = builder.build(symbol)
                snap = observer_uc.create_snapshot(snap_dict)

                feats = feature_mapper.map(snap.to_dict())
                row = {
                    "snapshot_id": snap.snapshot_id,
                    "symbol": snap.symbol,
                    "snapshot_time_utc": snap.snapshot_time_utc,
                    "exchange": snap.context.get("exchange"),
                    "state_features": feats.features,
                    "feature_version": feats.feature_version,
                    "feature_hash": feats.feature_hash,
                    # Keep a few raw fields for convenience
                    "ltf_close": snap.ltf.get("price", {}).get("close"),
                    "funding_rate": snap.context.get("funding_rate"),
                    "session": snap.context.get("session"),
                }
                market_repo.append_rows([row])

                logger.info("DATA tick ok. symbol=%s snapshot=%s close=%s", symbol, snap.snapshot_id, snap.ltf.get("price", {}).get("close"))
        except Exception as e:
            logger.exception("DATA tick failed: %s", e)

        time.sleep(max(5, int(cycle_sec)))


def run_paper_or_live_loop(symbols: List[str], cycle_sec: int, feature_spec_path: str, live: bool) -> None:
    pipe = build_pipeline(feature_spec_path)
    observer_uc = pipe["observer_uc"]
    open_uc = pipe["open_uc"]
    resolve_uc = pipe["resolve_uc"]
    rl_dataset_uc = pipe["rl_dataset_uc"]
    scorer_dataset_uc = pipe["scorer_dataset_uc"]
    trade_repo: TradeRepoCSV = pipe["trade_repo"]

    # Dataset + logs
    feature_mapper = pipe["feature_mapper"]
    market_repo = pipe["market_dataset_repo"]
    decision_cycle_repo: DecisionCycleRepoJsonl = pipe["decision_cycle_repo"]
    orders_repo: OrderEventRepoJsonl = pipe["orders_repo"]
    executions_repo: ExecutionEventRepoJsonl = pipe["executions_repo"]

    policy = pipe["policy"]

    risk_engine = _make_risk_engine_from_env()
    risk_guard = _make_risk_guard_from_env()

    ex = make_exchange_from_env()
    sb_cfg = SnapshotBuilderConfig(
        ltf_tf=os.getenv("BOT_LTF", "5m"),
        htf_tfs=[x.strip() for x in (os.getenv("BOT_HTF_LIST", "15m,1h,4h") or "15m,1h,4h").split(",") if x.strip()],
        atr_period=_env_int("ATR_PERIOD", "14"),
        vol_threshold_atr_pct=_env_float("VOL_THRESHOLD_ATR_PCT", "0.003"),
        ms_lookback=_env_int("MS_LOOKBACK", "20"),
        ma_fast=_env_int("MA_FAST", "20"),
        ma_slow=_env_int("MA_SLOW", "50"),
        htf_vol_threshold_atr_pct=_env_float("HTF_VOL_THRESHOLD_ATR_PCT", "0.01"),
    )
    builder = SnapshotBuilderV1(ex, sb_cfg)

    fee_rate = _env_float("FEE_RATE", "0.0006")  # rough taker fee estimate

    # NOTE:
    # - LIVE: keep the safety default (MAX_OPEN_POSITIONS=1) unless user overrides.
    # - PAPER: if MAX_OPEN_POSITIONS is missing or <= 1, auto-set to len(symbols) to avoid
    #          blocking trades across multi-symbol universe (AUTO). This change ONLY affects PAPER.
    #          To force-respect MAX_OPEN_POSITIONS in paper, set PAPER_RESPECT_MAX_OPEN_POSITIONS=1.
    _raw_max_open = (os.getenv("MAX_OPEN_POSITIONS") or "").strip()
    _paper_respect = _env_bool("PAPER_RESPECT_MAX_OPEN_POSITIONS", "0")
    _auto_max_open_positions = False

    if live:
        max_open_positions = _env_int("MAX_OPEN_POSITIONS", "1")
    else:
        if _paper_respect and _raw_max_open:
            max_open_positions = int(_raw_max_open)
        else:
            try:
                _v = int(_raw_max_open) if _raw_max_open else 0
            except Exception:
                _v = 0
            if _v <= 1 and len(symbols) > 1:
                max_open_positions = max(1, len(symbols))
                _auto_max_open_positions = True
            else:
                max_open_positions = max(1, _v) if _v > 0 else max(1, len(symbols))

    logger.info(
        "%s mode: exchange=%s symbols=%s cycle_sec=%s",
        "LIVE" if live else "PAPER",
        getattr(ex, "exchange_id", "unknown"),
        ",".join(symbols),
        cycle_sec,
    )

    # Universe auto-refresh (only if BOT_SYMBOLS=AUTO)
    universe_auto = (os.getenv("BOT_SYMBOLS") or "").strip().upper() == "AUTO"
    universe_refresh_min = _env_int("UNIVERSE_REFRESH_MIN", "360")
    universe_next_refresh = int(time.time()) + max(60, universe_refresh_min * 60)

    while True:
        cycle_time_utc = int(time.time())
        try:
            # Optional: refresh auto universe
            if universe_auto and int(time.time()) >= universe_next_refresh:
                try:
                    symbols = _select_symbols_auto(ex)
                    universe_next_refresh = int(time.time()) + max(60, universe_refresh_min * 60)
                    logger.info("Universe refreshed: %s", ",".join(symbols))
                    # PAPER: keep MAX_OPEN_POSITIONS in sync with universe size (only when auto-managed).
                    if (not live) and _auto_max_open_positions:
                        max_open_positions = max(1, len(symbols))
                    try:
                        if _env_bool("TELEGRAM_ENABLED", "0"):
                            TelegramClient().send(
                                "🤖 *UNIVERSE REFRESHED*\n" + "\n".join([f"- `{s}`" for s in symbols])
                            )
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning("Universe refresh failed: %s", e)

            # 1) monitor existing open trades
            open_trades = trade_repo.list_open()
            if open_trades:
                open_symbols = sorted(list({t.symbol for t in open_trades if getattr(t, "symbol", None)}))
                tickers = ex.fetch_tickers_many(open_symbols)

                for t in list(open_trades):
                    sym = t.symbol
                    tk = tickers.get(sym) or {}
                    last_price = float(tk.get("last") or tk.get("close") or 0.0)
                    if last_price <= 0:
                        continue

                    hit_tp = False
                    hit_sl = False
                    if t.decision.direction.upper() == "LONG":
                        hit_tp = last_price >= float(t.decision.tp_price)
                        hit_sl = last_price <= float(t.decision.sl_price)
                    else:
                        hit_tp = last_price <= float(t.decision.tp_price)
                        hit_sl = last_price >= float(t.decision.sl_price)

                    if live:
                        pos_qty = ex.fetch_position_qty(sym)
                        if abs(pos_qty) < 1e-12:
                            exit_type = "UNKNOWN"
                            exit_price = last_price
                            tp_id = getattr(t.execution_state, "tp_order_id", None)
                            sl_id = getattr(t.execution_state, "sl_order_id", None)
                            if tp_id:
                                od = ex.fetch_order(sym, tp_id)
                                if od and str(od.get("status", "")).lower() in ("closed", "filled"):
                                    exit_type = "TP"
                                    exit_price = float(od.get("average") or od.get("price") or exit_price)
                            if exit_type == "UNKNOWN" and sl_id:
                                od = ex.fetch_order(sym, sl_id)
                                if od and str(od.get("status", "")).lower() in ("closed", "filled"):
                                    exit_type = "SL"
                                    exit_price = float(od.get("average") or od.get("price") or exit_price)

                            # cancel remaining (best-effort)
                            if tp_id:
                                ex.cancel_order(sym, tp_id)
                            if sl_id:
                                ex.cancel_order(sym, sl_id)

                            exit_ts = int(time.time())
                            try:
                                snap_exit = observer_uc.create_snapshot(builder.build(sym))
                            except Exception:
                                snap_exit = observer_uc.create_snapshot(_make_synthetic_snapshot(sym, exit_ts, exit_price, atr_pct=0.002))

                            exec_state = ExecutionState(
                                status="CLOSED",
                                entry_time_utc=int(t.execution_state.entry_time_utc or t.entry_snapshot_time_utc),
                                entry_fill_price=float(t.execution_state.entry_fill_price or t.decision.entry_price),
                                exit_time_utc=int(exit_ts),
                                exit_fill_price=float(exit_price),
                                exit_type=str(exit_type),
                                fees_total=float(getattr(t.execution_state, "fees_total", 0.0) or 0.0),
                                funding_paid=float(getattr(t.execution_state, "funding_paid", 0.0) or 0.0),
                                exchange=getattr(ex, "exchange_id", None),
                                account_type="USDT-M",
                                margin_mode="isolated",
                                position_mode="oneway",
                                leverage=getattr(t.execution_state, "leverage", None),
                                qty=getattr(t.execution_state, "qty", None),
                                notional=getattr(t.execution_state, "notional", None),
                                entry_order_id=getattr(t.execution_state, "entry_order_id", None),
                                tp_order_id=getattr(t.execution_state, "tp_order_id", None),
                                sl_order_id=getattr(t.execution_state, "sl_order_id", None),
                                client_order_id=getattr(t.execution_state, "client_order_id", None),
                            )

                            since_ms = int((t.entry_snapshot_time_utc - 60) * 1000)
                            ohlcv = ex.fetch_ohlcv(sym, timeframe=os.getenv("BOT_LTF", "5m"), limit=200, since_ms=since_ms)
                            ohlc_bars = _to_ohlc_bars(ohlcv) if ohlcv else []
                            if not ohlc_bars:
                                ohlc_bars = [
                                    {"timestamp": t.entry_snapshot_time_utc, "open": t.decision.entry_price, "high": max(t.decision.entry_price, t.decision.tp_price), "low": min(t.decision.entry_price, t.decision.sl_price), "close": t.decision.entry_price},
                                    {"timestamp": exit_ts, "open": t.decision.entry_price, "high": max(t.decision.entry_price, exit_price), "low": min(t.decision.entry_price, exit_price), "close": float(exit_price)},
                                ]

                            resolve_uc.resolve_trade(t.trade_id, exec_state, ohlc_bars, snap_exit.snapshot_id, snap_exit.snapshot_time_utc)
                            executions_repo.append({
                                "schema_version": "v1",
                                "event_time_utc": int(exit_ts),
                                "event_type": "trade.close",
                                "trade_id": t.trade_id,
                                "symbol": sym,
                                "order_id": None,
                                "fill_qty": getattr(t.execution_state, "qty", None),
                                "fill_price": float(exit_price),
                                "fee_paid": float(getattr(exec_state, "fees_total", 0.0) or 0.0),
                                "meta": {"exit_type": exit_type},
                            })

                            n1 = rl_dataset_uc.build_and_save()
                            n2 = scorer_dataset_uc.build_and_save()
                            logger.info("LIVE closed trade=%s type=%s rl_appended=%s scorer_appended=%s", t.trade_id, exit_type, n1, n2)

                    else:
                        if hit_tp or hit_sl:
                            exit_type = "TP" if hit_tp else "SL"
                            exit_price = float(t.decision.tp_price if hit_tp else t.decision.sl_price)
                            exit_ts = int(time.time())

                            try:
                                snap_exit = observer_uc.create_snapshot(builder.build(sym))
                            except Exception:
                                snap_exit = observer_uc.create_snapshot(_make_synthetic_snapshot(sym, exit_ts, exit_price, atr_pct=0.002))

                            qty = float(getattr(t.execution_state, "qty", 0.0) or 0.0)
                            notional = float(getattr(t.execution_state, "notional", 0.0) or 0.0)
                            est_fees = abs(notional) * float(fee_rate) * 2.0 if notional else 0.0

                            exec_state = ExecutionState(
                                status="CLOSED",
                                entry_time_utc=int(t.execution_state.entry_time_utc or t.entry_snapshot_time_utc),
                                entry_fill_price=float(t.execution_state.entry_fill_price or t.decision.entry_price),
                                exit_time_utc=int(exit_ts),
                                exit_fill_price=float(exit_price),
                                exit_type=str(exit_type),
                                fees_total=float(est_fees),
                                funding_paid=0.0,
                                exchange=getattr(ex, "exchange_id", None),
                                account_type="USDT-M",
                                margin_mode="isolated",
                                position_mode="oneway",
                                leverage=getattr(t.execution_state, "leverage", None),
                                qty=float(qty) if qty else None,
                                notional=float(notional) if notional else None,
                                client_order_id=getattr(t.execution_state, "client_order_id", None),
                            )
                            ohlc_bars = [
                                {"timestamp": t.entry_snapshot_time_utc, "open": t.decision.entry_price, "high": max(t.decision.entry_price, t.decision.tp_price), "low": min(t.decision.entry_price, t.decision.sl_price), "close": t.decision.entry_price},
                                {"timestamp": exit_ts, "open": t.decision.entry_price, "high": max(t.decision.entry_price, exit_price), "low": min(t.decision.entry_price, exit_price), "close": float(exit_price)},
                            ]
                            resolve_uc.resolve_trade(t.trade_id, exec_state, ohlc_bars, snap_exit.snapshot_id, snap_exit.snapshot_time_utc)
                            executions_repo.append({
                                "schema_version": "v1",
                                "event_time_utc": int(exit_ts),
                                "event_type": "trade.close",
                                "trade_id": t.trade_id,
                                "symbol": sym,
                                "order_id": None,
                                "fill_qty": float(qty) if qty else None,
                                "fill_price": float(exit_price),
                                "fee_paid": float(est_fees),
                                "meta": {"exit_type": exit_type},
                            })

                            n1 = rl_dataset_uc.build_and_save()
                            n2 = scorer_dataset_uc.build_and_save()
                            logger.info("PAPER closed trade=%s type=%s rl_appended=%s scorer_appended=%s", t.trade_id, exit_type, n1, n2)

            # 2) open new trades (one per symbol per cycle; gate via max_open_positions)
            open_trades = trade_repo.list_open()
            open_by_symbol = {t.symbol: t for t in open_trades}

            for symbol in symbols:
                # always snapshot + decision log even if blocked by position limits
                try:
                    snap = observer_uc.create_snapshot(builder.build(symbol))
                except Exception as e:
                    logger.warning("snapshot failed %s: %s", symbol, e)
                    snap = observer_uc.create_snapshot(_make_synthetic_snapshot(symbol, int(time.time()), 0.0, atr_pct=0.002))

                # market features row
                try:
                    feats = feature_mapper.map(snap.to_dict())
                    market_repo.append_rows([
                        {
                            "snapshot_id": snap.snapshot_id,
                            "symbol": snap.symbol,
                            "snapshot_time_utc": snap.snapshot_time_utc,
                            "exchange": snap.context.get("exchange"),
                            "state_features": feats.features,
                            "feature_version": feats.feature_version,
                            "feature_hash": feats.feature_hash,
                            "ltf_close": snap.ltf.get("price", {}).get("close"),
                            "funding_rate": snap.context.get("funding_rate"),
                            "session": snap.context.get("session"),
                        }
                    ])
                except Exception:
                    pass

                # decision proposal
                try:
                    decision = policy.decide(snap)
                except Exception as e:
                    logger.warning("policy.decide failed %s: %s", symbol, e)
                    decision = None

                rule_conf, model_score, final_conf = _hybrid_conf_components(policy, snap)

                if decision is not None:
                    conf_mode = (os.getenv("HYBRID_CONF_MODE", "mul") or "mul").strip().lower()
                    chosen_conf = decision.confidence
                    if conf_mode == "mul" and final_conf is not None:
                        chosen_conf = final_conf
                    elif conf_mode == "model" and model_score is not None:
                        chosen_conf = model_score
                    elif conf_mode == "rule" and rule_conf is not None:
                        chosen_conf = rule_conf

                    # rebuild decision with chosen confidence
                    if chosen_conf is not None and decision.confidence != chosen_conf:
                        from trade_ai.domain.entities.trade_decision import TradeDecision

                        decision = TradeDecision(
                            action_type=int(decision.action_type),
                            direction=str(decision.direction),
                            entry_price=float(decision.entry_price),
                            sl_price=float(decision.sl_price),
                            tp_price=float(decision.tp_price),
                            risk_unit=float(decision.risk_unit),
                            rr=float(decision.rr),
                            confidence=float(chosen_conf),
                        )

                # decision cycle record (will be appended exactly once)
                exchange_id = getattr(ex, "exchange_id", "unknown")
                did = _decision_id(exchange_id, symbol, snap.snapshot_id, int(snap.snapshot_time_utc))

                rec = {
                    "schema_version": "v1",
                    "decision_id": did,
                    "snapshot_id": snap.snapshot_id,
                    "snapshot_time_utc": int(snap.snapshot_time_utc),
                    "symbol": symbol,
                    "exchange": exchange_id,
                    "mode": "live" if live else "paper",
                    "cycle_time_utc": int(cycle_time_utc),

                    "action_type": int(getattr(decision, "action_type", 0)) if decision is not None else None,
                    "direction": str(getattr(decision, "direction", "")) if decision is not None else None,
                    "entry_price": float(getattr(decision, "entry_price", 0.0)) if decision is not None else None,
                    "sl_price": float(getattr(decision, "sl_price", 0.0)) if decision is not None else None,
                    "tp_price": float(getattr(decision, "tp_price", 0.0)) if decision is not None else None,
                    "rr": float(getattr(decision, "rr", 0.0)) if decision is not None else None,
                    "risk_unit": float(getattr(decision, "risk_unit", 0.0)) if decision is not None else None,

                    "rule_confidence": rule_conf,
                    "model_score": model_score,
                    "final_confidence": final_conf if final_conf is not None else (decision.confidence if decision is not None else None),

                    "risk_blocked": False,
                    "blocked_reason": None,
                    "is_opened": False,
                    "trade_id": None,
                }

                # pre-gates: position limit
                if len(open_trades) >= max_open_positions:
                    rec["risk_blocked"] = True
                    rec["blocked_reason"] = "max_open_positions"
                    decision_cycle_repo.append(rec)
                    continue

                if symbol in open_by_symbol:
                    rec["risk_blocked"] = True
                    rec["blocked_reason"] = "already_open_symbol"
                    decision_cycle_repo.append(rec)
                    continue

                if decision is None:
                    rec["risk_blocked"] = True
                    rec["blocked_reason"] = "decision_error"
                    decision_cycle_repo.append(rec)
                    continue

                # account state
                if live:
                    equity, free = ex.fetch_account_equity_free()
                    account = AccountState(equity_usdt=float(equity), free_usdt=float(free))
                else:
                    account = _paper_account_state()

                # risk guard (daily loss, streak, cooldown, trades/day)
                # NOTE: In paper mode we often only want market data + AI decisions, so the guard is live-only by default.
                # You can enable it for paper by setting RISK_GUARD_PAPER=1.
                use_risk_guard = live or _env_bool("RISK_GUARD_PAPER", "0")
                if use_risk_guard and (not risk_guard.ok(trade_repo, account, now_utc=int(time.time()))):
                    rec["risk_blocked"] = True
                    rec["blocked_reason"] = "risk_guard_block"
                    decision_cycle_repo.append(rec)
                    continue

                # market constraints
                mc = ex.get_market_constraints(symbol)
                constraints = MarketConstraints(
                    min_notional_usdt=float(mc.get("min_notional_usdt") or 5.0),
                    min_qty=float(mc.get("min_qty")) if mc.get("min_qty") is not None else None,
                    qty_step=float(mc.get("qty_step")) if mc.get("qty_step") is not None else None,
                )

                plan = risk_engine.build_plan(account=account, constraints=constraints, decision=decision)
                if not plan.ok:
                    rec["risk_blocked"] = True
                    rec["blocked_reason"] = str(plan.reason)
                    decision_cycle_repo.append(rec)
                    continue

                # open trade aggregate
                policy_info = {"policy_name": policy.__class__.__name__, "policy_version": "v1", "policy_type": os.getenv("BOT_POLICY", "hybrid")}
                ta = open_uc.open_trade(snap.snapshot_id, policy_info, decision_override=decision)

                # log OMS event
                orders_repo.append({
                    "schema_version": "v1",
                    "event_time_utc": int(time.time()),
                    "event_type": "trade.open.plan",
                    "trade_id": ta.trade_id,
                    "symbol": symbol,
                    "order_id": None,
                    "side": "buy" if decision.direction.upper() == "LONG" else "sell",
                    "qty": float(plan.qty) if plan.qty is not None else None,
                    "price": float(decision.entry_price),
                    "meta": {"notional": plan.notional_usdt, "leverage": plan.leverage, "risk_usdt": plan.risk_usdt},
                })

                # execution state
                if live:
                    try:
                        ex.set_oneway_mode(symbol)
                        ex.set_isolated_margin(symbol)
                        ex.set_leverage(symbol, int(plan.leverage or _env_int("LEVERAGE", "3")))
                    except Exception:
                        pass

                    ids = ex.place_entry_and_brackets(
                        symbol=symbol,
                        direction=decision.direction,
                        qty=float(plan.qty),
                        entry_price=float(decision.entry_price),
                        tp_price=float(decision.tp_price),
                        sl_price=float(decision.sl_price),
                    )

                    for k, oid in (ids or {}).items():
                        if oid:
                            orders_repo.append({
                                "schema_version": "v1",
                                "event_time_utc": int(time.time()),
                                "event_type": f"order.place.{k}",
                                "trade_id": ta.trade_id,
                                "symbol": symbol,
                                "order_id": str(oid),
                                "side": "buy" if decision.direction.upper() == "LONG" else "sell",
                                "qty": float(plan.qty) if plan.qty is not None else None,
                                "price": float(decision.entry_price) if k == "entry_order_id" else None,
                                "meta": None,
                            })

                    ex_state = ExecutionState(
                        status="OPEN",
                        entry_time_utc=int(time.time()),
                        entry_fill_price=float(decision.entry_price),
                        exit_time_utc=None,
                        exit_fill_price=None,
                        exit_type=None,
                        fees_total=0.0,
                        funding_paid=0.0,
                        exchange=getattr(ex, "exchange_id", None),
                        account_type="USDT-M",
                        margin_mode="isolated",
                        position_mode="oneway",
                        leverage=int(plan.leverage or _env_int("LEVERAGE", "3")),
                        qty=float(plan.qty) if plan.qty is not None else None,
                        notional=float(plan.notional_usdt) if plan.notional_usdt is not None else None,
                        entry_order_id=str((ids or {}).get("entry_order_id")) if (ids or {}).get("entry_order_id") else None,
                        tp_order_id=str((ids or {}).get("tp_order_id")) if (ids or {}).get("tp_order_id") else None,
                        sl_order_id=str((ids or {}).get("sl_order_id")) if (ids or {}).get("sl_order_id") else None,
                        client_order_id=None,
                    )
                    trade_repo.update_execution_state(ta.trade_id, ex_state)

                else:
                    # paper: simulated fills at entry price
                    qty = float(plan.qty or 0.0)
                    notional = float(plan.notional_usdt or 0.0)
                    est_fee_entry = abs(notional) * float(fee_rate) if notional else 0.0
                    ex_state = ExecutionState(
                        status="OPEN",
                        entry_time_utc=int(time.time()),
                        entry_fill_price=float(decision.entry_price),
                        exit_time_utc=None,
                        exit_fill_price=None,
                        exit_type=None,
                        fees_total=float(est_fee_entry),
                        funding_paid=0.0,
                        exchange=getattr(ex, "exchange_id", None),
                        account_type="USDT-M",
                        margin_mode="isolated",
                        position_mode="oneway",
                        leverage=int(plan.leverage or _env_int("LEVERAGE", "3")),
                        qty=float(qty) if qty else None,
                        notional=float(notional) if notional else None,
                        client_order_id=str(uuid.uuid4()),
                    )
                    trade_repo.update_execution_state(ta.trade_id, ex_state)

                rec["is_opened"] = True
                rec["trade_id"] = ta.trade_id
                decision_cycle_repo.append(rec)

                logger.info(
                    "OPEN trade=%s %s dir=%s qty=%.6f entry=%.6f tp=%.6f sl=%.6f conf=%.3f",
                    ta.trade_id,
                    symbol,
                    decision.direction,
                    float(plan.qty),
                    float(decision.entry_price),
                    float(decision.tp_price),
                    float(decision.sl_price),
                    float(decision.confidence or 0.0),
                )

            # sleep until next cycle
            time.sleep(max(5, int(cycle_sec)))

        except Exception as e:
            logger.exception("%s loop failed: %s", "LIVE" if live else "PAPER", e)
            time.sleep(max(5, int(cycle_sec)))


def main() -> None:
    # Helpful startup diagnostics (do NOT print secrets)
    if _ENV_FILE_USED:
        logger.info("Env loaded from: %s", _ENV_FILE_USED)
    else:
        logger.info("Env loaded from: (none)")

    tg_enabled = _env_bool("TELEGRAM_ENABLED", "1")
    if tg_enabled and (not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID")):
        logger.warning(
            "Telegram is enabled but TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID is missing. "
            "Fix: set BOT_ENV_FILE=... or create project-root .env from .env.example."
        )

    _ensure_dirs()

    # Default: paper (an toàn + đúng mục tiêu "tài khoản giả định lấy data")
    mode = (os.getenv("BOT_MODE", "paper") or "paper").lower().strip()
    symbols = _parse_symbols_from_env()
    cycle_sec = _env_int("BOT_CYCLE_SEC", "60")
    feature_spec_path = os.getenv("BOT_FEATURE_SPEC", "trade_ai/feature_engineering/feature_spec_v1.yaml")

    logger.info("Start runtime. mode=%s symbols=%s cycle_sec=%s", mode, ",".join(symbols), cycle_sec)

    # Mode router
    # Safety default: paper
    if mode in ("demo", "data") and not _env_bool("DEV_ENABLE_DEMO_DATA", "0"):
        logger.warning(
            "BOT_MODE=%s requires DEV_ENABLE_DEMO_DATA=1. Falling back to BOT_MODE=paper for safety.",
            mode,
        )
        mode = "paper"

    # Exchange is only needed for AUTO selection
    if (os.getenv("BOT_SYMBOLS") or "").strip().upper() == "AUTO" and mode in ("data", "paper", "live"):
        try:
            ex = make_exchange_from_env()
            symbols = _select_symbols_auto(ex)
            logger.info("AUTO selected symbols: %s", ",".join(symbols))
        except Exception as e:
            logger.warning("AUTO universe selection failed, fallback to BOT_SYMBOL. err=%s", e)
            symbols = _parse_symbols_from_env()

    if mode == "demo":
        return run_demo_loop(symbols[0], cycle_sec, feature_spec_path)
    if mode == "data":
        return run_data_loop(symbols, cycle_sec, feature_spec_path)
    if mode == "paper":

        return run_paper_or_live_loop(symbols, cycle_sec, feature_spec_path, live=False)
    if mode == "live":
        # Hard guard: require explicit opt-in
        if not _env_bool("LIVE_CONFIRM", "0"):
            raise SystemExit("LIVE_CONFIRM=1 is required to run BOT_MODE=live")
        return run_paper_or_live_loop(symbols, cycle_sec, feature_spec_path, live=True)

    raise SystemExit(f"Unknown BOT_MODE={mode}")


if __name__ == "__main__":
    main()
