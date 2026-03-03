@echo off
setlocal EnableExtensions

REM ========================================
REM 비서최재형 데몬 중지
REM ========================================

set "BASE=%~dp0"

echo ===== %date% %time% =====
echo [DAEMON] Stopping 비서최재형 daemon...

REM 1. bot_brain 프로세스 찾기 및 종료
powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process -Filter \"name='python.exe' or name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'bot_brain' }; if ($procs) { $procs | ForEach-Object { Write-Output \"  Killing PID=$($_.ProcessId)\"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; exit 0 } else { Write-Output '  No bot_brain processes found'; exit 1 }" 2>NUL

REM 2. daemon wrapper 프로세스 종료
powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process -Filter \"name='python.exe' or name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'bot_brain_daemon' }; if ($procs) { $procs | ForEach-Object { Write-Output \"  Killing daemon PID=$($_.ProcessId)\"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }" 2>NUL

REM 3. Lock 파일 정리
if exist "%BASE%working.json" (
    del "%BASE%working.json" 2>NUL
    echo [INFO] Cleared working lock
)
if exist "%BASE%mybot_autoexecutor.lock" (
    del "%BASE%mybot_autoexecutor.lock" 2>NUL
    echo [INFO] Cleared executor lock
)
if exist "%BASE%daemon.pid" (
    del "%BASE%daemon.pid" 2>NUL
    echo [INFO] Cleared PID file
)

REM 4. 종료 확인
timeout /t 1 /nobreak >NUL
powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process -Filter \"name='python.exe' or name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'bot_brain' }; if ($procs) { exit 1 } else { exit 0 }" 2>NUL
if %ERRORLEVEL% EQU 0 (
    echo [OK] Daemon stopped successfully.
) else (
    echo [WARN] Some processes may still be running. Check manually.
)
