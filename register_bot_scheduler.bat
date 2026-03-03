@echo off
REM register_bot_scheduler.bat - Register "BiseoJaehyung_Bot" in Task Scheduler
REM Must be run as Administrator
REM
REM Creates a scheduled task that:
REM   1. Runs at user logon
REM   2. Repeats every 5 minutes (re-checks if daemon_wrapper died)
REM   3. Calls _restart_daemon.ps1 which starts daemon_wrapper.ps1
REM   4. daemon_wrapper.ps1 runs bot_brain.py single-shot every 10 seconds
REM

cd /d "%~dp0"

set TASK_NAME=BiseoJaehyung_Bot
set PS_SCRIPT=%~dp0_restart_daemon.ps1
set WORK_DIR=%~dp0

echo ============================================
echo   Task Scheduler Registration
echo   Task: %TASK_NAME%
echo ============================================
echo.

REM --- Check for admin privileges ---
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: This script must be run as Administrator!
    echo Right-click and select "Run as administrator"
    pause
    exit /b 1
)

REM --- Delete existing task if present ---
schtasks /Query /TN "%TASK_NAME%" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Removing existing task "%TASK_NAME%"...
    schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1
)

REM --- Create the XML task definition ---
REM Using XML for full control over triggers (logon + repetition)

set XML_FILE=%TEMP%\%TASK_NAME%_task.xml

(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Description^>BiseoJaehyung Bot - auto-restart daemon for bot_brain.py^</Description^>
echo   ^</RegistrationInfo^>
echo   ^<Triggers^>
echo     ^<LogonTrigger^>
echo       ^<Enabled^>true^</Enabled^>
echo       ^<Repetition^>
echo         ^<Interval^>PT5M^</Interval^>
echo         ^<StopAtDurationEnd^>false^</StopAtDurationEnd^>
echo       ^</Repetition^>
echo     ^</LogonTrigger^>
echo   ^</Triggers^>
echo   ^<Principals^>
echo     ^<Principal id="Author"^>
echo       ^<LogonType^>InteractiveToken^</LogonType^>
echo       ^<RunLevel^>HighestAvailable^</RunLevel^>
echo     ^</Principal^>
echo   ^</Principals^>
echo   ^<Settings^>
echo     ^<MultipleInstancesPolicy^>IgnoreNew^</MultipleInstancesPolicy^>
echo     ^<DisallowStartIfOnBatteries^>false^</DisallowStartIfOnBatteries^>
echo     ^<StopIfGoingOnBatteries^>false^</StopIfGoingOnBatteries^>
echo     ^<AllowHardTerminate^>true^</AllowHardTerminate^>
echo     ^<StartWhenAvailable^>true^</StartWhenAvailable^>
echo     ^<RunOnlyIfNetworkAvailable^>false^</RunOnlyIfNetworkAvailable^>
echo     ^<IdleSettings^>
echo       ^<StopOnIdleEnd^>false^</StopOnIdleEnd^>
echo       ^<RestartOnIdle^>false^</RestartOnIdle^>
echo     ^</IdleSettings^>
echo     ^<AllowStartOnDemand^>true^</AllowStartOnDemand^>
echo     ^<Enabled^>true^</Enabled^>
echo     ^<Hidden^>false^</Hidden^>
echo     ^<ExecutionTimeLimit^>PT0S^</ExecutionTimeLimit^>
echo     ^<Priority^>7^</Priority^>
echo   ^</Settings^>
echo   ^<Actions Context="Author"^>
echo     ^<Exec^>
echo       ^<Command^>powershell.exe^</Command^>
echo       ^<Arguments^>-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%PS_SCRIPT%"^</Arguments^>
echo       ^<WorkingDirectory^>%WORK_DIR%^</WorkingDirectory^>
echo     ^</Exec^>
echo   ^</Actions^>
echo ^</Task^>
) > "%XML_FILE%"

REM --- Register the task from XML ---
echo Registering task "%TASK_NAME%"...
schtasks /Create /TN "%TASK_NAME%" /XML "%XML_FILE%" /F

if %ERRORLEVEL% equ 0 (
    echo.
    echo SUCCESS! Task "%TASK_NAME%" registered.
    echo.
    echo Summary:
    echo   - Trigger: At user logon, repeats every 5 minutes
    echo   - Action: _restart_daemon.ps1 -^> daemon_wrapper.ps1 -^> bot_brain.py
    echo   - daemon_wrapper: 10초마다 bot_brain.py 단발 실행 (안정적)
    echo   - 5분마다 래퍼 생존 확인, 죽었으면 재시작
    echo.
    echo Useful commands:
    echo   schtasks /Query /TN "%TASK_NAME%" /FO LIST
    echo   schtasks /Run   /TN "%TASK_NAME%"
    echo   schtasks /Change /TN "%TASK_NAME%" /DISABLE
    echo   schtasks /Change /TN "%TASK_NAME%" /ENABLE
    echo   schtasks /Delete /TN "%TASK_NAME%" /F
    echo.
    echo To start immediately:
    echo   schtasks /Run /TN "%TASK_NAME%"
) else (
    echo.
    echo FAILED to register task. Check permissions.
)

REM --- Cleanup temp XML ---
del "%XML_FILE%" 2>nul

echo.
pause
