@echo off
rem 既定の起動。トレイ（タスクトレイ常駐）で立ち上げる。中身は image-reviewer-tray.cmd。
rem コンソール付きで立ち上げたいときは start-image-reviewer-console.cmd を使う。
call "%~dp0image-reviewer-tray.cmd"
exit /b 0
