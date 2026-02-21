# Bảng điều chỉnh cấu hình (Paper/LIVE)

File này gom **toàn bộ biến môi trường** (env) quan trọng để bạn có thể:
- setup venv
- khởi động bot
- chuyển chế độ **paper (giả lập để lấy data) / live (tiền thật)**
- tối ưu cho **vốn nhỏ**
- chuẩn hóa output dữ liệu để người khác có thể **train model** sau này

> Gợi ý: copy `.env.example` -> `.env` rồi chỉnh.

## 1) Runtime

| Biến | Ví dụ | Ý nghĩa |
|---|---:|---|
| `BOT_MODE` | `paper` / `live` | Chế độ chạy. `paper` = lấy data không đặt lệnh. `live` = đặt lệnh thật. |
| `BOT_SYMBOL` | `BTCUSDT` | Symbol chính để chạy (1 symbol). |
| `BOT_CYCLE_SEC` | `60` | Chu kỳ chạy (giây). 60s phù hợp timeframe 1m. |
| `BOT_LTF` | `1m` | Low timeframe dùng cho snapshot. |
| `BOT_HTF_LIST` | `1h,4h` | Danh sách HTF để tính regime/trend. |
| `BOT_POLICY` | `rule` / `hybrid` | `hybrid` = rule tạo entry/SL/TP + ML scorer đặt confidence. |
| `BOT_FEATURE_SPEC` | `trade_ai/feature_engineering/feature_spec_v1.yaml` | Spec mapping features (để train/score nhất quán). |
| `LOG_LEVEL` | `INFO` | Mức log. |

## 2) Exchange Futures (USDT‑M)

| Biến | Ví dụ | Ý nghĩa |
|---|---:|---|
| `EXCHANGE` | `binance` / `bybit` / `mexc` | Sàn Futures. |
| `EXCHANGE_TESTNET` | `1` | Bật sandbox/testnet nếu CCXT hỗ trợ (khuyến nghị trước khi live). |
| `EXCHANGE_RATE_LIMIT` | `1` | Bật rate limit nội bộ CCXT. |
| `EXCHANGE_TIMEOUT_MS` | `30000` | Timeout API. |

### API Keys

| Sàn | Key env |
|---|---|
| Binance | `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `BINANCE_API_PASSWORD` (optional) |
| Bybit | `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `BYBIT_API_PASSWORD` (optional) |
| MEXC | `MEXC_API_KEY`, `MEXC_API_SECRET`, `MEXC_API_PASSWORD` (optional) |

> Nếu bạn thấy tài liệu cũ có `demo/data` thì coi như **deprecated** (bot sẽ tự map về `paper`).

## 3) Safe-guard cho Live

| Biến | Ví dụ | Ý nghĩa |
|---|---:|---|
| `LIVE_CONFIRM` | `1` | **Bắt buộc** phải =1 mới chạy `BOT_MODE=live`. Tránh bật nhầm. |

## 4) Risk Engine (tối ưu vốn nhỏ)

| Biến | Ví dụ | Ý nghĩa |
|---|---:|---|
| `RISK_PER_TRADE_PCT` | `0.25` | % equity rủi ro mỗi lệnh. Vốn nhỏ nên 0.1–0.5%. |
| `RISK_PER_TRADE_USDT` | `0.5` | Nếu set >0, sẽ dùng fixed risk (USDT) thay vì %. |
| `LEVERAGE` | `3` | Leverage mặc định. |
| `MAX_LEVERAGE` | `10` | Trần leverage. |
| `MARGIN_UTILIZATION` | `0.30` | Chỉ dùng tối đa 30% free margin để mở lệnh. |
| `MAX_NOTIONAL_USDT` | *(trống)* | Nếu set, cap notional mỗi lệnh. |
| `MIN_CONFIDENCE` | `0.55` | Ngưỡng confidence (từ ML scorer). Dưới ngưỡng sẽ skip. |
| `MIN_NOTIONAL_POLICY` | `skip` | Nếu notional < min sàn: `skip` hoặc `override_with_cap`. |
| `MAX_RISK_MULTIPLIER_ON_OVERRIDE` | `2.0` | Nếu override min notional, risk tối đa = risk_budget * multiplier. |
| `MAX_RISK_OVERRIDE_USDT` | *(trống)* | Trần cứng risk khi override (USDT). |
| `MAX_OPEN_POSITIONS` | `1` | Giới hạn số lệnh mở. (Bản runtime hiện assume 1 lệnh/symbol). |
| `FEE_RATE` | `0.0006` | Ước lượng phí (paper). Live: tuỳ sàn. |

### Risk guard (optional)

| Biến | Ví dụ | Ý nghĩa |
|---|---:|---|
| `MAX_DAILY_LOSS_USDT` | `5` | Lỗ tối đa trong ngày (USDT). Vượt → stop mở lệnh mới. |
| `MAX_DAILY_LOSS_PCT` | `2` | Lỗ tối đa trong ngày (% equity). |
| `MAX_CONSECUTIVE_LOSSES` | `3` | Chuỗi thua liên tiếp tối đa. |
| `COOLDOWN_SEC` | `300` | Nghỉ giữa các lệnh (s) sau khi đóng. |
| `MAX_TRADES_PER_DAY` | `10` | Giới hạn số lệnh/ngày. |

### Paper account

| Biến | Ví dụ | Ý nghĩa |
|---|---:|---|
| `PAPER_EQUITY_USDT` | `100` | Equity giả lập paper mode. |
| `PAPER_FREE_USDT` | `100` | Free margin giả lập paper mode. |

## 5) ML Scorer

| Biến | Ví dụ | Ý nghĩa |
|---|---:|---|
| `SCORER_MODEL_PATH` | `data/models/scorer_xgb_v1.json` | Đường dẫn model để score. Nếu không có → confidence=1.0. |
| `SCORER_MODEL_TYPE` | `auto` | `auto|xgb|lgbm|sklearn`. |

## 6) Output paths (dữ liệu để học)

| Biến | Default | Ý nghĩa |
|---|---|---|
| `BOT_SNAPSHOT_DIR` | `data/runtime/snapshots` | Lưu SnapshotV3 dạng JSON. |
| `BOT_TRADES_OPEN` | `data/runtime/trades_open.csv` | Trades OPEN. |
| `BOT_TRADES_CLOSED` | `data/runtime/trades_closed.csv` | Trades CLOSED. |
| `BOT_RL_DATASET_PATH` | `data/datasets/rl/rl_dataset_v2.parquet` | Dataset RL transitions (state/action/reward/next_state). |
| `BOT_SCORER_DATASET_PATH` | `data/datasets/supervised/scorer_dataset_v1.parquet` | Dataset supervised để train scorer. |
| `BOT_MARKET_DATASET_PATH` | `data/datasets/market/market_features_v1.parquet` | Dataset market-only (snapshot features streaming). |

---

## Preset khuyến nghị cho vốn nhỏ

**Paper (an toàn nhất để kiểm tra):**
```env
BOT_MODE=paper
EXCHANGE=binance
EXCHANGE_TESTNET=1
RISK_PER_TRADE_USDT=0.5
LEVERAGE=3
MAX_LEVERAGE=10
MARGIN_UTILIZATION=0.25
MIN_CONFIDENCE=0.60
MAX_OPEN_POSITIONS=1
```

**Data (chỉ lấy data cho AI):**
```env
BOT_MODE=data
BOT_CYCLE_SEC=60
EXCHANGE=binance
EXCHANGE_TESTNET=0
```
