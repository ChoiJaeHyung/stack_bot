@echo off
chcp 65001 >NUL
setlocal EnableExtensions EnableDelayedExpansion

echo ========================================
echo 소놀봇 (mybot_ver2) 자동 설정
echo ========================================
echo.

REM 현재 폴더 경로 자동 감지
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

echo [1/4] 프로젝트 경로 확인
echo       %PROJECT_DIR%
echo.

REM Python 버전 확인
echo [2/4] Python 확인 중...
python --version >NUL 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다!
    echo        https://www.python.org/downloads/ 에서 Python을 설치해주세요.
    pause
    exit /b 1
)
python --version
echo.

REM Python 패키지 설치
echo [3/4] Python 패키지 설치 중...
pip install -r "%PROJECT_DIR%\requirements.txt"
if errorlevel 1 (
    echo [오류] 패키지 설치 실패!
    pause
    exit /b 1
)
echo       ✅ 패키지 설치 완료!
echo.

REM .env 파일 확인 및 생성
echo [4/4] .env 파일 확인 중...
if not exist "%PROJECT_DIR%\.env" (
    echo [설정] .env 파일이 없습니다. 생성합니다.
    echo.
    echo === 텔레그램 봇 설정 ===
    echo.

    set /p BOT_TOKEN="텔레그램 봇 토큰 입력 (BotFather에서 발급): "
    set /p USER_ID="허용할 사용자 ID 입력: "

    (
        echo TELEGRAM_BOT_TOKEN=!BOT_TOKEN!
        echo TELEGRAM_ALLOWED_USERS=!USER_ID!
        echo TELEGRAM_POLLING_INTERVAL=10
    ) > "%PROJECT_DIR%\.env"

    echo       ✅ .env 파일 생성 완료!
) else (
    echo       ✅ .env 파일 존재함
)
echo.

echo ========================================
echo 설치 완료!
echo ========================================
echo.
echo 다음 단계:
echo   1. Windows 작업 스케줄러 등록 (선택):
echo      run_register_scheduler.bat 실행
echo.
echo   2. 수동 테스트:
echo      python quick_check.py
echo.
echo   3. 텔레그램 봇 테스트:
echo      텔레그램에서 봇에게 메시지 보내기
echo.
pause
