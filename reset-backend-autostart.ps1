#Requires -RunAsAdministrator
<#
.SYNOPSIS
    彻底清理旧的 GeniusQA 后端自启动项，杀掉所有 SYSTEM/session-0 残留进程，
    并以当前登录用户重新注册新的 pythonw 无窗口启动方式。
.DESCRIPTION
    必须以管理员身份运行一次（右键 -> 使用 PowerShell 运行）。
    它会：
    1. 删除启动文件夹中旧的快捷方式；
    2. 删除 HKLM/HKCU 中旧的自启动注册表项；
    3. 删除所有与 GeniusQA/backend 相关的计划任务；
    4. 强制结束所有 python.exe 进程（包括 SYSTEM 的 session-0 残留）；
    5. 重新在 HKCU Run 注册新的 start-backend.ps1 启动项；
    6. 立即运行 start-backend.ps1，启动 pythonw.exe + guard_loop.py 守护。
#>
param()

$ErrorActionPreference = "Continue"
Set-StrictMode -Off

$projectRoot = "D:\GeniusQA"
$startBackend = "$projectRoot\start-backend.ps1"
$regName = "GeniusQA-Backend"

function Write-Step([string]$msg) {
    Write-Host "[reset] $msg" -ForegroundColor Cyan
}

# 1. 删除启动文件夹中的旧快捷方式
$startupDirs = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Startup"
)
foreach ($dir in $startupDirs) {
    if (Test-Path $dir) {
        Get-ChildItem -Path $dir -Filter "*GeniusQA*" -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Step "删除启动文件夹项: $($_.FullName)"
            Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}

# 2. 删除旧的注册表自启动项（HKLM 需要管理员）
$regPaths = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run"
)
foreach ($path in $regPaths) {
    if (Test-Path $path) {
        $names = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue | Get-Member -MemberType NoteProperty | Select-Object -ExpandProperty Name
        foreach ($n in $names) {
            if ($n -match "GeniusQA|Backend|backend") {
                Write-Step "删除注册表项 $path\$n"
                Remove-ItemProperty -Path $path -Name $n -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# 3. 删除所有含 GeniusQA/backend 关键字的计划任务（包括 SYSTEM 创建的任务）
Write-Step "删除相关计划任务 ..."
$tasks = schtasks /query /fo csv /v 2>$null | ConvertFrom-Csv -ErrorAction SilentlyContinue
foreach ($t in $tasks) {
    $tn = $t.TaskName
    if ($tn -and ($tn -match "GeniusQA|backend|run-as-service|force-restart")) {
        Write-Step "删除计划任务: $tn"
        schtasks /delete /tn "$tn" /f 2>$null | Out-Null
    }
}

# 4. 结束所有 python.exe 进程（包括 SYSTEM/session-0，管理员权限可以做到）
Write-Step "强制结束所有 python.exe 进程 ..."
$procs = Get-Process -Name "python" -ErrorAction SilentlyContinue
foreach ($p in $procs) {
    Write-Step "结束 PID $($p.Id) ($($p.SessionId))"
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}
# 再补一轮 taskkill，确保顽固进程被干掉
taskkill /F /IM python.exe 2>$null | Out-Null
taskkill /F /IM pythonw.exe 2>$null | Out-Null

# 等待端口释放
Start-Sleep -Seconds 3

# 5. 清理旧的 restart.flag 和日志，避免误判
$flagPaths = @(
    "$projectRoot\backend\logs\restart.flag",
    "$projectRoot\logs\restart.flag"
)
foreach ($fp in $flagPaths) {
    if (Test-Path $fp) {
        Write-Step "清理旧 restart.flag: $fp"
        Remove-Item $fp -Force -ErrorAction SilentlyContinue
    }
}

# 6. 重新注册 HKCU Run 启动项，指向新的 start-backend.ps1
$runPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
if (-not (Test-Path $runPath)) { New-Item -Path $runPath -Force | Out-Null }
$runValue = "powershell.exe -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$startBackend`""
Write-Step "注册新的自启动项: $runValue"
Set-ItemProperty -Path $runPath -Name $regName -Value $runValue -Force -ErrorAction SilentlyContinue

# 7. 立即启动一次新的后端
Write-Step "立即启动新的后端 ($startBackend) ..."
Start-Process -FilePath "powershell.exe" -ArgumentList "-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$startBackend`"" -WindowStyle Hidden

Write-Step "完成。请在 10 秒后检查任务管理器，应出现 pythonw.exe 和一个子 python.exe（均为 Administrator，Session 1）。"
Write-Step "若仍看到 SYSTEM 的 python.exe，请再次重启电脑后再试。"

Start-Sleep -Seconds 2
