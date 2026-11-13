# -*- coding: utf-8 -*-
# 项目构建与打包脚本（Windows，完全配置驱动）
# 由 构建打包.bat 委派执行。所有中文输出在此（UTF-8 BOM）。
# 逻辑：解析 Python -> 释放文件锁 -> 确保 PyInstaller -> 调用构建脚本 -> 校验产物 -> 启动冒烟测试。

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot "build-config.ps1")

function Write-Banner($msg) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor DarkGray
    Write-Host $msg -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor DarkGray
}

function Test-PythonForBuild($PythonPath, $RequiredImports) {
    # 按配置探测必需模块是否可导入（GUI 程序通常要求 tkinter），仅做导入，不创建窗口。
    try {
        $code = ($RequiredImports | ForEach-Object { "import $_" }) -join "; "
        & $PythonPath -c $code 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Resolve-BuildPython($Candidates, $RequiredImports) {
    $existing = @()
    foreach ($c in $Candidates) {
        $p = [System.Environment]::ExpandEnvironmentVariables($c)
        if (Test-Path $p) { $existing += $p }
    }
    # 优先选择满足全部必需模块的 Python
    foreach ($p in $existing) {
        if (Test-PythonForBuild $p $RequiredImports) { return $p }
    }
    # 回退：PATH 中满足必需模块的 python
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-PythonForBuild $cmd.Source $RequiredImports)) { return $cmd.Source }
    # 都不满足：返回第一个存在的 Python，交给后续显式报错
    if ($existing.Count -gt 0) { return $existing[0] }
    $cmd2 = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd2) { return $cmd2.Source }
    return $null
}

function Stop-RunningInstance($ImageName, $WaitSeconds) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($ImageName)
    Write-Host "==> 检查运行中的实例: $ImageName" -ForegroundColor Cyan
    $proc = Get-Process -Name $base -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "    发现运行实例，先停止以释放文件锁..." -ForegroundColor Yellow
        Stop-Process -Name $base -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds $WaitSeconds
        Write-Host "    已释放文件锁。" -ForegroundColor Gray
    } else {
        Write-Host "    无运行实例。" -ForegroundColor Gray
    }
}

try {
    # 本脚本位于 scripts/ 下，项目根目录为其父目录
    $PROJECT_ROOT = Split-Path $PSScriptRoot -Parent
    $config = Get-BuildConfig $PSScriptRoot
    $env:PYTHONIOENCODING = $config.runtime.python_io_encoding

    Write-Banner "$($config.project.name) 构建与打包"
    Write-Host "项目根目录: $PROJECT_ROOT"

    # 1. 解析 Python
    Write-Banner "步骤 1/5: 解析 Python 解释器"
    $required = $config.runtime.required_imports
    $python = Resolve-BuildPython $config.runtime.python_candidates $required
    $minVer = ($config.runtime.python_min_version -join ".")
    if (-not $python) { throw "未找到 Python 解释器。请安装 Python $minVer+ 后重试。" }
    Write-Host "使用 Python: $python"
    & $python --version
    if (-not (Test-PythonForBuild $python $required)) {
        throw "所选 Python ($python) 缺少必需模块: $($required -join ', ')。该程序为 GUI 应用，打包必需这些模块。请安装包含 Tcl/Tk 的 Python（官方 python.org 安装器需勾选 'tcl/tk and IDLE'），或在满足依赖的构建机上运行本脚本。"
    }

    # 2. 释放文件锁（覆盖式打包前停掉旧实例，避免 WinError 5）
    $guard = $config.build_safeguards.stop_before_build
    if ($guard.enabled) {
        Write-Banner "步骤 2/5: 释放文件锁（停止运行实例）"
        Stop-RunningInstance $guard.image_name $guard.wait_seconds
    }

    # 3. 确保 PyInstaller（配置值先取局部变量，避免参数模式下长属性链解析歧义）
    $pyiModule = $config.build.pyinstaller.module
    $pyiPackage = $config.build.pyinstaller.pip_package
    Write-Banner "步骤 3/5: 确保 $pyiModule"
    & $python -m $pyiModule --version 2>$null | Out-Null
    $piOk = ($LASTEXITCODE -eq 0)
    if (-not $piOk) {
        Write-Host "$pyiModule 缺失，正在安装..." -ForegroundColor Yellow
        & $python -m pip install $pyiPackage
        if ($LASTEXITCODE -ne 0) { throw "$pyiModule 安装失败。" }
    } else {
        Write-Host "$pyiModule 可用。" -ForegroundColor Gray
    }

    # 4. 执行打包
    Write-Banner "步骤 4/5: 构建可执行文件"
    $buildScript = Join-Path $PROJECT_ROOT $config.build.build_script
    if (-not (Test-Path $buildScript)) { throw "未找到构建脚本: $buildScript" }
    & $python $buildScript
    if ($LASTEXITCODE -ne 0) { throw "$pyiModule 构建失败（退出码 $LASTEXITCODE）。" }

    # 5. 校验产物
    Write-Banner "步骤 5/5: 校验构建产物"
    $exePath = [System.IO.Path]::Combine($PROJECT_ROOT, $config.build.dist_dir, $config.build.exe_name)
    if (-not (Test-Path $exePath)) { throw "未找到构建产物: $exePath" }
    $sizeMB = (Get-Item $exePath).Length / 1MB
    $minMB = $config.verification.min_exe_size_mb
    if ($sizeMB -lt $minMB) { throw "产物体积过小（$('{0:F2}' -f $sizeMB) MB < $minMB MB），构建可能不完整。" }
    Write-Host "[OK] 产物: $exePath ($('{0:F2}' -f $sizeMB) MB)" -ForegroundColor Green

    # 启动冒烟测试：确认 exe 真实可执行
    $smoke = $config.verification.launch_smoke_test
    if ($smoke.enabled) {
        Write-Host ""
        Write-Host "==> 启动冒烟测试（稳定期 $($smoke.stable_seconds)s / 超时 $($smoke.timeout_seconds)s）..." -ForegroundColor Cyan
        try {
            $proc = Start-Process -FilePath $exePath -PassThru -WindowStyle Hidden -ErrorAction Stop
            # 先等稳定期再判定：onefile 解包阶段进程必然存活，立即判断会把
            # "解包存活、随后崩溃"误判为成功（历史教训：pyautogui 缺失即如此）
            Start-Sleep -Seconds $smoke.stable_seconds
            if (-not $proc.HasExited) {
                Write-Host "[OK] 可执行文件稳定运行 $($smoke.stable_seconds)s（PID $($proc.Id)）。执行成功已确认。" -ForegroundColor Green
                try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
            } else {
                throw "可执行文件启动后立即退出（退出码 $($proc.ExitCode)）。产物可能缺依赖，请用 --console 诊断版查看报错。"
            }
        } catch {
            Write-Warning "启动冒烟测试未通过： $_"
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
