BUILD EXE - GÓI DEBUG (khi dist trống)
====================================

Hiện tượng:
- Folder dist\ trống sau khi bạn chạy build.

Lý do thường gặp:
- Script build đã xóa dist rồi build bị fail, nên dist trống.
- Bạn chạy build ở sai thư mục (không phải thư mục gốc dự án).
- Thiếu file .spec / sai tên spec / thiếu control_panel_pro.py.
- PyInstaller lỗi nhưng cửa sổ CMD đóng quá nhanh nên bạn không thấy log.

Cách dùng:
1) Giải nén các file trong gói này vào THƯ MỤC GỐC dự án (nơi có control_panel_pro.py).
2) Double-click: 01_DIAG_BUILD_ENV.bat (để kiểm tra nhanh)
3) Double-click: build_exe_win10_clean_LOG.cmd (build + ghi log)
4) Mở file build_exe.log nếu vẫn fail.

Output mong đợi:
- dist\control_panel_pro\control_panel_pro.exe
