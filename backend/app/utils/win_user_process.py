# -*- coding: utf-8 -*-
"""
从 Windows 服务/非交互会话中，在已登录用户的交互式桌面里打开文件夹/文件。
主要用于后端以 SYSTEM 身份运行时，仍能帮用户定位到本地技能目录。
"""
import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _open_in_user_session_win(path: str) -> bool:
    """使用 WTS API + CreateProcessAsUser 在活跃用户会话中启动 explorer。"""
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes as wt

        wts = ctypes.windll.wtsapi32
        adv = ctypes.windll.advapi32
        userenv = ctypes.windll.userenv
        kernel = ctypes.windll.kernel32

        WTS_CURRENT_SERVER_HANDLE = 0
        WTSActive = 0
        CREATE_UNICODE_ENVIRONMENT = 0x00000400
        STARTF_USESHOWWINDOW = 0x00000001
        SW_SHOWNORMAL = 1

        class WTS_SESSION_INFO(ctypes.Structure):
            _fields_ = [
                ("SessionId", wt.DWORD),
                ("pWinStationName", wt.LPWSTR),
                ("State", wt.INT),
            ]

        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD),
                ("lpReserved", wt.LPWSTR),
                ("lpDesktop", wt.LPWSTR),
                ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD),
                ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD),
                ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD),
                ("dwYCountChars", wt.DWORD),
                ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD),
                ("cbReserved2", wt.WORD),
                ("lpReserved2", wt.LPBYTE),
                ("hStdInput", wt.HANDLE),
                ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE),
            ]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", wt.HANDLE),
                ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD),
            ]

        # 绑定函数签名
        wts.WTSEnumerateSessionsW.argtypes = [
            wt.HANDLE, wt.DWORD, wt.DWORD,
            ctypes.POINTER(ctypes.POINTER(WTS_SESSION_INFO)),
            ctypes.POINTER(wt.DWORD),
        ]
        wts.WTSEnumerateSessionsW.restype = wt.BOOL

        wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        wts.WTSFreeMemory.restype = None

        wts.WTSQueryUserToken.argtypes = [wt.DWORD, ctypes.POINTER(wt.HANDLE)]
        wts.WTSQueryUserToken.restype = wt.BOOL

        userenv.CreateEnvironmentBlock.argtypes = [
            ctypes.POINTER(wt.LPVOID), wt.HANDLE, wt.BOOL
        ]
        userenv.CreateEnvironmentBlock.restype = wt.BOOL
        userenv.DestroyEnvironmentBlock.argtypes = [wt.LPVOID]
        userenv.DestroyEnvironmentBlock.restype = wt.BOOL

        adv.CreateProcessAsUserW.argtypes = [
            wt.HANDLE, wt.LPCWSTR, wt.LPWSTR,
            ctypes.c_void_p, ctypes.c_void_p, wt.BOOL,
            wt.DWORD, wt.LPVOID, wt.LPCWSTR,
            ctypes.POINTER(STARTUPINFOW),
            ctypes.POINTER(PROCESS_INFORMATION),
        ]
        adv.CreateProcessAsUserW.restype = wt.BOOL

        kernel.CloseHandle.argtypes = [wt.HANDLE]
        kernel.CloseHandle.restype = wt.BOOL

        # 1) 枚举会话，找到 Active 会话
        sessions_ptr = ctypes.POINTER(WTS_SESSION_INFO)()
        count = wt.DWORD()
        if not wts.WTSEnumerateSessionsW(
            WTS_CURRENT_SERVER_HANDLE, 0, 1,
            ctypes.byref(sessions_ptr), ctypes.byref(count)
        ):
            logger.warning("WTSEnumerateSessionsW 失败，无法跨会话打开文件夹")
            return False

        active_session = None
        try:
            for i in range(count.value):
                if sessions_ptr[i].State == WTSActive:
                    active_session = sessions_ptr[i].SessionId
                    break
        finally:
            wts.WTSFreeMemory(sessions_ptr)

        if active_session is None:
            active_session = wts.WTSGetActiveConsoleSessionId()
            if active_session == 0xFFFFFFFF:
                logger.warning("未找到活跃用户会话")
                return False

        logger.info("尝试在用户会话 %s 中打开目录: %s", active_session, path)

        # 2) 获取用户令牌
        token = wt.HANDLE()
        if not wts.WTSQueryUserToken(active_session, ctypes.byref(token)):
            logger.warning("WTSQueryUserToken 失败，错误码=%s", ctypes.get_last_error())
            return False

        try:
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            # /root 表示在资源管理器中直接打开该目录
            cmd = f'explorer.exe /root,"{path}"'

            si = STARTUPINFOW()
            si.cb = ctypes.sizeof(si)
            si.lpDesktop = "WinSta0\\Default"
            si.dwFlags = STARTF_USESHOWWINDOW
            si.wShowWindow = SW_SHOWNORMAL

            pi = PROCESS_INFORMATION()
            env = wt.LPVOID()
            created_env = userenv.CreateEnvironmentBlock(
                ctypes.byref(env), token, False
            )
            creation_flags = CREATE_UNICODE_ENVIRONMENT

            ok = adv.CreateProcessAsUserW(
                token,
                None,
                cmd,
                None,
                None,
                False,
                creation_flags,
                env if created_env else None,
                system_root,
                ctypes.byref(si),
                ctypes.byref(pi),
            )

            if created_env and env:
                userenv.DestroyEnvironmentBlock(env)

            if ok:
                kernel.CloseHandle(pi.hProcess)
                kernel.CloseHandle(pi.hThread)
                logger.info("已在用户会话 %s 中创建 explorer 进程: %s", active_session, cmd)
                return True
            else:
                logger.warning("CreateProcessAsUserW 失败，错误码=%s", ctypes.get_last_error())
                return False
        finally:
            kernel.CloseHandle(token)

    except Exception as exc:
        logger.warning("跨会话打开文件夹异常: %s", exc)
        return False


def open_folder_in_user_session(path: str) -> bool:
    """
    优先尝试在已登录用户的交互式桌面打开文件夹；失败时回退到 os.startfile / xdg-open / open。
    """
    target = Path(path).resolve()
    if not target.exists():
        logger.warning("目标路径不存在，无法打开: %s", target)
        return False

    if sys.platform == "win32" and _open_in_user_session_win(str(target)):
        return True

    try:
        if sys.platform == "win32":
            os.startfile(str(target))
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(target)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(target)])
        return True
    except Exception as exc:
        logger.warning("常规方式打开文件夹失败: %s", exc)
        return False
