# 检查 AstrBot 上游是否已修复合并转发问题
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File .\check-upstream.ps1
# 依赖：已登录的 gh CLI（gh auth status 应显示已登录）
# 退出码：0 = 未修复；1 = 已修复；2 = 检查失败

$ErrorActionPreference = 'Stop'

$Repo = 'AstrBotDevs/AstrBot'
$Path = 'astrbot/core/utils/quoted_message/chain_parser.py'
$StateFile = Join-Path $PSScriptRoot '.last-check.json'

function Invoke-GhApi {
    param([string]$Endpoint)
    $out = gh api $Endpoint 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "gh api 调用失败: $out"
    }
    return ($out | Out-String)
}

try {
    $commits = @(Invoke-GhApi "repos/$Repo/commits?path=$Path&per_page=1" | ConvertFrom-Json)
    if ($commits.Count -eq 0) {
        throw '未取到提交记录'
    }
    $sha = $commits[0].sha
    $date = $commits[0].commit.author.date
    $msg = ($commits[0].commit.message -split "`n")[0]

    $fileJson = Invoke-GhApi "repos/$Repo/contents/$Path" | ConvertFrom-Json
    $b64 = $fileJson.content
    $text = [Text.Encoding]::UTF8.GetString(
        [Convert]::FromBase64String(($b64 -replace '\s', ''))
    )

    # 截取 forward 分支前后的一段代码用于判断
    $lines = $text -split "`n"
    $match = $lines | Select-String -Pattern 'seg_type in \("forward"' | Select-Object -First 1
    if (-not $match) {
        throw '未找到 forward 分支，上游结构可能已重构'
    }
    $start = [Math]::Max(0, $match.LineNumber - 1)
    $end = [Math]::Min($lines.Count - 1, $start + 24)
    $block = ($lines[$start..$end] -join "`n")

    $contentIdx = $block.IndexOf('nested_nodes = seg_data.get("content")')
    $idIdx = $block.IndexOf('fid = seg_data.get("id")')
    # content 判断排在 id 判断之前 => 上游已改为优先使用 content
    $fixed = ($contentIdx -ge 0) -and ($idIdx -lt 0 -or $contentIdx -lt $idIdx)

    $state = [ordered]@{
        checkedAt = (Get-Date).ToString('s')
        sha       = $sha
        date      = $date
        commitMsg = $msg
        fixed     = $fixed
    }
    $state | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8

    Write-Host ''
    Write-Host "上游最新提交: $($sha.Substring(0,10))  $date"
    Write-Host "提交信息    : $msg"
    Write-Host ''
    if ($fixed) {
        Write-Host '[已修复] 上游已改为优先使用 content，可以移除 AstrBot-fix 挂载了。' -ForegroundColor Green
        exit 1
    } else {
        Write-Host '[未修复] 上游仍是「有 id 就只记 id」，补丁继续有效。' -ForegroundColor Yellow
        exit 0
    }
}
catch {
    Write-Host "[检查失败] $($_.Exception.Message)" -ForegroundColor Red
    exit 2
}
