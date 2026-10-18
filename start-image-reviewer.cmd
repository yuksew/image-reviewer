@echo off
rem image-reviewer を起動してブラウザを開く（このファイルをダブルクリック）
cd /d "%~dp0"
set UV_CACHE_DIR=%~dp0.uv-cache
start "" cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:8790"
uv run --no-sync image-reviewer serve --port 8790
pause