# -*- coding: utf-8 -*-
# AutoClicker 一键发布脚本（Windows）
# 由 一键发布.bat 委派执行。所有中文输出在此（UTF-8 BOM）。
# 逻辑：确保构建产物存在（缺失/过期则先构建）-> 打版本化发布包(zip) -> 校验包内容。

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

try {
    # 本脚本位于 scripts/ 下，项目根目录为其父目录
    $PROJECT_ROOT = Split-Path $PSScriptRoot -Parent
    Write-Banner "AutoClicker 一键发布"
    Write-Host "项目根目录: $PROJECT_ROOT"

    # 读取配置（config.build.json 与本脚本同目录）
    $configPath = Join-Path $PSScriptRoot "config.build.json"
    if (-not (Test-Path $configPath)) { throw "未找到配置文件: $configPath" }
    $config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json

    $distDir = $config.build.dist_dir
    $exeName = $config.build.exe_name
    $exePath = [System.IO.Path]::Combine($PROJECT_ROOT, $distDir, $exeName)

    # 步骤 1：确保构建产物
    Write-Banner "步骤 1/4: 确保构建产物"
    $needBuild = $false
    if (-not (Test-Path $exePath)) {
        Write-Host "未找到产物 $exePath，需要先构建。" -ForegroundColor Yellow
        $needBuild = $true
    } else {
        # 源码（根目录 .py / .spec）比产物新则视为过期，需重建
        # 注意：Get-ChildItem 的 -Include 不带 -Recurse 时会被忽略（PS 陷阱），改用扩展名过滤
        $exeTime = (Get-Item $exePath).LastWriteTime
        $stale = $false
        Get-ChildItem -Path $PROJECT_ROOT -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in ".py", ".spec" } |
            ForEach-Object { if ($_.LastWriteTime -gt $exeTime) { $stale = $true } }
        if ($stale) {
            Write-Host "源码已更新，产物过期，需要先重新构建。" -ForegroundColor Yellow
            $needBuild = $true
        } else {
            Write-Host "产物已存在且为最新，跳过构建: $exePath" -ForegroundColor Gray
        }
    }

    if ($needBuild) {
        $buildPs1 = Join-Path $PSScriptRoot "build_package.ps1"
        if (-not (Test-Path $buildPs1)) { throw "未找到构建脚本: $buildPs1" }
        Write-Host "==> 调用构建脚本..." -ForegroundColor Cyan
        & $buildPs1
        if ($LASTEXITCODE -ne 0) { throw "构建失败（退出码 $LASTEXITCODE），无法继续发布。" }
        if (-not (Test-Path $exePath)) { throw "构建后仍未找到产物: $exePath" }
    }

    # 步骤 2：收集发布文件
    Write-Banner "步骤 2/4: 收集发布文件"
    $filesToPack = New-Object System.Collections.ArrayList
    [void]$filesToPack.Add((Resolve-Path $exePath).Path)
    foreach ($rel in $config.release.include) {
        $incPath = Join-Path $PROJECT_ROOT $rel
        if (Test-Path $incPath) {
            [void]$filesToPack.Add((Resolve-Path $incPath).Path)
            Write-Host "  包含: $rel" -ForegroundColor Gray
        } else {
            Write-Warning "  发布包含文件不存在，已跳过: $rel"
        }
    }
    if ($filesToPack.Count -eq 0) { throw "没有可打包的文件。" }

    # 步骤 3：生成版本化发布包
    Write-Banner "步骤 3/4: 生成发布包 (zip)"
    $ver = $config.release.version
    $arch = $config.release.arch
    $pkgName = $config.release.package_name -replace "\{version\}", $ver -replace "\{arch\}", $arch
    $outDir = Join-Path $PROJECT_ROOT $config.release.output_dir
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    $zipPath = Join-Path $outDir ($pkgName + ".zip")

    # 先删除旧包，避免 Compress-Archive 的"已存在"报错
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path $filesToPack -DestinationPath $zipPath -Force
    Write-Host "[OK] 发布包: $zipPath" -ForegroundColor Green

    # 步骤 4：校验发布包
    Write-Banner "步骤 4/4: 校验发布包"
    if (-not (Test-Path $zipPath)) { throw "发布包未生成: $zipPath" }
    $zipSizeMB = (Get-Item $zipPath).Length / 1MB
    # 校验包内必须包含 exe 且体积达标（用 ZipFile 读取，确定性优于 Shell COM 的 ExtendedProperty）
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $entry = $zip.Entries | Where-Object { $_.FullName -eq $exeName } | Select-Object -First 1
        if ($null -eq $entry) { throw "发布包内缺少 $exeName。" }
        $exeBytes = $entry.Length
        $minBytes = $config.verification.min_exe_size_mb * 1MB
        if ([double]$exeBytes -lt $minBytes) {
            throw "发布包内 $exeName 体积异常（$($exeBytes) 字节），打包可能不完整。"
        }
        Write-Host "[OK] 包内 $exeName 体积: $('{0:F2}' -f ([double]$exeBytes / 1MB)) MB" -ForegroundColor Green
        Write-Host "[OK] 包内条目: $($zip.Entries.Count) 个（$((($zip.Entries | ForEach-Object { $_.FullName }) -join ', ')))" -ForegroundColor Gray
    } finally {
        $zip.Dispose()
    }
    Write-Host "[OK] 发布包总大小: $('{0:F2}' -f $zipSizeMB) MB" -ForegroundColor Green

    Write-Banner "发布成功完成"
    Write-Host "产物 exe : $exePath" -ForegroundColor Green
    Write-Host "发布包  : $zipPath" -ForegroundColor Green
    Write-Host "内容    : $($filesToPack.Count) 个文件（含 $exeName + 文档）" -ForegroundColor Green
    exit 0
} catch {
    Write-Host ""
    Write-Host ("!" * 60) -ForegroundColor Red
    Write-Host "发布失败: $_" -ForegroundColor Red
    Write-Host ("!" * 60) -ForegroundColor Red
    exit 1
}
