@echo off
chcp 65001 >nul
cd /d "%~dp0"
git init -b main
git add .
git commit -m "FH Monitor: AI-моніторинг замовлень Freelancehunt"
git remote remove origin >nul 2>nul
git remote add origin https://github.com/Maksopinto/fh-monitor.git
git push -u origin main
echo.
echo   Готово, якщо вище немає помилок.
pause
