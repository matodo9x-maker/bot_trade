# bot_trade (Upgraded)

Repo này là phiên bản **nâng cấp** từ code cũ của bạn, tập trung vào:

- Fix bug **feature_spec_v1.yaml** (trước đây bị nhầm thành file Python)
- Fix **TradeRepoCSV**: deserialize đầy đủ decision/execution/reward để build dataset không bị mất dữ liệu
- Fix **TradeAggregate.attach_execution** để cho phép truyền `entry_fill_price` ngay lúc close (demo/real runtime thường gặp)
- Thêm **VPS setup + start scripts** (nohup + systemd)
- Thêm **supervisor + runtime loop demo** để test end-to-end trên VPS
- Thêm **kết nối Futures thật (CCXT)**: Binance/Bybit/MEXC (USDT‑M), One‑Way + Isolated (best-effort)
- Thêm **RiskEngineV1** (sizing + confidence gate) + **HybridPolicyV1** (rule → XGB/LGBM scorer)
- Thêm **data outputs** (market features + RL dataset + supervised scorer dataset)
- **Harden Telegram env**: secrets nằm ngoài project ở `/etc/bot_trade/bot_trade.env` (chmod 600)

## Quick start (local)

Local dev có thể dùng `.env` cho tiện (nhưng **đừng zip/share** file này):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
TELEGRAM_ENABLED=0 BOT_MODE=paper python -m apps.runtime_trader
```

## VPS

Xem `docs/VPS_SETUP.md`.

## Start bot (demo loop)

```bash
bash ./vps_start.sh /opt/bot_trade
# logs
bash ./vps_logs.sh /opt/bot_trade
```

> Lưu ý: runtime chính thức chỉ dùng **2 chế độ**: `paper` (giả lập để lấy data) và `live` (tiền thật).

## Modes

- `BOT_MODE=paper` : dữ liệu Futures thật + policy + risk engine, **không đặt lệnh** (dùng để lấy data)
- `BOT_MODE=live`  : đặt lệnh Futures thật (cần `LIVE_CONFIRM=1`)

> `demo/data` (nếu còn thấy ở tài liệu cũ) được coi là deprecated và sẽ tự map về `paper` để tránh crash.

Docs:
- `docs/CONFIG_MATRIX.md`
- `docs/OPERATOR_GUIDE_FUTURES.md`
