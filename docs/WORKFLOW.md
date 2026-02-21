# Workflow (Cấu trúc làm việc)

## Các lệnh chính

- Demo 1 lần (test nhanh):

```bash
TELEGRAM_ENABLED=0 python3 supervisor.py demo
```

- Chạy supervisor (khuyến nghị khi deploy):

```bash
python3 supervisor.py runtime
```

- Bot runtime (demo loop) tạo snapshot -> open -> resolve -> build dataset:

```bash
python3 -m apps.runtime_trader
```

## ENV (Telegram/API keys)

- VPS: secrets nằm ở `/etc/bot_trade/bot_trade.env` (chmod 600)
- Local dev: có thể dùng `.env` (nhưng **đừng zip/share**)

## Luồng dữ liệu (demo hiện tại)

1. Tạo **SnapshotV3** (immutable) và lưu `data/runtime/snapshots/*.json`
2. Policy tạo **TradeDecision**
3. Resolve tạo **RewardState** (pnl_raw, pnl_r, mfe/mae)
4. Dataset builder xuất **rl_transition parquet** -> `data/datasets/rl/rl_dataset_v1.parquet`

> Khi bạn sẵn sàng trade futures thật, phần “market snapshot” và “execution report” sẽ được thay bằng dữ liệu từ sàn + fills thật.
