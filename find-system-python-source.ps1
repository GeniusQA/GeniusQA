#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Find which scheduled task or service is launching SYSTEM python.exe on port 8100.
#>
param()

$ErrorActionPreference = "Continue"

# Auto-elevate
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Admin required. Re-launching..." -ForegroundColor Yellow
    $scriptPath = $MyInvocation.MyCommand.Path
    if (-not $scriptPath) { $scriptPath = $PSCommandPath }
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" -Verb RunAs -Wait
    exit
}

function Get-TaskXml([string]$taskName) {
    $xml = schtasks /query /tn "$taskName" /xml /fo list 2>$null | Out-String
    return $xml
}

# All scheduled tasks
Write-Host "=== Scanning scheduled tasks for python/backend/GeniusQA references ===" -ForegroundColor Cyan
$tasks = schtasks /query /fo csv /v 2>$null | ConvertFrom-Csv -ErrorAction SilentlyContinue
$matched = @()
foreach ($t in $tasks) {
    $tn = $t.TaskName
    $xml = $null
    try { $xml = Get-TaskXml $tn } catch {}
    if ($xml -and ($xml -match 'python|GeniusQA|backend|start-backend|run-as-service|force-restart|8100')) {
        $matched += $tn
        Write-Host "MATCH: $tn" -ForegroundColor Yellow
        $xml | Select-String -Pattern 'Command|Arguments|Trigger' -Context 0,1 | ForEach-Object { Write-Host $_.Line }
    }
}
if ($matched.Count -eq 0) {
    Write-Host "No matching scheduled task found by content scan." -ForegroundColor Green
}

# Tasks in non-Microsoft folders
Write-Host "`n=== All non-Microsoft task names ===" -ForegroundColor Cyan
foreach ($t in $tasks) {
    $tn = $t.TaskName
    if ($tn -and -not ($tn.StartsWith('\Microsoft\'))) {
        Write-Host $tn
    }
}

# Services with command lines containing python
Write-Host "`n=== Services whose binary path contains python ===" -ForegroundColor Cyan
$services = Get-WmiObject Win32_Service | Where-Object { $_.PathName -and ($_.PathName -match 'python|GeniusQA') } | Select-Object Name, DisplayName, StartMode, PathName
if ($services) { $services | Format-List } else { Write-Host "None found." }

# All running python processes with parent chain
Write-Host "`n=== Running python/pythonw process parent chains ===" -ForegroundColor Cyan
$procs = Get-Process -Name "python","pythonw" -ErrorAction SilentlyContinue
foreach ($p in $procs) {
    Write-Host "`nPID $($p.Id) Session=$($p.SessionId) Path=$($p.Path)" -ForegroundColor Yellow
    $cur = $p.Id
    for ($i = 0; $i -lt 8; $i++) {
        try {
            $info = Get-WmiObject Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
            if (-not $info) { break }
            $ppid = $info.ParentProcessId
            Write-Host "  -> PID $cur : $($info.Name) (parent=$ppid) cmd=$($info.CommandLine)"
            if ($ppid -eq $cur -or $ppid -eq 0) { break }
            $cur = $ppid
        } catch { break }
    }
}

# WMIC job list
Write-Host "`n=== WMI jobs ===" -ForegroundColor Cyan
wmic job list brief

Write-Host "`nScan complete. If nothing obvious found, the source may be a third-party service wrapper or shell startup script." -ForegroundColor Cyan
Start-Sleep -Seconds 3
