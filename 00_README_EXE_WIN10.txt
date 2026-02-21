BUILD & RUN CONTROL_PANEL_PRO.EXE (Win10)
========================================

1) Double-click: build_exe_win10_clean.cmd
2) Run EXE at: dist\control_panel_pro\control_panel_pro.exe
   - ONEDIR: keep the whole folder, do NOT copy only the .exe.

If EXE error about missing DLL:
- Make sure you run from dist\control_panel_pro\ (with _internal folder)
- Install Microsoft Visual C++ Redistributable 2015-2022 (x64) on the VPS

If EXE error about missing module customtkinter:
- Re-run build_exe_win10_clean.cmd (it installs customtkinter into .build_venv)
