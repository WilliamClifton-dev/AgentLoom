@echo off
setlocal
cd /d "%~dp0"
title AgentLoom Task 24 MiniMax Evidence Replay

echo Redirecting to the canonical Task 24 MiniMax evidence replay...
echo.
call "%~dp0START_TASK24_MINIMAX_REPLAY.cmd"
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
