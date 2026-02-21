# VPS Setup (Ubuntu 20.04/22.04)

> Mục tiêu: chạy được bot (demo/paper) ổn định trên VPS bằng CPU.

## 0) Quan trọng về bảo mật (Telegram/API keys)

- **KHÔNG** đặt token trong source code.
- **KHÔNG** commit hoặc zip kèm file `.env` có token.
- Bot dùng env file **ngoài project**: `/etc/bot_trade/bot_trade.env` (chmod 600).

Nếu trước đây bạn đã từng đưa token vào `.env` trong repo/zip → **hãy rotate token** (BotFather) và cập nhật lại env file.

---

## 1) Upload / clone code

Khuyến nghị đặt project ở:

- `/opt/bot_trade`

Ví dụ:

```bash
sudo mkdir -p /opt/bot_trade
sudo chown -R $USER:$USER /opt/bot_trade
cd /opt/bot_trade
# upload zip và unzip hoặc git clone
```

## 2) Setup môi trường

Chạy script setup (idempotent):

```bash
cd /opt/bot_trade
sudo bash ./vps_setup.sh /opt/bot_trade
```

Script sẽ:
- Cài python3/venv + tools
- Tạo `.venv/` và cài `requirements.txt`
- Tạo thư mục `data/` và `logs/`
- Tạo env file **bên ngoài project**: `/etc/bot_trade/bot_trade.env`

## 3) Cấu hình env (Telegram optional)

Mở và chỉnh:

```bash
nano /etc/bot_trade/bot_trade.env
```

Ví dụ bật Telegram:

```bash
TELEGRAM_ENABLED=1
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## 4) Start bot

### Cách A (đơn giản, nohup)

```bash
cd /opt/bot_trade
bash ./vps_start.sh /opt/bot_trade
```

Xem log:
```bash
tail -f logs/system.log
```

Dừng bot:
```bash
bash ./vps_stop.sh
```

### Cách B (systemd - khuyến nghị)

```bash
cd /opt/bot_trade
sudo bash ./deploy/install_systemd.sh /opt/bot_trade
sudo systemctl enable bot_trade
sudo systemctl start bot_trade
journalctl -u bot_trade -f
```

> systemd sẽ load env từ `/etc/bot_trade/bot_trade.env`.

## 5) Chế độ chạy

Trong env file `/etc/bot_trade/bot_trade.env`:
- `BOT_MODE=demo`   : chạy mô phỏng end-to-end để test pipeline + tạo dataset.
- `BOT_MODE=paper` : chạy trên dữ liệu Futures thật nhưng **không đặt lệnh** (giả lập fill) — an toàn để test.
- `BOT_MODE=live`   : (chưa implement exchange execution).
