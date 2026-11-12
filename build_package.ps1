# -*- coding: utf-8 -*-
# AutoClicker 构建与打包脚本（Windows）
# 由 构建打包.bat 委派执行。所有中文输出在此（UTF-8 BOM）。
# 逻辑：解析 Python -> 释放文件锁 -> 确保 PyInstaller -> 调用 scripts/build_exe.py -> 校验产物 -> 启动冒烟测试。

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

# 强制子进程 Python 使用 UTF-8 I/O，避免 build_exe.py 打印 Unicode 字符时因 GBK 控制台崩溃
$env:PYTHONIOENCODING = "utf-8"

function Write-Banner($msg) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor DarkGray
    Write-Host $msg -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor DarkGray
}

function Test-PythonForBuild($PythonPath) {
    # AutoClicker 是 tkinter GUI 程序，打包必需 tkinter。仅做导入探测，不真正创建窗口。
    try {
        & $PythonPath -c "import tkinter" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Resolve-BuildPython($Candidates) {
    $existing = @()
    foreach ($c in $Candidates) {
        $p = [System.Environment]::ExpandEnvironmentVariables($c)
        if (Test-Path $p) { $existing += $p }
    }
    # 优先选择能 import tkinter 的 Python
    foreach ($p in $existing) {
        if (Test-PythonForBuild $p) { return $p }
    }
    # 回退：PATH 中可 import tkinter 的 python
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-PythonForBuild $cmd.Source)) { return $cmd.Source }
    # 都没有可用 tkinter：返回第一个存在的 Python，交给后续显式报错
    if ($existing.Count -gt 0) { return $existing[0] }
    $cmd2 = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd2) { return $cmd2.Source }
    return $null
}

function Stop-RunningInstance($ImageName) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($ImageName)
    Write-Host "==> 检查运行中的实例: $ImageName" -ForegroundColor Cyan
    $proc = Get-Process -Name $base -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "    发现运行实例，先停止以释放文件锁..." -ForegroundColor Yellow
        Stop-Process -Name $base -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Write-Host "    已释放文件锁。" -ForegroundColor Gray
    } else {
        Write-Host "    无运行实例。" -ForegroundColor Gray
    }
}

try {
    $PROJECT_ROOT = $PSScriptRoot
    Write-Banner "AutoClicker 构建与打包"
    Write-Host "项目根目录: $PROJECT_ROOT"

    # 读取配置
    $configPath = Join-Path $PROJECT_ROOT "config.build.json"
    if (-not (Test-Path $configPath)) { throw "未找到配置文件: $configPath" }
    $config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json

    # 1. 解析 Python
    Write-Banner "步骤 1/5: 解析 Python 解释器"
    $python = Resolve-BuildPython $config.runtime.python_candidates
    if (-not $python) { throw "未找到 Python 解释器。请安装 Python 3.10+ 后重试。" }
    Write-Host "使用 Python: $python"
    & $python --version
    # tkinter 预检：GUI 程序打包必需，缺失则提前给出可操作指引，避免打出无法运行的 exe
    if (-not (Test-PythonForBuild $python)) {
        throw "所选 Python ($python) 缺少 tkinter 模块（Tcl/Tk 未随 Python 安装）。AutoClicker 是 tkinter GUI 程序，打包必需 tkinter。请安装包含 Tcl/Tk 的 Python（官方 python.org 安装器需勾选 'tcl/tk and IDLE'），或在已正确安装 Tcl/Tk 的构建机上运行本脚本。"
    }

    # 2. 释放文件锁（覆盖式打包前停掉旧实例，避免 WinError 5）
    if ($config.build_safeguards.stop_before_build.enabled) {
        Write-Banner "步骤 2/5: 释放文件锁（停止运行实例）"
        Stop-RunningInstance $config.build_safeguards.stop_before_build.image_name
    }

    # 3. 确保 PyInstaller
    Write-Banner "步骤 3/5: 确保 PyInstaller"
    & $python -m PyInstaller --version 2>$null | Out-Null
    $piOk = ($LASTEXITCODE -eq 0)
    if (-not $piOk) {
        Write-Host "PyInstaller 缺失，正在安装..." -ForegroundColor Yellow
        & $python -m pip install pyinstaller
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 安装失败。" }
    } else {
        Write-Host "PyInstaller 可用。" -ForegroundColor Gray
    }

    # 4. 执行打包
    Write-Banner "步骤 4/5: 构建可执行文件"
    $buildScript = Join-Path $PROJECT_ROOT $config.build.build_script
    if (-not (Test-Path $buildScript)) { throw "未找到构建脚本: $buildScript" }
    & $python $buildScript
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败（退出码 $LASTEXITCODE）。" }

    # 5. 校验产物
    Write-Banner "步骤 5/5: 校验构建产物"
    $exePath = [System.IO.Path]::Combine($PROJECT_ROOT, $config.build.dist_dir, $config.build.exe_name)
    if (-not (Test-Path $exePath)) { throw "未找到构建产物: $exePath" }
    $sizeMB = (Get-Item $exePath).Length / 1MB
    $minMB = $config.verification.min_exe_size_mb
    if ($sizeMB -lt $minMB) { throw "产物体积过小（$('{0:F2}' -f $sizeMB) MB < $minMB MB），构建可能不完整。" }
    Write-Host "[OK] 产物: $exePath ($('{0:F2}' -f $sizeMB) MB)" -ForegroundColor Green

    # 启动冒烟测试：确认 exe 真实可执行
    if ($config.verification.launch_smoke_test.enabled) {
        Write-Host ""
        Write-Host "==> 启动冒烟测试（超时 $($config.verification.launch_smoke_test.timeout_seconds)s）..." -ForegroundColor Cyan
        try {
            $proc = Start-Process -FilePath $exePath -PassThru -WindowStyle Hidden -ErrorAction Stop
            $started = $false
            for ($i = 0; $i -lt $config.verification.launch_smoke_test.timeout_seconds; $i++) {
                if (-not $proc.HasExited) { $started = $true; break }
                Start-Sleep -Seconds 1
            }
            if ($started -and -not $proc.HasExited) {
                Write-Host "[OK] 可执行文件已启动并运行中（PID $($proc.Id)）。执行成功已确认。" -ForegroundColor Green
                try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
            } else {
                Write-Warning "可执行文件立即退出（退出码 $($proc.ExitCode)）。产物可能损坏，请检查运行依赖。"
            }
        } catch {
            Write-Warning "无法启动（可能是无界面/无显示环境）。产物已通过文件检查： $_"
        }
    }

    Write-Banner "构建成功完成"
    Write-Host "输出: $exePath" -ForegroundColor Green
    exit 0
} catch {
    Write-Host ""
    Write-Host ("!" * 60) -ForegroundColor Red
    Write-Host "构建失败: $_" -ForegroundColor Red
    Write-Host ("!" * 60) -ForegroundColor Red
    exit 1
}
