# GeniusQA Backend 自启脚本（由注册表 HKCU\Run 调用）
# 进程运行在 explorer 上下文，与 IDE 工具进程树隔离。
# 改进：等待依赖服务就绪 + 启动延迟 + 日志记录
$ErrorActionPreference = 'SilentlyContinue'
$logFile = 'D:\GeniusQA\logs\autostart-backend.log'

# 确保日志目录存在，否则 Out-File 会静默失败
$logDir = Split-Path -Parent $logFile
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

function Write-Log($msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    try {
        "$ts | $msg" | Out-File -Append -FilePath $logFile -Encoding UTF8
    } catch {
        # 日志写入失败时仅控制台输出，不中断启动流程
        Write-Host "LOG-ERROR: $_"
    }
}

Write-Log "=== Autostart triggered ==="

# 1) 防重复：8100 已监听则退出
$listening = netstat -ano 2>$null | Select-String ':8100.*LISTEN'
if ($listening) { Write-Log "Port 8100 already listening, exit."; exit 0 }

# 2) 等待网络栈稳定（Tailscale 等 VPN/网络服务可能延迟初始化）
Write-Log "Waiting 15s for network stack (Tailscale/DNS)..."
Start-Sleep -Seconds 15

# 3) 等待 MySQL 就绪（最多 60 秒，每 5 秒检测一次）
Write-Log "Waiting for MySQL..."
$mysqlReady = $false
for ($i = 0; $i -lt 12; $i++) {
    $r = sc.exe query MySQL84 2>$null | Select-String 'RUNNING'
    if ($r) { $mysqlReady = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $mysqlReady) { Write-Log "WARNING: MySQL not ready after 60s, starting anyway..." }
else { Write-Log "MySQL ready." }

# 4) 等待 Redis 就绪
Write-Log "Waiting for Redis..."
$redisReady = $false
for ($i = 0; $i -lt 12; $i++) {
    $r = sc.exe query Redis 2>$null | Select-String 'RUNNING'
    if ($r) { $redisReady = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $redisReady) { Write-Log "WARNING: Redis not ready after 60s, starting anyway..." }
else { Write-Log "Redis ready." }

# 5) 再次检查防重复
$listening = netstat -ano 2>$null | Select-String ':8100.*LISTEN'
if ($listening) { Write-Log "Port 8100 now listening (another instance), exit."; exit 0 }

# 6) 启动后端守护进程
$backendDir = 'D:\GeniusQA\backend'
$serviceBat = Join-Path $backendDir 'run-as-service.bat'

try {
    $p = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList "/c `"$serviceBat`"" `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -PassThru
    Write-Log ("Started run-as-service.bat PID=" + $p.Id)
} catch {
    Write-Log ("FATAL: Failed to start backend: " + $_.Exception.Message)
}

Write-Log "=== Autostart done ==="
