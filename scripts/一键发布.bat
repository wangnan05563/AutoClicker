@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

REM ============================================================
REM AutoClicker publish launcher (pure ASCII, delegates to ps1)
REM This file is the double-click entry. All Chinese output is
REM produced by publish_package.ps1 (UTF-8 BOM).
REM
REM Preflight checks (mirrors AirMirror publish launcher):
REM   token -> git -> PowerShell -> Python -> gh -> delegate
REM Fails fast before invoking the pipeline when prerequisites
REM are missing. All detailed validation lives in the ps1.
REM
REM Usage:
REM   double-click this .bat             (auto build + tag + publish)
REM   this .bat -DryRun                  (validate only, no publish)
REM   set NO_PAUSE=1 & this .bat         (non-interactive / CI)
REM ============================================================

set "ROOT=%~dp0.."
set "ENV_FILE=%ROOT%\.env"
set "PUBLISH_PS=%~dp0publish_package.ps1"

REM --- 0. Load GH_TOKEN / GITHUB_TOKEN from .env (environment takes priority) ---
if not defined GH_TOKEN (
    for /f "tokens=1,* delims==" %%a in ('findstr /i "^GH_TOKEN=" "%ENV_FILE%" 2^>nul') do set "GH_TOKEN=%%b"
)
if not defined GITHUB_TOKEN (
    for /f "tokens=1,* delims==" %%a in ('findstr /i "^GITHUB_TOKEN=" "%ENV_FILE%" 2^>nul') do set "GITHUB_TOKEN=%%b"
)
if defined GH_TOKEN set "GH_TOKEN=!GH_TOKEN:"=!"
if defined GITHUB_TOKEN set "GITHUB_TOKEN=!GITHUB_TOKEN:"=!"

REM --- 1. git ---
where git >nul 2>nul
if errorlevel 1 (
    echo [FAIL] git not found. Install Git for Windows and add it to PATH.
    goto :fail
)
for /f "tokens=*" %%v in ('git --version 2^>nul') do echo [OK]   %%v

REM --- 2. PowerShell ---
where powershell >nul 2>nul
if errorlevel 1 (
    echo [FAIL] PowerShell not found; cannot run publish_package.ps1.
    goto :fail
)
echo [OK]   PowerShell available

REM --- 3. Python (AutoClicker is a Python project; deep deps validated in ps1) ---
where py >nul 2>nul
if not errorlevel 1 (
    for /f "tokens=*" %%v in ('py --version 2^>nul') do echo [OK]   Python %%v ^(py launcher^)
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [FAIL] Python not found ^(neither py nor python on PATH^). Install Python 3.10+.
        goto :fail
    ) else (
        for /f "tokens=*" %%v in ('python --version 2^>nul') do echo [OK]   Python %%v ^(PATH^)
    )
)

REM --- 4. gh CLI (optional: GitHub REST with token is the primary channel) ---
where gh >nul 2>nul
if not errorlevel 1 (
    echo [OK]   gh CLI available ^(optional publish channel^)
) else (
    echo [OK]   gh CLI not found; will publish via GitHub REST with token
)

REM --- 5. Token presence (value never echoed) ---
if defined GH_TOKEN (
    echo [OK]   GitHub token available ^(GH_TOKEN^)
) else if defined GITHUB_TOKEN (
    echo [OK]   GitHub token available ^(GITHUB_TOKEN^)
) else (
    echo [WARN] No token in env/.env; publish_package.ps1 will try ~/.git-credentials
)

REM --- 6. Delegate to the real pipeline (args passed through verbatim) ---
echo.
echo [INFO] powershell -NoProfile -ExecutionPolicy Bypass -File "%PUBLISH_PS%" %*
powershell -NoProfile -ExecutionPolicy Bypass -File "%PUBLISH_PS%" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [FAIL] Publish pipeline exited with code %RC%. See PowerShell output above.
    goto :fail
)

echo.
echo [DONE] Publish finished. Release URL is printed above by the pipeline.
if not defined NO_PAUSE pause >nul
exit /b 0

:fail
if not defined NO_PAUSE pause >nul
exit /b 1
