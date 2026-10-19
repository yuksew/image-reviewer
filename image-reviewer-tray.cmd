@echo off
rem image-reviewer のトレイ（タスクトレイ常駐）を起動する（このファイルをダブルクリック）
rem アイコンは画面の右下に出る。ダブルクリックでブラウザが開く。右クリックでメニュー。
rem うまくいかないときは <リポジトリ>\.tray\tray.log を見る（README の「動かす」）。
rem -ExecutionPolicy Bypass は必須（この環境では .ps1 が素では実行できない。docs/tray.md）。
setlocal
cd /d "%~dp0"
set "UV_CACHE_DIR=%~dp0.uv-cache"
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0tools\tray.ps1" -Port 8790
endlocal
exit /b 0
