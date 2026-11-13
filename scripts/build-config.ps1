# -*- coding: utf-8 -*-
# 共享构建配置加载器（UTF-8 BOM），由 build_package.ps1 / publish_package.ps1 点源引入。
# 主配置 config.build.json 入库且平台无关；本地覆盖 config.build.local.json 被 gitignore。
# 合并规则：顶层分段按键合并，两侧同为对象时递归按键合并；数组与标量以本地覆盖为准。

function Merge-BuildConfigSection($Base, $Override) {
    $result = @{}
    foreach ($prop in $Base.PSObject.Properties) { $result[$prop.Name] = $prop.Value }
    foreach ($prop in $Override.PSObject.Properties) {
        $name = $prop.Name
        $baseVal = $result[$name]
        if ($null -ne $baseVal -and $baseVal -is [PSCustomObject] -and $prop.Value -is [PSCustomObject]) {
            $result[$name] = Merge-BuildConfigSection $baseVal $prop.Value
        } else {
            $result[$name] = $prop.Value
        }
    }
    return [PSCustomObject]$result
}

function Get-BuildConfig($ScriptDir) {
    $mainPath = Join-Path $ScriptDir "config.build.json"
    if (-not (Test-Path $mainPath)) { throw "未找到主配置文件: $mainPath" }
    $cfg = Get-Content $mainPath -Raw -Encoding UTF8 | ConvertFrom-Json

    $localPath = Join-Path $ScriptDir "config.build.local.json"
    if (Test-Path $localPath) {
        $override = Get-Content $localPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $cfg = Merge-BuildConfigSection $cfg $override
        Write-Host "已加载本地配置覆盖: $localPath" -ForegroundColor Gray
    }
    return $cfg
}
