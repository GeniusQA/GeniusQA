#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""浏览器自定义安装路径配置管理。

支持为 edge/chrome/firefox/safari 指定自定义可执行文件路径，
解决浏览器未安装在默认目录导致 Playwright/Selenium 找不到浏览器的问题。
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

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


def is_headless_required() -> bool:
    """判断当前后端进程是否必须强制使用无头（headless）浏览器。

    后端常以 SYSTEM/服务身份运行于 **session 0**，该会话没有交互桌面
    （没有 winsta0\\default）。此时若以「有头模式」启动浏览器，msedge 进程
    虽能起来（Playwright 日志显示 <launched>），却因无法创建窗口而立即退出，
    Playwright 随即报 ``Target page, context or browser has been closed``。

    判定条件（满足任一即强制无头）：
    1. Windows 且当前进程位于 session 0（服务会话，最可靠）；
    2. 运行身份为 SYSTEM / LocalService / NetworkService。

    其余情况（如开发者在本机交互桌面内运行后端）返回 False，尊重前端的
    headless 开关，保留「可见浏览器」的录制体验。
    """
    if sys.platform != "win32":
        return False
    # 1) session 0 判定
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        sid = ctypes.c_ulong()
        if kernel32.ProcessIdToSessionId(
            kernel32.GetCurrentProcessId(), ctypes.byref(sid)
        ):
            if sid.value == 0:
                return True
    except Exception:
        pass
    # 2) 服务身份兜底
    try:
        import getpass
        if getpass.getuser().upper() in (
            "SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE"
        ):
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# 在交互桌面上启动浏览器（解决 SYSTEM/session-0 下有头模式无法弹窗的问题）
# ---------------------------------------------------------------------------
def _find_free_port() -> int:
    """获取一个可用的本地 TCP 端口。"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get_interactive_browser_executable(browser_type: str) -> str:
    """返回可用于交互桌面启动的浏览器可执行文件路径，找不到则抛异常。"""
    bt = _normalize_browser_type(browser_type)
    # 优先使用用户自定义路径
    custom = get_browser_path(bt)
    if custom and os.path.exists(custom):
        return custom

    candidates = []
    if bt in ("edge", "msedge"):
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
    elif bt == "chrome":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    elif bt == "chromium":
        candidates = [
            r"C:\Program Files\Chromium\Application\chrome.exe",
        ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise RuntimeError(f"找不到 {bt} 浏览器可执行文件，无法在当前桌面弹出交互窗口")


def find_bundled_chromium() -> Optional[str]:
    """查找 Playwright 自带的 Chromium 可执行文件。

    当系统安装的 Edge/Chrome 版本与当前 Playwright 不兼容时，直接复用 Playwright
    自带的、版本严格匹配的 Chromium 是最稳妥的回退方案。经测试，Playwright 1.62.0
    已与系统 Edge 151 兼容；此处仍保留 bundled Chromium 作为兜底。

    兼容 PLAYWRIGHT_BROWSERS_PATH 与默认用户目录两种存放位置。
    """
    roots = []
    pb_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if pb_path:
        roots.append(pb_path)
    # 用户默认目录
    roots.append(
        os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")
    )
    roots.append(
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")
    )

    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root), reverse=True):
            if name.startswith("chromium-"):
                for sub in ("chrome-win64", "chrome-win"):
                    exe = os.path.join(root, name, sub, "chrome.exe")
                    if os.path.exists(exe):
                        found.append(exe)

    if not found:
        # 也尝试更宽松的查找（firefox/webkit 不在范围内，仅 chromium）
        for root in roots:
            if not os.path.isdir(root):
                continue
            for name in sorted(os.listdir(root), reverse=True):
                if name.startswith("chromium"):
                    for sub in ("chrome-win64", "chrome-win", "chrome-linux", "chromium-win"):
                        exe = os.path.join(root, name, sub, "chrome.exe")
                        if os.path.exists(exe):
                            found.append(exe)
    return found[0] if found else None


def launch_interactive_browser(
    browser_type: str = "edge",
    user_data_dir: Optional[str] = None,
    remote_debugging_port: Optional[int] = None,
) -> Dict[str, Any]:
    """在当前登录用户的交互桌面上启动一个有头浏览器，并开启 CDP 调试端口。

    当后端以 SYSTEM/session-0 运行时，普通 ``launcher.launch(headless=False)``
    出来的浏览器进程没有桌面可写，窗口创建失败。本函数通过
    ``WTSQueryUserToken`` 拿到当前活动控制台会话的用户 Token，再用
    ``CreateProcessAsUser`` 把浏览器派生到 ``Winsta0\\Default`` 桌面，从而
    能在用户桌面上弹出可见窗口，供交互式录制。

    返回 ``{"pid": int, "cdp_port": int, "user_data_dir": str}``。
    调用方可用 ``playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")``
    连接。

    注意：调用进程需要足够权限（SYSTEM 或具有 SeTcbPrivilege）才能查询用户
    Token；普通管理员账户通常无法满足。
    """
    if sys.platform != "win32":
        raise OSError("交互桌面浏览器启动仅支持 Windows")

    import win32api
    import win32con
    import win32process
    import win32profile
    import win32security
    import win32ts

    session_id = win32ts.WTSGetActiveConsoleSessionId()
    if session_id == 0xFFFFFFFF:
        raise RuntimeError("当前没有用户登录到交互桌面，无法弹出浏览器窗口")

    exe_path = _get_interactive_browser_executable(browser_type)
    port = remote_debugging_port or _find_free_port()
    if user_data_dir is None:
        tmp_root = ensure_browser_temp_env()
        user_data_dir = os.path.join(tmp_root, f"interactive_profile_{port}")
    os.makedirs(user_data_dir, exist_ok=True)

    # 构造命令行：开启远程调试、指定用户数据目录、关闭首次运行向导
    cmd = (
        f'"{exe_path}" --remote-debugging-port={port} '
        f'--user-data-dir="{user_data_dir}" --no-first-run '
        f'--no-default-browser-check --disable-features=Translate '
        f'--disable-blink-features=AutomationControlled'
    )

    h_token = win32ts.WTSQueryUserToken(session_id)
    try:
        h_dup = win32security.DuplicateTokenEx(
            h_token,
            win32security.SecurityImpersonation,
            win32con.TOKEN_ALL_ACCESS,
            win32security.TokenPrimary,
        )
        try:
            env = win32profile.CreateEnvironmentBlock(h_dup, False)
            si = win32process.STARTUPINFO()
            si.dwFlags = win32con.STARTF_USESHOWWINDOW
            si.wShowWindow = win32con.SW_SHOW
            si.lpDesktop = "Winsta0\\Default"
            h_proc, h_thread, pid, tid = win32process.CreateProcessAsUser(
                h_dup,
                None,
                cmd,
                None,
                None,
                False,
                win32con.CREATE_NEW_CONSOLE | win32con.CREATE_UNICODE_ENVIRONMENT,
                env,
                os.path.dirname(exe_path),
                si,
            )
            win32api.CloseHandle(h_thread)
            win32api.CloseHandle(h_proc)
            logger.info(
                f"已在交互桌面启动 {browser_type} (pid={pid}, cdp_port={port})"
            )
            return {
                "pid": pid,
                "cdp_port": port,
                "user_data_dir": user_data_dir,
            }
        finally:
            win32api.CloseHandle(h_dup)
    finally:
        win32api.CloseHandle(h_token)


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


def register_active_browser(browser, pid: Optional[int] = None) -> None:
    """登记一个正在使用的浏览器实例，reap 时会跳过它，避免误杀在用的浏览器。

    对于通过 CDP 连接的浏览器（如交互桌面启动），没有 ``browser.process``，
    调用方可以直接传入 ``pid``。
    """
    try:
        if pid:
            _ACTIVE_BROWSER_PIDS.add(int(pid))
            return
        proc = getattr(browser, "process", None)
        if proc and getattr(proc, "pid", None):
            _ACTIVE_BROWSER_PIDS.add(int(proc.pid))
    except Exception:
        pass


def unregister_active_browser(browser, pid: Optional[int] = None) -> None:
    """浏览器关闭后注销登记。"""
    try:
        if pid:
            _ACTIVE_BROWSER_PIDS.discard(int(pid))
            return
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
    # 注意：不能用 subprocess.run(timeout=...) —— 超时后 run() 内部会 kill 然后无限 wait，
    # SYSTEM/服务会话下 wmic 杀不掉会永久卡住（实测踩坑）。用 Popen + 有限等待。
    try:
        _proc = _subprocess.Popen(
            "wmic process get Name,ProcessId,ParentProcessId",
            shell=True, stdout=_subprocess.PIPE, stderr=_subprocess.PIPE, text=True,
        )
        try:
            out, _ = _proc.communicate(timeout=8)
        except _subprocess.TimeoutExpired:
            _proc.kill()
            try:
                out, _ = _proc.communicate(timeout=2)
            except Exception:
                out = ""
            logger.warning("wmic 枚举进程超时(8s)，跳过残留浏览器回收")
            return 0
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
            _proc = _subprocess.Popen(
                f"taskkill /F /PID {pid}",
                shell=True, stdout=_subprocess.PIPE, stderr=_subprocess.PIPE, text=True,
            )
            try:
                _proc.communicate(timeout=5)
            except _subprocess.TimeoutExpired:
                _proc.kill()
                try:
                    _proc.communicate(timeout=1)
                except Exception:
                    pass
            killed += 1
        except Exception:
            pass
    if killed:
        logger.info(f"已回收 {killed} 个泄漏的浏览器子进程")
    return killed


def kill_playwright_driver_children() -> None:
    """清理本进程树内残留的 playwright node 驱动子进程（start() 超时/取消后用）。"""
    try:
        out = _subprocess.run(
            "wmic process get Name,ProcessId,ParentProcessId",
            shell=True, capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception as e:
        logger.warning(f"枚举进程失败，跳过驱动清理: {e}")
        return
    children: dict = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                children.setdefault(int(parts[-1]), []).append(int(parts[-2]))
            except ValueError:
                pass
    stack, doomed = [os.getpid()], []
    while stack:
        for pid in children.pop(stack.pop(), []):
            stack.append(pid)
            doomed.append(pid)
    for pid in doomed:
        try:
            _subprocess.run(
                f"taskkill /F /PID {pid}",
                shell=True, capture_output=True, text=True, timeout=5,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 进程级临时目录重定向（必须在任意 async_playwright().start() 之前生效）
# ---------------------------------------------------------------------------
# 关键：Playwright 的 user-data-dir 由它的 Node 驱动进程在 start() 时创建，
# 继承的是 start() 那一刻的 TEMP。若等到 launch 时才改 os.environ 已经太晚
# （Node 进程已缓存）。因此在模块被 import 时就立即重定向，确保任何
# async_playwright().start() 拿到的都是 .pw_tmp。
try:
    ensure_browser_temp_env()
except Exception:
    pass
