param(
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"

# 定位仓库根目录
$root = (git rev-parse --show-toplevel 2>$null)
if (-not $root) {
    Write-Error "当前目录不在 git 仓库内"
    exit 1
}
Set-Location $root

$ts = Get-Date -Format "yyyy-MM-dd HH:mm"
if (-not $Message) {
    $Message = "chore: 自动提交当前进度 $ts"
}

# 透明展示将要提交的内容
Write-Host "`n==> 将要提交以下改动：" -ForegroundColor Cyan
$changes = git status --short
if (-not $changes) {
    Write-Host "工作区无改动，无需提交。" -ForegroundColor Yellow
    exit 0
}
Write-Host $changes

git add -A
git commit -m $Message | Out-String | Write-Host
Write-Host "`n==> 已完成提交：$Message" -ForegroundColor Green
