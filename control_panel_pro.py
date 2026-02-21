import os
import sys
import json
import time
import subprocess
from pathlib import Path
import signal
import threading
from typing import Dict, Optional


# ============================================================
# Entrypoint router
# - GUI mode (default)
# - Runtime mode: this same file can run the bot loop in a separate process
#   so that the Control Panel EXE can start the bot reliably.
# ============================================================

# Paths are needed for both GUI and runtime mode
def _resolve_project_root() -> Path:
    """Resolve project root robustly (works for source run and PyInstaller onedir).

    The project root is identified by the presence of:
      - apps/ directory
      - trade_ai/ directory

    When running as an EXE, the working directory is often inside the dist folder,
    so we walk upwards from sys.executable to find the real repo root.
    """
    try:
        start = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    except Exception:
        start = Path.cwd()

    # Walk up a few levels to locate the repo root
    for base in [start] + list(start.parents)[:8]:
        if (base / "apps").is_dir() and (base / "trade_ai").is_dir():
            return base

    # Fallback: common onedir layout: <root>/dist/control_panel_pro/control_panel_pro.exe
    try:
        maybe = start.parent.parent
        if (maybe / "apps").is_dir() and (maybe / "trade_ai").is_dir():
            return maybe
    except Exception:
        pass

    return start

ROOT = _resolve_project_root()


def _parse_env_file(path: Path) -> Dict[str, str]:
    """Parse a simple .env file into a dict (best-effort).

    - Ignores comments and blank lines
    - Supports lines like: KEY=VALUE, export KEY=VALUE
    - Keeps VALUE as-is (including quotes)
    """
    out: Dict[str, str] = {}
    try:
        if not path.exists():
            return out
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if not k:
                continue
            out[k] = v.strip()
    except Exception:
        return out
    return out


def _write_env_kv(path: Path, kv: Dict[str, str]) -> None:
    lines = [f"{k}={v}" for k, v in kv.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_runtime_mode() -> None:
    """Run apps.runtime_trader.main() with env loaded from BOT_ENV_FILE."""
    # Ensure relative paths behave like running from repo root
    os.chdir(str(ROOT))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    # Best-effort env load (BOT_ENV_FILE -> .env fallback)
    try:
        from trade_ai.infrastructure.config.env_loader import load_env

        load_env()
    except Exception:
        pass

    from apps.runtime_trader import main as runtime_main

    runtime_main()


# CLI flags for non-GUI modes
if "--run-runtime" in sys.argv:
    _run_runtime_mode()
    raise SystemExit(0)


# GUI imports (lazy so runtime mode doesn't require tkinter)
import customtkinter as ctk
from tkinter import messagebox

# ============================================================
# Paths (GUI)
# ============================================================
CONFIG_FILE = ROOT / "bot_gui_config.json"
ENV_GUI_FILE = ROOT / "runtime_gui.env"

PID_FILE = ROOT / "data/runtime/bot.pid"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_LOG = LOG_DIR / "runtime_trader.log"

TRADES_OPEN = ROOT / "data/runtime/trades_open.csv"
TRADES_CLOSED = ROOT / "data/runtime/trades_closed.csv"

# Optional helper scripts (Win10)
SETUP_BAT = ROOT / "00_SETUP_WIN10_ONECLICK.bat"
OPEN_DOCS_BAT = ROOT / "02_HELP_OPEN_DOCS.bat"
OPEN_ENV_BAT = ROOT / "01_OPEN_ENV.bat"
INSTALL_TASK_BAT = ROOT / "03_INSTALL_TASK_SCHEDULER.bat"
REMOVE_TASK_BAT = ROOT / "04_REMOVE_TASK_SCHEDULER.bat"
OPEN_LOGS_BAT = ROOT / "05_OPEN_LOGS.bat"


DEFAULT_CFG = {
    "mode": "paper",                  # paper | live
    "equity_usdt": 100.0,             # PAPER_EQUITY_USDT (paper mode)
    "symbols_mode": "manual",         # manual | auto
    "symbols_csv": "BTCUSDT,ETHUSDT",
    "target_symbols": 3,              # UNIVERSE_TARGET_SYMBOLS when AUTO
    "leverage": 10,                   # LEVERAGE
    "max_leverage": 20,               # MAX_LEVERAGE
    "risk_per_trade_pct": 0.25,       # RISK_PER_TRADE_PCT
    "risk_per_trade_usdt": 0.0,       # optional override
    "telegram_enabled": 0,            # TELEGRAM_ENABLED (0/1)
    "cycle_sec": 300,                 # BOT_CYCLE_SEC (match 5m LTF default)
}

# ============================================================
# Config load/save
# ============================================================
def load_cfg():
    if CONFIG_FILE.exists():
        try:
            return {**DEFAULT_CFG, **json.loads(CONFIG_FILE.read_text(encoding="utf-8"))}
        except Exception:
            pass
    return DEFAULT_CFG.copy()

def save_cfg(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================
# Env writer (BOT_ENV_FILE)
# ============================================================
def write_env_file(cfg: dict):
    """Write runtime_gui.env.

    IMPORTANT:
    - runtime_trader's env_loader stops after the first found env file.
      If BOT_ENV_FILE points to runtime_gui.env, it will NOT load project-root .env.
    - Therefore we MERGE project-root .env into runtime_gui.env so Telegram token/chat_id
      (and exchange keys if any) are available when starting from the panel.
    """
    mode = (cfg.get("mode") or "paper").strip().lower()

    # 1) Base env (project root)
    base_env = _parse_env_file(ROOT / ".env")
    merged: Dict[str, str] = dict(base_env)

    # 2) Panel overrides
    merged["BOT_MODE"] = mode
    merged["BOT_CYCLE_SEC"] = str(int(cfg["cycle_sec"]))

    if cfg.get("symbols_mode") == "auto":
        merged["BOT_SYMBOLS"] = "AUTO"
        merged["UNIVERSE_TARGET_SYMBOLS"] = str(int(cfg["target_symbols"]))
    else:
        syms = (cfg.get("symbols_csv") or "").strip().upper().replace(" ", "")
        merged["BOT_SYMBOLS"] = syms

    merged["LEVERAGE"] = str(int(cfg["leverage"]))
    merged["MAX_LEVERAGE"] = str(int(cfg["max_leverage"]))
    merged["RISK_PER_TRADE_PCT"] = str(float(cfg["risk_per_trade_pct"]))

    if float(cfg.get("risk_per_trade_usdt", 0.0)) > 0:
        merged["RISK_PER_TRADE_USDT"] = str(float(cfg["risk_per_trade_usdt"]))

    if mode == "paper":
        merged["PAPER_EQUITY_USDT"] = str(float(cfg["equity_usdt"]))
        merged["LIVE_CONFIRM"] = "0"
        merged["RISK_GUARD_PAPER"] = "0"  # disable account safety lock in paper (live-only by default)
    else:
        # live mode safety gate
        merged["LIVE_CONFIRM"] = "1"

    merged["TELEGRAM_ENABLED"] = str(int(cfg.get("telegram_enabled", 0)))

    # Safer default to avoid Telegram markdown parse failures
    if merged.get("TELEGRAM_ENABLED", "0") in ("1", "true", "True"):
        merged.setdefault("TELEGRAM_PARSE_MODE", "off")

    # Normalize order a bit (stable output), but keep content complete
    # Put panel-managed keys on top for readability.
    top_keys = [
        "BOT_MODE",
        "BOT_SYMBOLS",
        "UNIVERSE_TARGET_SYMBOLS",
        "BOT_CYCLE_SEC",
        "LEVERAGE",
        "MAX_LEVERAGE",
        "RISK_PER_TRADE_PCT",
        "RISK_PER_TRADE_USDT",
        "PAPER_EQUITY_USDT",
        "LIVE_CONFIRM",
        "RISK_GUARD_PAPER",
        "TELEGRAM_ENABLED",
        "TELEGRAM_PARSE_MODE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]
    ordered: Dict[str, str] = {}
    for k in top_keys:
        if k in merged:
            ordered[k] = merged[k]
    for k in sorted(merged.keys()):
        if k not in ordered:
            ordered[k] = merged[k]

    _write_env_kv(ENV_GUI_FILE, ordered)


def _check_telegram_ready(env_kv: Dict[str, str]) -> Optional[str]:
    if str(env_kv.get("TELEGRAM_ENABLED", "0")).strip() not in ("1", "true", "True"):
        return None
    if not env_kv.get("TELEGRAM_BOT_TOKEN") or not env_kv.get("TELEGRAM_CHAT_ID"):
        return "Bạn đã bật Telegram nhưng thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID. Hãy điền trong file .env (ở thư mục bots/) rồi bấm Lưu lại."
    return None


# ============================================================
# PID helpers
# ============================================================
def read_pid() -> int:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0

def write_pid(pid: int):
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid), encoding="utf-8")

def clear_pid():
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

def pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        # Windows: fallback to tasklist
        if os.name == "nt":
            try:
                out = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}"], text=True, stderr=subprocess.DEVNULL)
                return str(pid) in out
            except Exception:
                return False
        return False


# ============================================================
# Bot start/stop with log to file
# ============================================================
def start_bot(cfg: dict):
    write_env_file(cfg)

    pid = read_pid()
    if pid and pid_running(pid):
        return False, f"⚠ Bot đang chạy (PID={pid})"

    env = os.environ.copy()
    env["BOT_ENV_FILE"] = str(ENV_GUI_FILE)
    env["BOT_ENV_OVERRIDE"] = "1"

    # Pre-flight checks
    env_kv = _parse_env_file(ENV_GUI_FILE)
    warn = _check_telegram_ready(env_kv)
    if warn:
        try:
            messagebox.showwarning("Telegram chưa sẵn sàng", warn)
        except Exception:
            pass

    # Write header to log
    with open(RUNTIME_LOG, "a", encoding="utf-8") as f:
        f.write("\n" + "="*70 + "\n")
        f.write(f"START {time.strftime('%Y-%m-%d %H:%M:%S')} | mode={cfg.get('mode')} | env={ENV_GUI_FILE.name}\n")

    # When frozen (PyInstaller), sys.executable is the EXE, not python.
    # We use the same file in "runtime mode" so EXE can spawn the bot reliably.
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--run-runtime"]
    else:
        cmd = [sys.executable, "-u", str(Path(__file__).resolve()), "--run-runtime"]

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    p = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=open(RUNTIME_LOG, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    write_pid(p.pid)

    # Quick crash detection (common when env is wrong)
    time.sleep(0.3)
    if p.poll() is not None:
        code = p.returncode
        clear_pid()
        return False, f"❌ Bot thoát ngay (code={code}). Mở {RUNTIME_LOG.name} để xem lỗi."

    return True, f"✅ Bot started (PID={p.pid}). Log: {RUNTIME_LOG.name}"

def stop_bot():
    pid = read_pid()
    if not pid:
        return False, "⚠ Không thấy PID (bot chưa chạy?)"

    try:
        if os.name == "nt":
            subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
        clear_pid()
        return True, f"⛔ Bot đã dừng (PID={pid})"
    except Exception as e:
        return False, f"❌ Không dừng được PID={pid}: {e}"


# ============================================================
# Trades/PnL reader
# ============================================================
def _iter_trade_json_rows(csv_path: Path):
    if not csv_path.exists():
        return
    try:
        for line in csv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            if line.lower().startswith("trade_id,"):
                continue
            try:
                _, blob = line.split(",", 1)
                yield json.loads(blob)
            except Exception:
                continue
    except Exception:
        return

def calc_pnl():
    closed = list(_iter_trade_json_rows(TRADES_CLOSED))
    realized = 0.0
    wins = 0
    losses = 0
    last_symbol = "-"
    last_pnl = 0.0

    for t in closed[-300:]:
        rs = t.get("reward_state") or {}
        pnl = rs.get("pnl_usdt")
        if pnl is None:
            pnl = rs.get("pnl_raw", 0.0)
        try:
            pnl = float(pnl)
        except Exception:
            pnl = 0.0
        realized += pnl
        wins += int(pnl >= 0)
        losses += int(pnl < 0)
        last_symbol = t.get("symbol", "-")
        last_pnl = pnl

    open_last = {}
    for t in _iter_trade_json_rows(TRADES_OPEN):
        tid = t.get("trade_id")
        if tid:
            open_last[str(tid)] = t

    return {
        "realized": realized,
        "wins": wins,
        "losses": losses,
        "open_count": len(open_last),
        "closed_count": len(closed),
        "last_symbol": last_symbol,
        "last_pnl": last_pnl,
    }


# ============================================================
# Utilities to run helper .bat
# ============================================================
def run_bat(path: Path):
    if not path.exists():
        messagebox.showwarning("Thiếu file", f"Không thấy: {path.name}")
        return
    try:
        subprocess.Popen(["cmd", "/c", str(path)], cwd=str(ROOT))
    except Exception as e:
        messagebox.showerror("Lỗi", str(e))

def open_file(path: Path):
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        messagebox.showwarning("Không mở được", str(path))


def open_logs_folder():
    """Open the logs folder in Explorer (no .bat dependency)."""
    logs_dir = ROOT / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        os.startfile(str(logs_dir))  # type: ignore[attr-defined]
    except Exception as e:
        messagebox.showwarning("Không mở được", f"{logs_dir}\n{e}")


# ============================================================
# UI with scroll
# ============================================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.title("BOT TRADE CONTROL PANEL — PRO")
app.geometry("920x820")
app.minsize(820, 640)

cfg = load_cfg()

# Top sticky bar
top = ctk.CTkFrame(app)
top.pack(fill="x", padx=12, pady=(12, 8))

ctk.CTkLabel(top, text="🔥 BOT TRADE CONTROL — PRO", font=("Arial", 18)).pack(side="left", padx=12, pady=10)

def on_save():
    try:
        new = get_cfg_from_ui()
        save_cfg(new)
        write_env_file(new)
        status_lbl.configure(text=f"✅ Đã lưu. Env: {ENV_GUI_FILE.name}")
    except Exception as e:
        messagebox.showerror("Lỗi", str(e))

def on_start():
    try:
        new = get_cfg_from_ui()
        save_cfg(new)
        ok, msg = start_bot(new)
        status_lbl.configure(text=msg)
    except Exception as e:
        messagebox.showerror("Lỗi", str(e))

def on_stop():
    ok, msg = stop_bot()
    status_lbl.configure(text=msg)

ctk.CTkButton(top, text="💾 Lưu", command=on_save).pack(side="right", padx=8)
ctk.CTkButton(top, text="🚀 Chạy Bot", command=on_start, fg_color="green").pack(side="right", padx=8)
ctk.CTkButton(top, text="⛔ Dừng Bot", command=on_stop, fg_color="red").pack(side="right", padx=8)

# Scroll area
scroll = ctk.CTkScrollableFrame(app)
scroll.pack(fill="both", expand=True, padx=12, pady=(0, 10))

def row_entry(parent, label, default):
    frame = ctk.CTkFrame(parent)
    frame.pack(fill="x", pady=6)
    ctk.CTkLabel(frame, text=label, width=260, anchor="w").pack(side="left", padx=12, pady=12)
    ent = ctk.CTkEntry(frame)
    ent.pack(side="right", fill="x", expand=True, padx=12, pady=12)
    ent.insert(0, str(default))
    return ent

def row_option(parent, label, values, default):
    frame = ctk.CTkFrame(parent)
    frame.pack(fill="x", pady=6)
    ctk.CTkLabel(frame, text=label, width=260, anchor="w").pack(side="left", padx=12, pady=12)
    opt = ctk.CTkOptionMenu(frame, values=values)
    opt.set(str(default))
    opt.pack(side="right", padx=12, pady=12)
    return opt

def row_switch(parent, label, default_int):
    frame = ctk.CTkFrame(parent)
    frame.pack(fill="x", pady=6)
    var = ctk.IntVar(value=int(default_int))
    sw = ctk.CTkSwitch(frame, text=label, variable=var)
    sw.pack(side="left", padx=12, pady=12)
    return var

mode_opt = row_option(scroll, "Chế độ chạy", ["paper", "live"], cfg["mode"])
equity_ent = row_entry(scroll, "Tài khoản (USDT) - paper", cfg["equity_usdt"])
cycle_ent = row_entry(scroll, "Chu kỳ (giây) BOT_CYCLE_SEC", cfg["cycle_sec"])
lev_ent = row_entry(scroll, "Đòn bẩy LEVERAGE", cfg["leverage"])
maxlev_ent = row_entry(scroll, "Max leverage MAX_LEVERAGE", cfg["max_leverage"])
riskpct_ent = row_entry(scroll, "Risk %/trade RISK_PER_TRADE_PCT", cfg["risk_per_trade_pct"])
riskusdt_ent = row_entry(scroll, "Risk USDT/trade (0 = tắt)", cfg["risk_per_trade_usdt"])

symbols_mode_opt = row_option(scroll, "Chọn coin", ["manual", "auto"], cfg["symbols_mode"])
symbols_ent = row_entry(scroll, "Manual coins (CSV) BOT_SYMBOLS", cfg["symbols_csv"])
target_ent = row_entry(scroll, "AUTO: số coin UNIVERSE_TARGET_SYMBOLS", cfg["target_symbols"])
tg_var = row_switch(scroll, "Telegram enabled (TELEGRAM_ENABLED)", cfg["telegram_enabled"])

# Setup / helper buttons
helper = ctk.CTkFrame(scroll)
helper.pack(fill="x", pady=10)
ctk.CTkLabel(helper, text="🧰 Công cụ", font=("Arial", 15)).pack(anchor="w", padx=12, pady=(10, 6))

btns = ctk.CTkFrame(helper)
btns.pack(fill="x", padx=12, pady=12)

ctk.CTkButton(btns, text="One-click Setup", command=lambda: run_bat(SETUP_BAT)).pack(side="left", padx=8, pady=10)
ctk.CTkButton(btns, text="Mở .env", command=lambda: run_bat(OPEN_ENV_BAT)).pack(side="left", padx=8, pady=10)
ctk.CTkButton(btns, text="Mở hướng dẫn", command=lambda: run_bat(OPEN_DOCS_BAT)).pack(side="left", padx=8, pady=10)
ctk.CTkButton(btns, text="Cài Task Scheduler", command=lambda: run_bat(INSTALL_TASK_BAT)).pack(side="left", padx=8, pady=10)
ctk.CTkButton(btns, text="Gỡ Task Scheduler", command=lambda: run_bat(REMOVE_TASK_BAT)).pack(side="left", padx=8, pady=10)
ctk.CTkButton(btns, text="Mở logs", command=open_logs_folder).pack(side="left", padx=8, pady=10)


# Telegram quick test
def on_test_tele():
    try:
        new = get_cfg_from_ui()
        save_cfg(new)
        write_env_file(new)
        env_kv = _parse_env_file(ENV_GUI_FILE)
        warn = _check_telegram_ready(env_kv)
        if warn:
            messagebox.showwarning("Telegram chưa sẵn sàng", warn)
            return

        def _work():
            try:
                # Avoid polluting GUI process env; pass explicit token/chat_id
                from trade_ai.infrastructure.notify.telegram_client import TelegramClient

                c = TelegramClient(
                    bot_token=env_kv.get("TELEGRAM_BOT_TOKEN"),
                    chat_id=env_kv.get("TELEGRAM_CHAT_ID"),
                    enabled=True,
                )
                res = c.send("🤖 BOT_START (test from control_panel)", parse_mode=None)
                ok = isinstance(res, dict) and bool(res.get("ok"))
                msg = "✅ Test Telegram OK" if ok else f"❌ Telegram failed: {res.get('description') or res.get('reason') or res}"
            except Exception as e:
                msg = f"❌ Telegram exception: {e}"
            app.after(0, lambda: status_lbl.configure(text=msg))

        threading.Thread(target=_work, daemon=True).start()
    except Exception as e:
        messagebox.showerror("Lỗi", str(e))


ctk.CTkButton(btns, text="📨 Test Tele", command=on_test_tele).pack(side="left", padx=8, pady=10)

# Status/PnL footer
status_box = ctk.CTkFrame(app)
status_box.pack(fill="x", padx=12, pady=(0, 12))

status_lbl = ctk.CTkLabel(status_box, text="", font=("Arial", 14))
status_lbl.pack(anchor="w", padx=12, pady=(10, 0))

pnl_lbl = ctk.CTkLabel(status_box, text="", font=("Arial", 13))
pnl_lbl.pack(anchor="w", padx=12, pady=(6, 12))

def get_cfg_from_ui():
    return {
        "mode": mode_opt.get().strip().lower(),
        "equity_usdt": float(equity_ent.get().strip()),
        "cycle_sec": int(float(cycle_ent.get().strip())),
        "leverage": int(float(lev_ent.get().strip())),
        "max_leverage": int(float(maxlev_ent.get().strip())),
        "risk_per_trade_pct": float(riskpct_ent.get().strip()),
        "risk_per_trade_usdt": float(riskusdt_ent.get().strip()),
        "symbols_mode": symbols_mode_opt.get().strip().lower(),
        "symbols_csv": symbols_ent.get().strip().upper().replace(" ", ""),
        "target_symbols": int(float(target_ent.get().strip())),
        "telegram_enabled": int(tg_var.get()),
    }

def refresh_status():
    try:
        pid = read_pid()
        running = pid and pid_running(pid)
        s = calc_pnl()
        pnl_lbl.configure(
            text=(
                f"📊 PnL realized: {s['realized']:.3f} USDT | "
                f"Closed: {s['closed_count']} (W:{s['wins']}/L:{s['losses']}) | "
                f"Open: {s['open_count']} | "
                f"Last: {s['last_symbol']} {s['last_pnl']:+.3f} | "
                f"Bot: {'RUNNING' if running else 'STOPPED'}"
            )
        )
    except Exception:
        pass
    app.after(2000, refresh_status)

refresh_status()
app.mainloop()
