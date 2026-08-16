# Desktop Admin Watch: 常驻监视桌面，新 exe 出现立即自动配置 RUNASADMIN
$desktop = [Environment]::GetFolderPath('Desktop')
$key = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers'
$logFile = 'D:\GeniusQA\logs\desktop-admin-sync.log'

function Set-Admin([string]$path) {
    if (-not $path -or -not (Test-Path $path)) { return }
    try { $val = (Get-ItemProperty $key -Name $path -ErrorAction SilentlyContinue).$path } catch { $val = $null }
    if ($val -notmatch 'RUNASADMIN') {
        New-ItemProperty -Path $key -Name $path -Value '~ RUNASADMIN' -PropertyType String -Force | Out-Null
        try { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) auto: $path" | Out-File $logFile -Append -Encoding UTF8 } catch {}
    }
}

Get-ChildItem $desktop -Filter *.exe -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object { Set-Admin $_.FullName }

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $desktop
$watcher.Filter = '*.exe'
$watcher.IncludeSubdirectories = $true
$watcher.EnableRaisingEvents = $true

$action = {
    $p = $Event.SourceEventArgs.FullPath
    if ($p -and (Test-Path $p)) {
        $k = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers'
        try { $v = (Get-ItemProperty $k -Name $p -ErrorAction SilentlyContinue).$p } catch { $v = $null }
        if ($v -notmatch 'RUNASADMIN') {
            New-ItemProperty -Path $k -Name $p -Value '~ RUNASADMIN' -PropertyType String -Force | Out-Null
            try { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) auto: $p" | Out-File 'D:\GeniusQA\logs\desktop-admin-sync.log' -Append -Encoding UTF8 } catch {}
        }
    }
}
Register-ObjectEvent -InputObject $watcher -EventName Created -Action $action | Out-Null
Register-ObjectEvent -InputObject $watcher -EventName Renamed -Action $action | Out-Null

while ($true) { Start-Sleep -Seconds 30 }
