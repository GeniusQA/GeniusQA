# Desktop Admin Sync: 扫描桌面所有 exe，自动配置 RUNASADMIN（含 setup 安装包，exe 级最可靠）
$desktop = [Environment]::GetFolderPath('Desktop')
$key = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers'
$added = @()
Get-ChildItem $desktop -Filter *.exe -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
    $path = $_.FullName
    try {
        $val = (Get-ItemProperty $key -Name $path -ErrorAction SilentlyContinue).$path
    } catch { $val = $null }
    if ($val -notmatch 'RUNASADMIN') {
        New-ItemProperty -Path $key -Name $path -Value '~ RUNASADMIN' -PropertyType String -Force | Out-Null
        $added += $path
    }
}
$logDir = 'D:\GeniusQA\logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
"$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) added=$($added.Count) total-scanned done" | Out-File -FilePath "$logDir\desktop-admin-sync.log" -Append -Encoding UTF8
