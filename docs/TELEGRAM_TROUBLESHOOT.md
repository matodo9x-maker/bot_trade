# Telegram troubleshooting

Nếu bạn thấy log kiểu:

```
Telegram send failed: {'reason': 'no-token-or-chatid', ...}
```

thì **bot đang không thấy** `TELEGRAM_BOT_TOKEN` hoặc `TELEGRAM_CHAT_ID` trong môi trường chạy.

## 1) Kiểm tra env được load từ đâu

Bot hỗ trợ 3 cách (ưu tiên theo thứ tự):

1. `BOT_ENV_FILE=/path/to/bot_trade.env`
2. Linux VPS: `/etc/bot_trade/bot_trade.env`
3. Dev/Windows: `.env` ở project root

Bạn có thể test nhanh:

```bash
python tools/tele_test.py
```

Script sẽ in `env_loaded=...` và kết quả gửi telegram.

## 2) Windows (CMD/PowerShell)

### Cách A: Dùng `.env` trong project

1. Copy mẫu:

```bat
copy .env.example .env
```

2. Điền:

```
TELEGRAM_ENABLED=1
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

3. Test:

```bat
python tools\tele_test.py
```

### Cách B: Dùng file env riêng (không nằm trong repo)

```bat
set BOT_ENV_FILE=C:\secrets\bot_trade.env
python tools\tele_test.py
```

## 3) Linux VPS + systemd

- Tạo env file:

```bash
sudo mkdir -p /etc/bot_trade
sudo nano /etc/bot_trade/bot_trade.env
sudo chmod 600 /etc/bot_trade/bot_trade.env
```

- Bật service theo template đã có.

## 4) Lưu ý quan trọng

- Không commit hoặc zip `.env` có token thật.
- Bot sẽ **không in token** ra log (redacted).
