@echo off
chcp 65001 >NUL
setlocal EnableExtensions

echo ========================================
echo Windows 작업 스케줄러 등록 (포그라운드 모드 - GUI 표시 가능)
echo ========================================
echo.

REM 현재 폴더 경로 자동 감지
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "BAT_FILE=%PROJECT_DIR%\mybot_autoexecutor.bat"

REM 폴더명 추출 (멀티 봇 지원!)
for %%I in ("%PROJECT_DIR%") do set "FOLDER_NAME=%%~nxI"

REM 작업 이름 동적 생성 (폴더명 기반)
set "TASK_NAME=Claude_AutoBot_%FOLDER_NAME%"

echo 프로젝트 경로: %PROJECT_DIR%
echo 폴더 이름:     %FOLDER_NAME%
echo 작업 이름:     %TASK_NAME%
echo 실행 파일:     %BAT_FILE%
echo 모드:          포그라운드 (GUI 표시 가능 - Chrome, Playwright 등)
echo.

REM 관리자 권한 확인
net session >NUL 2>&1
if errorlevel 1 (
    echo [오류] 관리자 권한이 필요합니다!
    echo        이 파일을 마우스 우클릭 → "관리자 권한으로 실행"
    pause
    exit /b 1
)

REM 현재 사용자 계정 가져오기
for /f "tokens=*" %%u in ('whoami') do set "CURRENT_USER=%%u"
echo 실행 사용자:   %CURRENT_USER%
echo.

echo [작업] 기존 작업 삭제 (있으면)...
schtasks /Delete /TN "%TASK_NAME%" /F >NUL 2>&1

echo [작업] 새 작업 등록 (1분마다 실행, 포그라운드 모드)...
REM /IT: 인터랙티브 모드 (GUI 표시 가능)
REM /RL HIGHEST: 최고 권한으로 실행
REM /RU %CURRENT_USER%: 현재 사용자로 실행 (시스템 계정 아님!)
schtasks /Create /TN "%TASK_NAME%" /TR "\"%BAT_FILE%\"" /SC MINUTE /MO 1 /RL HIGHEST /IT /RU "%CURRENT_USER%" /F
if errorlevel 1 (
    echo [오류] 작업 등록 실패!
    pause
    exit /b 1
)

echo.
echo ========================================
echo ✅ 작업 스케줄러 등록 완료!
echo ========================================
echo.
echo 작업 이름: %TASK_NAME%
echo 실행 주기: 1분마다
echo 실행 파일: %BAT_FILE%
echo 실행 모드: 포그라운드 (GUI 표시 가능)
echo 실행 계정: %CURRENT_USER%
echo.
echo ⚠️  주의사항:
echo   - 포그라운드 모드는 사용자가 로그인되어 있을 때만 작동합니다
echo   - Chrome, Playwright 등 GUI 프로그램을 실행할 수 있습니다
echo   - 백그라운드 모드가 필요하면 "register_scheduler(백그라운드).bat"를 사용하세요
echo.
echo 작업 확인:
echo   schtasks /Query /TN "%TASK_NAME%" /FO LIST
echo.
echo 작업 비활성화:
echo   schtasks /Change /TN "%TASK_NAME%" /DISABLE
echo.
echo 작업 활성화:
echo   schtasks /Change /TN "%TASK_NAME%" /ENABLE
echo.
echo 작업 삭제:
echo   schtasks /Delete /TN "%TASK_NAME%" /F
echo.
pause
