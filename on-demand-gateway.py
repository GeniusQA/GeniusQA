#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GeniusQA 按需网关（on-demand gateway）
- 常驻轻量进程（约 8MB），监听 8101
- 有访问请求时：按序拉起 MySQL(3306) → Redis(6379) → 后端(8100)，就绪后转发
- 空闲超过 IDLE_MINUTES（默认 10 分钟）无请求：自动停止后端 + MySQL + Redis
- TCP 透明转发（支持 HTTP/WebSocket），由 tailscale serve 指到本端口

启动：pythonw.exe on-demand-gateway.py（注册表 Run 自启）
日志：D:\\GeniusQA\\logs\\gateway.log
"""
import os
import sys
import time
import socket
import select
import subprocess
import threading
from datetime import datetime
from pathlib import Path

# ── 配置 ──
LISTEN_PORT = 8101
BACKEND_PORT = 8100
MYSQL_PORT = 3306
REDIS_PORT = 6379
IDLE_MINUTES = int(os.environ.get("GATEWAY_IDLE_MINUTES", "1"))   # 空闲多少分钟后自动停止（默认 1 分钟，可环境变量覆盖）
STARTUP_TIMEOUT = 50       # 服务拉起就绪总超时（秒）
HEALTH_INTERVAL = 30       # 空闲检查间隔（秒）
LOG_FILE = Path(r"D:\GeniusQA\logs\gateway.log")

BACKEND_DIR = Path(r"D:\GeniusQA\backend")
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "pythonw.exe"
GUARD_SCRIPT = BACKEND_DIR / "guard_loop.py"

MYSQL_SERVICE = "MySQL84"
# Windows 静默：子进程不弹控制台窗口
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
REDIS_SERVICE = "Redis"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[gateway] {ts} {msg}\n")
    except OSError:
        pass


def port_listening(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.1)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def run_cmd(args, timeout=30):
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
    except Exception as e:
        log(f"cmd error {args} -> {e}")
        return None


def start_mysql() -> bool:
    # 先清理残留 mysqld（服务已停但进程残留会导致新实例绑定失败）
    run_cmd(["taskkill", "/F", "/IM", "mysqld.exe"])
    time.sleep(2)
    log("starting MySQL service...")
    run_cmd(["sc.exe", "start", MYSQL_SERVICE])
    for _ in range(90):
        if port_listening(MYSQL_PORT):
            log("MySQL ready")
            return True
        time.sleep(1)
    # 超时：重置服务再试一次（可能处于异常状态）
    log("WARN: MySQL not ready in 90s, retry once...")
    run_cmd(["sc.exe", "stop", MYSQL_SERVICE])
    time.sleep(3)
    run_cmd(["taskkill", "/F", "/IM", "mysqld.exe"])
    run_cmd(["sc.exe", "start", MYSQL_SERVICE])
    for _ in range(90):
        if port_listening(MYSQL_PORT):
            log("MySQL ready (retry)")
            return True
        time.sleep(1)
    log("WARN: MySQL not ready after retry")
    return False


def start_redis() -> bool:
    run_cmd(["taskkill", "/F", "/IM", "redis-server.exe"])
    time.sleep(1)
    log("starting Redis service...")
    run_cmd(["sc.exe", "start", REDIS_SERVICE])
    for _ in range(30):
        if port_listening(REDIS_PORT):
            log("Redis ready")
            return True
        time.sleep(1)
    log("WARN: Redis not ready in 30s, retry once...")
    run_cmd(["sc.exe", "stop", REDIS_SERVICE])
    time.sleep(2)
    run_cmd(["sc.exe", "start", REDIS_SERVICE])
    for _ in range(30):
        if port_listening(REDIS_PORT):
            log("Redis ready (retry)")
            return True
        time.sleep(1)
    log("WARN: Redis not ready after retry")
    return False


def _pids_by_cmdline():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and ($_.CommandLine -match 'guard_loop|run_portable') -and ($_.CommandLine -notmatch 'on-demand-gateway') } | Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW)
        pids = [int(x.strip()) for x in out.stdout.split() if x.strip().isdigit()]
        return pids
    except Exception:
        return []


def _guard_loop_running() -> bool:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'guard_loop' } | Select-Object -ExpandProperty ProcessId"],
        capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW)
    return bool([x for x in out.stdout.split() if x.strip().isdigit()])


def start_backend() -> bool:
    log("starting backend guard_loop...")
    if _guard_loop_running():
        log("guard_loop already running, skip")
        for _ in range(STARTUP_TIMEOUT):
            if port_listening(BACKEND_PORT):
                return True
            time.sleep(1)
        return port_listening(BACKEND_PORT)
    if not VENV_PYTHON.exists():
        log(f"FATAL: pythonw not found: {VENV_PYTHON}")
        return False
    subprocess.Popen(
        [str(VENV_PYTHON), str(GUARD_SCRIPT)],
        cwd=str(BACKEND_DIR),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for _ in range(STARTUP_TIMEOUT):
        if port_listening(BACKEND_PORT):
            log("backend ready")
            return True
        time.sleep(1)
    log("WARN: backend not ready within %ds" % STARTUP_TIMEOUT)
    return False


def ensure_services() -> bool:
    if port_listening(BACKEND_PORT):
        return True
    # 串行化：已有拉起在进行则跳过（页面会自动刷新重试）
    if not _start_lock.acquire(blocking=False):
        log("startup already in progress, skip")
        return False
    try:
        need_mysql = not port_listening(MYSQL_PORT)
        need_redis = not port_listening(REDIS_PORT)
        if need_mysql:
            start_mysql()
        if need_redis:
            start_redis()
        if not port_listening(BACKEND_PORT):
            start_backend()
        return port_listening(BACKEND_PORT)
    finally:
        _start_lock.release()


def stop_backend() -> None:
    pids = _pids_by_cmdline()
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=15, creationflags=_NO_WINDOW)
            log(f"backend process {pid} stopped")
        except Exception as e:
            log(f"stop backend {pid} error: {e}")


def stop_all() -> None:
    log(f"idle timeout, stopping services...")
    stop_backend()
    run_cmd(["sc.exe", "stop", REDIS_SERVICE])
    run_cmd(["sc.exe", "stop", MYSQL_SERVICE])
    log("all services stopped")


_last_activity = time.time()
_stop_lock = threading.Lock()
_start_lock = threading.Lock()  # 拉起串行锁：同一时刻只有一个 ensure_services 执行


def idle_monitor():
    global _last_activity
    while True:
        time.sleep(HEALTH_INTERVAL)
        try:
            idle = time.time() - _last_activity
            if idle > IDLE_MINUTES * 60 and port_listening(BACKEND_PORT):
                with _stop_lock:
                    if time.time() - _last_activity > IDLE_MINUTES * 60:
                        stop_all()
        except Exception as e:
            log(f"idle monitor error: {e}")


class ForwardHandler:
    def handle(self, client_sock):
        global _last_activity
        try:
            peer = client_sock.getpeername()
            if not port_listening(BACKEND_PORT):
                with _stop_lock:
                    log(f"request arrived from {peer}, services cold-starting...")
                    # 立即返回'启动中'页面（浏览器自动刷新），后台异步拉起服务
                    try:
                        page = ("<html><head><meta http-equiv=\"refresh\" content=\"5\"><meta charset=\"utf-8\"></head>"
                                "<body style=\"font-family:sans-serif;text-align:center;padding-top:15vh;background:#f5f7fa;color:#333;\">"
                                "<h2>GeniusQA 服务启动中...</h2>"
                                "<p style=\"color:#888;\">按需服务正在拉起（MySQL / Redis / 后端），约 10-60 秒，页面将自动刷新。</p>"
                                "</body></html>").encode('utf-8')
                        client_sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: " + str(len(page)).encode() + b"\r\nConnection: close\r\n\r\n" + page)
                    except OSError:
                        pass
                    threading.Thread(target=ensure_services, daemon=True).start()
                    return
            _last_activity = time.time()
            upstream = socket.create_connection(("127.0.0.1", BACKEND_PORT), timeout=10)
            client_sock.settimeout(0.5)
            upstream.settimeout(0.5)
            sockets = [client_sock, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], 1.0)
                if not readable:
                    continue
                for s in readable:
                    try:
                        data = s.recv(65536)
                    except OSError:
                        data = b""
                    if not data:
                        return
                    target = upstream if s is client_sock else client_sock
                    try:
                        target.sendall(data)
                    except OSError:
                        return
                    _last_activity = time.time()
        except Exception as e:
            log(f"forward error: {e}")
        finally:
            try:
                client_sock.close()
            except OSError:
                pass


class ThreadingServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port

    def serve_forever(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(64)
        log(f"gateway listening on {self.host}:{self.port}, idle-stop after {IDLE_MINUTES} min")
        while True:
            try:
                conn, _ = srv.accept()
                threading.Thread(target=ForwardHandler().handle, args=(conn,), daemon=True).start()
            except OSError as e:
                log(f"accept error: {e}")
                time.sleep(1)


if __name__ == "__main__":
    log("=== gateway starting ===")
    threading.Thread(target=idle_monitor, daemon=True).start()
    ThreadingServer("0.0.0.0", LISTEN_PORT).serve_forever()
