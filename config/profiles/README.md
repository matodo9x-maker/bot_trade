# Profiles

Các file `.env` trong thư mục này **không chứa secrets** (API keys / Telegram token).
Chúng chỉ là preset cấu hình nhanh cho bot.

Cách dùng:
- Trên VPS: `bash ./vps_panel.sh apply-profile demo`
- Sau đó sửa `/etc/bot_trade/bot_trade.env` để thêm API keys, TELEGRAM_BOT_TOKEN/CHAT_ID nếu cần.

Lưu ý:
- BOT_MODE=live yêu cầu `LIVE_CONFIRM=1` mới chạy được.

Gợi ý:
- `paper_auto_3symbols.env`: Paper mode + auto chọn 1–3 symbol theo thanh khoản/biến động/correlation.
