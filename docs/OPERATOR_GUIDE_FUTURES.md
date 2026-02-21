# Operator Guide: Futures thật (USDT‑M) + Risk Engine + Hybrid Scorer

## 0) Chuẩn bị

### A) Setup venv

**Ubuntu/VPS**
```bash
cd bot_trade
python3 -m venv .venv
source .venv/bin/activate

pip install -U pip
pip install -r requirements.txt

# ML (tuỳ chọn, chỉ cần khi train model hoặc muốn chạy scorer thật)
pip install -r requirements_ml.txt
```

**Windows (PowerShell)**
```powershell
cd bot_trade
py -m venv .venv
.\.venv\Scripts\Activate.ps1

py -m pip install -U pip
pip install -r requirements.txt
pip install -r requirements_ml.txt
```

### B) Tạo env file (khuyến nghị)

**Khuyến nghị (an toàn hơn):** dùng env file ngoài project:

```bash
sudo bash ./deploy/create_env_file.sh /etc/bot_trade/bot_trade.env
sudo chmod 600 /etc/bot_trade/bot_trade.env
nano /etc/bot_trade/bot_trade.env
```

Bot sẽ tự load env theo thứ tự ưu tiên:
1) `BOT_ENV_FILE` (nếu set)
2) `/etc/bot_trade/bot_trade.env`
3) `.env` trong thư mục project (fallback, **không khuyến nghị khi zip/share**)

Bạn cũng có thể dùng panel:
```bash
sudo bash ./vps_panel.sh apply-profile demo
```

## 1) Chạy nhanh 4 chế độ

> Entry point: `apps/runtime_trader.py`

### 1.1 Demo (không cần key)
```bash
BOT_MODE=demo python -m apps.runtime_trader
```

### 1.2 Data (kết nối Futures thật để lấy snapshot + features)
```bash
BOT_MODE=data EXCHANGE=binance BOT_SYMBOL=BTCUSDT python -m apps.runtime_trader
```

Output:
- `data/runtime/snapshots/*.json` (SnapshotV3)
- `data/datasets/market/market_features_v1.parquet` (features vector + meta)

### 1.3 Paper (dữ liệu thật + quyết định thật + sizing thật, KHÔNG đặt lệnh)
```bash
BOT_MODE=paper EXCHANGE=binance EXCHANGE_TESTNET=1 python -m apps.runtime_trader
```

Output:
- trades open/closed CSV
- RL dataset + scorer dataset (idempotent, không append trùng)

### 1.4 Live (trade thật)

⚠️ Bắt buộc đặt `LIVE_CONFIRM=1`.

```bash
BOT_MODE=live LIVE_CONFIRM=1 EXCHANGE=binance EXCHANGE_TESTNET=1 \
BINANCE_API_KEY=... BINANCE_API_SECRET=... \
python -m apps.runtime_trader
```

> Khuyến nghị chạy testnet trước (Binance/Bybit hỗ trợ tốt hơn). Với MEXC có thể không có testnet.

## 2) Risk Engine đang làm gì?

Risk engine (`RiskEngineV1`) chỉ làm **sizing** và gate theo confidence:
- Tính `risk_budget` = `% equity` hoặc `fixed USDT`
- Tính `qty = risk_budget / stop_distance` (stop_distance = |entry - SL|)
- Ép `qty` theo `min_qty`, `qty_step`
- Ép theo `min_notional`
- Chọn leverage và/hoặc scale-down qty để không vượt `MARGIN_UTILIZATION * free_usdt`
- Nếu dùng hybrid policy, gate thêm `MIN_CONFIDENCE`

Các cấu hình nằm trong `.env` (xem `docs/CONFIG_MATRIX.md`).

## 3) Hybrid Rule → ML Scorer hoạt động ra sao?

- Rule policy tạo:
  - direction (LONG/SHORT)
  - entry/sl/tp
  - rr

- ML scorer (XGB/LGBM/sklearn) cho ra **score** ∈ [0,1] → ghi vào `TradeDecision.confidence`.

- Risk engine dùng `MIN_CONFIDENCE` để skip signal yếu.

## 4) Dữ liệu xuất ra để người khác học

### 4.1 Market features (streaming, không cần trade)
File: `data/datasets/market/market_features_v1.parquet`

Mỗi dòng:
- `snapshot_id`, `symbol`, `snapshot_time_utc`, `exchange`
- `state_features` (vector)
- `feature_version`, `feature_hash`
- raw fields tiện dụng: `ltf_close`, `funding_rate`, `session`

### 4.2 RL dataset (trade-based)
File: `data/datasets/rl/rl_dataset_v2.parquet`

Mỗi dòng là 1 transition (trade kết thúc = done=True):
- `state_features`
- `action_type`, `action_rr`, `action_sl_distance`, `action_confidence`
- (optional futures) `action_qty`, `action_notional_usdt`, `action_leverage`
- `reward` (pnl_r), `pnl_raw`, (optional) `pnl_usdt`, `risk_usdt`
- `next_state_features`
- `behavior_policy` + `risk_plan`

### 4.3 Supervised scorer dataset
File: `data/datasets/supervised/scorer_dataset_v1.parquet`

Mỗi dòng:
- `features` (vector)
- `label_cls` (1 nếu pnl_r > 0)
- `label_reg` (pnl_r)
- meta: `trade_id`, `symbol`, `timestamp_entry`, `rr`, `sl_distance`, ...

## 5) Train scorer model

1) Build dataset từ closed trades (nếu runtime chưa append):
```bash
python tools/build_scorer_dataset.py
```

2) Train model:
```bash
SCORER_MODEL_TYPE=auto python tools/train_scorer.py
```

3) Dùng model trong runtime:
```env
BOT_POLICY=hybrid
SCORER_MODEL_PATH=data/models/scorer_xgb_v1.json
MIN_CONFIDENCE=0.60
```

## 6) Giai đoạn lấy data cho AI (khuyến nghị)

### Stage A — Backfill lịch sử (nhanh)
```bash
EXCHANGE=binance BOT_SYMBOL=BTCUSDT BOT_LTF=1m SINCE_UTC=2025-01-01 \
python tools/collect_ohlcv.py
```

### Stage B — Streaming market features (chạy lâu)
```bash
BOT_MODE=data BOT_SYMBOL=BTCUSDT BOT_CYCLE_SEC=60 python -m apps.runtime_trader
```

### Stage C — Paper trading để tạo label theo trade outcome
```bash
BOT_MODE=paper EXCHANGE=binance EXCHANGE_TESTNET=1 python -m apps.runtime_trader
```

---

## 7) Notes cho vốn nhỏ

- Giữ `MAX_OPEN_POSITIONS=1`.
- Dùng `RISK_PER_TRADE_USDT` (ví dụ 0.5–1.0 USDT) thay vì % nếu vốn cực nhỏ.
- Nếu thường xuyên bị `notional<min_notional` → đổi symbol có min_qty nhỏ hơn, hoặc tăng timeframe/đợi setup SL gần hơn.
- Luôn ưu tiên **paper/testnet** trước khi bật live.
