@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo   脚本执行出错，请检查上方错误信息。
)
pause
