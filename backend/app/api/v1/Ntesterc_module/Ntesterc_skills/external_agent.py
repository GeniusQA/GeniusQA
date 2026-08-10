# -*- coding: utf-8 -*-
"""外部编程 Agent（Claude Code / Codex / OpenCode）调用装配。

两类目标 Agent 都依赖外部编程 Agent 驱动：
- Playwright Test Agents：init-agents --loop=<vscode|claude|codex|opencode> 后由 loop 执行
- agent-device：以 MCP server 形式被 Claude Code 等加载，由外部 Agent 驱动 inspect-act-verify

本模块只负责「构造命令 + 探测可用 Agent 二进制 + 生成 MCP 配置」，不碰数据库。
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

SUPPORTED_AGENTS = ("claude", "codex", "opencode")

# 默认值可按实际安装的 CLI 调整
DEFAULT_PW_TEST_AGENTS_INIT = "npx @playwright/test init-agents"
AGENT_DEVICE_DEFAULT_CMD = "npx agent-device"


def detect_external_agents(custom_agents: Optional[List[str]] = None) -> Dict[str, Dict[str, str]]:
    """探测本机可用的外部 Agent CLI 二进制。

    支持传入自定义 Agent 名称列表，与默认支持的 Agent 一起探测。
    自定义 Agent 保留原始大小写作为展示 key，查找时转小写。
    """
    result: Dict[str, Dict[str, str]] = {}
    agents = list(SUPPORTED_AGENTS)
    display_names: Dict[str, str] = {}
    for raw in (custom_agents or []):
        raw = (raw or "").strip()
        name = raw.lower()
        if name and name not in agents:
            agents.append(name)
            display_names[name] = raw
    for name in agents:
        # 自定义 Agent 若为绝对路径/含目录分隔符，直接按文件是否存在判定
        if (os.path.isabs(name) or "\\" in name or "/" in name) and os.path.isfile(name):
            key = display_names.get(name, name)
            result[key] = {"binary": key, "available": True}
            continue
        path = shutil.which(name) or shutil.which(f"{name}.cmd") or shutil.which(f"{name}.exe")
        key = display_names.get(name, name)
        result[key] = {"binary": path or "", "available": bool(path)}
    # npx 作为兜底（Playwright Test Agents / agent-device 常以 npx 包形式存在）
    if "npx" not in result and "npx" not in display_names:
        npx = shutil.which("npx") or shutil.which("npx.cmd")
        result["npx"] = {"binary": npx or "", "available": bool(npx)}
    return result


def resolve_agent_binary(agent: str) -> Optional[str]:
    """解析 Agent 二进制路径。支持自定义 Agent 名称（通过 PATH 直接查找）。"""
    agent = (agent or "").strip().lower()
    if not agent:
        return None
    info = detect_external_agents().get(agent)
    if info and info.get("available"):
        return info["binary"]
    # 允许任意自定义 Agent 名称
    return shutil.which(agent) or shutil.which(f"{agent}.cmd") or shutil.which(f"{agent}.exe")


def _shell_quote_arg(s: str) -> str:
    """用于 cmd.exe / sh 的简易引号包裹（内部双引号转义）。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _escape_prompt(prompt: str) -> str:
    """将 prompt 转义为可放在双引号 '-p "..."' 内的安全字符串（cmd.exe 语义）。"""
    return prompt.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


def write_mcp_config_file(servers: List[Dict[str, Any]]) -> Path:
    """将 agent-device 等 MCP server 配置写成临时 mcp.json，供 Claude Code --mcp-config 加载。"""
    payload: Dict[str, Any] = {"mcpServers": {}}
    for s in servers:
        name = s.get("name")
        entry = s.get("entry")
        if name and entry:
            payload["mcpServers"][name] = entry
    home = Path.home()
    d = home / ".n-tester" / "agent-runtime"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"mcp_{abs(hash(json.dumps(payload, sort_keys=True)))}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def build_external_agent_command(
    *,
    agent: str,
    prompt: str,
    mcp_config_path: Optional[str] = None,
    permission_mode: str = "bypassPermissions",
    model: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> str:
    """构造外部 Agent CLI 命令（在本机 cwd 下执行）。

    Claude Code: claude --permission-mode bypassPermissions [--mcp-config path] [-p "prompt"]
    Codex:       codex --approval-mode unchecked --mcp-config path -q "prompt"
    OpenCode:    opencode --mcp-config path -p "prompt"
    """
    agent_raw = (agent or "claude").strip()
    agent = agent_raw.lower()
    # 绝对路径自定义 Agent：直接作为可执行文件，保留原始大小写，无需系统 PATH
    if os.path.isabs(agent_raw) and os.path.isfile(agent_raw):
        bin_path = agent_raw
    else:
        bin_path = resolve_agent_binary(agent) or agent
    # 路径含空格时必须加引号，否则 cmd.exe 会按空格拆断
    if " " in bin_path and not (bin_path.startswith('"') and bin_path.endswith('"')):
        bin_path = _shell_quote_arg(bin_path)

    if agent == "claude":
        parts = [bin_path, "--permission-mode", permission_mode]
    elif agent == "codex":
        parts = [bin_path, "--approval-mode", "unchecked"]
    elif agent == "opencode":
        parts = [bin_path]
    else:
        parts = [bin_path]

    if mcp_config_path:
        parts += ["--mcp-config", _shell_quote_arg(mcp_config_path)]
    if model:
        parts += ["--model", model]
    if extra_args:
        parts += list(extra_args)

    if agent == "codex":
        parts += [_shell_quote_arg(prompt)]
    else:
        parts += ["-p", _shell_quote_arg(prompt)]
    return " ".join(parts)


def build_pw_test_agents_scaffold_command(*, loop: str, command: Optional[str] = None) -> str:
    """构造 Playwright Test Agents 脚手架命令（init-agents --loop=...）。"""
    loop = (loop or "claude").strip().lower()
    if command and command.strip():
        return command.strip()
    return f"{DEFAULT_PW_TEST_AGENTS_INIT} --loop={loop}"


def build_agent_device_prompt(*, device_ref: str, task: str, session_name: str, os_type: str = "android") -> str:
    """构造面向 agent-device MCP 的测试执行 prompt。"""
    ref = device_ref or "default"
    return (
        f"使用 agent-device MCP 在 {os_type} 设备 {ref} 上执行测试任务。"
        f"请通过 mcp 工具连接设备（session={session_name}），"
        f"按 inspect-act-verify 循环完成：{task}。"
        f"完成后用稳定选择器将步骤录制到 .ad 脚本以便后续免 Agent 回放。"
    )


def agent_device_server_entry(command: str, args: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """生成写入 Claude Code --mcp-config 的 agent-device stdio server 项。"""
    entry: Dict[str, Any] = {
        "type": "stdio",
        "command": command or AGENT_DEVICE_DEFAULT_CMD,
        "args": list(args or []),
    }
    if env:
        entry["env"] = {str(k): str(v) for k, v in env.items() if k}
    return entry
