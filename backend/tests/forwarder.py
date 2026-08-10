#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 消息转发器

监听群聊、频道、私聊及机器人消息，通过多层过滤条件将匹配的消息合并转发到QQ 邮箱。

功能：
  - 群组/频道监听：@提及、目标用户本人、回复目标用户、群组内指定用户
  - 私聊监听：支持用户白名单过滤
  - 机器人监听：支持指定机器人白名单
  - 置顶消息监听：检测群组/频道的置顶操作
  - 群组黑白名单、用户白名单、多层消息过滤
  - 消息合并发送（避免邮件轰炸）
  - 自动重连与异常恢复
  - 完善的日志系统
  - 支持 Docker / systemd 持续部署

用法：
  python forwarder.py                  # 使用默认 config.yaml
  python forwarder.py -c my_config.yaml  # 指定配置文件
  python forwarder.py --login            # 仅执行登录（首次认证）
"""

import os
import sys
import ssl
import smtplib
import asyncio
import logging
import signal
import argparse
import re
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

import yaml

# 设置 SQLite 连接参数，避免 Telethon session 数据库锁冲突
import sqlite3
import sqlite3.dbapi2 as _sqlite_dbapi2
import threading

_orig_sqlite_connect = sqlite3.connect

# 全局锁：确保同一时刻只有一个线程在执行 SQLite PRAGMA 设置
# 避免多个线程同时创建连接并争抢 PRAGMA 执行权
_sqlite_init_lock = threading.Lock()


# 在 patch 模块注入一个可选的 logger 引用，供后续设置使用（模块初始化时可能还没有 logger）
_patch_logger = None


def _patch_log(msg: str, level: str = "debug"):
    """向 patch 关联的 logger 发送日志（如果有的话）"""
    if _patch_logger:
        getattr(_patch_logger, level, _patch_logger.debug)(msg)


def _patched_sqlite_connect(*args, **kwargs):
    """SQLite 连接补丁：

    解决 Telethon session 数据库在断线重连/多协程并发场景下的database is locked问题

    策略：
    - journal_mode=DELETE（默认模式）：事务期间产生 .session-journal 临时文件，
      事务结束自动删除，不会常驻（避免 WAL 模式留下 .wal/.shm 文件）
    - busy_timeout=30000：锁冲突时等待最多 30 秒（覆盖重连风暴期）
    - synchronous=NORMAL：写入不强制 fsync，缩短锁持有时间
      （session 数据允许少量丢失，不会影响功能）
    - check_same_thread=False：允许跨线程共享连接
    """
    kwargs.setdefault("check_same_thread", False)

    conn = _orig_sqlite_connect(*args, **kwargs)

    is_session_db = any(
        kw in str(args[0]) for kw in ("session", "forwarder")
    ) if args else False

    # PRAGMA 设置加锁，避免多线程并发创建连接时的竞争
    with _sqlite_init_lock:
        for pragma_sql, label in [
            ("PRAGMA journal_mode=DELETE", "journal"),
            ("PRAGMA busy_timeout=30000", "busy_timeout"),
            ("PRAGMA synchronous=NORMAL", "synchronous"),
        ]:
            try:
                result = conn.execute(pragma_sql).fetchone()
                # fetchone() 返回单元素元组，如 ('delete',)，取第一个元素显示更清晰
                value = result[0] if result else None
                if is_session_db:
                    _patch_log(f"SQLite 连接 [{args[0] if args else '?'}] {label}={value}", "debug")
            except Exception as e:
                if is_session_db:
                    _patch_log(f"SQLite 连接 [{args[0] if args else '?'}] 设置 {label} 失败: {e}", "warning")

    return conn


sqlite3.connect = _patched_sqlite_connect  # type: ignore[assignment]
_sqlite_dbapi2.connect = _patched_sqlite_connect  # type: ignore[assignment]


def _cleanup_temp_files(session_path: str, logger: logging.Logger | None = None):
    """清理项目目录中的临时文件

    清理对象：
    - SQLite 残留临时文件: *.session-wal, *.session-shm, *.session-journal
      （DELETE 模式下正常运行不会产生这些文件，仅清理异常退出时的残留）
    - Python 缓存: __pycache__/ 目录
    - 编译缓存: *.pyc 文件

    安全说明：
    - .session 主文件是 Telethon 登录凭证，绝不会被删除
    - DELETE 模式下数据库事务结束会自动删除 .journal 文件，正常运行无残留
    - __pycache__ 是 Python 字节码缓存，需要时会自动重新生成
    """
    log = logger or logging.getLogger("tg_forwarder")
    db_path = Path(session_path + ".session")
    project_dir = db_path.parent

    cleaned = 0

    # 1. 清理 SQLite 残留的临时文件（仅异常退出才会残留）
    for ext in (".session-wal", ".session-shm", ".session-journal"):
        stale = project_dir / (db_path.stem + ext)
        if stale.exists():
            try:
                stale.unlink()
                log.info(f"清理 SQLite 临时文件: {stale.name}")
                cleaned += 1
            except PermissionError:
                # 文件被占用（脚本正在运行），跳过
                pass
            except Exception:
                pass

    # 2. 清理 __pycache__ 目录
    pycache_dir = project_dir / "__pycache__"
    if pycache_dir.exists():
        try:
            import shutil
            shutil.rmtree(pycache_dir)
            log.info("清理 Python 缓存目录: __pycache__/")
            cleaned += 1
        except PermissionError:
            pass
        except Exception:
            pass

    # 3. 清理项目根目录下的 *.pyc 文件（非递归，仅根目录）
    for pyc_file in project_dir.glob("*.pyc"):
        try:
            pyc_file.unlink()
            log.info(f"清理编译文件: {pyc_file.name}")
            cleaned += 1
        except Exception:
            pass

    if cleaned > 0:
        log.info(f"临时文件清理完成，共清理 {cleaned} 个文件/目录")
    else:
        log.debug("无临时文件需要清理")


def _recover_session_db(session_path: str, logger: logging.Logger | None = None):
    """启动前恢复并优化 session 数据库文件

    执行一次，确保 session 文件可正常打开且无残留锁，
    避免 'database is locked' 错误。

    策略（DELETE 模式，不再使用 WAL）：
    - 用超长 busy_timeout 打开数据库，确认无锁
    - 设置 synchronous=NORMAL 缩短锁持有时间
    - 清理可能残留的 .wal/.shm/.journal 临时文件（旧 WAL 模式遗留）
    """
    db_path = Path(session_path + ".session")
    if not db_path.exists():
        return

    log = logger or logging.getLogger("tg_forwarder")

    try:
        conn = sqlite3.connect(str(db_path), timeout=60)
        conn.execute("PRAGMA busy_timeout=60000")

        # 1) 强制使用 DELETE 模式（默认，不产生常驻临时文件）
        #    如果数据库之前是 WAL 模式，此处会切换回 DELETE，
        #    SQLite 会自动把 WAL 内容合并回主文件并删除 .wal/.shm
        old_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        new_mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        log.debug(f"Session 数据库 journal 模式: {old_mode} → {new_mode}")

        # 2) 设置其他优化参数
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA page_size=4096")

        conn.close()
        log.debug("Session 数据库恢复完成")

        # 3) 清理可能残留的临时文件（WAL 模式遗留的 .wal/.shm，
        #    以及异常退出可能残留的 .journal）
        for ext in (".session-wal", ".session-shm", ".session-journal"):
            stale = db_path.parent / (db_path.stem + ext)
            if stale.exists():
                try:
                    stale.unlink()
                    log.info(f"已清理残留的 session 临时文件: {stale.name}")
                except Exception:
                    pass

    except Exception as e:
        log.warning(f"Session 数据库恢复失败: {e}")
        log.warning("如果问题持续，请先停止程序，然后手动删除 session 文件重新登录")


def _delete_session_files(session_name: str, logger: logging.Logger | None = None):
    """删除 session 文件及其附属文件（journal/wal/shm），用于修复格式损坏的 session。

    当 Telethon 版本升级后旧 session 格式不再兼容时，调用此函数彻底
    清理并让下次连接时重新走登录流程。
    Windows 上 SQLite 可能未完全释放文件锁，会多次重试 + 渐增等待。
    """
    log = logger or logging.getLogger("tg_forwarder")
    base = session_name if session_name.endswith(".session") else session_name + ".session"
    base_path = Path(base)

    all_paths = [base_path] + sorted([
        p for suffix in (".journal", "-journal", "-wal", "-shm")
        for p in [Path(f"{base}{suffix}")] if p.exists()
    ], key=lambda p: p.stat().st_ctime if p.exists() else 0, reverse=True)

    # 先把所有存在的文件收集起来
    existing = [p for p in all_paths if p.exists()]
    if not existing:
        log.debug("没有需要清理的 session 文件")
        return

    files_removed = []
    for path in existing:
        filename = path.name
        for attempt in range(5):
            try:
                os.remove(str(path))
                files_removed.append(filename)
                if attempt > 0:
                    log.debug(f"删除 {filename} 成功（第{attempt+1}次尝试）")
                break
            except PermissionError:
                if attempt < 4:
                    log.warning(f"删除 {filename} 失败（文件被锁定），"
                                f"等待{(attempt+1)*0.5}秒后重试...")
                    time.sleep((attempt + 1) * 0.5)
                else:
                    log.error(f"无法删除 {filename}：文件已被锁定超过 5 次尝试，"
                              f"请手动关闭占用进程后重试")
            except Exception as e:
                log.warning(f"删除 {filename} 失败: {e}")
                break

    if files_removed:
        log.info(f"已清理 session 文件: {', '.join(files_removed)}")
    else:
        log.error("警告：未能清理任何 session 文件！建议手动删除后重试")


try:
    from telethon import TelegramClient, events
    from telethon.tl.types import (
        PeerUser, PeerChat, PeerChannel,
        MessageEntityMention, MessageEntityMentionName,
        User,
        # 通话事件
        UpdatePhoneCall,
        PhoneCallRequested,
        PhoneCallDiscarded,
        PhoneCallDiscardReasonMissed,
    )
    # 引入 Telethon 错误类，用于识别限流（FloodWait）和瞬时网络错误
    # 让重连逻辑能区分"等够 N 秒再连"与"指数退避"
    from telethon.errors import (
        FloodWaitError,
        SlowModeWaitError,
        ChatAdminRequiredError,
        ServerError,
    )
    # Telethon 超时类在 RPCErrorList 中名为 TimeoutError（不是 TimedOutError）
    from telethon.errors.rpcerrorlist import TimeoutError
except ImportError:
    print("错误：请先安装 telethon 库：pip install telethon")
    sys.exit(1)





# ============================================
# 配置加载
# ============================================
class Config:
    """配置管理器"""

    DEFAULT_CONFIG_PATH = "config.yaml"

    def __init__(self, config_path: str = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._config = {}
        self.load()

    def load(self):
        """加载配置文件"""
        config_file = Path(self.config_path)
        if not config_file.exists():
            print(f"错误：配置文件 {self.config_path} 不存在")
            print(f"请复制 config.yaml.example 为 config.yaml 并填写配置")
            sys.exit(1)

        with open(config_file, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}

        self._validate()

    def _validate(self):
        """验证必要配置项"""
        tg = self._config.get("telegram", {})
        if not tg.get("api_id") or not tg.get("api_hash"):
            raise ValueError("配置错误：telegram.api_id 和 telegram.api_hash 为必填项")
        if not tg.get("phone"):
            raise ValueError("配置错误：telegram.phone 为必填项（首次登录需要）")

        email = self._config.get("email", {})
        if not email.get("sender") or email.get("sender") == "your_qq@qq.com":
            raise ValueError("配置错误：请填写有效的 email.sender（QQ邮箱地址）")
        if not email.get("auth_code") or email.get("auth_code") == "your_auth_code_here":
            raise ValueError("配置错误：请填写有效的 email.auth_code（QQ邮箱授权码）")
        if not email.get("receiver"):
            raise ValueError("配置错误：请填写有效的 email.receiver（收件邮箱）")

        target = self._config.get("target_user", {})
        if not target.get("user_id"):
            raise ValueError("配置错误：target_user.user_id 为必填项")

    # 便捷属性访问
    @property
    def api_id(self) -> int:
        return int(self._config["telegram"]["api_id"])

    @property
    def api_hash(self) -> str:
        return self._config["telegram"]["api_hash"]

    @property
    def phone(self) -> str:
        return self._config["telegram"]["phone"]

    @property
    def session_name(self) -> str:
        """获取 session 文件路径，Docker 环境自动使用 /app/data/ 目录"""
        name = self._config["telegram"].get("session_name", "forwarder_session")
        # 如果 /app/data 目录存在（Docker环境），session 存放到数据持久化目录
        data_dir = Path("/app/data")
        if data_dir.exists():
            return str(data_dir / name)
        return name

    @property
    def target_user_id(self) -> int:
        return int(self._config["target_user"]["user_id"])

    @property
    def target_username(self) -> str:
        return self._config["target_user"].get("username", "")

    @property
    def email_sender(self) -> str:
        return self._config["email"]["sender"]

    @property
    def email_auth_code(self) -> str:
        return self._config["email"]["auth_code"]

    @property
    def email_receiver(self) -> str:
        return self._config["email"]["receiver"]

    @property
    def smtp_server(self) -> str:
        return self._config["email"].get("smtp_server", "smtp.qq.com")

    @property
    def smtp_port(self) -> int:
        return int(self._config["email"].get("smtp_port", 465))

    @property
    def use_ssl(self) -> bool:
        return self._config["email"].get("use_ssl", True)

    @property
    def smtp_use_proxy(self) -> bool:
        """SMTP 是否使用代理，默认 false 直连 SMTP"""
        return self._config.get("email", {}).get("smtp_use_proxy", False)

    @property
    def only_mentions(self) -> bool:
        return self._config.get("filter", {}).get("only_mentions", True)

    @property
    def include_replies(self) -> bool:
        return self._config.get("filter", {}).get("include_replies", False)

    @property
    def monitor_pinned_messages(self) -> bool:
        return self._config.get("filter", {}).get("monitor_pinned_messages", False)

    @property
    def monitor_calls(self) -> bool:
        """是否监听目标用户的音频/视频通话"""
        return self._config.get("filter", {}).get("monitor_calls", False)

    @property
    def monitored_bots(self) -> list:
        """监听的机器人列表（username 或 ID），为空则不监听任何机器人"""
        return self._config.get("filter", {}).get("monitored_bots", [])

    @property
    def monitored_groups(self) -> list:
        return self._config.get("filter", {}).get("monitored_groups", [])

    @property
    def ignored_groups(self) -> list:
        return self._config.get("filter", {}).get("ignored_groups", [])

    @property
    def monitor_private_chats(self) -> bool:
        return self._config.get("filter", {}).get("monitor_private_chats", False)

    @property
    def monitored_users(self) -> list:
        return self._config.get("filter", {}).get("monitored_users", [])

    @property
    def monitored_group_users(self) -> list:
        """群组内指定用户监听列表

        格式: [{"group": -100xxx, "users": ["@user1", 123456]}, ...]
        用于监听特定群组中特定用户的所有消息并独立转发。
        """
        return self._config.get("filter", {}).get("monitored_group_users", [])

    @property
    def service_notification_enabled(self) -> bool:
        """是否启用服务通知监听（如 Telegram 登录验证码）"""
        return self._config.get("filter", {}).get("service_notification", {}).get("enabled", False)

    @property
    def service_notification_user_id(self) -> int:
        """Telegram 服务通知账号 ID（默认 777000 为官方服务通知）"""
        return int(self._config.get("filter", {}).get("service_notification", {}).get("service_user_id", 777000))

    @property
    def service_notification_keywords(self) -> list:
        """服务通知触发关键词列表（不区分大小写）"""
        return self._config.get("filter", {}).get("service_notification", {}).get("keywords", [])

    @property
    def monitor_group_calls(self) -> bool:
        """是否监听群组语音/视频聊天"""
        return self._config.get("filter", {}).get("monitor_group_calls", False)

    @property
    def merge_interval(self) -> int:
        return int(self._config.get("mail_settings", {}).get("merge_interval", 30))

    @property
    def max_messages_per_email(self) -> int:
        return int(self._config.get("mail_settings", {}).get("max_messages_per_email", 50))

    @property
    def max_wait(self) -> int:
        """缓冲区最大等待时间（秒）：自首条消息起计时，到点强制发送，
        防止消息密集时定时器被反复重置导致邮件迟迟不发。默认 60 秒。"""
        return int(self._config.get("mail_settings", {}).get("max_wait", 60))

    @property
    def subject_prefix(self) -> str:
        return self._config.get("mail_settings", {}).get("subject_prefix", "[TG转发]")

    @property
    def include_message_link(self) -> bool:
        return self._config.get("mail_settings", {}).get("include_message_link", True)

    @property
    def log_level(self) -> str:
        return self._config.get("logging", {}).get("level", "INFO")

    @property
    def log_file(self) -> str:
        return self._config.get("logging", {}).get("file", "forwarder.log")

    @property
    def log_max_size_mb(self) -> int:
        return int(self._config.get("logging", {}).get("max_size_mb", 10))

    @property
    def log_backup_count(self) -> int:
        return int(self._config.get("logging", {}).get("backup_count", 5))

    @property
    def reconnect_delay(self) -> int:
        return int(self._config.get("runtime", {}).get("reconnect_delay", 30))

    @property
    def connect_timeout(self) -> int:
        """连接 Telegram 的超时时间（秒），超时后自动重试，避免卡在「正在连接」"""
        return int(self._config.get("runtime", {}).get("connect_timeout", 30))

    @property
    def proxy(self) -> tuple | None:
        """获取代理配置，返回 (protocol, host, port, username, password) 或 None"""
        proxy = self._config.get("telegram", {}).get("proxy", {})
        if not proxy or not proxy.get("host") or not proxy.get("port"):
            return None
        return (
            proxy.get("protocol", "socks5"),
            proxy["host"],
            int(proxy["port"]),
            proxy.get("username", ""),
            proxy.get("password", ""),
        )

    @property
    def max_reconnects(self) -> int:
        return int(self._config.get("runtime", {}).get("max_reconnects", 0))


# ============================================
# 日志系统
# ============================================
def setup_logging(config: Config):
    """配置日志系统"""
    # 过滤 stderr 中的 Windows 系统级噪音（SQLite/Telethon 底层 C 代码直输）
    class _FilteredStderr:
        _NOISE_PATTERNS = (
            "The filename, directory name, or volume label syntax is incorrect",
            "filename, directory name, or volume label syntax",
        )
        def __init__(self, original):
            self._original = original
            self._buffer = ""
        def write(self, data):
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            self._buffer += data
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                stripped = line.rstrip()
                if not any(p in stripped.lower() for p in self._NOISE_PATTERNS):
                    self._original.write(line + "\n")
        def flush(self): self._original.flush()
        def __getattr__(self, name): return getattr(self._original, name)

    sys.stderr = _FilteredStderr(sys.stderr)

    logger = logging.getLogger("tg_forwarder")
    logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))
    logger.handlers.clear()

    # 控制台输出（替换无法在 Windows GBK 中显示的字符，避免 UnicodeEncodeError）
    class SafeStreamHandler(logging.StreamHandler):
        """安全的控制台处理器：替换不可编码字符而非抛异常"""
        def emit(self, record):
            try:
                super().emit(record)
            except UnicodeEncodeError:
                # 失败时用 ? 替换不可编码字符重试
                msg = self.format(record)
                try:
                    stream = self.stream
                    # 记录原始编码错误，避免无限递归
                    safe = msg.encode("gbk", errors="replace").decode("gbk", errors="replace")
                    stream.write(safe + self.terminator)
                    self.flush()
                except Exception:
                    self.handleError(record)

    console_handler = SafeStreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))
    console_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # 文件输出（轮转）
    file_handler = RotatingFileHandler(
        config.log_file,
        maxBytes=config.log_max_size_mb * 1024 * 1024,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    # 屏蔽 Telethon 库的 WARNING 级别日志，仅显示 ERROR
    logging.getLogger("telethon").setLevel(logging.ERROR)

    return logger


# ============================================
# 邮件发送器（smtplib + 独立线程 + SOCKS5 代理）
# ============================================
class EmailSender:
    """QQ 邮箱发送器

    核心设计（最终方案，经过多轮验证）：
    - 使用标准库 smtplib（同步、稳定、久经考验）
    - **每次发送创建全新独立线程**，不用 ThreadPoolExecutor 线程池复用
      （Windows 平台上线程池复用会导致：线程状态残留、monkey-patch 污染、
       run_in_executor 任务不调度等诡异问题）
    - **SMTP 连接走 SOCKS5 代理**（与 Telegram 共用代理配置），绕过 Clash TUN
    - **全局锁 _smtp_lock** 确保 monkey-patch socket.socket 的原子性
    - **asyncio.wait_for(timeout=90)** 超时保护，防止任何情况下永久挂起
    - 线程内使用 logging 模块写日志（Python logging 线程安全），
      确保 SMTP 日志同时输出到控制台和文件
    - socket.setdefaulttimeout(30) 全局兜底
    """

    _last_send_time = 0.0
    # 全局锁：确保同一时刻只有一个线程在 monkey-patch socket.socket
    # （即使每次用新线程，也需要这把锁保证原子性）
    _smtp_lock = None

    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        if EmailSender._smtp_lock is None:
            EmailSender._smtp_lock = threading.Lock()

    async def send_email(self, subject: str, html_body: str) -> bool:
        """异步发送邮件：构建邮件 → 创建新线程执行 SMTP → 等待结果

        关键：使用 concurrent.futures.Future + 新线程 + call_soon_threadsafe，
        完全绕过 ThreadPoolExecutor，避免 Windows 平台上线程池复用的所有问题。
        """
        import concurrent.futures as _futures

        # 频率控制：每封邮件至少间隔 5 秒
        _now = time.time()
        _since_last = _now - EmailSender._last_send_time
        if _since_last < 5:
            _wait = 5 - _since_last
            await asyncio.sleep(_wait)

        _send_start = time.time()
        loop = asyncio.get_event_loop()

        # 构建邮件（在主协程中完成，避免在线程中重复构建）
        msg = MIMEMultipart("alternative")
        msg["From"] = self.config.email_sender
        msg["To"] = self.config.email_receiver
        msg["Subject"] = subject
        text_body = self._html_to_plain(html_body)
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # === 创建 Future + 独立线程，完全绕过 ThreadPoolExecutor ===
        future = _futures.Future()

        def _worker_thread():
            """独立工作线程：获取锁 → monkey-patch → SMTP → 恢复 → 设置结果"""
            try:
                result = self._do_send_sync(msg, subject, _send_start)
                # 安全地设置结果：如果 Future 已被取消/完成（超时或任务取消），忽略
                if not future.done():
                    loop.call_soon_threadsafe(future.set_result, result)
                else:
                    self.logger.debug(f"SMTP 线程已完成但 Future 已取消，跳过 set_result")
            except Exception as exc:
                if not future.done():
                    loop.call_soon_threadsafe(future.set_exception, exc)

        thread = threading.Thread(
            target=_worker_thread,
            name=f"smtp-send-{int(time.time() % 10000)}",
            daemon=True,  # daemon 线程，程序退出时不阻塞
        )
        thread.start()
        self.logger.debug(f"已启动 SMTP 发送线程: {thread.name}")

        try:
            # 将 concurrent.future 包装为 asyncio.Future，加 90 秒超时保护
            async_future = asyncio.wrap_future(future)
            success = await asyncio.wait_for(async_future, timeout=90)
            if success:
                EmailSender._last_send_time = time.time()
                _elapsed = time.time() - _send_start
                self.logger.info(f"邮件已发送：{subject}（耗时{_elapsed:.1f}秒）")
            return success
        except asyncio.TimeoutError:
            _elapsed = time.time() - _send_start
            self.logger.error(f"邮件发送超时（{_elapsed:.0f}秒）：{subject}，SMTP 无响应")
            return False
        except Exception as e:
            _elapsed = time.time() - _send_start
            self.logger.error(f"邮件发送失败（耗时{_elapsed:.0f}秒）：{e}")
            return False

    def _do_send_sync(self, msg: MIMEMultipart, subject: str, send_start: float) -> bool:
        """同步 SMTP 发送（运行在专用线程中，由 _smtp_lock 串行化）

        关键点：
        1. 通过 SOCKS5 代理连接 SMTP，绕过 Clash TUN 的流量拦截
        2. 线程内 monkey-patch socket → socks.socksocket，发送完后恢复
           （_smtp_lock 确保同一时刻只有一个线程在做这件事，避免竞态）
        3. socket.setdefaulttimeout(30) 全局兜底
        4. 线程内使用 logging（Python logging 模块是线程安全的，可跨线程使用）
        """
        import socket as _socket
        import socks as _socks

        # 线程内日志：使用 logging 模块（线程安全），同时输出到控制台和文件
        _smtp_logger = self.logger.getChild("smtp")

        # 获取代理配置（仅当 smtp_use_proxy=True 时才走代理）
        proxy = self.config.proxy
        proxy_host = proxy[1] if proxy else None
        proxy_port = proxy[2] if proxy else None
        proxy_user = proxy[3] if proxy and len(proxy) > 3 and proxy[3] else None
        proxy_pass = proxy[4] if proxy and len(proxy) > 4 and proxy[4] else None
        if not self.config.smtp_use_proxy:
            proxy_host = None  # 强制直连，不走代理

        # === 获取全局锁：确保 monkey-patch socket.socket 的原子性 ===
        _smtp_logger.debug("获取 SMTP 发送锁...")
        EmailSender._smtp_lock.acquire()
        _smtp_logger.debug("已获取锁，开始连接")

        # 用变量保存返回值（不用 return，确保 finally 块一定执行释放锁）
        _result = False
        _orig_socket = _socket.socket
        smtp = None

        try:
            _socket.setdefaulttimeout(30)

            # Monkey-patch：让所有 socket 操作走 SOCKS5 代理
            if proxy_host:
                _smtp_logger.info(f"通过 SOCKS5 代理连接 SMTP {self.config.smtp_server}:{self.config.smtp_port}（代理 {proxy_host}:{proxy_port}）")
                if proxy_user:
                    _socks.set_default_proxy(_socks.SOCKS5, proxy_host, proxy_port, username=proxy_user, password=proxy_pass)
                else:
                    _socks.set_default_proxy(_socks.SOCKS5, proxy_host, proxy_port)
                _socket.socket = _socks.socksocket
            else:
                _smtp_logger.info(f"直连 SMTP {self.config.smtp_server}:{self.config.smtp_port}（无代理）")

            if self.config.use_ssl:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                smtp = smtplib.SMTP_SSL(
                    host=self.config.smtp_server,
                    port=self.config.smtp_port,
                    timeout=30,
                    context=ctx,
                    local_hostname="localhost",
                )
            else:
                smtp = smtplib.SMTP(
                    host=self.config.smtp_server,
                    port=self.config.smtp_port,
                    timeout=30,
                    local_hostname="localhost",
                )
                smtp.starttls()

            _smtp_logger.debug("SMTP 连接成功，正在登录...")

            smtp.login(self.config.email_sender, self.config.email_auth_code)
            _smtp_logger.debug("SMTP 登录成功，正在发送邮件...")

            smtp.sendmail(
                self.config.email_sender,
                [self.config.email_receiver],
                msg.as_string(),
            )
            _smtp_logger.debug("SMTP sendmail 完成")

            try:
                smtp.quit()
            except Exception:
                pass
            smtp = None

            _elapsed = time.time() - send_start
            _smtp_logger.info(f"邮件发送成功（耗时{_elapsed:.1f}秒）：{subject}")
            _result = True

        except smtplib.SMTPAuthenticationError:
            _smtp_logger.error("SMTP 认证失败：请检查邮箱地址和授权码")
        except smtplib.SMTPException as e:
            _smtp_logger.error(f"SMTP 错误：{e}")
        except (TimeoutError, OSError) as e:
            _smtp_logger.error(f"网络错误：{e}")
        except Exception as e:
            _smtp_logger.error(f"未知错误：{e}")
        finally:
            # === 无论成功/失败，都必须恢复原始 socket 并释放锁 ===
            if smtp is not None:
                try:
                    smtp.close()
                except Exception:
                    pass
            _socket.socket = _orig_socket
            _socket.setdefaulttimeout(None)
            EmailSender._smtp_lock.release()
            _smtp_logger.debug("已恢复 socket 并释放锁")

        return _result

    @staticmethod
    def _html_to_plain(html: str) -> str:
        """简单的 HTML 转纯文本（去除标签）"""
        text = re.sub(r"<br\s*/?>", "\n", html)
        text = re.sub(r"</p>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&amp;", "&", text)
        return text.strip()


# ============================================
# 消息缓冲区（合并发送）
# ============================================
class MessageBuffer:
    """
    消息合并缓冲区
    将同一群组的消息在指定时间窗口内合并为一封邮件发送
    """

    def __init__(self, config: Config, email_sender: EmailSender, logger: logging.Logger):
        self.config = config
        self.email_sender = email_sender
        self.logger = logger

        # 每个群组的待发送消息队列
        # key: group_id, value: list of message dicts
        self._buffers: dict[int, list] = defaultdict(list)
        # 每个群组的定时器任务
        self._timers: dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()
    async def add_message(self, group_id: int, group_name: str, message_data: dict):
        """添加一条消息到缓冲区"""
        async with self._lock:
            self._buffers[group_id].append(message_data)

            # 日志输出：摘要信息
            sender = message_data.get("sender_name", "未知")
            raw_text = (message_data.get("text", "") or "")
            # 将 [名](tg://user?id=xxx) 转为 @[名]（仅用于日志展示）
            log_text = re.sub(r'\[([^\]]*)\]\(tg://user\?id=\d+\)', r'@[\1]', raw_text)
            # 去除 Markdown 加粗标记 **text**
            log_text = re.sub(r'\*\*([^*]+)\*\*', r'\1', log_text)
            text_preview = log_text.replace("\n", " ")[:60]
            reason = message_data.get("reason", "")
            is_reply = message_data.get("is_reply_to_target", False)
            reply_to_sender = message_data.get("reply_to_sender", "")
            is_mention = message_data.get("is_mention", False)
            is_pinned = message_data.get("is_pinned", False)
            is_edited = message_data.get("is_edited", False)

            # 非文本消息 → 补充媒体类型描述
            media_info = message_data.get("media_info", {})
            media_type = media_info.get("type", "none")
            media_str = ""
            if media_type != "none":
                icon = media_info.get("icon", "")
                label = media_info.get("label", "")
                extra = ""
                dur = media_info.get("duration")
                if dur:
                    extra += f" {int(dur)}秒"
                fname = media_info.get("filename", "")
                if fname and media_type not in ("photo", "sticker"):
                    extra += f" {fname}"
                if icon and label:
                    media_str = f"{icon} {label}{extra}"
                elif label:
                    media_str = f"{label}{extra}"

            # 如果文本为空但媒体有描述，用媒体描述代替
            if not text_preview.strip() and media_str:
                text_preview = media_str

            # 确定消息类型前缀（按优先级）
            if is_pinned:
                type_tag = "置顶"
            elif "机器人" in reason:
                type_tag = "机器人"
            elif is_mention:
                type_tag = "@提及"
            elif is_reply or reply_to_sender:
                type_tag = "回复"
            elif reason == "私聊消息":
                type_tag = "私信"
            else:
                type_tag = "消息"

            # 回复引用内容
            quote_str = ""
            replied_sender = ""
            if reply_to_sender:
                parts = reply_to_sender.split(" | ", 1)
                replied_sender = parts[0] if parts else ""
                replied_content = parts[1] if len(parts) > 1 else ""
                if replied_content:
                    quote_str = f' ↩ "{replied_content[:40]}"'
                else:
                    quote_str = f" ↩ {replied_sender}"

            if is_reply or reply_to_sender:
                edit_prefix = "编辑 " if is_edited else ""
                self.logger.info(f"[{type_tag}] {group_name} | {sender}回复{replied_sender}: {edit_prefix}{text_preview}{quote_str}")
            elif is_mention:
                edit_prefix = "编辑 " if is_edited else ""
                self.logger.info(f"[{type_tag}] {group_name} | {sender} {edit_prefix}{text_preview}")
            elif is_pinned:
                edit_prefix = "编辑 " if is_edited else ""
                pinned_by = message_data.get("pinned_by", "")
                # 日志输出简洁格式（去掉 [身份角色] 前缀）
                _log_pinned_by = pinned_by.split("] ", 1)[-1] if "] " in pinned_by else pinned_by
                _log_sender = sender.split("] ", 1)[-1] if "] " in sender else sender
                self.logger.info(f"[{type_tag}] {group_name} | {_log_pinned_by} 置顶 {_log_sender}: {edit_prefix}{text_preview}")
            elif reason == "私聊消息":
                edit_prefix = "编辑 " if is_edited else ""
                self.logger.info(f"[{type_tag}] {sender} : {edit_prefix}{text_preview}")
            else:
                edit_prefix = "编辑 " if is_edited else ""
                self.logger.info(f"[{type_tag}] {group_name} | {sender}: {edit_prefix}{text_preview}")
            self.logger.debug(
                f"消息已缓冲：群组[{group_name}] 当前缓冲数={len(self._buffers[group_id])}"
            )

            # 如果达到最大消息数，立即发送
            if len(self._buffers[group_id]) >= self.config.max_messages_per_email:
                await self._flush_group(group_id, group_name)
                return

            # 如果合并间隔为0，立即发送
            if self.config.merge_interval <= 0:
                await self._flush_group(group_id, group_name)
                return

            # 启动定时器（仅在该群组尚无待执行定时器时启动）。
            # 后续消息只追加进缓冲区，不再重置定时器，
            # 保证最迟 max_wait 秒必然发送，避免消息密集时定时器被
            # 反复重置导致邮件迟迟不发（节流饥饿）。
            if group_id not in self._timers or self._timers[group_id].done():
                self._timers[group_id] = asyncio.create_task(
                    self._delayed_flush(group_id, group_name)
                )

    async def _delayed_flush(self, group_id: int, group_name: str):
        """延迟刷新缓冲区：自首条消息起等待 max_wait 秒后强制发送"""
        try:
            await asyncio.sleep(self.config.max_wait)
            self.logger.info(f"定时器触发，准备发送邮件：{group_name}")
            async with self._lock:
                await self._flush_group(group_id, group_name)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"定时发送邮件失败：{group_name} - {e}", exc_info=True)


    async def _flush_group(self, group_id: int, group_name: str):
        """刷新指定群组的缓冲区，发送邮件"""
        messages = self._buffers.pop(group_id, [])
        if group_id in self._timers:
            timer = self._timers.pop(group_id)
            if not timer.done():
                timer.cancel()

        if not messages:
            return

        # 标题格式化规则：
        #   私聊消息 → "[Telegram] 私聊 - 用户名"
        #   机器人消息 → "[Telegram] Robot 机器人名"
        #   群聊消息  → "[Telegram] 群组名"
        display_name = group_name
        subject = f"{self.config.subject_prefix} {display_name}"

        self.logger.info(f"开始发送邮件：{subject}（共{len(messages)}条消息）")

        try:
            html_body = self._build_email_html(group_name, messages)
        except Exception as e:
            self.logger.error(f"构建邮件HTML失败：{group_name} - {e}", exc_info=True)
            # 消息重新放回缓冲区
            self._buffers[group_id] = messages + self._buffers.get(group_id, [])
            return

        success = await self.email_sender.send_email(subject, html_body)
        if not success:
            # 发送失败，将消息重新放回缓冲区等待下次触发
            self.logger.error(
                f"邮件发送失败，消息已重新放回缓冲区：{group_name}"
            )
            self._buffers[group_id] = messages + self._buffers.get(group_id, [])

    async def flush_all(self):
        """刷新所有缓冲区"""
        async with self._lock:
            for group_id in list(self._buffers.keys()):
                group_name = self._buffers[group_id][0].get("group_name", str(group_id)) if self._buffers[group_id] else str(group_id)
                await self._flush_group(group_id, group_name)

    def _build_email_html(self, group_name: str, messages: list) -> str:
        """构建邮件 HTML 内容"""
        tz_shanghai = timezone(timedelta(hours=8))
        now = datetime.now(tz_shanghai).strftime("%Y-%m-%d %H:%M:%S")

        logo_tag = '📨'

        html_parts = [
            '<!DOCTYPE html>',
            '<html><head><meta charset="utf-8"></head>',
            '<body style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; '
            'max-width: 800px; margin: 0 auto; padding: 16px; background-color: #f0f2f5;">',
            f'<div style="background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">',
            f'<h2 style="color: #0088cc; margin: 0 0 8px; border-bottom: 2px solid #e1f5fe; padding-bottom: 10px; font-size: 18px;">'
            f'{logo_tag} {self.config.subject_prefix} {group_name}</h2>',
            # 消息数量 > 1 时才显示"生成时间 / 消息数量"，单条时隐藏（与消息时间戳重复）
            f'<p style="color: #888; font-size: 12px; margin: 0 0 12px 0;">生成时间：{now} | 消息数量：{len(messages)}</p>' if len(messages) > 1 else '',
            '<hr style="border: none; border-top: 1px solid #e0e0e0; margin: 8px 0;">',
        ]

        for i, msg in enumerate(messages, 1):
            sender = msg.get("sender_name", "未知用户")
            text = msg.get("text", "")
            timestamp = msg.get("timestamp", "")
            msg_link = msg.get("message_link", "")
            reply_to = msg.get("reply_to_sender", "")
            is_mention = msg.get("is_mention", False)

            mention_badge = (
                '<span style="background: #0088cc; color: white; padding: 2px 8px; '
                'border-radius: 4px; font-size: 11px; margin-left: 6px;">@提及</span>'
                if is_mention else ""
            )

            # 媒体类型标签（图片/视频/语音/文件等）
            media_info = msg.get("media_info", {})
            media_type = media_info.get("type", "none")
            media_badge = ""

            # 置顶消息特殊标签
            is_pinned = msg.get("is_pinned", False)
            pinned_by = msg.get("pinned_by", "")
            pin_badge = ""
            if is_pinned:
                # 检查置顶者是否为发送者本人：精简"由 XXX"冗余
                _sender_core = sender.split("] ", 1)[-1] if "] " in sender else sender
                _pinner_core = pinned_by.split("] ", 1)[-1] if "] " in pinned_by else pinned_by
                _same_pinner = (
                    pinned_by and (_sender_core == _pinner_core
                                   or _sender_core in _pinner_core
                                   or _pinner_core in _sender_core)
                )
                pin_text = "📌 置顶消息"
                if pinned_by and not _same_pinner:
                    pin_text += f"（由 {self._escape_html(pinned_by)} 置顶）"
                pin_badge = (
                    f'<span style="display: inline-block; background: #fff3e0; color: #e65100; '
                    f'padding: 3px 10px; border-radius: 4px; font-size: 11px; '
                    f'margin-left: 6px;">{pin_text}</span>'
                )

            # 机器人消息特殊标签
            is_bot_msg = msg.get("is_bot_msg", False)
            bot_badge = ""
            if is_bot_msg:
                bot_badge = (
                    f'<span style="display: inline-block; background: #e8f5e9; color: #2e7d32; '
                    f'padding: 3px 10px; border-radius: 4px; font-size: 11px; '
                    f'margin-left: 6px;">🤖 机器人消息</span>'
                )

            # 编辑消息标签 + 原消息内容
            is_edited = msg.get("is_edited", False)
            original_text = msg.get("original_text", "")
            edit_badge = ""
            edit_diff_html = ""  # 原消息与新消息对比HTML
            if is_edited:
                if original_text:
                    # 有原消息：显示详细对比
                    edit_badge = (
                        f'<span style="display: inline-block; background: #fff8e1; color: #f57c00; '
                        f'padding: 2px 8px; border-radius: 4px; font-size: 11px; '
                        f'margin-left: 6px;">✏️ 已编辑</span>'
                    )
                    escaped_original = self._escape_html(re.sub(r'\*\*([^*]+)\*\*', r'\1', original_text))
                    edit_diff_html = (
                        f'<div style="margin-top: 8px; padding: 8px 10px; background: #fffde7; '
                        f'border-radius: 4px; border-left: 3px solid #fbc02d;">'
                        f'<div style="font-size: 11px; color: #f57c00; margin-bottom: 4px; '
                        f'font-weight: 500;">📝 原消息内容：</div>'
                        f'<div style="color: #666; line-height: 1.5; word-break: break-word; '
                        f'white-space: pre-wrap; font-size: 12px; text-decoration: line-through; '
                        f'opacity: 0.75;">{escaped_original}</div></div>'
                    )
                else:
                    # 无原消息记录（可能是首次运行或缓存已清理）
                    edit_badge = (
                        f'<span style="display: inline-block; background: #fff8e1; color: #f57c00; '
                        f'padding: 2px 8px; border-radius: 4px; font-size: 11px; '
                        f'margin-left: 6px;">✏️ 编辑</span>'
                    )

            if media_type != "none":
                icon = self._escape_html(media_info.get("icon", ""))
                label = self._escape_html(media_info.get("label", ""))
                size = self._escape_html(media_info.get("size_human", ""))
                dur = ""
                if media_info.get("duration") is not None:
                    dur = f"{int(media_info['duration'])}秒"
                badge_parts = [f"{icon} {label}"] if (icon and label) else []
                if size and size != "0 B" and media_type not in ("photo", "sticker"):
                    badge_parts.append(size)
                if dur:
                    badge_parts.append(dur)
                if badge_parts:
                    bg_colors = {
                        "photo": "#e3f2fd", "video": "#fff3e0", "voice": "#f3e5f5",
                        "audio": "#fce4ec", "document": "#f1f8e9", "sticker": "#fce4ec",
                        "gif": "#fff8e1",
                        "geo": "#e8f5e9", "contact": "#eceff1", "poll": "#e0f2fe1",
                        "game": "#fce4ec", "webpage": "#f3e5f5",
                    }
                    text_colors = {
                        "photo": "#1565c0", "video": "#ef6c00", "voice": "#7b1fa2",
                        "audio": "#c62828", "document": "#558b2f", "sticker": "#c62828",
                        "gif": "#f9a825",
                        "geo": "#2e7d32", "contact": "#455a64", "poll": "#0277bd",
                        "game": "#c62828", "webpage": "#7b1fa2",
                    }
                    bg = bg_colors.get(media_type, "#f0f0f0")
                    tc = text_colors.get(media_type, "#666")
                    media_badge = (
                        f'<span style="display: inline-block; background: {bg}; color: {tc}; '
                        f'padding: 2px 7px; border-radius: 4px; font-size: 11px; '
                        f'margin-left: 5px;">{" · ".join(badge_parts)}</span>'
                    )

            reply_info = ""
            if reply_to:
                # reply_to 格式: "发送者名 | 消息内容" 或 "发送者名" 或 "发送者名 | [媒体类型]"
                parts = reply_to.split(" | ", 1)
                sender_name = self._escape_html(parts[0]) if parts else ""
                reply_content = self._escape_html(parts[1]) if len(parts) > 1 else ""

                if reply_content:
                    reply_info = (
                        f'<div style="background: #f5f7fa; border-radius: 4px; padding: 8px 10px; '
                        f'margin-bottom: 6px; border-left: 3px solid #b0bec5;">'
                        f'<div style="color: #78909c; font-size: 11px; margin-bottom: 3px;">'
                        f'↩ 回复 {sender_name} 的消息：</div>'
                        f'<div style="color: #455a64; font-size: 13px; line-height: 1.4; word-break: break-word;">'
                        f'{reply_content}</div></div>'
                    )
                else:
                    reply_info = (
                        f'<div style="color: #888; font-size: 12px; margin-bottom: 4px; '
                        f'border-left: 2px solid #ddd; padding-left: 8px;">'
                        f'↩ 回复 {sender_name}</div>'
                    )

            # 消息内容区域（位置消息特殊渲染：可点击地图链接）
            content_html = ""
            if media_type == "geo" and media_info.get("geo_url"):
                geo_url = media_info["geo_url"]
                geo_title = media_info.get("geo_title", "")
                geo_addr = media_info.get("geo_address", "")
                geo_lat = media_info.get("geo_lat")
                geo_lng = media_info.get("geo_lng")

                coord_str = ""
                if geo_lat is not None and geo_lng is not None:
                    coord_str = f"{geo_lat:.6f}, {geo_lng:.6f}"

                # 构建地图预览卡片
                map_card = f'''
                    <div style="background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
                               padding: 10px 12px; border-radius: 6px; border-left: 4px solid #4caf50;">
                        <div style="font-size: 20px; margin-bottom: 4px;">📍</div>
                        <a href="{geo_url}" target="_blank"
                           style="color: #2e7d32; font-weight: bold;
                                  text-decoration: none; display: inline-block; font-size: 13px;">
                            🗺️ 在 Google 地图中打开
                        </a>'''

                if geo_title or geo_addr:
                    detail_parts = []
                    if geo_title:
                        detail_parts.append(geo_title)
                    if geo_addr and geo_addr != geo_title:
                        detail_parts.append(geo_addr)
                    if coord_str:
                        detail_parts.append(coord_str)
                    map_card += f'<div style="color: #558b2f; font-size: 12px; margin-top: 4px;">'
                    map_card += " · ".join(detail_parts)
                    map_card += "</div>"
                elif coord_str:
                    map_card += f'<div style="color: #558b2f; font-size: 12px; margin-top: 4px;">坐标：{coord_str}</div>'
                map_card += "</div>"
                content_html = map_card
            elif media_type == "poll" and media_info.get("poll_question"):
                # 投票卡片：显示消息正文 + 投票标题、各选项及票数、进度条
                # 使用单行拼接避免缩进空格，使用 table 布局提升邮件客户端兼容性
                poll_q = self._escape_html(media_info["poll_question"])
                poll_opts = media_info.get("poll_options", [])
                poll_total = media_info.get("poll_total_voters", 0)
                poll_body = media_info.get("poll_body_text", "")

                # 构建选项行（使用 table 布局）
                opt_rows = ""
                for opt in poll_opts:
                    opt_name = self._escape_html(opt.get("option", ""))
                    opt_voters = opt.get("voters", 0)
                    opt_pct = opt.get("pct", 0)
                    bar_w = int(opt_pct)
                    # 进度条：用表格单元格 + 背景色宽度模拟
                    bar_html = (
                        f'<table cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;">'
                        f'<tr>'
                        f'<td style="background:#e8e8e8;height:6px;border-radius:3px;padding:0;width:100%;">'
                        f'<div style="background:#43a047;height:6px;border-radius:3px;width:{bar_w}%;"></div>'
                        f'</td>'
                        f'</tr>'
                        f'</table>'
                    )
                    opt_rows += (
                        f'<tr>'
                        f'<td style="font-size:13px;color:#333;padding:4px 0 2px 0;">{opt_name}</td>'
                        f'<td style="font-size:13px;color:#888;text-align:right;padding:4px 0 2px 6px;white-space:nowrap;" align="right">{opt_voters} 票</td>'
                        f'</tr>'
                        f'<tr>'
                        f'<td colspan="2" style="padding:0 0 4px 0;">{bar_html}</td>'
                        f'</tr>'
                    )

                body_html = ""
                if poll_body:
                    body_html = f'<div style="color:#333;font-size:14px;line-height:1.5;margin:0 0 6px 0;padding:8px 10px;background:#fff;border-radius:4px;word-break:break-word;">{self._escape_html(poll_body)}</div>'

                poll_card = (
                    f'<div style="background:#e3f2fd;padding:12px 14px;border-radius:6px;border-left:4px solid #1e88e5;margin:4px 0;">'
                    f'{body_html}'
                    f'<div style="font-size:14px;font-weight:bold;color:#1565c0;margin:0 0 6px 0;">📊 {poll_q}</div>'
                    f'<table cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;">{opt_rows}</table>'
                    f'<div style="color:#78909c;font-size:11px;margin:6px 0 0 0;">共 {poll_total} 人参与投票</div>'
                    f'</div>'
                )
                content_html = poll_card
            elif media_type == "webpage" and media_info.get("wp_url"):
                # 链接预览卡片：显示标题、描述、可点击链接（优先于原始 URL 文本）
                wp_url = media_info["wp_url"]
                wp_title = media_info.get("wp_title", "")
                wp_desc = media_info.get("wp_description", "")
                wp_site = media_info.get("wp_site_name", "")

                parsed = urlparse(wp_url)
                domain = parsed.netloc or wp_url

                # 构建链接预览卡片（适度留白、美观）
                info_parts = []
                if wp_site:
                    info_parts.append(
                        f'<span style="display:inline-block;background:#f8bbd9;color:#880e4f;'
                        f'padding:2px 6px;border-radius:3px;font-size:11px;line-height:1.4;">'
                        f'{self._escape_html(wp_site)}</span>'
                    )
                if wp_title:
                    info_parts.append(
                        f'<div style="color:#333;font-size:13px;font-weight:600;'
                        f'line-height:1.5;margin-top:5px;">'
                        f'{self._escape_html(wp_title)}</div>'
                    )
                if wp_desc:
                    info_parts.append(
                        f'<div style="color:#666;font-size:12px;'
                        f'line-height:1.5;margin-top:3px;">'
                        f'{self._escape_html(wp_desc)}</div>'
                    )
                info_html = "".join(info_parts)

                link_card = (
                    f'<div style="background:#fff0f3;padding:10px 14px;border-radius:6px;'
                    f'border-left:4px solid #e91e63;text-align:left;white-space:normal;margin:4px 0;">'
                    f'<a href="{self._escape_html(wp_url)}" target="_blank" '
                    f'style="color:#c2185b;text-decoration:none;font-size:13px;'
                    f'word-break:break-all;display:block;margin-bottom:5px;line-height:1.5;">'
                    f'{self._escape_html(wp_url)}</a>'
                    f'{info_html}'
                    f'</div>'
                )
                content_html = link_card
            elif media_type == "contact":
                # 联系人名片卡片：显示姓名、电话号码、Telegram 用户 ID
                cfname = self._escape_html(media_info.get("contact_first_name", ""))
                clname = self._escape_html(media_info.get("contact_last_name", ""))
                raw_phone = media_info.get("contact_phone", "")
                # 格式化手机号：识别国家代码并添加空格
                # +86 18086873837 / +1 5592495360 / +44 1234567890
                formatted_phone = _format_phone_with_country_code(raw_phone)
                cphone = self._escape_html(formatted_phone)
                cuid = media_info.get("contact_user_id", 0)
                full_name = f"{cfname} {clname}".strip() or "未知联系人"
                contact_card = (
                    f'<div style="background: linear-gradient(135deg, #eceff1 0%, #cfd8dc 100%); '
                    f'padding: 12px 14px; border-radius: 6px; border-left: 4px solid #607d8b;margin:4px 0;">'
                    f'<div style="display: flex; align-items: center; gap: 10px;">'
                    f'<div style="width: 40px; height: 40px; border-radius: 50%; '
                    f'background: #78909c; display: flex; align-items: center; '
                    f'justify-content: center; font-size: 20px; color: #fff; flex-shrink: 0;">👤</div>'
                    f'<div style="flex: 1;">'
                    f'<div style="font-weight: bold; color: #37474f; font-size: 14px; line-height: 1.3;">'
                    f'{full_name}</div>'
                )
                if cphone:
                    contact_card += (
                        f'<div style="color: #607d8b; font-size: 12px; line-height: 1.4; margin-top: 2px;">'
                        f'📞 {cphone}</div>'
                    )
                if cuid:
                    contact_card += (
                        f'<div style="color: #78909c; font-size: 11px; line-height: 1.4; margin-top: 1px;">'
                        f'🆔 Telegram ID: {cuid}</div>'
                    )
                contact_card += '</div></div></div>'
                content_html = contact_card
            elif text and media_type == "webpage":
                # 链接预览消息：用户写的文字 + 链接卡片要同时显示
                # 原因：text 是用户自己写的文字内容（可能包含 URL），
                # 与链接预览卡片的 title/description 是独立的两部分
                content_html = self._escape_html(text) + "<br><br>" + content_html
            elif text and not content_html:
                # content_html 已被 poll/contact/geo 等卡片填充时，
                # 不再重复显示原始文本（避免投票等消息冗余）
                content_html = self._escape_html(text)
            elif not content_html and media_type != "none":
                # 有媒体类型但无文字：发件人行的 media_badge 已展示所有信息，
                # 内容区留空，不显示冗余的"(无内容)"
                content_html = ""
            else:
                content_html = '<span style="color: #999;">(无内容)</span>'

            html_parts.extend([
                f'<div style="margin-bottom: 12px; padding: 10px 14px; background: #fafafa; border-radius: 6px; '
                f'border-left: 4px solid #0088cc;">',
                f'<div style="font-weight: bold; color: #333; margin-bottom: 5px; font-size: 14px;">'
                f'{sender} {mention_badge}{pin_badge}{bot_badge}{edit_badge}{media_badge}'
                f'<span style="float: right; color: #999; font-size: 11px; font-weight: normal;">'
                f'{timestamp}</span></div>',
                reply_info,
                f'<div style="color: #444; line-height: 1.5; word-break: break-word; white-space: pre-wrap;font-size:13px;">'
                f'{content_html}</div>',
                edit_diff_html,  # 原消息对比（仅编辑消息有）
                '</div>',
            ])

        html_parts.extend([
            '</div>',
            '<p style="text-align: center; color: #aaa; font-size: 12px; margin-top: 20px;">'
            '此邮件由 Telegram 消息转发器自动发送</p>',
            '</body></html>',
        ])

        return "".join(html_parts)

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符，并移除 tg:// 协议的内部跳转链接（如 tg://user?id=xxx）"""
        # 先移除 tg:// 链接（保留文本中其他正常内容）
        text = re.sub(r'\btg://[^\s<>"]+\b', '', text)
        # 清理 markdown 链接格式 [text](url) → text（去掉方括号、圆括号和 url）
        # 例如 "[方宪]() 797994" → "方宪 797994"
        text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )


def _format_phone_with_country_code(phone: str) -> str:
    """格式化国际手机号：+8618086873837 → +86 18086873837，+15592495360 → +1 5592495360"""
    if not phone or not phone.startswith("+"):
        return phone

    common_codes = [
        "+1",
        "+20", "+27", "+30", "+31", "+32", "+33", "+34", "+36", "+39",
        "+40", "+41", "+43", "+44", "+45", "+46", "+47", "+48", "+49",
        "+51", "+52", "+53", "+54", "+55", "+56", "+57", "+58",
        "+60", "+61", "+62", "+63", "+64", "+65", "+66",
        "+81", "+82", "+84", "+86", "+90", "+91", "+92", "+93", "+94", "+95", "+98",
    ]

    for code in common_codes:
        if phone.startswith(code):
            return code + " " + phone[len(code):]

    return phone


# ============================================
# 核心转发器
# ============================================
def create_telegram_client(config: Config, logger: logging.Logger) -> TelegramClient:
    """创建 TelegramClient 实例（统一处理代理配置，消除重复代码）

    代理逻辑集中在此处：国内需要走代理才能连上 Telegram；
    未配置代理时（海外服务器/系统级 TUN 代理）直接直连。
    """
    proxy = config.proxy
    base_kwargs = dict(
        session=config.session_name,
        api_id=config.api_id,
        api_hash=config.api_hash,
    )

    if not proxy:
        return TelegramClient(**base_kwargs)

    import socks
    protocol, host, port, username, password = proxy
    proxy_type = socks.SOCKS5 if protocol.lower() == "socks5" else socks.HTTP
    logger.info(f"使用代理: {protocol}://{host}:{port}")

    if username:
        base_kwargs["proxy"] = (proxy_type, host, port, username, password)
    else:
        base_kwargs["proxy"] = (proxy_type, host, port)
    return TelegramClient(**base_kwargs)


class TelegramForwarder:
    """Telegram 消息转发器核心类"""

    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_logging(config)
        self.email_sender = EmailSender(config, self.logger)
        self.message_buffer = MessageBuffer(config, self.email_sender, self.logger)
        self.client: TelegramClient | None = None
        self._running = False
        self._reconnect_count = 0

        # 群组信息缓存（dialog.id -> 名称）
        self._group_cache: dict[int, str] = {}
        # 用户信息缓存（user_id -> 名称，含机器人和普通用户）
        self._user_cache: dict[int, str] = {}

        # 运行时跟踪集合（用于实时更新数量统计）
        self._seen_group_ids: set[int] = set()
        self._seen_user_ids: set[int] = set()
        self._seen_bot_ids: set[int] = set()

        # 当前登录用户自身 ID（启动时由 get_me 获取）
        self._my_id: int | None = None

        # 目标用户的实体缓存
        self._target_entity = None

        # 通话缓存：call.id → 来电信息 dict（用于合并成一封邮件）
        self._pending_calls: dict[int, dict] = {}
        # 群组通话缓存：call.id → 群组通话信息
        self._pending_group_calls: dict[int, dict] = {}

        # 原始消息文本缓存（用于编辑消息时显示对比）
        # key: "chat_id:message_id", value: 原始消息文本
        self._msg_original_cache: dict[str, str] = {}

        # 实体缓存（完整 Telegram 对象）：key = (type, id) → User/Channel/Chat
        # 避免 15+ 处 get_entity RPC 调用重复拉取同一对象
        # 缓存上限约 1000 条，超限时从旧到新丢弃一半
        self._entity_cache: dict[tuple, Any] = {}
        self._entity_cache_max_size = 1000

    async def start(self):
        """启动转发器"""
        self.logger.info("=" * 60)
        self.logger.info("Telegram 消息转发器 启动中...")
        self.logger.info(f"转发邮箱: {self.config.email_receiver}")
        # 构建消息转发策略摘要
        strategies = []
        strategies.append("@提及目标用户")
        if self.config.include_replies:
            strategies.append("回复目标用户")
        if self.config.monitor_private_chats:
            strategies.append("私聊")
        if self.config.monitor_pinned_messages:
            strategies.append("群消息置顶")
        if self.config.monitor_calls:
            strategies.append("通话监听")
        if self.config.monitor_group_calls:
            strategies.append("群组视频聊天")
        if self.config.monitored_bots:
            strategies.append("机器人")
        self.logger.info(f"监听策略: {'、'.join(strategies)}")
        self.logger.info("=" * 60)

        # 将 logger 注入 SQLite patch 模块，让 patch 操作有日志可见
        global _patch_logger
        _patch_logger = self.logger

        # 启动前恢复 session 数据库（切换到 DELETE 模式 + 清理残留锁）
        _recover_session_db(self.config.session_name, self.logger)

        # 启动客户端（_connect_with_retry 内部负责创建 TelegramClient 实例）
        await self._connect_with_retry()

    async def _start_client(self):
        """启动 Telegram 客户端（仅连接+鉴权检测，不包含登录流程）

        登录流程单独放在 _login() 中，避免被 connect_timeout 超时截断。
        """
        await self.client.connect()

        if not await self.client.is_user_authorized():
            # Session 不存在或已失效，返回 False 让调用方走 _login() 流程
            return False

        # 已有有效 session
        return True

    async def _login(self):
        """完整登录流程（在 session 无效时由 _connect_with_retry 调用）

        不受 connect_timeout 限制，给用户充足时间输入验证码。
        """
        self.logger.error("未检测到有效 session，需要重新登录认证")

        # ── 第一步：彻底释放 SQLite 连接 ──
        # 显式关闭 session 内部的 SQLite 连接（Windows 必须）
        try:
            if hasattr(self.client, 'session') and hasattr(self.client.session, 'close'):
                self.client.session.close()
                self.logger.debug("Session SQLite 连接已关闭")
        except Exception as e:
            self.logger.debug(f"关闭 session 出错（可忽略）: {e}")

        # 断开 TCP 连接
        try:
            await self.client.disconnect()
        except Exception as e:
            self.logger.debug(f"断开连接出错（可忽略）: {e}")

        # 垃圾回收 + 等待 Windows 释放文件锁
        import gc as _gc
        self.client = None  # 丢弃旧引用，帮助 GC 回收
        _gc.collect()
        time.sleep(1.5)  # Windows 需更长时间释放 SQLite 锁

        # ── 第二步：自动删除旧的无效 session 文件 ──
        _delete_session_files(self.config.session_name, self.logger)

        # 删除后再次等待文件系统同步
        time.sleep(0.5)

        # ── 第三步：重建客户端并登录 ──
        self.client = create_telegram_client(self.config, self.logger)
        self.client.catch_up = True
        self._register_handlers()  # 新客户端必须重新注册消息处理器
        await self.client.connect()
        await self.client.send_code_request(self.config.phone)

        code = input("\nPlease check and enter your Telegram Login Code: ").strip()
        try:
            await self.client.sign_in(self.config.phone, code)
        except Exception as e:
            if "2FA" in str(e) or "password" in str(e).lower():
                password = input("Please enter your 2FA Password: ")
                await self.client.sign_in(self.config.phone, code, password=password)
            else:
                raise

    async def _connect_with_retry(self):
        """带重试的连接

        每次重连都创建全新的 TelegramClient 实例，彻底避免旧
        session 数据库连接残留导致的 'database is locked' 问题。
        """
        while True:
            try:
                self.logger.info("正在连接 Telegram 服务器...")

                # 每次连接都创建全新的 TelegramClient，避免旧 session
                # 数据库连接残留导致锁冲突
                self.client = create_telegram_client(self.config, self.logger)
                self.client.catch_up = True
                self._register_handlers()

                # 给 _start_client() 套一层超时：仅用于快速连接+鉴权检测，
                # 代理抖动/握手卡住时会在 connect_timeout 秒后抛出 TimeoutError。
                # 登录流程（_login）不受此超时限制，给用户充足时间输入验证码。
                try:
                    authorized = await asyncio.wait_for(
                        self._start_client(),
                        timeout=self.config.connect_timeout,
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"连接超时（{self.config.connect_timeout}秒），"
                        f"可能是代理抖动或网络不通，将自动重试"
                    )

                if not authorized:
                    # session 无效，走登录流程（无超时限制）
                    await self._login()

                self.logger.info("Telegram 连接成功！")

                # 获取自身信息
                me = await self.client.get_me()
                self.logger.info(f"已登录账号：{me.first_name} (ID: {me.id})")
                # 缓存当前用户自身信息
                self._my_id = me.id
                self._user_cache[me.id] = f"{me.first_name or ''} {me.last_name or ''}".strip() or me.username or str(me.id)

                # 尝试获取目标用户实体
                await self._resolve_target_user()

                # 列出已加入的群组（后台异步执行，不阻塞消息监听启动）
                # 避免一次性 get_dialogs 拉取大量对话导致触发 429 限流
                asyncio.ensure_future(self._background_list_groups())

                self._running = True
                self._reconnect_count = 0

                # 持续运行（直到服务器断开连接或发生异常）
                self.logger.info("开始监听消息...")
                try:
                    await self.client.run_until_disconnected()
                    # 正常返回：服务器主动关闭了连接（如网络切换、服务端重启）
                    self.logger.info("Telegram 服务器已断开连接，准备重连...")
                except Exception as inner_e:
                    # run_until_disconnected 内部抛出的异常也记录，不吞掉
                    self.logger.warning(f"消息监听循环异常退出：{inner_e}")
                    raise  # 向外层 except 抛出，触发重连逻辑

            except Exception as e:
                self._running = False
                self._reconnect_count += 1
                err_msg = str(e)

                # 记录完整的异常信息（包括 traceback）
                self.logger.error(
                    f"连接异常（第 {self._reconnect_count} 次）：{err_msg}",
                    exc_info=True,
                )

                # ------------------------------------------------------------
                # 限流 / 网络错误处理：
                # Telegram 会用 429 或 FloodWaitError 明确告诉我们"等 N 秒再试"。
                # 立即按固定 reconnect_delay 重连只会立刻再次撞限流 → 死循环。
                # 正确做法：检测到限流时按 Telegram 要求的时间等待；普通网络错误用指数退避。
                # ------------------------------------------------------------
                wait_seconds = 0
                is_rate_limit = False

                # 1) 显式 FloodWaitError：Telegram 直接告诉你等多少秒
                if isinstance(e, FloodWaitError):
                    wait_seconds = max(int(getattr(e, "seconds", 0)) + 2, 5)
                    is_rate_limit = True
                    self.logger.warning(
                        f"Telegram 触发 FloodWait，要求等待 {wait_seconds} 秒后再重连..."
                    )

                # 2) SlowModeWaitError：群组慢速模式
                elif isinstance(e, SlowModeWaitError):
                    wait_seconds = max(int(getattr(e, "seconds", 0)) + 2, 5)
                    is_rate_limit = True
                    self.logger.warning(
                        f"触发 SlowMode，等待 {wait_seconds} 秒后再重连..."
                    )

                # 3) 裸 429 限流（Telethon 没包装成 FloodWaitError，原始 HTTP 错误冒泡）
                elif "HTTP code 429" in err_msg or "too many requests" in err_msg.lower():
                    # 没有明确秒数，使用指数退避：5, 10, 20, 40, 60, 60...
                    base = self.config.reconnect_delay
                    wait_seconds = min(base * (2 ** min(self._reconnect_count, 6)), 300)
                    is_rate_limit = True
                    self.logger.warning(
                        f"Telegram 返回 HTTP 429 (限流)，将等待 {wait_seconds} 秒后重连，"
                        f"以避开限流窗口..."
                    )

                # 4) 服务端错误 / 网络抖动：轻度指数退避
                elif isinstance(e, (ServerError, TimeoutError)) or isinstance(e, (ConnectionError, asyncio.TimeoutError)):
                    base = self.config.reconnect_delay
                    wait_seconds = min(base * (2 ** min(self._reconnect_count, 4)), 120)

                # 5) 其他未分类异常：使用配置的固定 reconnect_delay
                else:
                    wait_seconds = self.config.reconnect_delay

                # 加 ±20% 抖动，避免多实例/重连风暴在整点同时撞限流
                import random
                jitter = wait_seconds * 0.2
                wait_seconds = max(1, int(wait_seconds + random.uniform(-jitter, jitter)))

                # 如果是 database is locked，在等待前先尝试恢复 session DB
                if "database is locked" in str(e).lower():
                    self.logger.info("检测到数据库锁冲突，尝试恢复 session 数据库...")
                    _recover_session_db(self.config.session_name, self.logger)

                # 如果是 session 文件格式损坏/不兼容（如 Telethon 版本升级后），
                # 自动删除旧 session 并重新登录，避免无限重试
                if "too many values to unpack" in err_msg or \
                   "not enough values to unpack" in err_msg:
                    self.logger.warning(
                        "检测到 session 文件格式不兼容，将自动删除旧 session 并重新登录..."
                    )
                    _delete_session_files(self.config.session_name, self.logger)
                    self._reconnect_count = 0  # 重置重试计数，给新登录充足的尝试机会

                # 检查是否达到最大重连次数（限流场景不计入，避免被踢出）
                if (
                    self.config.max_reconnects > 0
                    and self._reconnect_count > self.config.max_reconnects
                    and not is_rate_limit  # 限流时无限等，不要因为限流把脚本搞挂
                ):
                    self.logger.error(
                        f"已达最大重连次数 ({self.config.max_reconnects})，程序退出"
                    )
                    break

                self.logger.info(
                    f"将在 {wait_seconds} 秒后重连..."
                    f"(第 {self._reconnect_count} 次)"
                )
                await asyncio.sleep(wait_seconds)

                # 彻底清理旧连接：断开底层 socket，释放 session 数据库连接，
                # 避免残留连接导致下次连接时锁冲突
                if self.client:
                    try:
                        await self.client.disconnect()
                        self.logger.debug("旧 Telegram 连接已断开")
                    except Exception as disconnect_err:
                        self.logger.debug(f"断开旧连接时出现预期内的异常: {disconnect_err}")
                self.client = None

        self._running = False

    async def _resolve_target_user(self):
        """解析目标用户实体"""
        try:
            self._target_entity = await self._cached_get_entity(
                self.config.target_user_id
            )
            target_name = getattr(self._target_entity, "first_name", "") or ""
            target_last = getattr(self._target_entity, "last_name", "") or ""
            full_target_name = f"{target_name} {target_last}".strip()
            self._user_cache[self.config.target_user_id] = full_target_name or str(self.config.target_user_id)
            self.logger.info(
                f"目标用户：{full_target_name} "
                f"(ID: {self.config.target_user_id})"
            )
        except Exception as e:
            self.logger.warning(
                f"无法获取目标用户实体 (ID: {self.config.target_user_id})：{e}"
            )
            self.logger.warning("将使用 ID 匹配模式，不影响功能")

    async def _background_list_groups(self):
        """后台异步拉取群组列表

        与 _list_groups 的区别：捕获所有异常并记录，不向外冒泡。
        启动时在后台静默填充缓存，不阻塞消息监听开始。
        """
        try:
            await self._list_groups()
        except Exception as e:
            self.logger.warning(
                f"后台拉取群组列表失败（不影响转发功能，缓存在运行中逐步补充）: {e}"
            )

    async def _list_groups(self):
        """列出已加入的群组"""
        try:
            self.logger.info("正在获取活跃的群组/频道/私聊/Robot列表...")
            dialogs = await self.client.get_dialogs()
            groups = []
            channels = []
            users = []
            bots = []

            for dialog in dialogs:
                if dialog.is_group or dialog.is_channel:
                    if dialog.is_channel and not dialog.is_group:
                        channels.append(dialog)
                    else:
                        groups.append(dialog)
                    self._group_cache[dialog.id] = dialog.name
                elif dialog.is_user:
                    entity = dialog.entity
                    name = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
                    if not name:
                        name = entity.username or str(entity.id)
                    self._user_cache[entity.id] = name
                    if dialog.entity.bot:
                        bots.append(dialog)
                    else:
                        users.append(dialog)

            self.logger.info(f"共监听 {len(groups)} 个活跃群组")
            for g in groups:
                self.logger.info(f"  - {g.name} (ID: {g.id})")

            self.logger.info(f"共监听 {len(channels)} 个活跃频道")
            for c in channels:
                self.logger.info(f"  - {c.name} (ID: {c.id})")

            # 同步填充运行时跟踪集合
            for g in groups:
                self._seen_group_ids.add(g.id)
            for c in channels:
                self._seen_group_ids.add(c.id)
            for u in users:
                self._seen_user_ids.add(u.entity.id)
            for b in bots:
                self._seen_bot_ids.add(b.entity.id)

            # 显示私聊用户列表
            if self.config.monitor_private_chats:
                self.logger.info(f"共监听 {len(users)} 个活跃私聊")
                for u in users:
                    entity = u.entity
                    name = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
                    username = f"@{entity.username}" if entity.username else "(无用户名)"

                    self.logger.info(f"  - {name} {username} (ID: {entity.id})")

                # 显示机器人列表
                if bots:
                    self.logger.info(f"共监听 {len(bots)} 个活跃Robot")
                    for b in bots:
                        entity = b.entity
                        name = entity.first_name or ""
                        username = f"@{entity.username}" if entity.username else "(无用户名)"
                        self.logger.info(f"  - {name} {username} (ID: {entity.id})")

        except Exception as e:
            self.logger.warning(f"获取对话列表失败：{e}")

    def _register_handlers(self):
        """注册 Telegram 事件处理器"""

        @self.client.on(events.NewMessage())
        async def on_new_message(event):
            """处理新消息"""
            if not self._running:
                return

            try:
                await self._process_message(event)
            except Exception as e:
                self.logger.error(f"消息处理异常：{e}", exc_info=True)

        @self.client.on(events.MessageEdited())
        async def on_message_edited(event):
            """处理编辑后的消息

            场景：群聊中某人先发了一条未 @目标用户的消息（没被转发），
            随后编辑该消息添加了 @目标用户，此时应重新检测并转发。
            """
            if not self._running:
                return

            try:
                await self._process_message(event)
            except Exception as e:
                self.logger.error(f"编辑消息处理异常：{e}", exc_info=True)

        # === 置顶消息监听（使用 Raw 事件）===
        # 原因：events.NewMessage() 默认不触发服务消息（如置顶操作产生的 MessageService）
        # 置顶消息在 Telegram 中产生 UpdateChannelPinnedMessage / UpdateChatPinnedMessage
        # 需要通过 events.Raw 捕获原始 Update 来检测
        if self.config.monitor_pinned_messages:
            @self.client.on(events.Raw)
            async def on_raw_update(update):
                """处理原始 Update，检测置顶消息操作"""
                if not self._running:
                    return

                try:
                    update_cls_name = type(update).__name__

                    # 非置顶类 Update 不在此处输出日志（由 add_message 在入库时统一记录）
                    if "Pinned" not in update_cls_name and "pinned" not in update_cls_name.lower():
                        return

                    # UpdateChannelPinnedMessage 有 pinned 布尔字段：True=置顶, False=取消置顶
                    # 只处理置顶操作，忽略取消置顶
                    pinned_flag = getattr(update, "pinned", None)
                    if pinned_flag is False:
                        self.logger.debug(f"检测到取消置顶操作，忽略：{update_cls_name}")
                        return

                    # 获取被置顶的消息 ID 和频道/群组信息
                    # 注意：Telegram 有三种不同的置顶 Update 类型：
                    #   - UpdateChannelPinnedMessage: message_id (int, 单条)
                    #   - UpdatePinnedChannelMessages: messages (list[int], 批量/列表变更)
                    #   - UpdatePinnedMessages: peer (Peer 对象) + messages, 无 channel_id
                    raw_channel_id = getattr(update, "channel_id", None)
                    raw_chat_id = getattr(update, "chat_id", None)

                    # UpdatePinnedMessages 使用 peer 字段而非 channel_id/chat_id
                    if raw_channel_id is None and raw_chat_id is None:
                        peer = getattr(update, "peer", None)
                        if peer is not None:
                            from telethon.tl.types import PeerUser, PeerChat, PeerChannel
                            if isinstance(peer, PeerChannel):
                                raw_channel_id = peer.channel_id
                            elif isinstance(peer, PeerChat):
                                raw_chat_id = peer.chat_id
                            elif isinstance(peer, PeerUser):
                                # 私聊置顶（如收藏夹/已保存消息），跳过
                                self.logger.debug(f"检测到私聊置顶操作，跳过：{update_cls_name}")
                                return

                    msg_id = getattr(update, "message_id", None)
                    if msg_id is None:
                        # 尝试复数字段（UpdatePinnedChannelMessages 使用 messages 而非 message_id）
                        messages_list = getattr(update, "messages", None)
                        if isinstance(messages_list, list) and len(messages_list) > 0:
                            msg_id = messages_list[-1]  # 取列表中最后一条（最新被置顶的）
                    if msg_id is None:
                        # 尝试论坛主题置顶（UpdatePinnedForumTopic 使用 topic_id）
                        msg_id = getattr(update, "topic_id", None)
                    if msg_id is None or (raw_channel_id is None and raw_chat_id is None):
                        self.logger.debug(
                            f"收到非普通消息置顶更新，跳过：{update_cls_name} "
                            f"msg_id={msg_id} channel_id={raw_channel_id} chat_id={raw_chat_id} "
                            f"messages={getattr(update, 'messages', None)}"
                        )
                        return

                    # 构造正确的 Peer 对象
                    # Telethon 的 get_messages 如果传入正整数会当作 user_id，
                    # 必须用 PeerChannel / PeerChat 包装
                    from telethon.tl.types import PeerChannel, PeerChat
                    if raw_channel_id is not None:
                        peer = PeerChannel(raw_channel_id)
                        # chat_id 统一为与普通消息一致的格式：-100{channel_id}
                        chat_id = -1000000000000 - raw_channel_id
                    else:
                        peer = PeerChat(raw_chat_id)
                        # 普通群聊 chat_id 为负数
                        chat_id = -raw_chat_id

                    # 从缓存中查找群组/频道名称
                    # 注意：cache 的 key 格式多样：
                    #   - 频道: -100{channel_id}
                    #   - 群组(正向): {chat_id}
                    #   - 群组(负向): -{chat_id}
                    # 需要多种格式兜底查找
                    def _lookup_name(cache, raw_id):
                        if raw_id is None:
                            return ""
                        # 直接匹配
                        if raw_id in cache:
                            return cache[raw_id]
                        # 尝试 -100 前缀（频道）
                        if raw_id > 0:
                            full_id = int(f"-100{raw_id}")
                            if full_id in cache:
                                return cache[full_id]
                        # 尝试正负反转（基本群组的 dialog.id 可能为正或负）
                        neg_id = -raw_id
                        if neg_id != raw_id and neg_id in cache:
                            return cache[neg_id]
                        return ""

                    pinned_group_name = ""
                    if raw_channel_id is not None:
                        pinned_group_name = _lookup_name(self._group_cache, raw_channel_id)
                    elif raw_chat_id is not None:
                        pinned_group_name = _lookup_name(self._group_cache, raw_chat_id)

                    self.logger.info(
                        f"检测到置顶操作：{update_cls_name} msg_id={msg_id} "
                        f"chat_id={chat_id} name={pinned_group_name or '未知'}"
                    )

                    # 获取被置顶的消息实体
                    # 注意：当 ids 参数是 int（单条）时，get_messages 返回单个 Message 对象，不是列表！
                    # 当 ids 是列表时才返回列表。
                    try:
                        pinned_msg = await self.client.get_messages(peer, ids=msg_id)
                    except Exception as e:
                        self.logger.warning(f"获取置顶消息失败：peer={peer} msg_id={msg_id}: {e}")
                        return

                    if not pinned_msg:
                        return

                    # 获取群组名称
                    from telethon.tl import types as tl_types
                    peer_id_obj = pinned_msg.peer_id
                    group_name = ""
                    pinner_name = "群组管理员"
                    try:
                        if isinstance(peer_id_obj, (tl_types.PeerChannel, tl_types.PeerChat)):
                            entity = await self._cached_get_entity(peer_id_obj)
                            if entity:
                                group_name = getattr(entity, "title", "") or getattr(entity, "username", "") or str(chat_id)
                    except Exception:
                        group_name = f"群组({chat_id})"

                    # 尝试获取执行置顶操作的用户
                    # get_messages 返回的是被置顶的原始消息（非服务消息），
                    # 其 action 为 None。要获取置顶者，需要搜索最近的服务消息。
                    # 同时获取 service 消息的 reply_to 用于确定话题名称
                    pinner_name = "未知用户"
                    service_msg = None  # 找到的 service 消息，用于 fallback 获取话题
                    try:
                        # 扩大搜索范围（20条），增加找到服务消息的概率
                        from telethon.tl.types import MessageActionPinMessage, PeerChannel as PC
                        recent_msgs = await self.client.get_messages(peer, limit=20)
                        for rm in recent_msgs:
                            rm_action = getattr(rm, "action", None)
                            if isinstance(rm_action, MessageActionPinMessage):
                                # 服务消息的 from_id 就是执行置顶的用户
                                pinner_from = getattr(rm, "from_id", None)
                                if pinner_from:
                                    if hasattr(pinner_from, "user_id"):
                                        uid = pinner_from.user_id
                                        pinner_entity = await self._get_user_entity(uid, peer)
                                        if pinner_entity:
                                            pinner_name = self._format_entity_display(pinner_entity, include_username=True)
                                        else:
                                            pinner_name = f"用户{uid}"
                                    elif hasattr(pinner_from, "channel_id"):
                                        # 频道/群组自己置顶
                                        channel_id = pinner_from.channel_id
                                        try:
                                            pinner_entity = await self._cached_get_entity(pinner_from)
                                            pinner_name = self._format_entity_display(pinner_entity, include_username=True)
                                        except Exception:
                                            pinner_name = f"频道{channel_id}"
                                # 保存 service 消息用于话题名称获取
                                service_msg = rm
                                break

                        # 兜底：如果消息来自频道，使用频道名称作为置顶者
                        if pinner_name == "未知用户" and pinned_msg.from_id and isinstance(pinned_msg.from_id, PC):
                            try:
                                channel_entity = await self._cached_get_entity(pinned_msg.from_id)
                                pinner_name = self._format_entity_display(channel_entity, include_username=True)
                            except Exception:
                                pinner_name = "未知频道"
                    except Exception as e:
                        self.logger.debug(f"获取置顶者失败：{e}")

                    # 获取话题名称（论坛群聊）
                    # 优先用 pinned_msg.reply_to，如果为空则用 service 消息的 reply_to
                    # （机器人置顶时，被置顶的原始消息可能丢失 reply_to 字段）
                    self.logger.debug(
                        f"[置顶消息-Topic调试] pinned_msg.id={getattr(pinned_msg, 'id', None)} "
                        f"pinned_msg.reply_to={getattr(pinned_msg, 'reply_to', None)} "
                        f"service_msg.reply_to={getattr(service_msg, 'reply_to', None) if service_msg else 'None'} "
                        f"peer={peer}"
                    )
                    topic_name = await self._get_topic_name(pinned_msg, peer, fallback_message=service_msg)
                    if topic_name:
                        group_name = f"{group_name}—{topic_name}"
                        self.logger.debug(f"[置顶消息-Topic] 已附加话题名称：{topic_name}")
                    else:
                        self.logger.debug(
                            f"[置顶消息-Topic] 未获取到话题名称。"
                            f"pinned_msg.reply_to={getattr(pinned_msg, 'reply_to', None)}, "
                            f"service_msg.reply_to={getattr(service_msg, 'reply_to', None) if service_msg else 'None'}"
                        )

                    # 应用群组过滤规则（与 _process_group_message 保持一致）
                    if not self._check_group_filter(chat_id):
                        self.logger.debug(
                            f"置顶消息因群组过滤被忽略：chat_id={chat_id} name={group_name}"
                        )
                        return

                    # 复用 _process_pinned_event 的逻辑来构建消息数据并转发
                    await self._process_pinned_event(None, pinned_msg, chat_id, group_name, pinner_name)

                except Exception as e:
                    self.logger.warning(f"置顶消息处理异常：{e}", exc_info=True)

        # === 音频/视频通话监听 ===
        if self.config.monitor_calls:
            @self.client.on(events.Raw)
            async def on_call_update(update):
                """捕获通话事件（来电、去电、挂断等）"""
                if not self._running:
                    return
                if not isinstance(update, UpdatePhoneCall):
                    return
                try:
                    await self._process_call_event(update)
                except Exception as e:
                    self.logger.error(f"通话事件处理异常：{e}", exc_info=True)

        # === 群组视频聊天监听（通过 Raw 事件捕获）===
        if self.config.monitor_group_calls:
            @self.client.on(events.Raw)
            async def on_group_call_update(update):
                """捕获群组视频聊天事件"""
                if not self._running:
                    return
                up_name = type(update).__name__
                # 捕获群聊中的视频聊天邀请消息（通过 Raw 消息更新）
                if up_name == "UpdateGroupCallParticipants":
                    call_id = getattr(update, "call_id", None) or getattr(getattr(update, "call", None), "id", None)
                    # 调试：打印参与者更新详情
                    participants_list = getattr(update, "participants", None)
                    if isinstance(participants_list, (list, tuple)):
                        for p in participants_list:
                            peer = getattr(p, "peer", None)
                            uid = getattr(peer, "user_id", None) if peer else None
                            left = getattr(p, "left", False)
                            flags = getattr(p, "flags", 0)
                            self.logger.info(f"  参与者变更: user_id={uid} left={left} flags={flags}")
                    participants_count = getattr(update, "participants_count", 0) or 0
                    participants_len = len(participants_list) if isinstance(participants_list, (list, tuple)) else 0
                    count = max(participants_count, participants_len, 1)
                    if call_id and call_id in self._pending_group_calls:
                        old = self._pending_group_calls[call_id].get("participants_count", 0)
                        new_count = max(count, old)
                        if new_count != old:
                            group_name = self._pending_group_calls[call_id].get("group_name", "?")
                            self._pending_group_calls[call_id]["participants_count"] = new_count
                            self.logger.info(f"群组参与人数更新：群组[{group_name}] {old} -> {new_count}")
                    return
                if up_name != "UpdateGroupCall":
                    return
                try:
                    await self._process_group_call_event(update)
                except Exception as e:
                    self.logger.error(f"群组通话事件处理异常：{e}", exc_info=True)

    async def _process_call_event(self, update):
        """处理通话事件并转发到邮箱
        策略：来电立即发「等待接听」，结束时发第二封状态更新。
        """
        call = update.phone_call

        if isinstance(call, PhoneCallRequested):
            # === 来电：立即发送通知 ===
            admin_id = call.admin_id
            participant_id = call.participant_id
            is_video = getattr(call, "video", False)
            call_type = "视频通话" if is_video else "语音通话"
            call_time = self._format_timestamp(call.date)

            # 只关心打给目标用户的来电
            is_incoming = (participant_id == self.config.target_user_id)
            is_outgoing = (admin_id == self.config.target_user_id)
            if not is_incoming and not is_outgoing:
                return
            if is_outgoing:
                self.logger.info(
                    f"检测到目标用户拨出 {call_type}（对方ID={participant_id}），跳过"
                )
                return

            # 获取呼叫方名称
            caller_name = f"用户{admin_id}"
            try:
                caller_entity = await self._cached_get_entity(admin_id)
                if caller_entity:
                    first = getattr(caller_entity, "first_name", "") or ""
                    last = getattr(caller_entity, "last_name", "") or ""
                    username = getattr(caller_entity, "username", "") or ""
                    caller_name = f"{first} {last}".strip()
                    if username:
                        caller_name += f" (@{username})"
                self._user_cache[admin_id] = caller_name
            except Exception as e:
                self.logger.warning(f"获取呼叫方信息失败: {e}")

            # 使用本地收到事件的时间（避免 Telegram 服务器时间偏差）
            local_now = datetime.now(timezone.utc)
            call_time = self._format_timestamp(local_now)

            # 缓存来电信息，供后续使用
            self._pending_calls[call.id] = {
                "caller_name": caller_name,
                "call_type": call_type,
                "call_time": call_time,
                "is_video": is_video,
                "timestamp": local_now,
            }

            # 立即发送第一封：来电通知
            subject = f"[Telegram] 来电提醒 - {caller_name} 发起{call_type}"
            html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5;">
  <div style="max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <div style="text-align: center; font-size: 48px; margin-bottom: 10px;">
      {'📹' if is_video else '📞'}
    </div>
    <h2 style="text-align: center; color: #333; margin: 10px 0 20px;">{call_type}</h2>
    <table style="width: 100%; border-collapse: collapse;">
      <tr>
        <td style="padding: 10px 15px; color: #666; width: 100px;">呼叫方</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{caller_name}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">类型</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">私聊</td>
      </tr>
      <tr>
        <td style="padding: 10px 15px; color: #666;">时间</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{call_time}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">状态</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #e65100;">等待接听</td>
      </tr>
    </table>
  </div>
</body>
</html>"""
            self.logger.info(f"发送来电通知：呼叫方={caller_name} 类型={call_type} 时间={call_time}")
            await self.email_sender.send_email(subject, html_body)

        elif isinstance(call, PhoneCallDiscarded):
            # === 通话结束：发送最终状态 ===
            call_id = call.id

            # 取缓存中的来电信息
            cached = self._pending_calls.pop(call_id, None)
            caller_name = cached.get("caller_name", "未知用户") if cached else "未知用户"
            call_type = cached.get("call_type", "通话") if cached else "通话"
            call_time = cached.get("call_time", "未知") if cached else "未知"
            is_video = cached.get("is_video", False) if cached else False

            # 计算响铃时长（秒，仅日志显示）
            ring_duration = 0
            if cached and cached.get("timestamp"):
                ring_duration = (datetime.now(timezone.utc) - cached["timestamp"]).total_seconds()

            status_text = "通话请求已结束"
            status_color = "#757575"

            end_time = self._format_timestamp(datetime.now(timezone.utc))

            # 发送第二封：状态更新
            subject = f"[Telegram] {caller_name} {call_type} - {status_text}"
            html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5;">
  <div style="max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <div style="text-align: center; font-size: 48px; margin-bottom: 10px;">
      {'📹' if is_video else '📞'}
    </div>
    <h2 style="text-align: center; color: #333; margin: 10px 0 20px;">{call_type}</h2>
    <table style="width: 100%; border-collapse: collapse;">
      <tr>
        <td style="padding: 10px 15px; color: #666; width: 100px;">呼叫方</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{caller_name}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">类型</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">私聊</td>
      </tr>
      <tr>
        <td style="padding: 10px 15px; color: #666;">来电时间</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{call_time}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">结束时间</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{end_time}</td>
      </tr>
      <tr>
        <td style="padding: 10px 15px; color: #666;">最终状态</td>
        <td style="padding: 10px 15px; font-weight: bold; color: {status_color};">{status_text}</td>
      </tr>
    </table>
  </div>
</body>
</html>"""
            self.logger.info(f"发送通话结束通知：call_id={call_id} status={status_text} ring={ring_duration:.0f}s")
            await self.email_sender.send_email(subject, html_body)

        else:
            # 其他中间状态，打印类型用于排查
            call_type_name = type(call).__name__
            call_id = getattr(call, "id", "?")
            self.logger.debug(f"通话中间状态：type={call_type_name} call_id={call_id}")
            return

    async def _process_group_call_event(self, update):
        """处理群组视频聊天事件"""
        call = getattr(update, "call", None)
        if call is None:
            return
        call_type = type(call).__name__
        # 处理 GroupCall（开始/进行中）和 GroupCallDiscarded（结束）
        if call_type == "GroupCallDiscarded":
            call_id = call.id
            cached = self._pending_group_calls.pop(call_id, None)
            if not cached:
                return
            group_name = cached.get("group_name", "未知群组")
            sender_name = cached.get("sender_name", "Owner/Admin")
            participants_count = cached.get("participants_count", 0)
            is_scheduled = cached.get("is_scheduled", False)
            end_time = self._format_timestamp(datetime.now(timezone.utc))
            duration = int((datetime.now(timezone.utc) - cached["start_time"]).total_seconds())
            mins, secs = divmod(duration, 60)
            dur_str = f"{mins}分{secs}秒" if mins > 0 else f"{secs}秒"
            if is_scheduled:
                # 预约被取消
                subject = f"[Telegram] 群组语音/视频聊天预约已取消 - {group_name}"
                self.logger.info(f"群组语音/视频聊天预约已取消：群组[{group_name}]")
            else:
                subject = f"[Telegram] 群组语音/视频聊天已结束 - {group_name}"
                self.logger.info(f"群组语音/视频聊天已结束：群组[{group_name}] 参与人数={participants_count} 持续={dur_str}")
            if is_scheduled:
                # 预约取消模板
                html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5;">
  <div style="max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <div style="text-align: center; font-size: 48px; margin-bottom: 10px;">❌</div>
    <h2 style="text-align: center; color: #333; margin: 10px 0 20px;">语音/视频聊天预约</h2>
    <table style="width: 100%; border-collapse: collapse;">
      <tr>
        <td style="padding: 10px 15px; color: #666; width: 100px;">群组</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{group_name}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">状态</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #757575;">已取消</td>
      </tr>
    </table>
  </div>
</body>
</html>"""
            else:
                html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5;">
  <div style="max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <div style="text-align: center; font-size: 48px; margin-bottom: 10px;">🎙️</div>
    <h2 style="text-align: center; color: #333; margin: 10px 0 20px;">语音/视频聊天</h2>
    <table style="width: 100%; border-collapse: collapse;">
      <tr>
        <td style="padding: 10px 15px; color: #666; width: 100px;">群组</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{group_name}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">类型</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">群组</td>
      </tr>
      <tr>
        <td style="padding: 10px 15px; color: #666;">发起者</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{sender_name}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">参与人数</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{participants_count}</td>
      </tr>
      <tr>
        <td style="padding: 10px 15px; color: #666;">持续时长</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{dur_str}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">结束时间</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{end_time}</td>
      </tr>
    </table>
  </div>
</body>
</html>"""
            await self.email_sender.send_email(subject, html_body)
            return

        if call_type != "GroupCall":
            return

        call_id = call.id
        # 从 update 获取群组 ID（UpdateGroupCall 字段名不确定，尝试多种方式）
        chat_id = getattr(update, "chat_id", None)
        if chat_id is None or chat_id == 0:
            chat_id = getattr(update, "channel_id", None)

        # 打印关键属性用于调试
        if chat_id is None or chat_id == 0:
            self.logger.warning(f"UpdateGroupCall 无法获取 chat_id，update 类型={type(update).__name__}")
            for attr in ("chat_id", "channel_id", "peer", "chat", "id"):
                val = getattr(update, attr, "MISSING")
                self.logger.warning(f"  {attr}={val}")
            return

        # 转换为完整 chat_id（兼容群组过滤检查）
        full_chat_id = int(f"-100{chat_id}")
        if not self._check_group_filter(full_chat_id):
            return

        # 获取群组名称
        try:
            entity = await self._cached_get_entity(PeerChannel(chat_id))
            group_name = getattr(entity, "title", "") or f"群组({chat_id})"
        except Exception:
            group_name = f"群组({chat_id})"

        # 获取话题名称（论坛群聊）
        try:
            topic_name = await self._get_topic_name(None, PeerChannel(chat_id))
            if topic_name:
                group_name = f"{group_name}—{topic_name}"
        except Exception as e:
            self.logger.debug(f"获取话题名称失败: {e}")

        # 检测预约语音聊天（有 schedule_date 字段）

        schedule_date = getattr(call, "schedule_date", None)
        if schedule_date and call_id not in self._pending_group_calls:
            schedule_time = self._format_timestamp(schedule_date)
            subject = f"[Telegram] 群组语音/视频聊天预约 - {group_name}"
            self.logger.info(f"群组语音/视频聊天已预约：群组[{group_name}] 时间={schedule_time}")
            html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5;">
  <div style="max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <div style="text-align: center; font-size: 48px; margin-bottom: 10px;">📅</div>
    <h2 style="text-align: center; color: #333; margin: 10px 0 20px;">语音/视频聊天预约</h2>
    <table style="width: 100%; border-collapse: collapse;">
      <tr>
        <td style="padding: 10px 15px; color: #666; width: 100px;">群组</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{group_name}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">类型</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">群组</td>
      </tr>
      <tr>
        <td style="padding: 10px 15px; color: #666;">预约时间</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{schedule_time}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">状态</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #e65100;">已预约 ⏰</td>
      </tr>
    </table>
  </div>
</body>
</html>"""
            await self.email_sender.send_email(subject, html_body)
            self._pending_group_calls[call_id] = {
                "start_time": datetime.now(timezone.utc),
                "group_name": group_name,
                "sender_name": "Owner/Admin",
                "participants_count": 0,
                "is_scheduled": True,
            }
            return

        participants_count = max(getattr(call, "participants_count", 0) or 0, 1)

        # 检查是否是预约转为实际发起（之前有预约缓存，现在有人加入开始通话）
        if call_id in self._pending_group_calls:
            cached = self._pending_group_calls[call_id]
            if cached.get("is_scheduled") and participants_count >= 1:
                # 判断是手动 Start Now（schedule_date 被清除）还是自动到点（schedule_date 保留）
                if schedule_date is None:
                    start_type = "手动发起"
                    start_icon = "▶️"
                else:
                    start_type = "已到预约时间"
                    start_icon = "⏰"
                call_time = self._format_timestamp(datetime.now(timezone.utc))
                subject = f"[Telegram] 群组语音/视频聊天已开始（{start_type}） - {group_name}"
                self.logger.info(f"群组语音/视频聊天已开始（预约转发起）：群组[{group_name}]")
                html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5;">
  <div style="max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <div style="text-align: center; font-size: 48px; margin-bottom: 10px;">{start_icon}</div>
    <h2 style="text-align: center; color: #333; margin: 10px 0 20px;">群组语音/视频聊天（{start_type}）</h2>
    <table style="width: 100%; border-collapse: collapse;">
      <tr>
        <td style="padding: 10px 15px; color: #666; width: 100px;">群组</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{group_name}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">类型</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">群组</td>
      </tr>
      <tr>
        <td style="padding: 10px 15px; color: #666;">参与人数</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{participants_count}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">时间</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{call_time}</td>
      </tr>
      <tr>
        <td style="padding: 10px 15px; color: #666;">状态</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #43a047;">进行中 🟢</td>
      </tr>
    </table>
  </div>
</body>
</html>"""
                await self.email_sender.send_email(subject, html_body)
                # 更新缓存，移除预约标记
                cached["is_scheduled"] = False
                return

        if call_id not in self._pending_group_calls:
            # 新呼叫开始：立即发邮件
            self._pending_group_calls[call_id] = {
                "start_time": datetime.now(timezone.utc),
                "group_name": group_name,
                "sender_name": "Owner/Admin",
                "participants_count": participants_count,
            }
            call_time = self._format_timestamp(datetime.now(timezone.utc))
            subject = f"[Telegram] 群组语音/视频聊天已开始 - {group_name}"
            self.logger.info(f"群组语音/视频聊天已开始：群组[{group_name}] 参与人数={participants_count}")
            html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5;">
  <div style="max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <div style="text-align: center; font-size: 48px; margin-bottom: 10px;">🎙️</div>
    <h2 style="text-align: center; color: #333; margin: 10px 0 20px;">群组语音/视频聊天</h2>
    <table style="width: 100%; border-collapse: collapse;">
      <tr>
        <td style="padding: 10px 15px; color: #666; width: 100px;">群组</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{group_name}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">类型</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">群组</td>
      </tr>
      <tr>
        <td style="padding: 10px 15px; color: #666;">发起者</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">Owner/Admin</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">参与人数</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{participants_count}</td>
      </tr>
      <tr>
        <td style="padding: 10px 15px; color: #666;">时间</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #333;">{call_time}</td>
      </tr>
      <tr style="background: #f9f9f9;">
        <td style="padding: 10px 15px; color: #666;">状态</td>
        <td style="padding: 10px 15px; font-weight: bold; color: #43a047;">进行中 🟢</td>
      </tr>
    </table>
  </div>
</body>
</html>"""
            await self.email_sender.send_email(subject, html_body)
        else:
            # 已有呼叫，更新参与者数量
            old_count = self._pending_group_calls[call_id].get("participants_count", 0)
            # 取最大参与者数量（UpdateGroupCall 和 UpdateGroupCallParticipants 可能不同步）
            current_max = max(participants_count, self._pending_group_calls[call_id].get("participants_count", 0))
            self._pending_group_calls[call_id]["participants_count"] = current_max
            if current_max != old_count:
                self.logger.info(f"群组语音/视频聊天更新：群组[{group_name}] 参与人数 {old_count} -> {current_max}")

    async def _process_pinned_event(self, event, message, chat_id: int, group_name: str, pinner_name: str):
        # 构建消息数据（复用 _build_message_text_and_media 获取文本和媒体信息）
        pinned_sender_name = "未知用户"
        try:
            # 优先从缓存中查找发送者名称
            sender_id = None
            from telethon.tl import types as tl_types
            if message.from_id:
                if isinstance(message.from_id, tl_types.PeerUser):
                    sender_id = message.from_id.user_id
                elif isinstance(message.from_id, tl_types.PeerChannel):
                    # 频道消息：from_id 是 PeerChannel，需要获取频道/机器人实体
                    channel_id = message.from_id.channel_id
                    try:
                        channel_entity = await self._cached_get_entity(message.from_id)
                        if channel_entity:
                            # 使用 _format_entity_display 统一格式化（支持机器人展示 Robot @username）
                            pinned_sender_name = self._format_entity_display(channel_entity, include_username=True)
                            # 兜底：格式化结果为空时使用 title/username
                            if not pinned_sender_name or pinned_sender_name == "未知用户":
                                pinned_sender_name = getattr(channel_entity, "title", "") or getattr(channel_entity, "username", "") or f"频道{channel_id}"
                    except Exception:
                        # 尝试用 chat_id 反查缓存
                        full_channel_id = int(f"-100{channel_id}")
                        if full_channel_id in self._group_cache:
                            pinned_sender_name = self._group_cache[full_channel_id]
                        else:
                            pinned_sender_name = f"频道{channel_id}"
                    # 频道消息直接跳过后续用户查找
                    sender_id = None
            elif hasattr(message, "sender_id") and message.sender_id:
                sender_id = message.sender_id

            if sender_id is not None:
                # 先从缓存查找；若缓存是旧格式则重新获取
                cached = self._user_cache.get(sender_id, "")
                # 缓存有效性判断：兼容新旧格式
                # 新格式: [Robot] bgwcnmonitor @bgwcnmonitor_bot (以 [ 开头)
                # 旧格式: Robot @bgwcnmonitor_bot 或包含 (@username) 形式
                cache_valid = cached and (
                    cached.startswith("[")  # 新格式：以方括号开头
                    or " (@" in cached         # 旧格式：含括号username
                    or cached.startswith("Robot ")  # 旧格式：以Robot开头
                    or cached.startswith("Channel ")
                    or cached.startswith("Group ")
                    or cached.startswith("Chat ")
                )
                if cache_valid:
                    pinned_sender_name = cached
                else:
                    sender_entity = await self._get_user_entity(sender_id, self._chat_id_to_peer(chat_id))
                    if sender_entity:
                        pinned_sender_name = self._format_entity_display(sender_entity, include_username=True)
                        self._user_cache[sender_id] = pinned_sender_name
                    else:
                        pinned_sender_name = cached if cached else f"用户{sender_id}"
        except Exception as e:
            self.logger.debug(f"获取置顶消息发送者失败：{e}")

        timestamp = self._format_timestamp(message.date)

        text_display, media_info = self._build_message_text_and_media(message)

        # 媒体消息正文不重复文件名：media_badge 已显示完整信息（📎 文件 · xxx.zip · 103 MB）
        if not text_display:
            text_display = ""

        message_data = {
            "sender_name": pinned_sender_name,
            "text": text_display,
            "timestamp": timestamp,
            "message_link": self._get_message_link(message, chat_id),
            "message_id": message.id,
            "reply_to_sender": "",
            "is_mention": False,
            "group_name": group_name,
            "reason": f"置顶消息（由 {pinner_name} 置顶）",
            "media_info": media_info,
            "is_pinned": True,
            "pinned_by": pinner_name,
        }

        # 日志输出简洁格式（去掉 [身份角色] 前缀，只展示名称 @username）
        _log_sender = pinned_sender_name.split("] ", 1)[-1] if "] " in pinned_sender_name else pinned_sender_name
        _log_pinner = pinner_name.split("] ", 1)[-1] if "] " in pinner_name else pinner_name
        self.logger.info(
            f"捕获置顶消息：群组[{group_name}] 原始发送者[{_log_sender}] "
            f"置顶者[{_log_pinner}]"
        )
        self.logger.debug(f"置顶消息内容：{message.text[:100] if message.text else '(空)'}")

        # 添加到缓冲区
        await self.message_buffer.add_message(chat_id, group_name, message_data)

    async def _process_message(self, event):
        """处理单条消息，判断是否需要转发"""
        message = event.message

        # 忽略没有聊天信息的消息
        if not message or not message.peer_id:
            return

        # 获取聊天 ID
        chat_id = self._get_chat_id(message.peer_id)
        if chat_id is None:
            return

        # === 入口调试日志：记录所有进入处理流程的消息（仅 DEBUG 级别）===
        # 用于排查特定消息为何未被捕获或处理
        from_id_str = str(getattr(message.from_id, 'user_id', getattr(message.from_id, 'channel_id', 'N/A'))) if message.from_id else 'None'
        text_preview = repr(message.text)[:80] if message.text else '(空)'
        self.logger.debug(
            f"[MSG_IN] peer_id={chat_id} from_id={from_id_str} "
            f"text={text_preview} "
            f"msg_type={type(message).__name__}"
        )

        # 全局跳过收藏夹消息（自己发给自己的私聊）
        if self._my_id is not None and chat_id == self._my_id:
            return
        if chat_id == self.config.target_user_id:
            return

        # === 服务通知检测（如 Telegram 登录验证码，ID: 777000）===
        # 优先级最高，检测到即立即转发，不受其他过滤条件影响
        if self.config.service_notification_enabled:
            if await self._check_service_notification(message, chat_id):
                return  # 已处理并转发

        # === 统一机器人消息检测（优先于群组/私聊逻辑）===
        # Telegram 中机器人消息可能来自群组（PeerChannel）也可能来自私聊（PeerUser）
        # - monitored_bots = null/None → 丢弃所有机器人消息（不走群组/私聊）
        # - monitored_bots = [] → 所有机器人走机器人逻辑
        # - monitored_bots = [列表] → 仅列表中的走机器人逻辑，其余丢弃
        if self.config.monitored_bots is not None:
            is_bot, bot_name = await self._check_is_bot_async(message)
            if is_bot:
                sender_name = await self._get_sender_name(event)

                # 实时更新机器人统计
                try:
                    bot_sender = await event.get_sender()
                    if bot_sender and hasattr(bot_sender, 'id'):
                        self._log_new_entity("机器人", bot_sender.id, bot_name, self._seen_bot_ids)
                except Exception:
                    pass

                timestamp = self._format_timestamp(message.date)

                message_link = self._get_message_link(message, chat_id)

                # === MessageMediaUnsupported 处理 ===
                # 某些机器人使用私有协议发送消息，Telegram 标记为不支持，text 全为空
                bot_fallback_text = ""
                from telethon.tl.types import MessageMediaUnsupported
                if not (message.text or "").strip() and isinstance(getattr(message, 'media', None), MessageMediaUnsupported):
                    bot_fallback_text = "(机器人消息：使用特殊协议发送，API无法解析)"

                text_display, media_info = self._build_message_text_and_media(message)

                # 获取话题名称（论坛群聊）
                topic_name = await self._get_topic_name(message, message.peer_id)
                if topic_name:
                    robot_group_name = f"Robot {bot_name}—{topic_name}"
                else:
                    robot_group_name = f"Robot {bot_name}"

                # 非文本媒体：从 media_info 取有意义的回退文本
                if not text_display:
                    icon_label = f"{media_info.get('icon', '')} {media_info.get('label', '')}".strip()
                    text_display = icon_label if icon_label else "(非文本消息)"

                is_edited = isinstance(event, events.MessageEdited.Event)
                message_data = {
                    "sender_name": sender_name,
                    "text": text_display,
                    "timestamp": timestamp,
                    "message_link": message_link,
                    "message_id": message.id,  # 消息ID，用于编辑时查找原消息
                    "reply_to_sender": "",
                    "is_mention": False,
                    "group_name": robot_group_name,
                    "reason": "机器人消息",
                    "media_info": media_info,
                    "is_bot_msg": True,
                    "is_edited": is_edited,
                }

                # 原消息缓存处理（Forwarder 层面，确保与缓冲区解耦）
                orig_cache_key = f"{chat_id}:{message.id}"
                if is_edited:
                    original_text = self._msg_original_cache.get(orig_cache_key, "")
                    if original_text:
                        message_data["original_text"] = original_text
                        self.logger.debug(f"编辑消息匹配到原消息: key={orig_cache_key}")
                    else:
                        self.logger.warning(
                            f"编辑消息未找到原消息: key={orig_cache_key}, "
                            f"现有keys={list(self._msg_original_cache.keys())[-5:]}"
                        )
                else:
                    raw = (message.text or "").strip()
                    if raw:
                        self._msg_original_cache[orig_cache_key] = raw

                self.logger.info(
                    f"捕获机器人消息：发送者[{sender_name}] → 邮件标题[{robot_group_name}]"
                )

                await self.message_buffer.add_message(chat_id, robot_group_name, message_data)
                return  # 机器人消息已处理完毕

            # monitored_bots 有具体列表，且是机器人但不在列表中 → 丢弃
            if self.config.monitored_bots and await self._check_any_bot(message):
                self.logger.debug(f"机器人不在监听列表中，丢弃消息")
                return

        # monitored_bots = null：丢弃所有机器人消息（不走群组/私聊）
        elif await self._check_any_bot(message):
            self.logger.debug("monitored_bots=null，丢弃机器人消息")
            return

        # 检查是否为群组/频道消息
        is_group = isinstance(message.peer_id, (PeerChat, PeerChannel))
        # 检查是否为私聊消息
        is_private = isinstance(message.peer_id, PeerUser)

        # 处理群组消息
        if is_group:
            # 检查是否为服务消息（置顶操作等）
            from telethon.tl.patched import MessageService
            from telethon.tl.types import MessageActionPinMessage

            msg_type = type(message).__name__
            action_type = ""
            action_obj = getattr(message, "action", None)
            if action_obj:
                action_type = type(action_obj).__name__

            self.logger.debug(
                f"收到群组消息：type={msg_type} action={action_type} "
                f"text='{message.text[:50] if message.text else '(空)'}...' "
                f"is_service={isinstance(message, MessageService)}"
            )

            if isinstance(message, MessageService):
                await self._process_service_message(event, message, chat_id)
            else:
                # 检测是否为编辑消息（MessageEdited 事件）
                is_edited = isinstance(event, events.MessageEdited.Event)
                await self._process_group_message(event, message, chat_id, is_edited=is_edited)
        # 处理私聊消息
        elif is_private and self.config.monitor_private_chats:
            is_edited = isinstance(event, events.MessageEdited.Event)
            await self._process_private_message(event, message, chat_id, is_edited=is_edited)

    async def _process_service_message(self, event, message, chat_id: int):
        """处理群组服务消息（置顶操作等）"""
        from telethon.tl.types import MessageActionPinMessage

        action = getattr(message, "action", None)

        # === 处理置顶消息 ===
        # 检查是否开启了置顶消息监听
        if not self.config.monitor_pinned_messages:
            self.logger.debug("置顶消息监听未开启（monitor_pinned_messages=false），跳过")
            return

        # 检查群组过滤
        if not self._check_group_filter(chat_id):
            return

        # 只处理置顶操作
        if not isinstance(action, MessageActionPinMessage):
            return

        # 获取群组名称
        group_name = await self._get_group_name(chat_id, event)

        # 获取执行置顶操作的用户
        pinner_name = "未知用户"
        try:
            pinner_from = getattr(event.message, "from_id", None)
            if isinstance(pinner_from, PeerUser):
                pinner_entity = await self._get_user_entity(pinner_from.user_id, self._chat_id_to_peer(chat_id))
                if pinner_entity:
                    pinner_name = self._format_entity_display(pinner_entity, include_username=False)
            elif isinstance(pinner_from, PeerChannel):
                pinner_entity = await self._cached_get_entity(pinner_from)
                pinner_name = self._format_entity_display(pinner_entity, include_username=False)
        except Exception:
            pass
        if pinner_name == "未知用户":
            try:
                pinner = await event.get_sender()
                pinner_name = self._format_entity_display(pinner, include_username=False)
            except Exception:
                pinner_name = "未知用户"

        # 获取被置顶的原始消息
        pinned_msg = None
        try:
            pinned_msg = await event.get_reply_message()
        except Exception as e:
            self.logger.warning(f"获取置顶消息内容失败：{e}")

        if not pinned_msg:
            self.logger.info(f"置顶消息：群组[{group_name}] 置顶者[{pinner_name}]，但无法获取原始消息内容")
            return

        # 获取话题名称（论坛群聊）
        # 优先用 service 消息本身的 reply_to（更可靠，因为 pinned_msg 经过
        # get_reply_message() 获取时可能丢失 reply_to 字段）
        topic_name = await self._get_topic_name(pinned_msg, message.peer_id, fallback_message=message)
        if topic_name:
            group_name = f"{group_name}—{topic_name}"

        # 构建被置顶消息的发送者信息
        pinned_sender_name = "未知用户"
        try:
            if pinned_msg.from_id:
                if isinstance(pinned_msg.from_id, PeerUser):
                    sender_id = pinned_msg.from_id.user_id
                    cached = self._user_cache.get(sender_id, "")
                    # 缓存有效性判断：兼容新旧格式
                    # 新格式: [Robot] bgwcnmonitor @bgwcnmonitor_bot (以 [ 开头)
                    # 旧格式: Robot @bgwcnmonitor_bot 或含 (@username) 形式
                    cache_valid = cached and (
                        cached.startswith("[")
                        or " (@" in cached
                        or cached.startswith("Robot ")
                        or cached.startswith("Channel ")
                        or cached.startswith("Group ")
                        or cached.startswith("Chat ")
                    )
                    if cache_valid:
                        pinned_sender_name = cached
                    else:
                        sender_entity = await self._get_user_entity(sender_id, self._chat_id_to_peer(chat_id))
                        if sender_entity:
                            pinned_sender_name = self._format_entity_display(sender_entity, include_username=True)
                            self._user_cache[sender_id] = pinned_sender_name
                        else:
                            pinned_sender_name = cached if cached else f"用户{sender_id}"
                elif isinstance(pinned_msg.from_id, PeerChannel):
                    # 频道/群组自己发布并置顶的消息
                    channel_id = pinned_msg.from_id.channel_id
                    try:
                        channel_entity = await self._cached_get_entity(pinned_msg.from_id)
                        pinned_sender_name = self._format_entity_display(channel_entity, include_username=False)
                    except Exception:
                        pinned_sender_name = f"频道{channel_id}"
            elif hasattr(pinned_msg, "sender_id") and pinned_msg.sender_id:
                sender_id = pinned_msg.sender_id
                sender_entity = await self._get_user_entity(sender_id, self._chat_id_to_peer(chat_id))
                if sender_entity:
                    pinned_sender_name = self._format_entity_display(sender_entity, include_username=True)
                else:
                    pinned_sender_name = f"用户{sender_id}"
        except Exception:
            pass



        # 构建消息数据
        timestamp = self._format_timestamp(message.date)
        text_display, media_info = self._build_message_text_and_media(pinned_msg)


        # 媒体消息正文不重复文件名：media_badge 已显示完整信息
        if not text_display:
            text_display = ""

        message_data = {
            "sender_name": pinned_sender_name,
            "text": text_display,
            "timestamp": timestamp,
            "message_link": self._get_message_link(pinned_msg, chat_id),
            "message_id": pinned_msg.id,
            "reply_to_sender": "",
            "is_mention": False,
            "group_name": group_name,
            "reason": f"置顶消息（由 {pinner_name} 置顶）",
            "media_info": media_info,
            "is_pinned": True,
            "pinned_by": pinner_name,
        }

        # 日志输出简洁格式（去掉 [身份角色] 前缀，只展示名称 @username）
        _log_sender = pinned_sender_name.split("] ", 1)[-1] if "] " in pinned_sender_name else pinned_sender_name
        _log_pinner = pinner_name.split("] ", 1)[-1] if "] " in pinner_name else pinner_name
        self.logger.info(
            f"捕获置顶消息：群组[{group_name}] 原始发送者[{_log_sender}] "
            f"置顶者[{_log_pinner}]"
        )

        await self.message_buffer.add_message(chat_id, group_name, message_data)

    async def _process_group_message(self, event, message, chat_id: int, *, is_edited: bool = False):
        # 检查群组过滤
        if not self._check_group_filter(chat_id):
            return

        # 群组视频聊天已由 Raw 事件统一处理，此处不再重复

        # 获取群组名称
        group_name = await self._get_group_name(chat_id, event)

        # 获取话题名称（论坛群聊）
        topic_name = await self._get_topic_name(message, message.peer_id)
        if topic_name:
            group_name = f"{group_name}—{topic_name}"

        # 实时更新群组/频道统计
        self._log_new_entity("群组/频道", chat_id, group_name, self._seen_group_ids)

        # 机器人消息已在 _process_message 入口处统一检测并处理，此处不再重复

        # 检查是否涉及目标用户
        is_mention = self._check_mention(message)
        is_reply_to_target = await self._check_reply_to_target_async(event)
        is_from_target = self._check_from_target(message)
        # 检查是否为群组内指定监听用户（独立于 target_user 逻辑）
        is_monitored_group_user = False
        monitored_user_reason = ""
        if self.config.monitored_group_users:
            is_monitored_group_user, monitored_user_reason = await self._check_monitored_group_user(chat_id, event)

        # 根据配置决定是否转发
        should_forward = False
        reason = ""

        if is_mention:
            should_forward = True
            reason = "@提及目标用户"
        elif is_monitored_group_user:
            should_forward = True
            reason = monitored_user_reason
        elif is_reply_to_target and self.config.include_replies:
            should_forward = True
            reason = "回复目标用户"
        elif is_from_target and not self.config.only_mentions:
            should_forward = True
            reason = "目标用户发送的消息"

        if not should_forward:
            return

        # 构建消息数据（包含文本 + 媒体类型描述）
        sender_name = await self._get_sender_name(event)
        timestamp = self._format_timestamp(message.date)

        message_link = self._get_message_link(message, chat_id)

        # 获取被回复的消息信息（无论 reply_to 是否存在都尝试获取）
        # 原因：Telegram 的 message.reply_to 在某些情况下为 None，
        # 但 _check_reply_to_target_async 已通过其他方式检测到这是回复消息
        reply_to_sender = ""
        if is_reply_to_target or (hasattr(message, 'reply_to') and message.reply_to):
            if hasattr(message, 'reply_to') and message.reply_to:
                self.logger.debug(f"message.reply_to 存在: {message.reply_to}")
            reply_to_sender = await self._get_reply_to_sender(event)

        text_display, media_info = self._build_message_text_and_media(message)

        # 获取目标用户名称
        target_name = self._user_cache.get(self.config.target_user_id, "")

        message_data = {
            "sender_name": sender_name,
            "text": text_display,
            "timestamp": timestamp,
            "message_link": message_link,
            "message_id": message.id,  # 消息ID，用于编辑时查找原消息
            "reply_to_sender": reply_to_sender,
            "is_mention": is_mention,
            "is_reply_to_target": is_reply_to_target,
            "target_name": target_name,
            "group_name": group_name,
            "reason": reason,
            "media_info": media_info,
            "is_edited": is_edited,
        }

        # 原消息缓存处理（Forwarder 层面，确保与缓冲区解耦）
        orig_cache_key = f"{chat_id}:{message.id}"
        if is_edited:
            original_text = self._msg_original_cache.get(orig_cache_key, "")
            if original_text:
                message_data["original_text"] = original_text
                self.logger.debug(f"编辑消息匹配到原消息: key={orig_cache_key}")
            else:
                self.logger.warning(
                    f"编辑消息未找到原消息: key={orig_cache_key}, "
                    f"现有keys={list(self._msg_original_cache.keys())[-5:]}"
                )
        else:
            # 用 message.text（原始文本）而非 text_display 作为缓存内容
            raw = (message.text or "").strip()
            if raw:
                self._msg_original_cache[orig_cache_key] = raw

        self.logger.debug(f"消息内容：{message.text[:100] if message.text else '(空)'}")

        # 添加到缓冲区
        await self.message_buffer.add_message(chat_id, group_name, message_data)

    async def _process_private_message(self, event, message, chat_id: int, *, is_edited: bool = False):
        """处理私聊消息"""
        # 跳过目标用户自己发出的消息（发给别人或自己）
        # 使用 sender_id 判断最可靠：自己发送的消息 sender_id 始终是登录用户自身
        if self._my_id is not None and message.sender_id == self._my_id:
            return
        if self._check_from_target(message):
            return
        if chat_id == self.config.target_user_id:
            return

        # 检查是否为监听的用户
        if not self._check_user_filter(chat_id):
            return

        # 获取发送者信息
        sender_name = await self._get_sender_name(event)

        # 实时更新私聊用户统计
        self._log_new_entity("私聊用户", chat_id, sender_name, self._seen_user_ids)

        timestamp = self._format_timestamp(message.date)


        # 私聊消息使用特殊的"群组名"标识
        chat_name = f"私聊 - {sender_name}"

        # 构建消息数据（包含文本 + 媒体类型描述）
        text_display, media_info = self._build_message_text_and_media(message)

        message_data = {
            "sender_name": sender_name,
            "text": text_display,
            "timestamp": timestamp,
            "message_link": "",  # 私聊消息没有公开链接
            "message_id": message.id,  # 消息ID，用于编辑时查找原消息
            "reply_to_sender": "",
            "is_mention": False,
            "group_name": chat_name,
            "reason": "私聊消息",
            "media_info": media_info,
            "is_edited": is_edited,
        }

        # 原消息缓存处理（Forwarder 层面，确保与缓冲区解耦）
        orig_cache_key = f"{chat_id}:{message.id}"
        if is_edited:
            original_text = self._msg_original_cache.get(orig_cache_key, "")
            if original_text:
                message_data["original_text"] = original_text
                self.logger.debug(f"编辑消息匹配到原消息: key={orig_cache_key}")
            else:
                self.logger.warning(
                    f"编辑消息未找到原消息: key={orig_cache_key}, "
                    f"现有keys={list(self._msg_original_cache.keys())[-5:]}"
                )
        else:
            raw = (message.text or "").strip()
            if raw:
                self._msg_original_cache[orig_cache_key] = raw

        self.logger.info(
            f"捕获私聊消息：发送者[{sender_name}] (ID: {chat_id})"
        )
        self.logger.debug(f"消息内容：{message.text[:100] if message.text else '(空)'}")

        # 添加到缓冲区（使用原始 user_id）
        await self.message_buffer.add_message(chat_id, chat_name, message_data)

    def _build_message_text_and_media(self, message) -> tuple[str, dict]:
        """分析消息内容，返回 (文本显示, 媒体信息字典)

        媒体信息用于在邮件中展示图标、文件名、大小等。
        返回的 dict 结构：
          - type: 媒体类型（photo/video/voice/audio/document/sticker/gif/none）
          - icon: emoji 图标
          - label: 中文标签
          - filename: 文件名（如有）
          - size_human: 人类可读大小
          - duration: 时长秒数（视频/音频/语音）
        """
        media_info = {
            "type": "none",
            "icon": "",
            "label": "",
            "filename": "",
            "size_human": "",
            "duration": None,
        }

        # 提取消息文本：按优先级尝试多个字段
        # message.text 是格式化后的便捷属性（Telethon 封装）
        # message.raw_text 去除 Markdown 标记后的纯文本
        # message.message 底层 TL 原始字段
        # 某些机器人/特殊场景下 text 可能为空但 raw_text/message 有内容
        text = ""
        for attr_name in ("text", "raw_text", "message"):
            val = getattr(message, attr_name, None) or ""
            if val:
                text = val
                break
        # 去除 Markdown 加粗标记 **text** → text
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)

        if not hasattr(message, "media") or message.media is None:
            return (text or "(无内容)", media_info)

        from telethon.tl.types import (
            MessageMediaPhoto,
            MessageMediaDocument,
            MessageMediaGeo,
            MessageMediaGeoLive,
            MessageMediaVenue,
            MessageMediaContact,
            MessageMediaPoll,
            MessageMediaGame,
            MessageMediaWebPage,
        )
        from telethon.tl.types import (
            DocumentAttributeVideo,
            DocumentAttributeAudio,
            DocumentAttributeSticker,
            DocumentAttributeAnimated,
            DocumentAttributeFilename,
        )

        media = message.media
        doc = None
        is_photo = False
        is_video = False
        is_audio = False
        is_voice = False
        is_sticker = False
        is_gif = False
        is_geo = False       # 位置/地图
        is_contact = False   # 联系人名片
        is_poll = False      # 投票
        is_game = False      # 游戏
        is_webpage = False   # 链接预览
        geo_data = {}        # 位置数据：lat, long, title, address, url
        webpage_data = {}     # 链接预览数据：url, title, description, site_name
        file_size_bytes = 0
        filename = ""
        duration_sec = None

        # --- 位置消息（Google 地图等） ---
        if isinstance(media, (MessageMediaGeo, MessageMediaGeoLive)):
            is_geo = True
            if hasattr(media, "geo") and media.geo:
                gp = media.geo
                lat = getattr(gp, "lat", None)
                lng = getattr(gp, "long", None)
                geo_data["lat"] = lat
                geo_data["lng"] = lng
                if isinstance(media, MessageMediaGeoLive):
                    period = getattr(media, "period", 0)
                    geo_data["period"] = period
                if lat is not None and lng is not None:
                    geo_data["url"] = f"https://www.google.com/maps?q={lat},{lng}"

        elif isinstance(media, MessageMediaVenue):
            is_geo = True
            if hasattr(media, "geo") and media.geo:
                gp = media.geo
                geo_data["lat"] = getattr(gp, "lat")
                geo_data["lng"] = getattr(gp, "long")
            geo_data["title"] = getattr(media, "title", "")
            geo_data["address"] = getattr(media, "address", "")
            geo_data["url"] = f"https://www.google.com/maps?q={geo_data.get('lat','')},{geo_data.get('lng','')}"

        # --- 联系人名片 ---
        elif isinstance(media, MessageMediaContact):
            is_contact = True
            # 提取联系人详细信息
            contact_first_name = getattr(media, "first_name", "") or ""
            contact_last_name = getattr(media, "last_name", "") or ""
            contact_phone = getattr(media, "phone_number", "") or ""
            contact_user_id = getattr(media, "user_id", 0)
            contact_data = {
                "first_name": contact_first_name,
                "last_name": contact_last_name,
                "phone_number": contact_phone,
                "user_id": contact_user_id,
            }

        # --- 投票 ---
        elif isinstance(media, MessageMediaPoll):
            is_poll = True
            # 提取投票信息
            poll_obj = getattr(media, "poll", None)
            poll_results = getattr(media, "results", None)
            poll_question_text = ""
            if poll_obj:
                # 获取投票标题（poll.question 是投票的简要主题/描述）
                poll_q = getattr(poll_obj, "question", None)
                if poll_q:
                    if hasattr(poll_q, "text"):
                        poll_question_text = getattr(poll_q, "text", "")
                    else:
                        poll_question_text = str(poll_q) if poll_q else ""

                # 获取选项及答案数
                answers = getattr(poll_obj, "answers", []) or []
                voters_map = {}
                if poll_results:
                    result_list = getattr(poll_results, "results", [])
                    if result_list:
                        for r in result_list:
                            opt_bytes = getattr(r, "option", b"")
                            voter_count = getattr(r, "voters", 0)
                            voters_map[opt_bytes] = voter_count
                total_voters = getattr(poll_results, "total_voters", 0) if poll_results else 0

                # 保存原始消息正文（用于 HTML 卡片中独立显示）
                original_text = text

                # 构建投票文本：优先展示消息正文 text，再附加投票内容和选项
                option_lines = []
                for ans in answers:
                    opt_text_obj = getattr(ans, "text", None)
                    opt_text = ""
                    if opt_text_obj:
                        if hasattr(opt_text_obj, "text"):
                            opt_text = getattr(opt_text_obj, "text", "")
                        else:
                            opt_text = str(opt_text_obj) if opt_text_obj else ""
                    opt_bytes = getattr(ans, "option", b"")
                    count = voters_map.get(opt_bytes, 0)
                    option_lines.append(f"  - {opt_text}: {count} 票")
                option_str = "\n".join(option_lines)
                # 保留 message.text（正文），将投票信息附加在后面
                if text:
                    text = f"{text}\n📊 投票：{poll_question_text}\n{option_str}\n共 {total_voters} 人参与"
                else:
                    text = f"📊 投票：{poll_question_text}\n{option_str}\n共 {total_voters} 人参与"

                # 将详细数据存入 media_info 供 HTML 渲染使用
                poll_detail_lines = []
                for ans in answers:
                    opt_text_obj = getattr(ans, "text", None)
                    opt_text = ""
                    if opt_text_obj:
                        if hasattr(opt_text_obj, "text"):
                            opt_text = getattr(opt_text_obj, "text", "")
                        else:
                            opt_text = str(opt_text_obj) if opt_text_obj else ""
                    opt_bytes = getattr(ans, "option", b"")
                    count = voters_map.get(opt_bytes, 0)
                    pct = (count / total_voters * 100) if total_voters > 0 else 0
                    poll_detail_lines.append({"option": opt_text, "voters": count, "pct": pct})
                media_info["poll_body_text"] = original_text
                media_info["poll_question"] = poll_question_text
                media_info["poll_options"] = poll_detail_lines
                media_info["poll_total_voters"] = total_voters

        # --- 游戏 ---
        elif isinstance(media, MessageMediaGame):
            is_game = True

        # --- 链接预览（纯链接，无文件）---
        elif isinstance(media, MessageMediaWebPage):
            is_webpage = True
            if hasattr(media, "webpage") and media.webpage:
                wp = media.webpage
                webpage_data["url"] = getattr(wp, "url", "") or ""
                webpage_data["title"] = getattr(wp, "title", "") or ""
                webpage_data["description"] = getattr(wp, "description", "") or ""
                webpage_data["site_name"] = getattr(wp, "site_name", "") or ""
                # 额外提取 Telegram 通话链接的备用字段
                webpage_data["display_url"] = getattr(wp, "display_url", "") or ""
                webpage_data["type"] = getattr(wp, "type", "") or ""
                # 调试日志：打印 webpage 信息的实际值
                if "t.me/call/" in webpage_data["url"]:
                    self.logger.info(f"通话链接: URL={webpage_data['url']!r}")
                else:
                    self.logger.info(
                        f"网页预览数据: url={webpage_data['url']!r} "
                        f"title={webpage_data['title']!r} "
                        f"desc={webpage_data['description']!r} "
                        f"site={webpage_data['site_name']!r} "
                        f"type={webpage_data['type']!r}"
                    )
                # 标题/描述为空时，根据 URL 类型补充默认文案
                if not webpage_data["title"] and not webpage_data["description"]:
                    if "t.me/call/" in webpage_data["url"]:
                        webpage_data["title"] = "Call Link"
                        webpage_data["description"] = "You are invited to join a Telegram Call."
                        webpage_data["site_name"] = "Telegram"


        elif isinstance(media, MessageMediaPhoto):
            is_photo = True
            if hasattr(media, "photo") and media.photo:
                for attr in getattr(media.photo, "sizes", []):
                    if hasattr(attr, "size"):
                        file_size_bytes += attr.size
                        break

        elif isinstance(media, MessageMediaDocument):
            if hasattr(media, "document") and media.document:
                doc = media.document
                file_size_bytes = doc.size
                mime_type = getattr(doc, "mime_type", "") or ""
                filename = getattr(doc, "filename", "") or ""

                # === 第一遍：收集所有属性标志（一个文档可能有多个属性）===
                has_video_attr = False
                has_audio_attr = False
                is_voice_flag = False
                has_sticker_attr = False
                has_animated_attr = False

                for attr in getattr(doc, "attributes", []) or []:
                    if isinstance(attr, DocumentAttributeVideo):
                        has_video_attr = True
                        duration_sec = attr.duration
                    elif isinstance(attr, DocumentAttributeAudio):
                        has_audio_attr = True
                        is_voice_flag = bool(getattr(attr, "voice", False))
                        duration_sec = attr.duration
                    elif isinstance(attr, DocumentAttributeSticker):
                        has_sticker_attr = True
                    elif isinstance(attr, DocumentAttributeAnimated):
                        has_animated_attr = True
                    elif isinstance(attr, DocumentAttributeFilename):
                        # 优先使用属性中的文件名（比 doc.filename 更准确）
                        if not filename:
                            filename = attr.file_name

                # === 第二遍：按优先级确定媒体类型 ===
                # 优先级：贴纸 > GIF(动画) > 语音 > 音频 > 视频 > 普通文件
                # Telegram 的 GIF 同时有 DocumentAttributeVideo + DocumentAttributeAnimated
                # Sticker 有 DocumentAttributeSticker 属性
                if has_sticker_attr:
                    is_sticker = True
                elif has_animated_attr:
                    is_gif = True
                elif has_audio_attr:
                    if is_voice_flag:
                        is_voice = True
                    else:
                        is_audio = True
                elif has_video_attr:
                    is_video = True
                else:
                    # 无特殊属性，通过 MIME type 兜底判断
                    if "video" in mime_type:
                        is_video = True
                    elif "audio" in mime_type:
                        is_audio = True
                    elif "image/webp" in mime_type or "image/tgs" in mime_type:
                        is_sticker = True
                    elif "gif" in mime_type:
                        is_gif = True

                # 调试日志：记录媒体检测结果（方便排查识别问题）
                type_name = (
                    "photo" if is_photo else
                    "geo" if is_geo else
                    "contact" if is_contact else
                    "poll" if is_poll else
                    "game" if is_game else
                    "webpage" if is_webpage else
                    "sticker" if is_sticker else
                    "gif" if is_gif else
                    "voice" if is_voice else
                    "audio" if is_audio else
                    "video" if is_video else
                    "document" if doc is not None else
                    "none"
                )
                self.logger.debug(
                    f"媒体检测：type={type_name} mime={mime_type} filename={filename} "
                    f"attrs(sticker={has_sticker_attr}, animated={has_animated_attr}, "
                    f"video={has_video_attr}, audio={has_audio_attr}, voice={is_voice_flag})"
                )

        def _fmt_size(b: int) -> str:
            if b < 1024:
                return f"{b} B"
            if b < 1048576:
                return f"{b / 1024:.1f} KB"
            return f"{b / 1048576:.1f} MB"

        if is_photo:
            media_info.update(type="photo", icon="🖼️", label="图片")
        elif is_geo:
            # 位置消息：显示坐标 + Google 地图链接
            lat = geo_data.get("lat")
            lng = geo_data.get("lng")
            title = geo_data.get("title", "")
            address = geo_data.get("address", "")
            period = geo_data.get("period")

            if title and address:
                label_text = f"位置 · {title}（{address}）"
            elif title:
                label_text = f"位置 · {title}"
            elif address:
                label_text = f"位置 · {address}"
            elif period:
                label_text = f"实时位置 · 共享{int(period)}秒"
            else:
                lat_str = f"{lat:.4f}" if lat is not None else "?"
                lng_str = f"{lng:.4f}" if lng is not None else "?"
                label_text = f"位置 · {lat_str}, {lng_str}"

            media_info.update(
                type="geo", icon="📍", label=label_text,
                geo_lat=lat, geo_lng=lng, geo_url=geo_data.get("url"),
                geo_title=title, geo_address=address,
            )
        elif is_contact:
            media_info.update(
                type="contact", icon="👤", label="联系人名片",
                contact_first_name=contact_data["first_name"],
                contact_last_name=contact_data["last_name"],
                contact_phone=contact_data["phone_number"],
                contact_user_id=contact_data["user_id"],
            )
        elif is_poll:
            media_info.update(type="poll", icon="📊", label="投票")
        elif is_game:
            media_info.update(type="game", icon="🎮", label="游戏")
        elif is_webpage:
            wp_url = webpage_data.get("url", "")
            wp_title = webpage_data.get("title", "")
            wp_site = webpage_data.get("site_name", "")

            # 标签显示：优先用站点名+标题，其次用 URL 域名
            if wp_title and wp_site:
                label_text = f"链接 · {wp_site} · {wp_title}"
            elif wp_title:
                label_text = f"链接 · {wp_title}"
            elif wp_url:
                parsed = urlparse(wp_url)
                domain = parsed.netloc or wp_url
                label_text = f"链接 · {domain}"
            else:
                label_text = "链接"

            media_info.update(
                type="webpage", icon="🔗", label=label_text,
                wp_url=wp_url, wp_title=webpage_data.get("title", ""),
                wp_description=webpage_data.get("description", ""),
                wp_site_name=wp_site,
                wp_display_url=webpage_data.get("display_url", ""),
            )
        elif is_voice:
            media_info.update(type="voice", icon="🎤", label="语音消息")
        elif is_video:
            media_info.update(type="video", icon="🎬", label="视频", duration=duration_sec)
            if filename:
                media_info["label"] = f"视频 · {filename}"
        elif is_audio:
            media_info.update(type="audio", icon="🎵", label="音频文件", duration=duration_sec)
        elif is_sticker:
            media_info.update(type="sticker", icon="😀", label="贴纸")
        elif is_gif:
            media_info.update(type="gif", icon="🎞️", label="GIF 动图")
        elif doc is not None:
            media_info.update(
                type="document", icon="📎",
                label=f"文件{' · ' + filename if filename else ''}",
            )

        media_info["filename"] = filename
        media_info["size_human"] = _fmt_size(file_size_bytes)

        if text and not is_webpage:
            # 普通文本消息（链接消息的 text 是 URL，不在这里显示，走卡片渲染）
            display_text = text
        elif media_info.get("type") == "geo" and media_info.get("geo_url"):
            # 位置消息：显示可点击的地图链接（内容区有特殊卡片渲染）
            url = media_info["geo_url"]
            label = media_info.get("label", "位置")
            icon = media_info.get("icon", "📍")
            display_text = f"{icon} {label}（{url}）"
        elif media_info.get("type") == "webpage":
            # 链接预览：优先用消息正文；正文为空时尝试用网页描述作为回退
            if text:
                display_text = text
            else:
                wp_desc = webpage_data.get("description", "")
                wp_title = webpage_data.get("title", "")
                display_text = wp_desc or wp_title or ""
        elif media_info.get("type") == "contact":
            # 联系人名片：直接展示联系人姓名和电话，避免外层回退为"(非文本消息)"
            cfname = media_info.get("contact_first_name", "")
            clname = media_info.get("contact_last_name", "")
            raw_phone = media_info.get("contact_phone", "")
            # 格式化手机号：识别国家代码并添加空格
            cphone = _format_phone_with_country_code(raw_phone)
            full_name = f"{cfname} {clname}".strip()
            if full_name and cphone:
                display_text = f"👤 联系人名片：{full_name}（{cphone}）"
            elif full_name:
                display_text = f"👤 联系人名片：{full_name}"
            elif cphone:
                display_text = f"👤 联系人名片：{cphone}"
            else:
                display_text = "👤 联系人名片"
        else:
            # 非文本媒体消息：内容区不再重复 icon/label/文件名/大小等信息，
            # 这些已由发件人行的彩色 media_badge 展示，避免冗余。
            if media_info.get("type") == "none":
                display_text = "(无内容)"
            else:
                display_text = ""

        return (display_text, media_info)

    def _check_mention(self, message) -> bool:
        """检查消息是否 @提及了目标用户
        
        检测逻辑（三层匹配）：
        1. MessageEntityMentionName：Telegram 内嵌用户提及实体，user_id 直接匹配
        2. MessageEntityMention：@username 文本格式，通过用户名匹配
        3. 文本兜底：检查消息文本中是否包含 @目标用户名
        """
        target_id = self.config.target_user_id

        # 获取目标用户名（配置中指定或从实体缓存获取）
        target_username = self.config.target_username
        if self._target_entity:
            entity_username = getattr(self._target_entity, "username", "") or ""
            if entity_username and not target_username:
                target_username = entity_username

        # 第1层：检查 MessageEntityMentionName（Telegram 原生用户提及实体）
        # 当用户在输入框中 @选择目标用户时，Telegram 会生成此实体
        if message.entities:
            for entity in message.entities:
                if isinstance(entity, MessageEntityMentionName):
                    if entity.user_id == target_id:
                        return True

                # 第2层：检查 MessageEntityMention（@username 文本格式）
                if isinstance(entity, MessageEntityMention):
                    if message.text and target_username:
                        mention_text = message.text[
                            entity.offset : entity.offset + entity.length
                        ]
                        clean_mention = mention_text.lstrip("@")
                        if clean_mention.lower() == target_username.lower():
                            return True

        # 第3层：文本兜底检查（防止实体解析遗漏）
        if message.text and target_username:
            pattern = rf'@{re.escape(target_username)}\b'
            if re.search(pattern, message.text, re.IGNORECASE):
                return True

        return False

    async def _check_reply_to_target_async(self, event) -> bool:
        """异步检查消息是否回复了目标用户的消息"""
        message = event.message
        if not message.reply_to:
            return False
        try:
            reply_msg = await event.get_reply_message()
            if reply_msg:
                # 排除 Forum 话题创建消息（reply_to 指向话题创建消息）
                action = getattr(reply_msg, "action", None)
                if action and type(action).__name__ == "MessageActionTopicCreate":
                    return False
                if reply_msg.from_id and isinstance(reply_msg.from_id, PeerUser):
                    return reply_msg.from_id.user_id == self.config.target_user_id
        except Exception:
            pass
        return False

    def _check_from_target(self, message) -> bool:
        """检查消息是否来自目标用户"""
        if message.from_id and isinstance(message.from_id, PeerUser):
            return message.from_id.user_id == self.config.target_user_id
        return False

    async def _check_is_bot_async(self, message) -> tuple[bool, str]:
        """异步检测消息是否来自监听列表的机器人，返回 (is_bot, bot_display_name)

        检测逻辑：
        1. 首先检查 message.from_id（消息发送者）是否为机器人
        2. 若 from_id 无法判断，则通过 message.peer_id（聊天对象）判断是否为机器人私聊

        注意：当用户向机器人发送命令时，from_id 是用户自身，peer_id 是机器人；
              当机器人回复时，from_id 是机器人，peer_id 是用户。
        """
        from telethon.tl.types import User as TlUser, PeerUser as TlPeerUser

        # 获取发送者 ID（优先用 from_id，这是真正的消息发送者）
        sender_id = None
        sender_is_from_id = False
        if hasattr(message, 'from_id') and message.from_id and isinstance(message.from_id, TlPeerUser):
            sender_id = message.from_id.user_id
            sender_is_from_id = True
        else:
            # 回退：直接从 peer_id 获取（私聊场景，此时 peer_id 即为对方）
            if isinstance(message.peer_id, TlPeerUser):
                sender_id = message.peer_id.user_id
                sender_is_from_id = False

        if not sender_id:
            return False, ""

        try:
            entity = await self._cached_get_entity(sender_id)
            if not isinstance(entity, TlUser) or not getattr(entity, 'bot', False):
                return False, ""
        except Exception as e:
            self.logger.debug(f"获取发送者信息失败：sender_id={sender_id}: {e}")
            return False, ""

        # 匹配监听列表中的机器人
        monitored_bots = self.config.monitored_bots
        bot_username = getattr(entity, 'username', '') or ''
        fn = getattr(entity, 'first_name', '') or ''
        ln = getattr(entity, 'last_name', '') or ''
        bot_display_name = f"{fn} {ln}".strip() or (f"@{bot_username}" if bot_username else str(sender_id))

        # 空列表 = 监听所有机器人
        if not monitored_bots:
            source_hint = "from_id(机器人主动发)" if sender_is_from_id else "peer_id(用户发给机器人)"
            self.logger.debug(f"机器人匹配成功（全局监听）：@{bot_username} (ID:{sender_id}) 来源={source_hint}")
            return True, bot_display_name

        for entry in monitored_bots:
            entry_str = str(entry).strip().lower()
            target = entry_str.lstrip('@')
            if target == str(sender_id) or (target and bot_username.lower() == target):
                source_hint = "from_id(机器人主动发)" if sender_is_from_id else "peer_id(用户发给机器人)"
                self.logger.debug(f"机器人匹配成功：{entry} → @{bot_username} (ID:{sender_id}) 来源={source_hint}")
                return True, bot_display_name

        self.logger.debug(f"是机器人但不在监听列表：@{bot_username} (ID:{sender_id})")
        return False, ""

    async def _check_any_bot(self, message) -> bool:
        """检查消息发送者是否为机器人（不校验监听列表）
        
        用于丢弃未在监听列表中的机器人消息，防止走私聊/群组逻辑。
        """
        from telethon.tl.types import User as TlUser, PeerUser as TlPeerUser

        sender_id = None
        if hasattr(message, 'from_id') and message.from_id and isinstance(message.from_id, TlPeerUser):
            sender_id = message.from_id.user_id
        else:
            if isinstance(message.peer_id, TlPeerUser):
                sender_id = message.peer_id.user_id

        if not sender_id:
            return False

        try:
            entity = await self._cached_get_entity(sender_id)
            return isinstance(entity, TlUser) and getattr(entity, 'bot', False)
        except Exception:
            return False

    async def _check_service_notification(self, message, chat_id: int) -> bool:
        """检查是否来自 Telegram 服务通知并包含触发关键词（如登录验证码）

        检测逻辑：
        1. 消息来自 Telegram 官方服务通知账号（ID: 777000）
        2. 消息文本包含配置中的任意触发关键词（不区分大小写）
        3. 符合条件则即时转发到邮箱（不走缓冲区合并）

        返回 True 表示已处理并转发，False 表示不匹配。
        """
        # 检查是否来自服务通知账号
        service_user_id = self.config.service_notification_user_id
        sender_id = None
        if hasattr(message, 'from_id') and message.from_id and isinstance(message.from_id, PeerUser):
            sender_id = message.from_id.user_id
        elif isinstance(message.peer_id, PeerUser):
            sender_id = message.peer_id.user_id

        if sender_id != service_user_id:
            return False

        # 检查消息文本是否包含触发关键词
        text = message.text or ""
        if not text:
            self.logger.debug(f"服务通知消息无文本内容，跳过")
            return False

        keywords = self.config.service_notification_keywords
        if not keywords:
            return False

        text_lower = text.lower()
        matched_keyword = None
        for kw in keywords:
            if kw.lower() in text_lower:
                matched_keyword = kw
                break

        if not matched_keyword:
            return False

        # 清理 Markdown 加粗标记（**），使邮件和日志显示更干净
        clean_text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)

        # === 匹配成功，即时转发到邮箱 ===
        self.logger.info(
            f"检测到服务通知登录验证码消息（关键词: {matched_keyword}）"
            f" | 内容: {clean_text}"
        )

        # 构建消息数据
        timestamp = self._format_timestamp(message.date)

        message_data = {
            "sender_name": "Telegram 服务通知",
            "text": clean_text,
            "timestamp": timestamp,
            "message_link": "",
            "reply_to_sender": "",
            "is_mention": False,
            "group_name": "Telegram 服务通知",
            "reason": f"服务通知-登录验证码",
            "media_info": {"type": "none", "icon": "", "label": "", "filename": "", "size_human": "", "duration": None},
        }

        # 使用 merge_interval=0 立即发送（登录验证码有时效性）
        # 直接调用 email_sender.send_email 发送，不走缓冲区定时合并
        subject = f"{self.config.subject_prefix} Telegram 服务通知 - 登录验证码"
        html_body = self.message_buffer._build_email_html("Telegram 服务通知", [message_data])

        success = await self.email_sender.send_email(subject, html_body)
        if success:
            self.logger.info(f"登录验证码邮件已发送：{clean_text}")
        else:
            self.logger.error("登录验证码邮件发送失败")

        return True

    def _check_group_filter(self, chat_id: int) -> bool:
        """检查群组是否在监听范围内"""
        monitored = self.config.monitored_groups
        ignored = self.config.ignored_groups

        # 转换为统一的整数列表
        monitored_ids = [int(g) if isinstance(g, (int, str)) and str(g).lstrip("-").isdigit() else g for g in monitored]
        ignored_ids = [int(g) if isinstance(g, (int, str)) and str(g).lstrip("-").isdigit() else g for g in ignored]

        # 如果指定了监听群组列表，则只监听这些群组
        if monitored_ids:
            if chat_id not in monitored_ids:
                return False

        # 检查忽略列表
        if chat_id in ignored_ids:
            return False

        return True

    def _check_user_filter(self, user_id: int) -> bool:
        """检查用户是否在监听范围内（用于私聊）"""
        monitored = self.config.monitored_users

        # 如果配置为空列表，则监听所有私聊用户
        if monitored is None or len(monitored) == 0:
            return True

        # 转换为统一的整数列表
        monitored_ids = [int(u) if isinstance(u, (int, str)) and str(u).lstrip("-").isdigit() else u for u in monitored]

        # 检查用户是否在监听列表中
        return user_id in monitored_ids

    def _log_new_entity(self, entity_type: str, entity_id: int, entity_name: str, seen_set: set) -> None:
        """检测到新出现的实体时，更新跟踪集合并打印增量统计日志

        在运行时实时更新启动时打印的群组/私聊/机器人数量统计。
        仅在新实体首次出现时打印一次，避免刷屏。
        """
        if entity_id in seen_set:
            return

        seen_set.add(entity_id)
        total = len(seen_set)
        self.logger.info(
            f"[实时统计] 新增{entity_type} → {entity_name} (ID: {entity_id}) | "
            f"当前{entity_type}总数: {total}"
        )

    async def _check_monitored_group_user(self, chat_id: int, event) -> tuple:
        """检查消息发送者是否在群组内指定监听用户列表中

        返回 (is_match: bool, reason: str)
        当配置的 monitored_group_users 中 group 匹配 chat_id 且 user 匹配发送者时返回 True。
        支持按 @username 和数字 ID 两种方式匹配用户。
        """
        monitored_entries = self.config.monitored_group_users
        if not monitored_entries:
            return False, ""

        message = event.message
        sender_id = None
        sender_username = ""

        # 从 from_id 获取发送者 ID
        if message.from_id and isinstance(message.from_id, PeerUser):
            sender_id = message.from_id.user_id

        # 尝试从 message.sender 获取用户名（Telethon 可能会预填充）
        sender = getattr(message, 'sender', None)
        if sender:
            sender_username = (getattr(sender, 'username', '') or '').lower()

        # 如果没有 sender 信息，异步获取发送者实体
        if not sender_username and sender is None:
            try:
                sender = await event.get_sender()
                if sender:
                    sender_username = (getattr(sender, 'username', '') or '').lower()
                    if not sender_id:
                        sender_id = getattr(sender, 'id', None)
            except Exception:
                pass

        for entry in monitored_entries:
            entry_group = entry.get("group")
            try:
                entry_group = int(entry_group)
            except (TypeError, ValueError):
                continue

            if int(chat_id) != entry_group:
                continue

            users = entry.get("users", [])
            for user in users:
                user_str = str(user).strip()

                if user_str.startswith("@"):
                    # 按用户名匹配
                    target_username = user_str.lstrip("@").lower()
                    if sender_username == target_username:
                        return True, f"群组内指定用户监听 ({user_str})"
                else:
                    # 按数字 ID 匹配
                    try:
                        target_id = int(user_str)
                        if sender_id is not None and int(sender_id) == target_id:
                            return True, f"群组内指定用户监听 (ID:{target_id})"
                    except (ValueError, TypeError):
                        continue

        return False, ""

    async def _get_group_name(self, chat_id: int, event=None) -> str:
        """获取群组名称（带缓存）

        chat_id: 完整群组 ID（含 -100 前缀的完整格式）
        event:   可选的事件对象，提供时优先用 event.get_chat()，否则用 _cached_get_entity
        """
        if chat_id in self._group_cache:
            return self._group_cache[chat_id]

        try:
            if event is not None:
                chat = await event.get_chat()
                name = getattr(chat, "title", None) or getattr(chat, "first_name", None) or str(chat_id)
            else:
                # 无 event 时用缓存 get_entity（减少 RPC）
                entity = await self._cached_get_entity(self._chat_id_to_peer(chat_id))
                name = getattr(entity, "title", "") or getattr(entity, "first_name", "") or str(chat_id)
            self._group_cache[chat_id] = name
            return name
        except Exception:
            return str(chat_id)

    async def _get_topic_name(self, message, peer, fallback_message=None) -> str:
        """获取论坛话题名称（如果消息属于 Forum Topic）

        参数:
            message: 主要消息对象（被置顶的消息或普通消息）
            peer: 消息所属的 peer
            fallback_message: 备选消息对象。当 message.reply_to 为空时（如被置顶的消息
                             经过 get_messages 简化后可能丢失 reply_to），可使用
                             备选消息的 reply_to（如 service 消息本身的 reply_to）
        """
        try:
            # 情况1: 消息本身就是话题创建消息
            action = getattr(message, "action", None)
            if action and type(action).__name__ == "MessageActionTopicCreate":
                return getattr(action, "title", "")

            # 获取 channel_entity 并检查是否为 Forum
            channel_entity = await self._cached_get_entity(peer)
            if not getattr(channel_entity, "forum", False):
                return ""

            # 情况2: 消息在话题中，从 reply_to 获取话题ID
            # 优先用 message.reply_to，如果为空则用 fallback_message.reply_to
            reply_to = getattr(message, "reply_to", None)
            if not reply_to and fallback_message is not None:
                reply_to = getattr(fallback_message, "reply_to", None)

            # 兜底：如果 reply_to 仍然为空，尝试重新获取消息
            # Telethon 的事件对象有时不返回 reply_to 字段，重新获取可以补全
            if not reply_to and getattr(message, "id", None):
                try:
                    fresh = await self.client.get_messages(peer, ids=message.id)
                    if fresh:
                        reply_to = getattr(fresh, "reply_to", None)
                except Exception:
                    pass

            if reply_to:
                # 在 Forum 中：
                #   - 普通话题消息：reply_to_msg_id 指向话题创建消息
                #   - 回复消息：reply_to_top_id 指向话题创建消息，reply_to_msg_id 指向被回复的具体消息
                topic_id = getattr(reply_to, "reply_to_top_id", None)
                if not topic_id:
                    # reply_to_msg_id 可能是话题创建消息本身（普通话题消息）
                    # 也可能是被回复的具体消息（回复消息）
                    msg_id = getattr(reply_to, "reply_to_msg_id", None)
                    if msg_id:
                        # 先尝试将 msg_id 当作话题创建消息直接获取标题
                        try:
                            topic_msg = await self.client.get_messages(peer, ids=msg_id)
                            if topic_msg:
                                topic_action = getattr(topic_msg, "action", None)
                                if topic_action and type(topic_action).__name__ == "MessageActionTopicCreate":
                                    return getattr(topic_action, "title", "")
                        except Exception:
                            pass

                        # 核心修复：topic_msg 没有 action 字段时（get_messages 可能不返回 action），
                        # msg_id 本身就是话题创建消息的 ID，直接用作 topic_id
                        # 不要落到 topic_id=1（General 话题）的错误分支！
                        if not topic_id:
                            topic_id = msg_id

                        # 只在上一步不成立时，才尝试追踪被回复消息所属的话题
                        if topic_id == msg_id and topic_msg and hasattr(topic_msg, "reply_to") and topic_msg.reply_to:
                            originated_topic = getattr(topic_msg.reply_to, "reply_to_top_id", None) or getattr(topic_msg.reply_to, "reply_to_msg_id", None)
                            if originated_topic:
                                topic_id = originated_topic

                        # 被回复消息没有 reply_to 且 msg_id 不是话题创建消息 → 在 General 话题中
                        if not topic_id:
                            topic_id = 1
                    else:
                        topic_id = 1
            else:
                # reply_to 为空 -> 消息在 General 话题中，ID 固定为 1
                topic_id = 1

            if not topic_id:
                return ""

            # 通过 get_messages 获取话题创建消息
            try:
                topic_msg = await self.client.get_messages(peer, ids=topic_id)
                if topic_msg:
                    topic_action = getattr(topic_msg, "action", None)
                    if topic_action and type(topic_action).__name__ == "MessageActionTopicCreate":
                        return getattr(topic_action, "title", "")
            except Exception:
                pass

            # 兜底：使用 get_forum_topics API 获取所有话题并匹配
            try:
                result = await self.client.get_forum_topics(channel_entity, limit=100)
                if result and result.topics:
                    for topic in result.topics:
                        if topic.id == topic_id:
                            return topic.title
            except Exception:
                pass

            # 兜底：使用 GetForumTopicsByIDRequest 直接获取话题名称
            # 适用于所有 topic_id（包括 topic_id=1 的 General 话题）
            try:
                from telethon.tl.functions.channels import GetForumTopicsByIDRequest
                result = await self.client(GetForumTopicsByIDRequest(
                    channel=channel_entity,
                    topics=[topic_id],
                ))
                if result and result.topics:
                    return result.topics[0].title
            except Exception:
                pass

            # topic_id=1（General 话题）的最后兜底：通过 GetFullChannelRequest
            # 获取群组完整信息中的 forum_topics 列表查找 ID=1 的标题
            # Telegram API 默认不返回 General 话题，此方法作为实验性补充
            if topic_id == 1:
                try:
                    from telethon.tl.functions.channels import GetFullChannelRequest
                    full = await self.client(GetFullChannelRequest(channel_entity))
                    full_chat = getattr(full, "full_chat", None)
                    if full_chat:
                        forum_topics = getattr(full_chat, "forum_topics", None)
                        if isinstance(forum_topics, list):
                            for t in forum_topics:
                                if getattr(t, "id", None) == 1:
                                    gen_title = getattr(t, "title", "")
                                    if gen_title:
                                        return gen_title
                except Exception:
                    pass

                # 所有方法都失败：返回空字符串（不写死"General"）
                return ""
        except Exception:
            pass

        return ""

    def _format_entity_display(self, entity, include_username: bool = True) -> str:
        """格式化用户/机器人/频道显示名称

        统一格式: [身份角色] 名称 [@username 或 ID]
        身份前缀规则（用于在日志/邮件中清晰区分消息来源身份）：
        - [Robot] 名称 @username:  机器人（User 类型且 bot=True）
        - [Channel] 名称 @username: 频道（Channel 类型且 broadcast=True）
        - [Group] 名称 @username:   超级群组（Channel 类型且 megagroup=True）
        - [Chat] 名称:              基础群组（Chat 类型）
        - [User] 名称 @username:    普通用户（User 类型，bot=False）
        - [Unknown] 用户ID:         兜底显示

        兜底规则：
        - 名称优先：first_name+last_name（User） / title（Channel/Chat）
        - 名称为空时回退：@username → ID
        - 附加后缀：优先 @username，没有 @username 时用 ID
        """
        if not entity:
            return "[Unknown] 未知用户"

        # 导入 Telethon 实体类型用于判断
        from telethon.tl import types as tl_types

        # === 1. Channel 类型：区分频道(broadcast)和超级群组(megagroup) ===
        if isinstance(entity, tl_types.Channel):
            title = getattr(entity, "title", "") or ""
            username = getattr(entity, "username", "") or ""
            channel_id = getattr(entity, "id", "")
            if getattr(entity, "broadcast", False):
                prefix = "Channel"
            elif getattr(entity, "megagroup", False):
                prefix = "Group"
            else:
                prefix = "Channel"
            # 主名称：优先 title，其次 ID
            if title:
                display_name = title
            else:
                display_name = f"频道{channel_id}"
            result = f"[{prefix}] {display_name}"
            # 附加后缀：@username 或 ID（如果主名称已用 ID 兜底则不重复）
            if include_username:
                if username:
                    result += f" @{username}"
                elif title:
                    # title 存在但没有 username，用 ID 兜底
                    result += f" ID:{channel_id}"
            return result

        # === 2. Chat 类型：基础群组（小群聊）===
        if isinstance(entity, tl_types.Chat):
            title = getattr(entity, "title", "") or ""
            chat_id = getattr(entity, "id", "")
            if title:
                display_name = title
            else:
                display_name = f"群组{chat_id}"
            return f"[Chat] {display_name}"

        # === 3. User 类型：区分机器人和普通用户 ===
        is_bot = getattr(entity, "bot", False)
        first = getattr(entity, "first_name", "") or ""
        last = getattr(entity, "last_name", "") or ""
        username = getattr(entity, "username", "") or ""
        user_id = getattr(entity, "id", "")

        # 拼接显示名称：first_name + last_name
        name = f"{first} {last}".strip()
        prefix = "Robot" if is_bot else "User"

        # 主名称：优先 name（first_name+last_name），其次 ID
        if name:
            display_name = name
        else:
            display_name = f"用户{user_id}"
        result = f"[{prefix}] {display_name}"

        # 附加后缀：@username 或 ID
        if include_username:
            if username:
                result += f" @{username}"
            elif name:
                # name 存在但没有 username，用 ID 兜底
                result += f" ID:{user_id}"
        return result

    def _chat_id_to_peer(self, chat_id: int):
        """根据 chat_id 构造对应的 Peer 对象"""
        s = str(chat_id)
        if s.startswith("-100"):
            return PeerChannel(int(s[4:]))
        elif chat_id < 0:
            return PeerChat(-chat_id)
        else:
            return PeerUser(chat_id)

    async def _cached_get_entity(self, peer, ttl_seconds: int = 300):
        """带一级缓存 + TTL 的 get_entity

        避免相同 peer（用户/频道/群组）在短时间内被反复 RPC 拉取，
        这是降低 429 频率最核心的手段。Telegram 实体信息（用户名/头像等）
        在会话期间几乎不变，300 秒缓存完全安全。

        参数:
            peer: 与 client.get_entity() 一致的参数格式（int / PeerUser / PeerChannel / PeerChat / str）
            ttl_seconds: 缓存生存期秒数（默认 300 秒）
        """
        # 生成统一缓存 key
        cache_key = None
        if isinstance(peer, int):
            cache_key = ("user", peer)
        elif isinstance(peer, PeerUser):
            cache_key = ("user", peer.user_id)
        elif isinstance(peer, PeerChannel):
            cache_key = ("channel", peer.channel_id)
        elif isinstance(peer, PeerChat):
            cache_key = ("chat", peer.chat_id)

        if cache_key and cache_key in self._entity_cache:
            entry = self._entity_cache[cache_key]
            if isinstance(entry, tuple) and len(entry) == 2:
                cached_entity, deadline = entry
                if time.monotonic() < deadline:
                    return cached_entity
                # 过期：移除旧条目
                del self._entity_cache[cache_key]
            else:
                # 兼容旧格式（无 TTL）
                return entry

        entity = await self.client.get_entity(peer)
        if cache_key:
            # 超过最大容量时清理一半旧数据
            if len(self._entity_cache) >= self._entity_cache_max_size:
                self._clean_entity_cache()
            self._entity_cache[cache_key] = (entity, time.monotonic() + ttl_seconds)
        return entity

    def _clean_entity_cache(self):
        """清理 entity_cache：丢弃最早的一半条目"""
        now = time.monotonic()
        # 先移除过期条目
        expired_keys = [
            k for k, v in self._entity_cache.items()
            if isinstance(v, tuple) and len(v) == 2 and v[1] < now
        ]
        for k in expired_keys:
            del self._entity_cache[k]
        # 如果还是超过一半，丢弃最早的一半
        if len(self._entity_cache) >= self._entity_cache_max_size // 2:
            sorted_items = sorted(
                self._entity_cache.items(),
                key=lambda x: x[1][1] if isinstance(x[1], tuple) and len(x[1]) == 2 else 0,
            )
            for k, _ in sorted_items[:len(sorted_items) // 2]:
                del self._entity_cache[k]

    async def _get_user_entity(self, user_id: int, chat_peer=None):
        """尝试多种方式获取用户实体（优先走实体缓存）"""
        # 先走缓存
        try:
            cached = await self._cached_get_entity(PeerUser(user_id))
            return cached
        except Exception:
            pass
        if chat_peer is not None:
            try:
                from telethon.tl.functions.channels import GetParticipantRequest
                result = await self.client(GetParticipantRequest(chat_peer, user_id))
                user = getattr(getattr(result, "participant", None), "user", None)
                if user:
                    return user
            except Exception:
                pass
        return None

    async def _get_sender_name(self, event) -> str:
        """获取消息发送者名称"""
        try:
            sender = await event.get_sender()
            if sender:
                return self._format_entity_display(sender, include_username=True)
        except Exception:
            pass
        return "未知用户"

    async def _get_reply_to_sender(self, event) -> str:
        """获取被回复消息的发送者名称和内容，格式为：发送者名 | 消息内容"""
        import html as _html
        message = event.message

        # === 方法1: 使用 Telethon 的 get_reply_message（首选）===
        try:
            reply_msg = await event.get_reply_message()
            self.logger.debug(
                f"[回复检测] get_reply_message 结果: "
                f"type={type(reply_msg).__name__ if reply_msg else 'None'} "
                f"id={reply_msg.id if reply_msg else 'N/A'}"
            )
            if reply_msg and hasattr(reply_msg, 'from_id') and reply_msg.from_id:
                # 排除 Forum 话题创建消息（reply_to 指向话题创建消息）
                action = getattr(reply_msg, "action", None)
                if action and type(action).__name__ == "MessageActionTopicCreate":
                    return ""
                sender = await self._cached_get_entity(reply_msg.from_id)
                sender_name = getattr(sender, "first_name", "") or str(reply_msg.from_id.user_id)

                reply_text = (reply_msg.text or "")[:100]
                if reply_msg.text and len(reply_msg.text) > 100:
                    reply_text += "..."

                result = ""
                if reply_text:
                    result = f"{sender_name} | {_html.escape(reply_text)}"
                    self.logger.debug(f"被回复消息信息（get_reply）：{result}")
                    return result
                else:
                    _, media_info = self._build_message_text_and_media(reply_msg)
                    media_label = media_info.get("label", "")
                    if media_label:
                        result = f"{sender_name} | [{media_label}]"
                        self.logger.info(f"被回复消息（非文本）：{result}")
                        return result
                    self.logger.info(f"被回复消息发送者：{sender_name}（无内容）")
                    return sender_name
            elif reply_msg:
                self.logger.warning(f"被回复消息存在但缺少 from_id: id={reply_msg.id}")
            else:
                self.logger.info("get_reply_message() 返回 None，尝试兜底方案")
        except Exception as e:
            self.logger.warning(f"get_reply_message 失败: {e}")

        # === 方法2（兜底）: 从 message.reply_to.reply_to_msg_id 手动获取 ===
        try:
            if hasattr(message, 'reply_to') and message.reply_to:
                reply_header = message.reply_to
                reply_to_id = getattr(reply_header, 'reply_to_msg_id', None)
                chat_peer = getattr(message, 'peer_id', None)
                self.logger.debug(
                    f"[回复检测-兜底] reply_to_msg_id={reply_to_id} peer_id={chat_peer}"
                )
                if reply_to_id is not None and chat_peer:
                    from telethon.tl.types import PeerChannel as PC, PeerChat as PCh
                    if isinstance(chat_peer, (PC, PCh)):
                        replied = await self.client.get_messages(chat_peer, ids=reply_to_id)
                        if replied:
                            # 排除 Forum 话题创建消息（reply_to 指向话题创建消息）
                            action = getattr(replied, "action", None)
                            if action and type(action).__name__ == "MessageActionTopicCreate":
                                return ""
                            r_sender_name = "未知"
                            if replied.from_id:
                                try:
                                    r_sender = await self._cached_get_entity(replied.from_id)
                                    r_sender_name = getattr(r_sender, "first_name", "") or str(replied.from_id.user_id)
                                except Exception:
                                    pass
                            r_text = (replied.text or "")[:100]
                            fallback = ""
                            if r_text:
                                fallback = f"{r_sender_name} | {_html.escape(r_text)}"
                            elif r_sender_name != "未知":
                                fallback = r_sender_name
                            if fallback:
                                self.logger.debug(f"兜底获取到被回复消息：{fallback}")
                                return fallback
                        else:
                            self.logger.warning(f"兜底: get_messages(ids={reply_to_id}) 返回空")
            else:
                self.logger.debug(f"[回复检测] message.reply_to 不存在或为空: {getattr(message, 'reply_to', None)}")
        except Exception as e2:
            self.logger.warning(f"兜底获取被回复消息失败: {e2}", exc_info=True)

        return ""

    def _get_message_link(self, message, chat_id: int) -> str:
        """获取消息链接"""
        if not self.config.include_message_link:
            return ""

        try:
            # 频道/超级群组的消息有链接
            if isinstance(message.peer_id, PeerChannel):
                channel_id = message.peer_id.channel_id
                # 需要获取 channel 的 username 来构建链接
                # 简化处理：使用 chat_id
                return f"https://t.me/c/{channel_id}/{message.id}"
            elif isinstance(message.peer_id, PeerChat):
                return f"https://t.me/c/{message.peer_id.chat_id}/{message.id}"
        except Exception:
            pass
        return ""

    @staticmethod
    def _get_chat_id(peer_id) -> int | None:
        """从 Peer 对象获取 chat ID"""
        if isinstance(peer_id, PeerChat):
            return -peer_id.chat_id
        elif isinstance(peer_id, PeerChannel):
            # Channel 的 ID 需要加上 -100 前缀
            return -1000000000000 - peer_id.channel_id
        elif isinstance(peer_id, PeerUser):
            return peer_id.user_id
        return None

    @staticmethod
    def _format_timestamp(dt: datetime) -> str:
        """格式化时间戳为北京时间"""
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        tz_shanghai = timezone(timedelta(hours=8))
        return dt.astimezone(tz_shanghai).strftime("%Y-%m-%d %H:%M:%S")

    async def stop(self):
        """停止转发器"""
        self.logger.info("正在停止转发器...")
        self._running = False

        # 刷新所有缓冲区
        try:
            await self.message_buffer.flush_all()
        except Exception as e:
            self.logger.error(f"刷新缓冲区失败：{e}")

        # 断开 Telegram 连接
        if self.client and self.client.is_connected():
            await self.client.disconnect()

        self.logger.info("转发器已停止")


# ============================================
# 登录助手
# ============================================
async def login_only(config: Config):
    """仅执行登录（首次认证时使用）"""
    logger = logging.getLogger("tg_forwarder")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)

    logger.info("正在启动 Telegram 客户端进行首次登录认证...")
    logger.info("请按照提示输入验证码和二步验证密码（如有）")

    # 复用统一的 client 创建逻辑（代理配置集中处理）
    client = create_telegram_client(config, logger)

    await client.connect()

    # 手动发送验证码请求
    sent = await client.send_code_request(config.phone)

    # 自定义验证码提示
    code = input(f"\nPlease check and enter your Telegram Login Code: ").strip()
    
    try:
        me = await client.sign_in(config.phone, code, password=None)
    except Exception as e:
        if "2FA" in str(e) or "password" in str(e).lower():
            password = input("\nPlease enter your 2FA Password: ")
            me = await client.sign_in(config.phone, code, password=password)
        else:
            raise

    logger.info(f"Signed in successfully as {me.first_name or ''} {me.last_name or ''} ; remember to not break the ToS or you will risk an account ban!")
    logger.info(f"Session 文件已保存：{config.session_name}.session")
    logger.info("现在可以使用 python forwarder.py 启动转发器了")

    await client.disconnect()


# ============================================
# 主入口
# ============================================
def main():
    parser = argparse.ArgumentParser(
        description="Telegram 消息转发器 - 监听群组@提及消息并转发到QQ邮箱"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="配置文件路径（默认：config.yaml）",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="仅执行登录认证（首次使用时需要）",
    )
    args = parser.parse_args()

    try:
        config = Config(args.config)
    except ValueError as e:
        print(f"配置错误：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"加载配置失败：{e}")
        sys.exit(1)

    if args.login:
        asyncio.run(login_only(config))
        return

    forwarder = TelegramForwarder(config)

    # 启动前清理临时文件（__pycache__、残留的 SQLite 临时文件）
    _cleanup_temp_files(config.session_name, forwarder.logger)

    # 优雅退出
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def shutdown(signal_name=None):
        if signal_name:
            forwarder.logger.info(f"收到信号 {signal_name}，正在优雅退出...")
        await forwarder.stop()
        loop.stop()

    # 注册信号处理器
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: loop.create_task(shutdown(s)))
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass

    try:
        loop.run_until_complete(forwarder.start())
    except KeyboardInterrupt:
        forwarder.logger.info("收到键盘中断，正在退出...")
    finally:
        # 确保缓冲区刷新
        try:
            loop.run_until_complete(forwarder.message_buffer.flush_all())
        except Exception:
            pass
        try:
            loop.run_until_complete(forwarder.client.disconnect())
        except Exception:
            pass
        loop.close()

        # 退出后清理临时文件（SQLite 连接已关闭，残留临时文件可安全删除）
        _cleanup_temp_files(config.session_name, forwarder.logger)


if __name__ == "__main__":
    main()
