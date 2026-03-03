@echo off
REM run_bot.bat - Manual launcher for debugging (shows console output)
REM Press Ctrl+C to stop

cd /d "%~dp0"
echo ============================================
echo   bot_brain.py - Manual Debug Launcher
echo   Press Ctrl+C to stop
echo ============================================
echo.
echo Starting bot_brain.py --loop ...
echo.

python -u bot_brain.py --loop

echo.
echo bot_brain.py exited with code %ERRORLEVEL%
pause
