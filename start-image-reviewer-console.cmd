@echo off
rem image-reviewer をコンソール付きで起動してブラウザを開く（いままでの起動。このファイルをダブルクリック）
rem 黒い窓にログが出る。窓を閉じるとサーバも止まる。常駐させたいときは start-image-reviewer.cmd（トレイ）。
cd /d "%~dp0"
set UV_CACHE_DIR=%~dp0.uv-cache
start "" cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:8790"
uv run --no-sync image-reviewer serve --port 8790
pause
