@echo off
chcp 65001 >NUL
setlocal EnableExtensions

echo ========================================
echo Windows 작업 스케줄러 등록
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
echo.

REM 관리자 권한 확인
net session >NUL 2>&1
if errorlevel 1 (
    echo [오류] 관리자 권한이 필요합니다!
    echo        이 파일을 마우스 우클릭 → "관리자 권한으로 실행"
    pause
    exit /b 1
)

echo [작업] 기존 작업 삭제 (있으면)...
schtasks /Delete /TN "%TASK_NAME%" /F >NUL 2>&1

echo [작업] 새 작업 등록 (1분마다 실행, 창 숨김)...
schtasks /Create /TN "%TASK_NAME%" /TR "wscript.exe \"%PROJECT_DIR%\run_hidden.vbs\" \"%BAT_FILE%\"" /SC MINUTE /MO 1 /F
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
