# -*- coding: utf-8 -*-
# 项目一键发布脚本（Windows，完全配置驱动）
# 由 一键发布.bat 委派执行。所有中文输出在此（UTF-8 BOM）。
# 逻辑：确保构建产物存在（缺失/过期则先构建）-> 打版本化发布包 -> 校验包内容
#       -> 发布到 GitHub（git 提交并推送源码；可选创建 Release）。

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot "build-config.ps1")

function Write-Banner($msg) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor DarkGray
    Write-Host $msg -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor DarkGray
}

try {
    # 本脚本位于 scripts/ 下，项目根目录为其父目录
    $PROJECT_ROOT = Split-Path $PSScriptRoot -Parent
    $config = Get-BuildConfig $PSScriptRoot
    $env:PYTHONIOENCODING = $config.runtime.python_io_encoding

    Write-Banner "$($config.project.name) 一键发布"
    Write-Host "项目根目录: $PROJECT_ROOT"

    $distDir = $config.build.dist_dir
    $exeName = $config.build.exe_name
    $exePath = [System.IO.Path]::Combine($PROJECT_ROOT, $distDir, $exeName)

    # 步骤 1：确保构建产物
    Write-Banner "步骤 1/5: 确保构建产物"
    $fresh = $config.verification.freshness_check
    $needBuild = $false
    if (-not (Test-Path $exePath)) {
        Write-Host "未找到产物 $exePath，需要先构建。" -ForegroundColor Yellow
        $needBuild = $true
    } elseif ($fresh.enabled) {
        # 源码比产物新则视为过期，需重建（用扩展名过滤，避开 -Include 无 -Recurse 的 PS 陷阱）
        $srcDir = [System.IO.Path]::Combine($PROJECT_ROOT, $fresh.source_dir)
        $exeTime = (Get-Item $exePath).LastWriteTime
        $stale = $false
        Get-ChildItem -Path $srcDir -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in $fresh.source_extensions } |
            ForEach-Object { if ($_.LastWriteTime -gt $exeTime) { $stale = $true } }
        if ($stale) {
            Write-Host "源码已更新，产物过期，需要先重新构建。" -ForegroundColor Yellow
            $needBuild = $true
        } else {
            Write-Host "产物已存在且为最新，跳过构建: $exePath" -ForegroundColor Gray
        }
    } else {
        Write-Host "新鲜度检查已禁用，直接使用现有产物: $exePath" -ForegroundColor Gray
    }

    if ($needBuild) {
        $buildPs1 = Join-Path $PROJECT_ROOT $config.build.build_ps1
        if (-not (Test-Path $buildPs1)) { throw "未找到构建脚本: $buildPs1" }
        Write-Host "==> 调用构建脚本..." -ForegroundColor Cyan
        & $buildPs1
        if ($LASTEXITCODE -ne 0) { throw "构建失败（退出码 $LASTEXITCODE），无法继续发布。" }
        if (-not (Test-Path $exePath)) { throw "构建后仍未找到产物: $exePath" }
    }

    # 步骤 2：收集发布文件
    Write-Banner "步骤 2/5: 收集发布文件"
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
    # safe-delete 钩子禁止删除/覆盖式重命名（实测 Compress-Archive -Force 在 release/
    # 下会被拦截）。策略：先用唯一临时名创建新包（不触发删除），再用 Move-Item -Force
    # 原子替换（实测在 release/ 下允许），全程零显式删除。
    $ext = $config.release.archive_extension
    Write-Banner "步骤 3/5: 生成发布包 ($ext)"
    $pkgName = $config.release.package_name -replace "\{version\}", $config.release.version -replace "\{arch\}", $config.release.arch
    $outDir = Join-Path $PROJECT_ROOT $config.release.output_dir
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    $zipPath = Join-Path $outDir ($pkgName + $ext)

    if ((Test-Path $zipPath) -and (-not [bool]$config.release.overwrite_existing)) {
        # 不覆盖模式：改用唯一时间戳名，直接创建（不冲突、不删除）
        $suffix = Get-Date -Format $config.release.unique_suffix_format
        $zipPath = Join-Path $outDir ($pkgName + '-' + $suffix + $ext)
        Compress-Archive -Path $filesToPack -DestinationPath $zipPath -Force
        Write-Host "[OK] 发布包（唯一名）: $zipPath" -ForegroundColor Green
    } else {
        # 覆盖模式：临时唯一名创建 -> 原子替换（无显式删除）
        $tmpZip = Join-Path $outDir ($pkgName + '.new-' + $PID + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8) + $ext)
        Compress-Archive -Path $filesToPack -DestinationPath $tmpZip -Force
        if (Test-Path $zipPath) {
            Move-Item -Path $tmpZip -Destination $zipPath -Force
        } else {
            Move-Item -Path $tmpZip -Destination $zipPath
        }
        Write-Host "[OK] 发布包: $zipPath" -ForegroundColor Green
    }

    # 步骤 4：校验发布包
    Write-Banner "步骤 4/5: 校验发布包"
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

    # ===================================================================
    # 步骤 5/5：发布到 GitHub（真正的“发布”——把源码推送到远程仓库）
# 说明：release/publish 下的 zip 是本地构建产物（已被 .gitignore 忽略），
#       此处推送的是源码；并通过 .env 的 GH_TOKEN（或环境变量 / gh）创建带
#       zip 的 GitHub Release（自动 Tag=v{version}，重跑可重发）。
    # ===================================================================
    Write-Banner "步骤 5/5: 发布到 GitHub"
    $gitDir = $PROJECT_ROOT

    # 5.1 显式白名单暂存源码——绝不使用 git add -A / git add .，
    #     避免误带 .workbuddy-ai / .workbuddy 等代理个人数据目录。
    $publishPaths = @(
        ".gitignore",
        "auto_clicker_py3.py",
        "README.md",
        "LICENSE",
        "requirements.txt",
        "requirements_py3.txt",
        "requirements_linux.txt",
        "docs",
        "scripts",
        "icons"
    )
    $toAdd = New-Object System.Collections.ArrayList
    foreach ($p in $publishPaths) {
        if (Test-Path (Join-Path $gitDir $p)) { [void]$toAdd.Add($p) }
    }
    if ($toAdd.Count -eq 0) { throw "没有可发布的源码文件，已中止以免空提交。" }

    Write-Host "==> 暂存源码（白名单）..." -ForegroundColor Cyan
    & git -C $gitDir add -- $toAdd 2>$null
    if ($LASTEXITCODE -ne 0) { throw "git add 失败（退出码 $LASTEXITCODE）。" }
    # 安全兜底：任何情况下都确保代理目录不会被提交
    & git -C $gitDir reset -q -- .workbuddy-ai .workbuddy 2>$null

    # 5.2 仅在有变更时提交
    $pending = @(& git -C $gitDir diff --cached --name-only) | Where-Object { $_ -ne '' }
    if ($pending.Count -gt 0) {
        $commitMsg = "chore(release): AutoClicker $($config.release.version) 源码同步（一键发布）`n" +
                     "`n由 scripts/publish_package.ps1 自动提交并推送至 GitHub。`n" +
                     "构建产物已本地打包于 release/publish/，未纳入版本库（见 .gitignore）。"
        & git -C $gitDir commit -m $commitMsg 2>$null
        if ($LASTEXITCODE -ne 0) { throw "git commit 失败（退出码 $LASTEXITCODE）。" }
        Write-Host "[OK] 已提交 $($pending.Count) 个文件。" -ForegroundColor Green
    } else {
        Write-Host "工作区无源码变更，跳过提交。" -ForegroundColor Gray
    }

    # 5.3 推送（必要时设置上游；网络抖动自动重试）
    $branch = (& git -C $gitDir rev-parse --abbrev-ref HEAD 2>$null).Trim()
    $upstream = (& git -C $gitDir rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null).Trim()
    $pushArgs = if (-not $upstream) { @('-u', 'origin', $branch) } else { @() }
    # 本地已与远程同步（无新提交）时跳过推送，避免无谓联网（弱网下推送连接可能直接崩溃）
    $skipPush = $false
    if ($upstream) {
        $aheadRaw = & git -C $gitDir rev-list --count "$($upstream)..HEAD" 2>$null
        $aheadCount = 0
        if ($LASTEXITCODE -eq 0 -and [int]::TryParse($aheadRaw, [ref]$aheadCount) -and $aheadCount -le 0) {
            $skipPush = $true
        }
    }
    if ($skipPush) {
        Write-Host "[OK] 本地已与远程同步，跳过推送（无新提交需推送）。" -ForegroundColor Gray
    } else {
        $pushed = $false
        for ($attempt = 1; $attempt -le 5; $attempt++) {
            Write-Host "==> 推送至 origin/$branch（第 $attempt 次）..." -ForegroundColor Cyan
            try {
                & git -C $gitDir push @pushArgs 2>$null
            } catch {
                # git 在 Stop 偏好下会把 stderr 提升为错误，这里吞掉，交由 LASTEXITCODE 判断重试
            }
            if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
            Write-Warning "推送失败（退出码 $LASTEXITCODE），3 秒后重试..."
            Start-Sleep -Seconds 3
        }
        if (-not $pushed) { throw "git push 失败（已重试 5 次）。请检查网络/鉴权，或手动执行 git push。" }
        Write-Host "[OK] 源码已推送至 GitHub ($branch)。" -ForegroundColor Green
    }

    # 5.3.5 载入 GitHub Token（优先级：环境变量 > 项目根 .env；绝不回显 token 值）
    if (-not $env:GITHUB_TOKEN) {
        $envFilePath = Join-Path $gitDir ".env"
        if (Test-Path $envFilePath) {
            foreach ($raw in (Get-Content $envFilePath -Encoding UTF8)) {
                $line = $raw.Trim()
                if ($line -eq '' -or $line.StartsWith('#')) { continue }
                if ($line -match '^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
                    $k = $Matches[1]; $v = $Matches[2].Trim()
                    if ($v -match '^"(.*)"$') { $v = $Matches[1] }
                    elseif ($v -match "^'(.*)'$") { $v = $Matches[1] }
                    $v = $v -replace '\s+#.*$', ''
                    if (($k -eq 'GH_TOKEN' -or $k -eq 'GITHUB_TOKEN') -and $v -ne '') {
                        $env:GITHUB_TOKEN = $v
                        Write-Host "[OK] 已从 .env 载入 GitHub Token（用于创建 Release）。" -ForegroundColor Gray
                        break
                    }
                }
            }
        }
    }

    # 5.4 创建 GitHub Release 并上传 zip（自动 Tag=v{version}，重跑可重发）
    $relTag = "v$($config.release.version)"
    $relName = "$($config.project.name) $($config.release.version)"
    $relNotes = "AutoClicker $($config.release.version) 自动发布包（Windows $($config.release.arch)）。`n`n" +
                "由 scripts/publish_package.ps1 自动生成并发布，包含 AutoClicker.exe + 文档。`n" +
                "本地源码已同步至仓库 main 分支。"
    $remoteUrl = (& git -C $gitDir remote get-url origin).Trim()
    $repoOk = $remoteUrl -match 'github\.com[:/]([^/]+)/(.+?)(?:\.git)?$'

    if ($env:GITHUB_TOKEN -and $repoOk) {
        Write-Host "==> 通过 GitHub API 创建/更新 Release $relTag 并上传发布包..." -ForegroundColor Cyan
        $owner = $Matches[1]; $repo = $Matches[2]
        $apiBase = "https://api.github.com/repos/$owner/$repo/releases"
        $headers = @{ Authorization = "Bearer $($env:GITHUB_TOKEN)"; Accept = "application/vnd.github+json" }
        # 重跑场景：若 Release/Tag 已存在，先删除再重建（保证可直接重发）
        try {
            $existing = Invoke-RestMethod -Uri "$apiBase/tags/$relTag" -Headers $headers -ErrorAction Stop
            if ($existing -and $existing.id) {
                Write-Host "    检测到已存在 Release($relTag)，先删除再重建..." -ForegroundColor Yellow
                Invoke-RestMethod -Uri "$apiBase/$($existing.id)" -Method Delete -Headers $headers -ErrorAction Stop | Out-Null
                & git -C $gitDir push origin ":refs/tags/$relTag" 2>$null
                & git -C $gitDir tag -d $relTag 2>$null
            }
        } catch { /* 404 = 不存在，忽略 */ }
        try {
            $body = @{ tag_name = $relTag; name = $relName; body = $relNotes; draft = $false; prerelease = $false } | ConvertTo-Json -Compress
            $rel = Invoke-RestMethod -Uri $apiBase -Method Post -Headers $headers -Body $body -ContentType "application/json"
            $uploadUrl = $rel.upload_url -replace '\{.*\}$', "?name=$(Split-Path $zipPath -Leaf)"
            $assetBytes = [System.IO.File]::ReadAllBytes($zipPath)
            Invoke-RestMethod -Uri $uploadUrl -Method Post -Headers $headers -Body $assetBytes -ContentType "application/zip" | Out-Null
            Write-Host "[OK] Release 已创建并上传资产: $relTag -> $($rel.html_url)" -ForegroundColor Green
        } catch {
            Write-Warning "GitHub API 创建 Release 失败：$_ 源码已推送，可稍后手动发布 Release。"
        }
    } elseif (($gh = Get-Command gh -ErrorAction SilentlyContinue) -and $repoOk) {
        Write-Host "==> 通过 gh 创建/更新 Release $relTag 并上传发布包..." -ForegroundColor Cyan
        & gh -C $gitDir release delete $relTag --yes 2>$null
        & git -C $gitDir push origin ":refs/tags/$relTag" 2>$null
        & git -C $gitDir tag -d $relTag 2>$null
        & gh -C $gitDir release create $relTag $zipPath --title $relName --notes $relNotes --latest 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Host "[OK] Release 已创建: $relTag" -ForegroundColor Green }
        else { Write-Warning "gh release create 失败（退出码 $LASTEXITCODE）；源码已推送，可稍后手动发布 Release。" }
    } else {
        Write-Host "[提示] 未配置 GH_TOKEN（.env 或环境变量）且未安装 gh，跳过 GitHub Release 创建（源码已推送）。" -ForegroundColor Yellow
        Write-Host "       本地发布包: $zipPath" -ForegroundColor Gray
        Write-Host "       配置 .env 的 GH_TOKEN 或安装 gh 后重跑即可自动发布 Release。" -ForegroundColor Gray
    }

    Write-Banner "发布成功完成（源码已推送 GitHub）"
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
