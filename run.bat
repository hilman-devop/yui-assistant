@echo off
cd /d %~dp0
echo Yui jalan — Ctrl+C dua kali untuk berhenti total.
:loop
.venv\Scripts\python.exe -u main.py
echo.
echo Yui berhenti (kode %errorlevel%) — restart dalam 3 detik... (Ctrl+C sekarang untuk berhenti)
timeout /t 3 >nul
goto loop
