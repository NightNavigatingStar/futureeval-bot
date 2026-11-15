@echo off
REM Fall 2026 FutureEval bot - one-shot run, appends to logs\run.log
REM Called by Windows Task Scheduler every 20 minutes.
setlocal
cd /d "%~dp0"

REM Strip the sandbox/WorkBuddy proxy vars: they break pypi AND api.deepseek.com routing.
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set http_proxy=
set https_proxy=
set all_proxy=

if not exist "logs" mkdir "logs"
echo ===== %DATE% %TIME% start =====>> logs\run.log
python main.py >> logs\run.log 2>&1
echo ===== %DATE% %TIME% exit=%ERRORLEVEL% =====>> logs\run.log
endlocal
