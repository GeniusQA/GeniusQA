@echo off
chcp 65001 >nul
title GeniusQA 服务持久化安装
echo ================================================
echo  正在安装 GeniusQA 持久化启动方案
echo ================================================
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 需要管理员权限！请右键→以管理员身份运行。
    pause
    exit /b 1
)

:: ========== 1. 设置 MySQL/Redis 为自动启动 ==========
echo [1/5] 设置 Windows 服务自动启动...
sc config MySQL84 start=delayed-auto >nul 2>&1 && echo   MySQL84 → 延迟自动启动 || echo   MySQL84 未安装
sc config Redis start=delayed-auto >nul 2>&1 && echo   Redis   → 延迟自动启动 || echo   Redis   未安装

:: ========== 2. 创建后端计划任务 (当前用户，登录时启动，pythonw 无窗口) ==========
echo [2/5] 创建后端计划任务 (当前用户登录启动，pythonw 无窗口)...
schtasks /delete /tn "GeniusQA-Backend" /f >nul 2>&1
schtasks /create /tn "GeniusQA-Backend" /sc ONLOGON ^
    /tr "powershell.exe -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File D:\GeniusQA\start-backend.ps1" /f >nul 2>&1
if %errorlevel% equ 0 (
    echo   ✓ GeniusQA-Backend 计划任务已创建（当前用户登录后启动，pythonw 无窗口）
) else (
    echo   ✗ 计划任务创建失败
)

:: ========== 3. 注册 HKLM\Run (所有用户登录后启动主脚本) ==========
echo [3/5] 注册 HKLM\Run 主启动脚本...
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "GeniusQA Master" /t REG_SZ /d "cmd /c D:\GeniusQA\start-master.cmd" /f >nul 2>&1
if %errorlevel% equ 0 (
    echo   ✓ GeniusQA Master 已添加到 HKLM\Run（所有用户登录时启动）
) else (
    echo   ✗ HKLM\Run 添加失败
)

:: ========== 4. 清理冗余的 HKCU\Run 项 ==========
echo [4/5] 清理冗余的 HKCU\Run 项...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "GeniusQA MinIO" /f >nul 2>&1 && echo   ✓ 删除 GeniusQA MinIO（已并入主脚本）
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "GeniusQA Playwright MCP" /f >nul 2>&1 && echo   ✓ 删除 GeniusQA Playwright MCP（已并入主脚本）
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "GeniusQA Frontend" /f >nul 2>&1 && echo   ✓ 删除 GeniusQA Frontend（已并入主脚本）

:: ========== 5. 立即启动后端 ==========
echo [5/5] 立即启动所有服务...
schtasks /run /tn "GeniusQA-Backend" >nul 2>&1 && echo   ✓ 后端已启动（SYSTEM权限）
start "" cmd /c "D:\GeniusQA\start-master.cmd"

echo.
echo ================================================
echo  持久化安装完成！
echo.
echo  ╔══ 开机启动顺序 ══════════════════════════╗
echo  ║ 1. MySQL/Redis 服务（OS 启动时）         ║
echo  ║ 2. 用户登录后，HKLM\Run 触发主脚本:       ║
echo  ║    → MinIO → Playwright MCP → 前端 → 后端 ║
echo  ║ 3. GeniusQA-Backend 计划任务（ONLOGON）:  ║
echo  ║    → pythonw.exe 无窗口启动后端 (Session 1) ║
echo  ╚═══════════════════════════════════════════╝
echo.
echo  管理命令:
echo    启动后端:   schtasks /run /tn "GeniusQA-Backend"
echo    停止后端:   schtasks /end /tn "GeniusQA-Backend"
echo    卸载服务:   见 D:\GeniusQA\uninstall-services.bat
echo ================================================
pause