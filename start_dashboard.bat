@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
start "Stock Monitor Backend" cmd /k "python backend\main.py"
ping -n 4 127.0.0.1 >nul
start "" "%~dp0frontend\index.html"
