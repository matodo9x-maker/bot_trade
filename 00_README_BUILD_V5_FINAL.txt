BUILD EXE V5 (WIN10) — FIX dist TRỐNG + FIX customtkinter
========================================================

Gói này cung cấp:
- 01_DIAG_BUILD_ENV.bat : kiểm tra đúng thư mục gốc (phải thấy control_panel_pro.py + apps\ + trade_ai\)
- build_exe_win10_clean_LOG.cmd : build EXE + ghi log đầy đủ vào build_exe.log
- control_panel_pro_win10.spec : spec đã collect_all("customtkinter") + darkdetect (script ưu tiên spec này)

Cách dùng:
1) Giải nén vào THƯ MỤC GỐC dự án (cùng cấp với control_panel_pro.py)
2) Chạy 01_DIAG_BUILD_ENV.bat -> phải báo OK
3) Chạy build_exe_win10_clean_LOG.cmd
4) Nếu fail: mở build_exe.log và gửi 30 dòng cuối

Output mong đợi:
- dist\control_panel_pro\control_panel_pro.exe (onedir, kèm _internal\)
