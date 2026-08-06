@echo off
setlocal
cd /d "%~dp0"
title AgentLoom Competition Evidence Replay

if not exist ".venv\Scripts\python.exe" (
    echo AgentLoom is not initialized.
    echo Run scripts\bootstrap.ps1 -Profile lite once, then reopen this file.
    pause
    exit /b 1
)

echo Starting the public, no-quota competition evidence replay...
echo Docker Desktop must be running and verified evidence must exist.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\competition-rollback-demo.ps1" -Mode replay -PublicOutput

if errorlevel 1 (
    echo.
    echo Replay could not start. Practice with START_DEMO.cmd first.
    pause
    exit /b 1
)

endlocal
