@echo off
chcp 65001 >nul
cd /d "%~dp0"
git rm --cached -q fh-monitor.zip >nul 2>nul
git add -A
git commit -m "update"
git pull --rebase -q
git push
echo.
echo   Оновлено на GitHub.
pause
