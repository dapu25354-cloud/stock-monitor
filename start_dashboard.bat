@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
start "Stock Monitor Backend" cmd /k "python backend\main.py"
timeout /t 3 /nobreak >nul
start "" "%~dp0frontend\index.html"
