@echo off
setlocal
cd /d "%~dp0"
title AgentLoom Practice Demo

if not exist ".venv\Scripts\agentloom.exe" (
    echo AgentLoom is not initialized.
    echo Run scripts\bootstrap.ps1 -Profile lite once, then reopen this file.
    pause
    exit /b 1
)

echo Starting the automatic local AgentLoom demonstration...
echo Close the panel with Ctrl+C when finished.
echo.
".venv\Scripts\agentloom.exe" tui --auto-run

if errorlevel 1 (
    echo.
    echo The demo could not start. See docs\competition\DEMO-CARD.zh-CN.md.
    pause
    exit /b 1
)

endlocal
