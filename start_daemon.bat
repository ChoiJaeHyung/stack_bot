@echo off
setlocal EnableExtensions

REM ========================================
REM 비서최재형 데몬 시작
REM   - bot_brain.py를 백그라운드 데몬으로 실행
REM   - idle timeout 없이 영구 실행
REM   - 크래시 시 자동 재시작
REM ========================================

set "BASE=%~dp0"
set "LOG=%BASE%bot_brain.log"
set "PID_FILE=%BASE%daemon.pid"

echo ===== %date% %time% =====
echo [DAEMON] Starting 비서최재형 daemon...

REM 1. 이미 실행 중인지 확인
powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -match 'bot_brain.*--daemon' }; if ($procs) { $procs | ForEach-Object { Write-Output \"  PID=$($_.ProcessId)\" }; exit 0 } else { exit 1 }" 2>NUL
if %ERRORLEVEL% EQU 0 (
    echo [WARN] Daemon is already running! Use stop_daemon.bat first.
    exit /b 1
)

REM 2. 잔여 lock 파일 정리
if exist "%BASE%mybot_autoexecutor.lock" (
    del "%BASE%mybot_autoexecutor.lock" 2>NUL
    echo [INFO] Cleared stale executor lock
)

REM 3. 데몬 시작 (백그라운드, 크래시 시 자동 재시작)
pushd "%BASE%" >NUL 2>&1

echo [INFO] Starting: pythonw bot_brain.py --daemon
echo [INFO] Log: %LOG%

REM pythonw 사용 (콘솔 창 없이 백그라운드 실행)
REM pythonw가 없으면 start /b python 사용
where pythonw >NUL 2>&1
if %ERRORLEVEL% EQU 0 (
    start "" pythonw "%BASE%bot_brain_daemon.py"
) else (
    start "" /b python "%BASE%bot_brain_daemon.py"
)

popd >NUL 2>&1

REM 4. 시작 확인 (2초 대기)
timeout /t 2 /nobreak >NUL

powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process -Filter \"name='python.exe' or name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'bot_brain' }; if ($procs) { $procs | ForEach-Object { Write-Output \"  PID=$($_.ProcessId)\" }; exit 0 } else { exit 1 }" 2>NUL
if %ERRORLEVEL% EQU 0 (
    echo [OK] Daemon started successfully!
) else (
    echo [ERROR] Daemon failed to start. Check %LOG%
)
