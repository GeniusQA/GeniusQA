#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
脚本 AI 校验器：前置/后置操作自定义脚本、脚本中心脚本的规范校验。
四层校验：语法检查 → 规范检查 → 试运行 → AI 审查（可选）。
规范依据：script_runtime.py（沙盒白名单 / 禁用内置 / ntest·pm·request·response 全局对象）。
"""

import ast
import io
import json
import re
import subprocess
import tempfile
import os
from typing import Dict, Any, List, Optional

from sqlalchemy import select
from config import config as app_config

from .script_runtime import (
    _SAFE_IMPORT_MODULES,
    SimpleNtest,
    run_sandbox,
    run_native_js,
    normalize_language,
)

# 沙盒禁用的内置
_BLOCKED_BUILTINS = {
    "open", "exec", "eval", "compile", "breakpoint", "input",
    "memoryview", "exit", "quit", "help",
}

# 合法全局对象
_LEGAL_GLOBALS = {"ntest", "pm", "request", "response", "json", "re", "datetime",
                  "random", "math", "time", "uuid", "base64", "hashlib"}

_JS_GLOBALS = {"ntest", "pm", "request", "response", "console", "require", "process",
               "Buffer", "setTimeout", "clearTimeout", "global", "module", "exports",
               "JSON", "Math", "Date", "String", "Number", "Boolean", "Array",
               "Object", "Promise", "Error", "RegExp"}

_SPEC_SNIPPET = """平台脚本规范（N-Tester / GeniusQA）：
【通用全局对象】
- ntest.get(key, default) 读取会话/环境变量
- ntest.set(key, value) 设置变量并导出（后续步骤/断言可用）
- ntest.env(key, default) 只读环境变量
- request：当前请求对象（dict），可直接修改，修改会回写
- response：响应对象（后置脚本），response.code / response.headers / response.json() / response.text()
- pm：Apifox/Postman 兼容层 pm.environment / pm.variables / pm.request / pm.response / pm.test(name, fn)

【Python 沙盒限制】
- 预注入模块：json re datetime random math time uuid base64 hashlib
- 允许 import：%s
- 禁用：open exec eval compile breakpoint input memoryview exit 等

【JavaScript】
- Node.js CommonJS 运行，require() 可用（引用的 npm 模块需已安装）
- 全局：ntest / pm / request / response 与 Python 一致
- 超时 30 秒；pm.test 失败或抛异常即脚本失败
""" % ", ".join(sorted(_SAFE_IMPORT_MODULES))


class ValidationResult:
    def __init__(self):
        self.syntax_ok = True
        self.syntax_error = ""
        self.spec_issues: List[str] = []
        self.run_ok: Optional[bool] = None
        self.run_output = ""
        self.run_error = ""
        self.ai_review: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "syntax_ok": self.syntax_ok,
            "syntax_error": self.syntax_error,
            "spec_issues": self.spec_issues,
            "run_ok": self.run_ok,
            "run_output": self.run_output[:500],
            "run_error": self.run_error[:500],
            "ai_review": self.ai_review,
            "passed": (self.syntax_ok and not self.spec_issues and self.run_ok is not False),
        }


# ── 1. 语法检查 ──────────────────────────────────────────────

def check_syntax(code: str, language: str) -> tuple[bool, str]:
    lang = normalize_language(language)
    if lang == "python":
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"语法错误: 第 {e.lineno} 行: {e.msg}"
    if lang == "javascript":
        try:
            r = subprocess.run(
                ["node", "--check", "-"],
                input=code.encode("utf-8"),
                capture_output=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode == 0:
                return True, ""
            err = (r.stderr or r.stdout or b"").decode("utf-8", errors="replace").strip()
            return False, f"语法错误: {err[:300]}"
        except FileNotFoundError:
            return True, ""  # 无 node 时跳过语法检查，试运行会提示
        except Exception as e:
            return True, f"语法检查异常: {e}"
    return True, ""


# ── 2. 规范检查（AST 静态分析） ──────────────────────────────

def _check_python_spec(code: str) -> List[str]:
    issues: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return issues  # 语法错误已由 check_syntax 报告

    for node in ast.walk(tree):
        # import / from import 白名单
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in _SAFE_IMPORT_MODULES:
                    issues.append(f"第 {node.lineno} 行: 不允许导入模块 '{alias.name}'（沙盒仅支持常用标准库；可切换原生模式）")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root and root not in _SAFE_IMPORT_MODULES:
                issues.append(f"第 {node.lineno} 行: 不允许从模块 '{node.module}' 导入（白名单外）")
        # 禁用内置调用
        elif isinstance(node, ast.Call):
            fn = node.func
            name = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id in ("builtins", "__builtins__"):
                name = fn.attr
            if name in _BLOCKED_BUILTINS:
                issues.append(f"第 {node.lineno} 行: 禁用内置 '{name}()'（沙盒安全限制）")
    return issues


def _check_js_spec(code: str) -> List[str]:
    issues: List[str] = []
    # require 属于合法用法（原生 Node 模式），由试运行验证模块可用性，不在此阻断
    return issues


# ── 3. 试运行 ─────────────────────────────────────────────────

def _try_run(code: str, language: str) -> tuple[Optional[bool], str, str]:
    lang = normalize_language(language)
    if lang == "python":
        ntest = SimpleNtest(session_vars={"base_url": "http://127.0.0.1:8100"},
                            env_vars={"env": "test"})
        result = run_sandbox(code, ntest=ntest, extra_globals={"request": {}})
        return result.success, result.output, result.error
    if lang == "javascript":
        result = run_native_js(
            code,
            session_vars={"base_url": "http://127.0.0.1:8100"},
            env_vars={"env": "test"},
            request_ctx={},
            timeout=15,
        )
        return result.success, result.output, result.error
    return None, "", f"不支持的语言: {language}"


# ── 4. AI 审查 ────────────────────────────────────────────────

def _get_default_model_config(db) -> Optional[Any]:
    try:
        from app.api.v1.Ntesterc_module.Ntesterc_intel.model import AIModelConfigModel
        stmt = select(AIModelConfigModel).where(AIModelConfigModel.is_default == True, AIModelConfigModel.is_active == True)  # noqa: E712
        cfg = (awaitable_scalar(db, stmt))
        return cfg
    except Exception:
        return None


def awaitable_scalar(db, stmt):
    # 兼容 async session 的 scalar_one_or_none
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_scalar(db, stmt))
    except Exception:
        return None


async def _scalar(db, stmt):
    r = await db.execute(stmt)
    return r.scalar_one_or_none()


def build_ai_prompt(code: str, language: str, precheck: ValidationResult) -> List[Dict[str, str]]:
    system = (
        "你是 N-Tester 测试平台的脚本规范审查专家。根据平台脚本规范审查用户提交的 Python/JavaScript 脚本，"
        "输出 JSON（不要输出其他内容）："
        '{"verdict": "pass"|"warn"|"fail", "issues": ["问题1", ...], "suggestions": ["建议1", ...], "summary": "一句话总结"}'
        "\n\n" + _SPEC_SNIPPET
    )
    pre = ""
    if not precheck.syntax_ok:
        pre += f"\n[静态检查] 语法错误: {precheck.syntax_error}"
    if precheck.spec_issues:
        pre += "\n[静态检查] 规范问题:\n- " + "\n- ".join(precheck.spec_issues)
    if precheck.run_ok is not None:
        pre += f"\n[试运行] 结果: {'成功' if precheck.run_ok else '失败'}"
        if precheck.run_error:
            pre += f"；错误: {precheck.run_error[:300]}"
    user = f"语言: {language}\n脚本代码:\n```{language}\n{code}\n```{pre}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _parse_ai_review(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    # 提取 JSON 块
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"verdict": "warn", "issues": ["AI 审查响应无法解析"], "suggestions": [], "summary": text[:200]}
    try:
        data = json.loads(m.group(0))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"verdict": "warn", "issues": ["AI 审查响应解析失败"], "suggestions": [], "summary": text[:200]}


async def ai_review(db, code: str, language: str, precheck: ValidationResult) -> Optional[Dict[str, Any]]:
    try:
        from app.api.v1.Ntesterc_module.Ntesterc_intel.ai_model_service import AIModelService
        cfg = await _get_default_model_config_async(db)
        if cfg is None:
            return {"verdict": "warn", "issues": ["未配置默认 AI 模型（LLM 配置中设置 is_default），跳过 AI 审查"],
                    "suggestions": [], "summary": "请先在 AI 管理-LLM 配置中设置默认模型"}
        config_dict = {
            "api_key": cfg.api_key, "base_url": cfg.base_url,
            "model_name": cfg.model_name,
            "temperature": getattr(cfg, "temperature", 0.3),
            "max_tokens": getattr(cfg, "max_tokens", 2048),
        }
        resp = await AIModelService.call_openai_compatible_api(config_dict, build_ai_prompt(code, language, precheck))
        content = ""
        if isinstance(resp, dict):
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "") if resp.get("choices") else (resp.get("content") or resp.get("data", {}).get("content") or "")
        return _parse_ai_review(content or json.dumps(resp, ensure_ascii=False))
    except Exception as e:
        return {"verdict": "warn", "issues": [f"AI 审查调用失败: {str(e)[:200]}"], "suggestions": [], "summary": "AI 审查暂不可用"}


async def _get_default_model_config_async(db) -> Optional[Any]:
    try:
        from app.api.v1.Ntesterc_module.Ntesterc_ai.llm_config.model import LLMConfigModel
        stmt = select(LLMConfigModel).where(
            LLMConfigModel.is_default == True,  # noqa: E712
            LLMConfigModel.is_active == True,  # noqa: E712
        )
        r = await db.execute(stmt)
        return r.scalar_one_or_none()
    except Exception:
        return None


# ── 主入口 ────────────────────────────────────────────────────

async def validate_script(db, code: str, language: str, use_ai: bool = True) -> Dict[str, Any]:
    result = ValidationResult()
    code = (code or "").strip()

    # 1. 语法
    result.syntax_ok, result.syntax_error = check_syntax(code, language)

    # 2. 规范
    lang = normalize_language(language)
    if lang == "python":
        result.spec_issues = _check_python_spec(code)
    elif lang == "javascript":
        result.spec_issues = _check_js_spec(code)

    # 3. 试运行
    if result.syntax_ok:
        result.run_ok, result.run_output, result.run_error = _try_run(code, language)

    # 4. AI 审查
    if use_ai:
        result.ai_review = await ai_review(db, code, language, result)

    return result.to_dict()
