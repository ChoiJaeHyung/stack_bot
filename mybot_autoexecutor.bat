@echo off
setlocal EnableExtensions

REM 이 배치 파일이 있는 폴더 (자동 감지)
set "BASE=%~dp0"
set "ROOT=%BASE%"
set "LOG=%BASE%claude_task.log"
set "LOCKFILE=%ROOT%\mybot_autoexecutor.lock"

echo ===== %date% %time% =====>> "%LOG%"
echo START CWD=%CD%>> "%LOG%"
echo ROOT=%ROOT%>> "%LOG%"

REM ========================================
REM 프로세스 중복 실행 방지
REM ========================================

REM 1. bot_brain.py 프로세스 확인 (실제 진행 중인지)
REM    Count python.exe processes whose CommandLine contains 'bot_brain'
powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -match 'bot_brain' }; if ($procs) { $procs | ForEach-Object { Write-Output \"  PID=$($_.ProcessId) CMD=$($_.CommandLine)\" }; exit 0 } else { exit 1 }" >> "%LOG%" 2>&1
if %ERRORLEVEL% EQU 1 goto PROCESS_NOT_FOUND

REM bot_brain 프로세스 발견 - 로그 갱신 시각 확인 (10분 초과 시 스탈)
powershell -NoProfile -Command "if (Test-Path '%ROOT%bot_brain.log') { if ((Get-Date) - (Get-Item '%ROOT%bot_brain.log').LastWriteTime -gt [TimeSpan]::FromMinutes(10)) { exit 1 } else { exit 0 } } else { exit 0 }" >NUL 2>&1
if %ERRORLEVEL% EQU 1 (
    echo [STALE] bot_brain idle ^>10min. Force-killing...>> "%LOG%"
    powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -match 'bot_brain' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >NUL 2>&1
    if exist "%LOCKFILE%" del "%LOCKFILE%" 2>NUL
    echo [STALE] Cleared stale state. Proceeding...>> "%LOG%"
    goto LOCK_OK
)
echo [BLOCKED] bot_brain already running. Skipping this invocation.>> "%LOG%"
echo.>> "%LOG%"
exit /b 98
:PROCESS_NOT_FOUND

REM 2. Lock 파일 확인 (프로세스 없는데 Lock 있으면 오류 중단 복구)
if not exist "%LOCKFILE%" goto LOCK_OK
echo [RECOVERY] Lock file exists but no process running - recovering.>> "%LOG%"
del "%LOCKFILE%" 2>NUL
echo [INFO] Stale lock removed.>> "%LOG%"
:LOCK_OK

REM 3. 빠른 메시지 확인 (새 메시지 없으면 bot_brain 실행 안 함)
echo [QUICK_CHECK] Checking for new messages...>> "%LOG%"
pushd "%ROOT%" >NUL 2>&1
python quick_check.py >> "%LOG%" 2>&1
set "CHECK_RESULT=%ERRORLEVEL%"
popd >NUL 2>&1

if %CHECK_RESULT% EQU 0 (
    echo [NO_MESSAGE] No new messages. Exiting.>> "%LOG%"
    echo.>> "%LOG%"
    exit /b 0
)

echo [NEW_MESSAGE] New messages found. Starting bot_brain...>> "%LOG%"

REM 4. Lock 파일 생성
echo %date% %time%> "%LOCKFILE%"
echo Lock file created: %LOCKFILE%>> "%LOG%"

REM 5. bot_brain.py 실행 (OpenAI API 기반, 루프 모드 - 5초마다 체크, 5분 idle 시 종료)
pushd "%ROOT%" >NUL 2>&1
echo [INFO] Running: python bot_brain.py --loop>> "%LOG%"
python bot_brain.py --loop >> "%LOG%" 2>&1
set "EC=%ERRORLEVEL%"
popd >NUL 2>&1

echo EXITCODE=%EC%>> "%LOG%"
echo.>> "%LOG%"

REM 6. Lock 파일 삭제
if exist "%LOCKFILE%" (
    del "%LOCKFILE%" 2>NUL
    echo Lock file deleted: %LOCKFILE%>> "%LOG%"
)

exit /b %EC%
