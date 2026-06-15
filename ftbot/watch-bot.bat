@echo off
rem Auto-updating launch: run the ClaudeBreakout paper bot and automatically
rem redeploy it whenever a new commit lands on main that touches ftbot/.
rem Stop everything with Ctrl+C in the window.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0watch-bot.ps1"
pause
