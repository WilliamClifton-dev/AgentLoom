@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
set "HEALTH=artifacts\agentteams\health.json"
set "RUN=artifacts\benchmarks\task24\task24-governed-20260815-p204013\severity-normalization\live\run-evidence.json"
set "VERIFIED=artifacts\benchmarks\task24\task24-governed-20260815-p204013\severity-normalization\verified\artifacts\live-repair-evidence.json"

echo AgentLoom Task 24 MiniMax evidence replay
echo ==========================================
echo This command validates fixed evidence. It does not call a model.
echo.

if not exist "%PYTHON%" goto :missing_python
if not exist "%HEALTH%" goto :missing_health
if not exist "%RUN%" goto :missing_run
if not exist "%VERIFIED%" goto :missing_verified

echo [1/2] Validating the bound evidence chain...
"%PYTHON%" -m agentloom.cli inspect-live ^
  --health-evidence "%HEALTH%" ^
  --run-evidence "%RUN%" ^
  --verified-evidence "%VERIFIED%" ^
  --public-output

if errorlevel 1 goto :validation_failed

echo.
echo Evidence validation passed.
echo Press any key to open the read-only MiniMax-M2.5 TUI replay.
pause >nul

echo [2/2] Opening TUI...
"%PYTHON%" -m agentloom.cli tui ^
  --health-evidence "%HEALTH%" ^
  --run-evidence "%RUN%" ^
  --verified-evidence "%VERIFIED%" ^
  --public-output
goto :end

:missing_python
echo ERROR: Missing Python environment: %PYTHON%
goto :failed

:missing_health
echo ERROR: Missing health evidence: %HEALTH%
goto :failed

:missing_run
echo ERROR: Missing run evidence: %RUN%
goto :failed

:missing_verified
echo ERROR: Missing verified evidence: %VERIFIED%
goto :failed

:validation_failed
echo.
echo ERROR: Evidence validation failed. The TUI was not opened.
goto :failed

:failed
echo.
pause
exit /b 1

:end
endlocal
