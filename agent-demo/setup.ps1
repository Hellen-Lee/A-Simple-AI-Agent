<#
  Agent Demo 初始化脚本
  - 检测 / 创建虚拟环境，安装依赖
  - 交互式配置 api_key / base_url / model
#>

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvDir     = Join-Path $ScriptDir ".venv"
$ConfigPath  = Join-Path $ScriptDir "config.json"
$ReqPath     = Join-Path $ScriptDir "requirements.txt"

$OnWindows = ($env:OS -eq "Windows_NT") -or (-not $PSVersionTable.Platform) -or ($PSVersionTable.Platform -eq "Win32NT")
if ($OnWindows) {
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    $VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"
} else {
    $VenvPython = Join-Path $VenvDir "bin/python"
    $VenvPip    = Join-Path $VenvDir "bin/pip"
}

# ── 辅助函数 ─────────────────────────────────────────────

function Show-Heading($text) {
    Write-Host ""
    Write-Host ("-" * 50) -ForegroundColor DarkGray
    Write-Host "  $text"  -ForegroundColor Cyan
    Write-Host ("-" * 50) -ForegroundColor DarkGray
}

function Show-Ok($text)    { Write-Host "  [OK] $text" -ForegroundColor Green }
function Show-Info($text)  { Write-Host "  $text"      -ForegroundColor Gray  }
function Show-Error($text) { Write-Host "  [!!] $text" -ForegroundColor Red   }

function Get-MaskedKey($key) {
    if ($key.Length -le 8) { return "****" }
    $key.Substring(0, 3) + ("*" * ($key.Length - 7)) + $key.Substring($key.Length - 4)
}

# 从 JSON 文本中读取字符串字段值
function Read-JsonField($Json, $FieldName) {
    $pattern = '"' + [regex]::Escape($FieldName) + '"\s*:\s*"([^"]*)"'
    if ($Json -match $pattern) { return $Matches[1] }
    return ""
}

# 在 JSON 文本中替换字符串字段值（保留原始格式）
function Write-JsonField($Json, $FieldName, $NewValue) {
    $escaped  = $NewValue.Replace('\', '\\').Replace('"', '\"')
    $pattern  = '("' + [regex]::Escape($FieldName) + '"\s*:\s*)"[^"]*"'
    $replace  = '${1}"' + $escaped + '"'
    return [regex]::Replace($Json, $pattern, $replace)
}

# ── 查找系统 Python ──────────────────────────────────────

function Find-SystemPython {
    foreach ($cmd in @("python", "python3")) {
        try {
            $null = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0) { return $cmd }
        } catch {}
    }
    return $null
}

# ── 步骤 1：虚拟环境 & 依赖 ─────────────────────────────

function Initialize-Venv {
    Show-Heading "步骤 1/2 - 虚拟环境与依赖安装"

    $python = Find-SystemPython
    if (-not $python) {
        Show-Error "未检测到 Python，请先安装 Python 3.10+"
        Write-Host "    下载地址: https://www.python.org/downloads/" -ForegroundColor Yellow
        return $false
    }

    $ver = (& $python --version 2>&1) -join ""
    Show-Info ("检测到 " + $ver.Trim())

    # 虚拟环境
    if ((Test-Path $VenvDir) -and (Test-Path $VenvPython)) {
        Show-Ok "虚拟环境已存在，跳过创建"
    } else {
        Show-Info "正在创建虚拟环境 (.venv) ..."
        & $python -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) { Show-Error "创建虚拟环境失败"; return $false }
        Show-Ok "虚拟环境创建完成"
    }

    # 依赖包（用 2>&1 合并 stderr 到 stdout，避免 PowerShell 把 traceback 当错误）
    $null = & $VenvPython -c "import openai; import rich; import dotenv" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Show-Ok "依赖包已安装，跳过安装"
    } else {
        Show-Info "正在安装依赖包（首次可能需要几分钟）..."
        & $VenvPip install -r $ReqPath
        if ($LASTEXITCODE -ne 0) { Show-Error "依赖安装失败"; return $false }
        Show-Ok "依赖包安装完成"
    }

    return $true
}

# ── 步骤 2：API 配置 ────────────────────────────────────

function Initialize-Config {
    Show-Heading "步骤 2/2 - API 配置"

    if (-not (Test-Path $ConfigPath)) {
        Show-Error "未找到 config.json"; return
    }

    $json    = [System.IO.File]::ReadAllText($ConfigPath, [System.Text.Encoding]::UTF8)
    $changed = $false

    $fields = @(
        @{ Key="api_key";  Label="API Key";               Secret=$true  },
        @{ Key="base_url"; Label="API 地址 (Base URL)";    Secret=$false },
        @{ Key="model";    Label="模型名称 (Model)";       Secret=$false }
    )

    foreach ($f in $fields) {
        $current = Read-JsonField $json $f.Key

        if ([string]::IsNullOrWhiteSpace($current)) {
            $value = Read-Host "  $($f.Label) [必填]"
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                $json = Write-JsonField $json $f.Key $value
                $changed = $true
            } else {
                Show-Info "$($f.Label) 未填写，稍后可手动编辑 config.json"
            }
        } else {
            $display = if ($f.Secret) { Get-MaskedKey $current } else { $current }
            $choice  = Read-Host "  $($f.Label) [$display] - 是否更改? (y/N)"
            if ($choice -match '^[yY]') {
                $value = Read-Host "  请输入新的 $($f.Label)"
                if (-not [string]::IsNullOrWhiteSpace($value)) {
                    $json = Write-JsonField $json $f.Key $value
                    $changed = $true
                }
            }
        }
    }

    if ($changed) {
        [System.IO.File]::WriteAllText($ConfigPath, $json, [System.Text.UTF8Encoding]::new($false))
        Show-Ok "配置已保存 -> config.json"
    } else {
        Show-Ok "配置未变更"
    }
}

# ── 主流程 ───────────────────────────────────────────────

Write-Host ""
Write-Host ("=" * 50) -ForegroundColor Blue
Write-Host "        Agent Demo - 初始化设置"  -ForegroundColor White
Write-Host ("=" * 50) -ForegroundColor Blue

try {
    $ok = Initialize-Venv
    if ($ok) { Initialize-Config }
} catch {
    Write-Host ""
    Show-Error "发生错误: $_"
    Read-Host "`n按 Enter 键退出"
    exit 1
}

Show-Heading "初始化完成!"
if ($OnWindows) { $run = ".venv\Scripts\python agent.py" }
else            { $run = ".venv/bin/python agent.py" }

Write-Host ""
Write-Host "  启动 Agent:" -ForegroundColor White
Write-Host "    $run"      -ForegroundColor Yellow
Write-Host ""
Read-Host "按 Enter 键退出"
