<#
.SYNOPSIS
    Clean up old GeniusQA backend autostart entries and SYSTEM/session-0 python.exe,
    then register/run the new pythonw.exe windowless autostart.
.DESCRIPTION
    Double-click to run. It will auto-elevate to administrator if needed.
    Steps:
    1. Remove old shortcuts from Startup folders.
    2. Remove old HKCU/HKLM Run entries.
    3. Remove related scheduled tasks.
    4. Kill all python.exe/pythonw.exe processes (including SYSTEM).
    5. Re-register HKCU Run -> start-backend.ps1.
    6. Launch start-backend.ps1 (pythonw.exe + guard_loop.py).
#>
param()

$ErrorActionPreference = "Continue"
Set-StrictMode -Off

# Auto-elevate
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[reset] Admin rights required. Re-launching as administrator ..." -ForegroundColor Yellow
    $scriptPath = $MyInvocation.MyCommand.Path
    if (-not $scriptPath) { $scriptPath = $PSCommandPath }
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" -Verb RunAs -Wait
    exit
}

$projectRoot = "D:\GeniusQA"
$startBackend = "$projectRoot\start-backend.ps1"
$regName = "GeniusQA-Backend"

function Write-Step([string]$msg) {
    Write-Host "[reset] $msg" -ForegroundColor Cyan
}

function Get-PythonProcs {
    return Get-Process -Name "python","pythonw" -ErrorAction SilentlyContinue | Select-Object Id, SessionId, @{Name="User";Expression={
        try { (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).GetOwner().User } catch { "N/A" }
    }}, Path
}

# 1. Remove old Startup folder shortcuts
$startupDirs = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Startup"
)
foreach ($dir in $startupDirs) {
    if (Test-Path $dir) {
        Get-ChildItem -Path $dir -Filter "*GeniusQA*" -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Step "Removing startup shortcut: $($_.FullName)"
            Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}

# 2. Remove old Run registry entries
$regPaths = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run"
)
foreach ($path in $regPaths) {
    if (Test-Path $path) {
        $names = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue | Get-Member -MemberType NoteProperty | Select-Object -ExpandProperty Name
        foreach ($n in $names) {
            if ($n -match "GeniusQA|Backend|backend") {
                Write-Step "Removing registry entry $path\$n"
                Remove-ItemProperty -Path $path -Name $n -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# 3. Remove related scheduled tasks
Write-Step "Removing related scheduled tasks ..."
# Hard-coded names left by install-persistent-services.bat
$hardTaskNames = @("GeniusQA-Backend", "GeniusQA-Restart-Backend", "GeniusQA-Restart")
foreach ($tn in $hardTaskNames) {
    Write-Step "Deleting scheduled task (if exists): $tn"
    schtasks /delete /tn "$tn" /f 2>$null | Out-Null
    if (Test-Path "C:\Windows\System32\Tasks\$tn") {
        Remove-Item "C:\Windows\System32\Tasks\$tn" -Force -ErrorAction SilentlyContinue
    }
}
try {
    $tasks = schtasks /query /fo csv /v 2>$null | ConvertFrom-Csv -ErrorAction SilentlyContinue
    foreach ($t in $tasks) {
        $tn = $t.TaskName
        if ($tn -and ($tn -match "GeniusQA|run-as-service|force-restart|start-backend")) {
            Write-Step "Deleting scheduled task: $tn"
            schtasks /delete /tn "$tn" /f 2>$null | Out-Null
        }
    }
} catch {
    Write-Step "Failed to enumerate scheduled tasks: $_"
}
# Also ensure legacy XML files are gone
$legacyXmlPaths = @(
    "C:\Windows\System32\Tasks\GeniusQA-Backend",
    "C:\Windows\System32\Tasks\GeniusQA-Restart-Backend",
    "C:\Windows\System32\Tasks\GeniusQA-Restart"
)
foreach ($xp in $legacyXmlPaths) {
    if (Test-Path $xp) {
        Write-Step "Removing legacy task XML: $xp"
        Remove-Item $xp -Force -ErrorAction SilentlyContinue
    }
}

# 4. Kill python processes repeatedly until no SYSTEM python remains
Write-Step "Killing python/pythonw processes (loop) ..."
for ($i = 0; $i -lt 5; $i++) {
    $procs = Get-PythonProcs
    if (-not $procs) {
        Write-Step "No python/pythonw processes found."
        break
    }
    foreach ($p in $procs) {
        Write-Step "Killing PID $($p.Id) [user=$($p.User), session=$($p.SessionId)]"
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
    taskkill /F /IM python.exe 2>$null | Out-Null
    taskkill /F /IM pythonw.exe 2>$null | Out-Null
    Start-Sleep -Seconds 2
}

# Verify
$remaining = Get-PythonProcs | Where-Object { $_.User -eq "SYSTEM" -or $_.SessionId -eq 0 }
if ($remaining) {
    Write-Step "WARNING: SYSTEM/session-0 python still alive:" -ForegroundColor Red
    $remaining | ForEach-Object { Write-Step "  PID $($_.Id) user=$($_.User) session=$($_.SessionId)" }
    Write-Step "Please REBOOT and run this script again immediately after login." -ForegroundColor Yellow
}

# 5. Clean old restart.flag
$flagPaths = @(
    "$projectRoot\backend\logs\restart.flag",
    "$projectRoot\logs\restart.flag"
)
foreach ($fp in $flagPaths) {
    if (Test-Path $fp) {
        Write-Step "Cleaning old restart.flag: $fp"
        Remove-Item $fp -Force -ErrorAction SilentlyContinue
    }
}

# 6. Register new HKCU Run
$runPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
if (-not (Test-Path $runPath)) { New-Item -Path $runPath -Force | Out-Null }
$runValue = "powershell.exe -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$startBackend`""
Write-Step "Registering new HKCU Run: $runValue"
Set-ItemProperty -Path $runPath -Name $regName -Value $runValue -Force -ErrorAction SilentlyContinue

# 7. Launch new backend
Write-Step "Launching new backend ($startBackend) ..."
Start-Process -FilePath "powershell.exe" -ArgumentList "-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$startBackend`"" -WindowStyle Hidden

Write-Step "Done. Wait 10s, then open Task Manager and search 'python' / 'pythonw'."
Write-Step "Expected: pythonw.exe + one child python.exe, both Administrator, Session 1."

Start-Sleep -Seconds 2
