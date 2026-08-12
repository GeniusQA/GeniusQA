# -*- coding: utf-8 -*-
"""
GeniusQA 游戏模式守护：运行游戏时自动停止 Windows 搜索索引(WSearch)，游戏退出自动恢复。
- 常驻后台（注册表 Run 自启），每 15 秒检测一次
- 游戏进程列表在下方 $gameProcesses 配置，按需增删
- 日志：D:\GeniusQA\logs\game-mode.log
"""
$gameProcesses = @(
    # 按需增删游戏进程名（不含 .exe）
    'BetterGI',            # 原神小助手
    'GenshinImpact',       # 原神
    'StarRail',            # 崩坏：星穹铁道
    'HoukaiStarRail',
    'YuanShen',
    'LeagueClient',        # 英雄联盟客户端
    'League of Legends',
    'VALORANT',
    'CS2',
    'Dota2',
    'PUBG',
    'NarakaBladepoint',    # 永劫无间
    'WarThunder',
    'GTA5',
    'Cyberpunk2077',
    'EldenRing',
    'WutheringWaves',      # 鸣潮
    'ZZZ',                 # 绝区零
    'HonkaiImpact3rd',
    'BlueArchive'
)
$intervalSeconds = 15
$logFile = 'D:\GeniusQA\logs\game-mode.log'

function Write-Log($msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    try {
        "$ts | $msg" | Out-File -Append -FilePath $logFile -Encoding UTF8
    } catch { }
}

# 避免重复运行（若已有实例则退出）
$existing = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -match '-File\s+.*game-mode-wsearch' -and $_.ProcessId -ne $PID }
if ($existing) { Write-Log '已有实例运行，本实例退出'; exit 0 }

Write-Log '=== 游戏模式守护启动 ==='
while ($true) {
    try {
        $gameRunning = Get-Process -Name $gameProcesses -ErrorAction SilentlyContinue
        $ws = Get-Service -Name WSearch -ErrorAction SilentlyContinue

        if ($gameRunning -and $ws.Status -eq 'Running') {
            Stop-Service -Name WSearch -Force -ErrorAction SilentlyContinue
            Write-Log "检测到游戏进程($($gameRunning[0].ProcessName))，已停止搜索索引"
        }
        elseif (-not $gameRunning -and $ws.Status -eq 'Stopped') {
            Start-Service -Name WSearch -ErrorAction SilentlyContinue
            Write-Log '无游戏进程，恢复搜索索引'
        }
    } catch { }
    Start-Sleep -Seconds $intervalSeconds
}
