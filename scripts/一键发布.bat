@echo off
setlocal
chcp 65001 >nul 2>&1

REM ============================================================
REM AutoClicker publish launcher (pure ASCII, delegates to ps1)
REM This file is the double-click entry. All Chinese output is
REM produced by the sibling publish script (UTF-8 BOM).
REM ============================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_package.ps1" %*
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
    echo.
    echo [PUBLISH OK] 已发布到 GitHub（源码已推送；本地包见 release/publish/）
) else (
    echo.
    echo [PUBLISH FAILED] Exit code %RC%.
)
echo Press any key to close...
pause >nul
exit /b %RC%
