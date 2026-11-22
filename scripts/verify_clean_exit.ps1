param(
    [string]$ExePath = (Join-Path $PSScriptRoot '..\release\dist\AutoClicker\AutoClicker.exe'),
    [int]$StartupTimeoutSeconds = 180,
    [int]$ExitTimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path $ExePath).Path
$tempHome = Join-Path $env:TEMP ("autoclicker_exit_test_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tempHome | Out-Null

# 隔离配置：不自动点击、不保活、关闭窗口即退出
$baseConfigPath = Join-Path $env:USERPROFILE '.auto_clicker_config_py3.json'
if (Test-Path $baseConfigPath) {
    $config = Get-Content $baseConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
    $config = [pscustomobject]@{
        interval_seconds = 60
        auto_start = $false
        prevent_sleep = $false
        close_to_tray = $false
        mouse_move_only = $false
        click_limit = 0
        duration_limit = 0
        failsafe_enabled = $false
        startup_countdown = 0
        theme_mode = 'light'
        config_version = 2
        profiles = @{}
        current_profile = $null
        multi_points = @()
        schedule = [pscustomobject]@{ enabled = $false; start_at = '09:00'; stop_after_min = 0; weekdays = @(1, 2, 3, 4, 5) }
        onboarding_done = $true
        onboarding_template = 'safe'
    }
}
$config.auto_start = $false
$config.prevent_sleep = $false
$config.close_to_tray = $false
$config.mouse_move_only = $false
$config.failsafe_enabled = $false
$config.startup_countdown = 0
$config.interval_seconds = 60
# 隔离配置已视为完成首启，避免 FR-01 向导抢走主窗口标题，干扰启动检测
if ($config.PSObject.Properties.Name -contains 'onboarding_done') {
    $config.onboarding_done = $true
} else {
    $config | Add-Member -NotePropertyName onboarding_done -NotePropertyValue $true
}
$config | ConvertTo-Json -Depth 20 | Set-Content (Join-Path $tempHome '.auto_clicker_config_py3.json') -Encoding UTF8

$beforeProcessIds = @(Get-Process AutoClicker -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$beforeWarnings = @(Get-Process AutoClicker -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -eq 'Warning' }).Count
$beforeTemp = @(Get-ChildItem $env:TEMP -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty Name)

$oldProfile = $env:USERPROFILE
$oldTitle = $env:AUTOCLICKER_WINDOW_TITLE
$oldMutex = $env:AUTOCLICKER_MUTEX_NAME
$testTitle = "AutoClicker ExitTest " + [guid]::NewGuid().ToString('N')
$testMutex = "AutoClicker_ExitTest_Mutex_" + [guid]::NewGuid().ToString('N')
try {
    $env:USERPROFILE = $tempHome
    $env:AUTOCLICKER_WINDOW_TITLE = $testTitle
    $env:AUTOCLICKER_MUTEX_NAME = $testMutex
    $launcher = Start-Process -FilePath $exe -PassThru
} finally {
    $env:USERPROFILE = $oldProfile
    $env:AUTOCLICKER_WINDOW_TITLE = $oldTitle
    $env:AUTOCLICKER_MUTEX_NAME = $oldMutex
}

$gui = $null
$startupWatch = [System.Diagnostics.Stopwatch]::StartNew()
$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 300
    # onedir 产物只有一个进程；直接按 PID 取，避免 Get-Process 全量枚举
    # 在杀软/系统负载高时被拖慢，导致启动耗时统计严重失真。
    $gui = Get-Process -Id $launcher.Id -ErrorAction SilentlyContinue
    if ($gui -and $gui.MainWindowTitle -eq $testTitle) { break }
    $gui = $null
}
$startupWatch.Stop()

if (-not $gui) {
    Write-Error "启动超时：${StartupTimeoutSeconds}s 内未出现主窗口（launcher PID $($launcher.Id)）。"
}

Write-Host "GUI PID=$($gui.Id) title=$($gui.MainWindowTitle)"
Write-Host ("启动耗时: {0:F2}s" -f $startupWatch.Elapsed.TotalSeconds)

# 发送 WM_CLOSE；close_to_tray=false 时应走 exit_application 完全退出
& taskkill /PID $gui.Id 2>&1 | Out-Host
$exitDeadline = (Get-Date).AddSeconds($ExitTimeoutSeconds)
while ((Get-Date) -lt $exitDeadline) {
    Start-Sleep -Milliseconds 500
    if (-not (Get-Process -Id $gui.Id -ErrorAction SilentlyContinue)) { break }
}
if (Get-Process -Id $gui.Id -ErrorAction SilentlyContinue) {
    Write-Error "进程在 ${ExitTimeoutSeconds}s 内未退出（PID $($gui.Id)）。"
}

Start-Sleep -Seconds 3
$afterWarnings = @(Get-Process AutoClicker -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -eq 'Warning' }).Count
$afterTemp = @(Get-ChildItem $env:TEMP -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty Name)
$newTemp = @($afterTemp | Where-Object { $beforeTemp -notcontains $_ })

# PyInstaller 父进程清理可能滞后于子进程退出，给 15s 宽限，但最终必须消失
$cleanupDeadline = (Get-Date).AddSeconds(15)
while ($newTemp.Count -gt 0 -and (Get-Date) -lt $cleanupDeadline) {
    Start-Sleep -Seconds 1
    $afterTemp = @(Get-ChildItem $env:TEMP -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Name)
    $newTemp = @($afterTemp | Where-Object { $beforeTemp -notcontains $_ })
}

$failed = $false
if ($afterWarnings -gt $beforeWarnings) {
    Write-Host "FAIL: 检测到新的 PyInstaller Warning 弹窗。" -ForegroundColor Red
    $failed = $true
}
if ($newTemp.Count -gt 0) {
    Write-Host "FAIL: 退出后新增未清理的 _MEI 目录：$($newTemp -join ', ')" -ForegroundColor Red
    $failed = $true
}

Remove-Item $tempHome -Recurse -Force -ErrorAction SilentlyContinue
if ($failed) { exit 1 }
Write-Host "PASS: 正常退出，无 Warning 弹窗，无新增 _MEI 残留。" -ForegroundColor Green
exit 0
