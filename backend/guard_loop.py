# -*- coding: utf-8 -*-
"""后端守护循环（pythonw.exe 启动，无控制台窗口）。
- 循环拉起 run_portable.py，退出后冷却 5 秒重启
- 监听 logs/restart.flag 软重启信号
- 日志轮转：bat_out.log 超过 5MB 归档
- 不创建控制台窗口，但后端在交互会话，支持 codegen 录制
"""
import subprocess
import sys
import os
import time
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
APP = BACKEND_DIR / "run_portable.py"
LOG_DIR = BACKEND_DIR / "logs"
LOG_FILE = LOG_DIR / "bat_out.log"
RESTART_FLAG = LOG_DIR / "restart.flag"
MAX_LOG_MB = 5


def log(msg: str) -> None:
    """追加日志，自动轮转。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # 轮转
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_MB * 1024 * 1024:
            ts = datetime.now().strftime("%Y%m%d%H%M")
            LOG_FILE.rename(LOG_DIR / f"bat_out.log.{ts}.old")
    except OSError:
        pass
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[guard] {ts} {msg}\n")


def main() -> None:
    log("service loop start")
    while True:
        # 检查软重启标记
        if RESTART_FLAG.exists():
            try:
                RESTART_FLAG.unlink()
            except OSError:
                pass
            log("restart flag detected, re-spawning after cooldown")
            time.sleep(5)
            continue

        try:
            log(f"launching backend")
            rc = subprocess.call(
                [str(VENV_PYTHON), str(APP)],
                cwd=str(BACKEND_DIR),
                # CREATE_NO_WINDOW 隐藏控制台窗口，但不影响 Playwright 弹出浏览器
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            log(f"backend exited exitcode={rc}")
        except Exception as e:
            log(f"fatal: {e}")

        # 冷却 5 秒避免高频重启
        time.sleep(5)


if __name__ == "__main__":
    main()
