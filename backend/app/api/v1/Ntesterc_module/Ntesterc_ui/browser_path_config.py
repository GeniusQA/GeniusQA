#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""浏览器自定义安装路径配置管理。

支持为 edge/chrome/firefox/safari 指定自定义可执行文件路径，
解决浏览器未安装在默认目录导致 Playwright/Selenium 找不到浏览器的问题。
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

from app.core.logger import logger


# 配置文件路径，放在 backend 根目录，避免和源码混在一起
_CONFIG_FILE = Path(__file__).resolve().parents[5] / "browser_paths.json"

# 支持的浏览器类型（统一命名）
_SUPPORTED_BROWSERS = {"edge", "chrome", "firefox", "safari", "chromium", "msedge", "webkit"}


def _normalize_browser_type(browser_type: Optional[str]) -> str:
    """统一浏览器命名，兼容旧值。"""
    if not browser_type:
        return "edge"
    bt = str(browser_type).strip().lower()
    mapping = {
        "msedge": "edge",
        "chromium": "chrome",
        "webkit": "safari",
    }
    return mapping.get(bt, bt)


def _load_config() -> Dict[str, str]:
    """读取配置文件，返回 browser_type -> path 映射。"""
    if not _CONFIG_FILE.exists():
        return {}
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning(f"browser_paths.json 格式异常，预期 dict，实际 {type(data)}")
            return {}
        return {k: str(v).strip() for k, v in data.items() if isinstance(v, (str,))}
    except Exception as e:
        logger.error(f"读取浏览器路径配置失败: {e}")
        return {}


def _save_config(config: Dict[str, str]) -> None:
    """保存配置文件。"""
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存浏览器路径配置失败: {e}")
        raise


def get_browser_path(browser_type: str) -> Optional[str]:
    """获取指定浏览器的自定义可执行文件路径，未配置返回 None。"""
    bt = _normalize_browser_type(browser_type)
    path = _load_config().get(bt)
    if path and os.path.exists(path):
        return path
    return path  # 即使文件不存在也返回，方便上层给出更精确提示


def get_all_browser_paths() -> Dict[str, str]:
    """获取所有已配置的自定义路径。"""
    return _load_config()


def set_browser_path(browser_type: str, executable_path: str) -> str:
    """保存浏览器自定义路径，返回统一后的浏览器类型。"""
    bt = _normalize_browser_type(browser_type)
    if bt not in _SUPPORTED_BROWSERS:
        raise ValueError(f"不支持的浏览器类型: {browser_type}")
    path = str(executable_path).strip()
    if not path:
        raise ValueError("可执行文件路径不能为空")
    # 统一路径分隔符
    path = os.path.normpath(path)
    config = _load_config()
    config[bt] = path
    _save_config(config)
    return bt


def remove_browser_path(browser_type: str) -> None:
    """删除指定浏览器的自定义路径。"""
    bt = _normalize_browser_type(browser_type)
    config = _load_config()
    if bt in config:
        del config[bt]
        _save_config(config)


def path_exists(browser_type: str) -> bool:
    """判断配置的自定义路径文件是否存在。"""
    path = get_browser_path(browser_type)
    return bool(path and os.path.exists(path))


# 为以 SYSTEM/服务身份运行的后端准备的浏览器临时目录
_PW_TMP = None


def ensure_browser_temp_env() -> str:
    """为以 SYSTEM/服务身份运行的后端准备可写的浏览器临时目录。

    Playwright 启动 Chromium/Edge 时，会用 tempfile.gettempdir() 作为
    user-data-dir 与崩溃上报的临时目录。当后端以 SYSTEM 身份运行于 session-0 时，
    默认的 C:\\WINDOWS\\TEMP 常出现 ACL/锁冲突，导致浏览器进程启动后立即退出
    （报错 Target page, context or browser has been closed）。把临时目录重定向到
    后端目录下的 .pw_tmp 可规避该问题。
    """
    global _PW_TMP
    if _PW_TMP and os.path.isdir(_PW_TMP):
        return _PW_TMP
    try:
        backend_root = Path(__file__).resolve().parents[5]
        tmp = backend_root / ".pw_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        tmp_str = str(tmp)
        os.environ['TEMP'] = tmp_str
        os.environ['TMP'] = tmp_str
        os.environ['TMPDIR'] = tmp_str
        tempfile.tempdir = tmp_str
        _PW_TMP = tmp_str
        return tmp_str
    except Exception as e:
        logger.warning(f"重定向浏览器临时目录失败: {e}")
        return tempfile.gettempdir()


def get_browser_launch_env() -> Dict[str, str]:
    """返回应传给浏览器进程的环境变量（继承当前环境并覆盖 TEMP/TMP）。"""
    ensure_browser_temp_env()
    return dict(os.environ)


# ---------------------------------------------------------------------------
# 泄漏浏览器子进程回收
# ---------------------------------------------------------------------------
# 录制/执行失败时，Playwright 已 spawn 出来的 msedge 进程常因异常未被回收，
# 每次失败泄漏一个。累积到一定程度会撑爆后端进程句柄/管道，导致后续启动直接报
# 「Target page, context or browser has been closed」。这里在每次启动前，仅回收
# 「当前后端进程树内的浏览器子进程」，绝不会误杀用户自己打开的 Edge。
import subprocess as _subprocess

_BROWSER_PROC_NAMES = (
    "msedge.exe", "chrome.exe", "chromium.exe",
    "headless_shell.exe", "chrome-headless-shell.exe",
)
_ACTIVE_BROWSER_PIDS = set()


def register_active_browser(browser) -> None:
    """登记一个正在使用的浏览器实例，reap 时会跳过它，避免误杀在用的浏览器。"""
    try:
        proc = getattr(browser, "process", None)
        if proc and getattr(proc, "pid", None):
            _ACTIVE_BROWSER_PIDS.add(int(proc.pid))
    except Exception:
        pass


def unregister_active_browser(browser) -> None:
    """浏览器关闭后注销登记。"""
    try:
        proc = getattr(browser, "process", None)
        if proc and getattr(proc, "pid", None):
            _ACTIVE_BROWSER_PIDS.discard(int(proc.pid))
    except Exception:
        pass


def reap_stale_browser_processes(extra_names=None) -> int:
    """回收当前进程树内泄漏的浏览器子进程（依赖 wmic/taskkill，无需第三方库）。

    返回被强制结束的进程数。仅作用于「本后端 python 进程的后代」，不会触碰
    用户自己的工作浏览器。
    """
    names = set(_BROWSER_PROC_NAMES)
    if extra_names:
        names.update(extra_names)
    try:
        out = _subprocess.run(
            "wmic process get Name,ProcessId,ParentProcessId",
            shell=True, capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception as e:
        logger.warning(f"枚举进程失败，跳过残留浏览器回收: {e}")
        return 0

    # 解析每行末两位为 pid / ppid，首段为进程名（可能含空格，但浏览器名不含空格）
    procs = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[-2])
            ppid = int(parts[-1])
        except ValueError:
            continue
        procs.append((pid, ppid, parts[0].lower()))

    children = {}
    for pid, ppid, name in procs:
        children.setdefault(ppid, []).append((pid, name))

    my_pid = os.getpid()
    doomed = []
    stack = [my_pid]
    while stack:
        cur = stack.pop()
        for cpid, cname in children.get(cur, []):
            stack.append(cpid)
            if cname in names and cpid not in _ACTIVE_BROWSER_PIDS:
                doomed.append(cpid)

    killed = 0
    for pid in doomed:
        try:
            _subprocess.run(
                f"taskkill /F /PID {pid}",
                shell=True, capture_output=True, text=True, timeout=10,
            )
            killed += 1
        except Exception:
            pass
    if killed:
        logger.info(f"已回收 {killed} 个泄漏的浏览器子进程")
    return killed
