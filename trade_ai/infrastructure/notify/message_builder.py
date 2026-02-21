# trade_ai/infrastructure/notify/message_builder.py
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
import os

VN_TZ = timezone(timedelta(hours=7))

def _fmt_vn_time(ts: Optional[int]) -> str:
    if ts is None:
        return "N/A"
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(VN_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S (VN)")
    except Exception:
        return "N/A"

def _fmt_holding(seconds: Optional[int]) -> str:
    if seconds is None:
        return "N/A"
    try:
        seconds = int(seconds)
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        remain_min = minutes % 60
        return f"{hours}h {remain_min}m"
    except Exception:
        return "N/A"

def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

def _safe(v: Any, fmt: str = "{}") -> str:
    if v is None:
        return "N/A"
    try:
        if isinstance(v, float):
            return fmt.format(v)
        return str(v)
    except Exception:
        return "N/A"

def _is_markdown_enabled() -> bool:
    # TelegramClient uses TELEGRAM_PARSE_MODE; if it's "off" we should avoid markdown tokens.
    mode = (os.getenv("TELEGRAM_PARSE_MODE") or "Markdown").strip().lower()
    return mode not in ("off", "none", "false", "0")

def _normalize_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if event is None or not isinstance(event, dict):
        return None

    if "event_type" in event:
        return {
            "event_type": event["event_type"],
            "symbol": event.get("symbol") or (event.get("payload") or {}).get("symbol"),
            "payload": event.get("payload") or {},
        }

    t = str(event.get("type", "") or "").lower()

    # ENTRY
    if t in ("trade.entry", "trade.entry_event", "trade.entry_event.v1"):
        trade = event.get("trade") or {
            "trade_id": event.get("trade_id"),
            "decision": event.get("decision"),
            "policy_info": event.get("policy_info"),
            "symbol": event.get("symbol"),
        }
        decision = trade.get("decision") or {}

        direction = decision.get("direction")
        if not direction:
            at = decision.get("action_type")
            if at in (1, "1", "long", "LONG"):
                direction = "LONG"
            elif at in (0, "0", "short", "SHORT"):
                direction = "SHORT"

        payload = {
            "trade_id": trade.get("trade_id"),
            "symbol": trade.get("symbol"),
            "direction": direction,
            "entry_price": decision.get("entry_price"),
            "sl_price": decision.get("sl_price"),
            "tp_price": decision.get("tp_price"),
            "rr": decision.get("rr"),
            "entry_time_utc": decision.get("decision_time_utc"),
            # leverage may not be present at entry event; fallback to env
            "leverage": (trade.get("execution_state") or {}).get("leverage"),
        }
        return {"event_type": "TRADE_ENTRY", "symbol": payload.get("symbol"), "payload": payload}

    # EXIT / CLOSED
    if t in ("trade.exit", "trade.close", "trade.closed"):
        payload = event.get("payload") or {}
        if not payload:
            payload = {
                "trade_id": event.get("trade_id"),
                "symbol": event.get("symbol"),
                "execution_state": event.get("execution_state"),
                "reward_state": event.get("reward_state"),
                "exit_type": event.get("exit_type"),
                "result": event.get("result"),
            }
        return {"event_type": "TRADE_EXIT", "symbol": payload.get("symbol"), "payload": payload}

    # SYSTEM
    if t in ("system.health", "bot.start", "bot_start", "bot.start.v1"):
        return {"event_type": "BOT_START", "symbol": None, "payload": {}}
    if t in ("bot.stop", "bot_stop", "bot.stop.v1"):
        return {"event_type": "BOT_STOP", "symbol": None, "payload": {}}

    return None

def build_message_from_event(event: Dict[str, Any]) -> Optional[str]:
    canon = _normalize_event(event)
    if not canon:
        return None

    md = _is_markdown_enabled()
    etype = canon["event_type"]
    payload = canon.get("payload", {}) or {}
    symbol = canon.get("symbol") or payload.get("symbol") or "N/A"

    def H(s: str) -> str:
        return f"*{s}*" if md else s

    # BOT START/STOP
    if etype in ("BOT_START", "BOT_STOP"):
        icon = "🤖" if etype == "BOT_START" else "🛑"
        # Always include icon; avoid markdown when parse_mode is off.
        return f"{icon} {H(etype)}" if md else f"{icon} {etype}"

    # TRADE ENTRY
    if etype == "TRADE_ENTRY":
        trade_id = payload.get("trade_id")
        direction = (payload.get("direction") or "N/A").upper()
        dir_icon = "🟢" if direction == "LONG" else ("🔴" if direction == "SHORT" else "⚪")
        lev = payload.get("leverage") or os.getenv("LEVERAGE") or "N/A"

        lines = [
            f"🚀 {H('TRADE ENTRY')}",
            f"Symbol: {symbol}",
            f"TradeId: {trade_id}",
            f"Direction: {dir_icon} {direction}",
            f"Leverage: x{lev}",
            f"Entry: {_safe(_num(payload.get('entry_price')), '{:.6f}')}",
            f"SL: {_safe(_num(payload.get('sl_price')), '{:.6f}')}",
            f"TP: {_safe(_num(payload.get('tp_price')), '{:.6f}')}",
            f"PnL R: {_safe(_num(payload.get('rr')), '{:.3f}')}",
            f"Time: {_fmt_vn_time(payload.get('entry_time_utc'))}",
        ]
        return "\n".join(lines)

    # TRADE EXIT
    if etype == "TRADE_EXIT":
        trade_id = payload.get("trade_id")
        es = payload.get("execution_state") or {}
        rs = payload.get("reward_state") or {}

        exit_type = payload.get("exit_type") or es.get("exit_type")
        result = payload.get("result") or exit_type

        pnl = payload.get("pnl")
        if pnl is None:
            pnl = rs.get("pnl_usdt") if rs.get("pnl_usdt") is not None else rs.get("pnl_raw")
        pnl_f = _num(pnl)
        pnl_icon = "🟢" if (pnl_f is not None and pnl_f >= 0) else "🔴"

        # win/loss label
        if pnl_f is None:
            wl = ("N/A", "ℹ️")
        elif pnl_f > 0:
            wl = ("WIN", "✅")
        elif pnl_f < 0:
            wl = ("LOSS", "❌")
        else:
            wl = ("BREAKEVEN", "⚪")

        pnl_r = payload.get("pnl_r") if payload.get("pnl_r") is not None else rs.get("pnl_r")
        holding_seconds = payload.get("holding_seconds") or rs.get("holding_seconds")
        exit_time_utc = payload.get("exit_time_utc") or es.get("exit_time_utc") or payload.get("exit_snapshot_time_utc")

        qty = payload.get("qty") or es.get("qty") or rs.get("qty")
        fees = payload.get("fees")
        if fees is None:
            fees = es.get("fees_total")
        if fees is None:
            fees = rs.get("fees_usdt")

        funding = payload.get("funding")
        if funding is None:
            funding = es.get("funding_paid")
        if funding is None:
            funding = rs.get("funding_usdt")

        lev = es.get("leverage") or os.getenv("LEVERAGE") or "N/A"
        notional = es.get("notional") or rs.get("notional_usdt")

        # result emoji
        r = str(result or "").upper()
        if "TP" in r:
            res_icon = "✅"
        elif "SL" in r:
            res_icon = "🛑"
        else:
            res_icon = "ℹ️"

        # signed pnl formatting
        pnl_str = "N/A"
        if pnl_f is not None:
            sign = "+" if pnl_f >= 0 else ""
            pnl_str = f"{sign}{pnl_f:.6f}"

        lines = [
            f"🏁 {H('TRADE EXIT')}",
            f"Symbol: {symbol}",
            f"TradeId: {trade_id}",
            f"Result: {res_icon} {result}",
            f"Type: {exit_type}",
            f"Leverage: x{lev}",
            f"PnL: {pnl_icon} {pnl_str}",
            f"Win/Loss: {wl[0]} {wl[1]}",
        ]
        if qty is not None:
            lines.append(f"Qty: {_safe(_num(qty), '{:.6f}')}")
        if notional is not None:
            lines.append(f"Notional: {_safe(_num(notional), '{:.2f}')} USDT")
        lines += [
            f"PnL R: {_safe(_num(pnl_r), '{:.3f}')}",
            f"Holding: {_fmt_holding(holding_seconds)}",
            f"Time: {_fmt_vn_time(exit_time_utc)}",
            f"Fees: {_safe(_num(fees), '{:.6f}')}",
            f"Funding: {_safe(_num(funding), '{:.6f}')}",
        ]
        return "\n".join(lines)

    return None
