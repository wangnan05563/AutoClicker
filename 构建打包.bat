@echo off
setlocal
chcp 65001 >nul 2>&1

REM ============================================================
REM AutoClicker build launcher (pure ASCII, delegates to ps1)
REM This file is the double-click entry. All Chinese output is
REM produced by build_package.ps1 (UTF-8 BOM).
REM ============================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_package.ps1" %*
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
    echo.
    echo [BUILD OK] Build completed successfully.
) else (
    echo.
    echo [BUILD FAILED] Exit code %RC%.
)
echo Press any key to close...
pause >nul
exit /b %RC%
