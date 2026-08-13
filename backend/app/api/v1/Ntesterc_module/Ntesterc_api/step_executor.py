#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: Rebort

from __future__ import annotations

import asyncio
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import jmespath
import pymysql
from jsonpath_ng import parse as jsonpath_parse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .model import ApiDatabaseModel, ApiModel
from .script_runtime import normalize_language, resolve_exec_mode, run_native, run_sandbox


# ---------------------------------------------------------------------------
# VariableContext — 步骤间变量共享 + ${var} 替换
# ---------------------------------------------------------------------------

_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")
_MUSTACHE_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")


class VariableContext:
    """维护 session_vars（步骤间共享）和 env_vars（环境只读）。"""

    def __init__(self, env_vars: Optional[Dict[str, Any]] = None):
        self.session_vars: Dict[str, Any] = {}
        self.env_vars: Dict[str, Any] = env_vars or {}

    def set(self, key: str, value: Any) -> None:
        self.session_vars[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.session_vars.get(key, self.env_vars.get(key, default))

    @staticmethod
    def _normalize_key(key: str) -> str:
        k = str(key or "").strip()
        if k.startswith("{{") and k.endswith("}}"):
            k = k[2:-2].strip()
        if k.startswith("${") and k.endswith("}"):
            k = k[2:-1].strip()
        if k.startswith("env."):
            k = k[4:].strip()
        return k

    def _lookup(self, key: str, fallback: str) -> str:
        k = self._normalize_key(key)
        if not k:
            return fallback
        if k.startswith("env."):
            val = self.env_vars.get(k[4:])
        else:
            val = self.session_vars.get(k, self.env_vars.get(k))
        if val is None:
            return fallback
        return str(val)

    def resolve(self, data: Any) -> Any:
        """递归替换 ${var} / {{var}} 占位符。未定义变量保留原文。"""
        if isinstance(data, str):
            text = data

            def _replace_dollar(m: re.Match) -> str:
                return self._lookup(m.group(1), m.group(0))

            def _replace_mustache(m: re.Match) -> str:
                return self._lookup(m.group(1), m.group(0))

            text = _VAR_PATTERN.sub(_replace_dollar, text)
            text = _MUSTACHE_PATTERN.sub(_replace_mustache, text)
            return text
        if isinstance(data, dict):
            return {k: self.resolve(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self.resolve(i) for i in data]
        return data

    def apply_extracts(self, extracts: List[Dict], response: Dict) -> List[Dict]:
        """从响应中提取变量写入 session_vars，返回带结果的提取列表。"""
        results = []
        for ext in extracts:
            name = ext.get("name", "")
            path = ext.get("path", "")
            extract_type = (ext.get("extract_type") or "jmespath").lower()
            result = dict(ext)
            try:
                value = _extract_value(extract_type, path, response)
                self.set(name, value)
                result["extract_result"] = "pass"
                result["extract_value"] = value
            except Exception as e:
                result["extract_result"] = "fail"
                result["message"] = str(e)
            results.append(result)
        return results


def _extract_value(extract_type: str, path: str, response: Dict) -> Any:
    """从 response 中按类型提取值。"""
    if extract_type == "jmespath":
        meta = {
            "status_code": response.get("code"),
            "headers": response.get("headers", {}),
            "body": response.get("body"),
        }
        return jmespath.search(path, meta)
    if extract_type == "jsonpath":
        body = response.get("body")
        matches = jsonpath_parse(path).find(body)
        if not matches:
            raise ValueError(f"jsonpath '{path}' 未匹配到数据")
        return matches[0].value
    if extract_type == "header":
        return response.get("headers", {}).get(path)
    raise ValueError(f"不支持的提取类型: {extract_type}")


# ---------------------------------------------------------------------------
# StepResult — 统一结果数据结构
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    name: str
    step_type: str
    success: bool = True
    skipped: bool = False
    duration: float = 0.0
    request: Dict = field(default_factory=dict)
    response: Dict = field(default_factory=dict)
    extracts: List = field(default_factory=list)
    validators: List = field(default_factory=list)
    error: str = ""
    children: List["StepResult"] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "step_type": self.step_type,
            "success": self.success,
            "skipped": self.skipped,
            "duration": round(self.duration, 3),
            "request": self.request,
            "response": self.response,
            "extracts": self.extracts,
            "validators": self.validators,
            "error": self.error,
            "children": [c.to_dict() for c in self.children],
            "logs": self.logs,
        }


# ---------------------------------------------------------------------------
# NtestContext — 脚本步骤的执行上下文对象
# ---------------------------------------------------------------------------

class NtestContext:
    """注入到 script 步骤的 `ntest` 对象，提供变量读写接口。"""

    def __init__(self, var_ctx: VariableContext):
        self._var_ctx = var_ctx
        self.exported_vars: Dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        """读取变量（优先 session_vars，其次 env_vars）。"""
        return self._var_ctx.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """写入变量到 exported_vars，执行后同步回 session_vars。"""
        self.exported_vars[key] = value

    def env(self, key: str, default: Any = None) -> Any:
        """读取环境变量（只读）。"""
        return self._var_ctx.env_vars.get(key, default)


# ---------------------------------------------------------------------------
# StepExecutor — 主执行器，根据 step_type 分发
# ---------------------------------------------------------------------------

class StepExecutor:
    def __init__(
        self,
        db: AsyncSession,
        env_id: int,
        user_id: int,
        result_id: str,
        ctx: VariableContext,
        log_fn: Callable,          # async (msg: str) -> None
        cancel_fn: Callable,       # () -> bool
        step_rely: bool = True,    # True=步骤间共享变量，False=每步骤独立
    ):
        self.db = db
        self.env_id = env_id
        self.user_id = user_id
        self.result_id = result_id
        self.ctx = ctx
        self._log = log_fn
        self._is_cancelled = cancel_fn
        self.step_rely = step_rely

    async def execute_steps(self, steps: List[Dict]) -> List[StepResult]:
        """顺序执行步骤列表，遇到取消信号立即停止。"""
        results: List[StepResult] = []
        for step in steps:
            if self._is_cancelled():
                break
            if not step.get("enable", True):
                r = StepResult(
                    name=step.get("name", ""),
                    step_type=step.get("step_type", "api"),
                    skipped=True,
                )
                results.append(r)
                continue

            # step_rely=False 时，为每个步骤创建独立的变量上下文（不共享提取结果）
            if not self.step_rely:
                isolated_ctx = VariableContext(self.ctx.env_vars.copy())
                original_ctx = self.ctx
                self.ctx = isolated_ctx
                r = await self.execute(step)
                self.ctx = original_ctx
            else:
                r = await self.execute(step)

            results.append(r)
        return results

    async def execute(self, step: Dict) -> StepResult:
        """根据 step_type 分发到对应处理器。"""
        step_type = (step.get("step_type") or "api").lower()
        # 向后兼容：旧格式步骤直接有 api_id 字段
        if step_type == "api" or ("api_id" in step and step_type not in
                                   ("sql", "script", "if", "loop", "wait")):
            step_type = "api"

        t0 = time.time()
        try:
            if step_type == "api":
                result = await self._exec_api(step)
            elif step_type == "sql":
                result = await self._exec_sql(step)
            elif step_type == "script":
                result = await self._exec_script(step)
            elif step_type == "if":
                result = await self._exec_if(step)
            elif step_type == "loop":
                result = await self._exec_loop(step)
            elif step_type == "wait":
                result = await self._exec_wait(step)
            else:
                result = StepResult(
                    name=step.get("name", ""),
                    step_type=step_type,
                    success=False,
                    error=f"不支持的步骤类型: {step_type}",
                )
        except Exception as e:
            result = StepResult(
                name=step.get("name", ""),
                step_type=step_type,
                success=False,
                error=str(e)[:500],
            )
            result.logs.append(f"步骤执行异常: {traceback.format_exc()[:300]}")

        result.duration = time.time() - t0
        return result


    # -----------------------------------------------------------------------
    # _exec_api — HTTP 请求步骤（复用 service.py 的发送逻辑）
    # -----------------------------------------------------------------------

    async def _exec_api(self, step: Dict) -> StepResult:
        from .service import ApiAutomationService

        result = StepResult(name=step.get("name", ""), step_type="api")
        # 兼容旧格式：api_id 在顶层或在 request 子对象中
        req_cfg_raw = step.get("request") or {}
        api_id = step.get("api_id") or req_cfg_raw.get("api_id")

        if not api_id:
            result.success = False
            result.error = "api 步骤缺少 api_id"
            return result

        api_row = (
            await self.db.execute(
                select(ApiModel).where(ApiModel.id == int(api_id), ApiModel.enabled_flag == 1)
            )
        ).scalar_one_or_none()
        if not api_row:
            result.success = False
            result.error = f"接口 id={api_id} 不存在"
            return result

        api_cfg = api_row.req or {}

        # 变量替换：先用步骤上下文（${var}/{{var}}），再走环境/全局变量 handle_var
        url = await ApiAutomationService.handle_var(
            self.db, self.env_id, self.ctx.resolve(api_row.url or "")
        )
        url = await ApiAutomationService._resolve_base_url(self.db, self.env_id, str(url or ""))
        headers = await ApiAutomationService.handle_var(
            self.db, self.env_id, self.ctx.resolve(ApiAutomationService.params_header(api_cfg.get("header")))
        )
        params = await ApiAutomationService.handle_var(
            self.db, self.env_id, self.ctx.resolve(ApiAutomationService.params_header(api_cfg.get("params")))
        )
        body = await ApiAutomationService.handle_var(
            self.db, self.env_id, self.ctx.resolve(api_cfg.get("body") or {})
        )
        form_data = await ApiAutomationService.handle_var(
            self.db, self.env_id, self.ctx.resolve(ApiAutomationService.params_header(api_cfg.get("form_data")))
        )
        form_urlencoded = await ApiAutomationService.handle_var(
            self.db, self.env_id, self.ctx.resolve(ApiAutomationService.params_header(api_cfg.get("form_urlencoded")))
        )
        file_paths = api_cfg.get("file_path") or []
        config = api_cfg.get("config") or {"retry": 0, "req_timeout": 5, "res_timeout": 5}

        if isinstance(url, str) and "{{" in url and "}}" in url:
            result.success = False
            result.error = f"URL 环境变量未替换：{url}（请确认已选择环境，且配置项名与占位符一致）"
            result.request = {"method": api_cfg.get("method"), "url": url}
            result.response = {"code": 500, "body": {"msg": "接口请求失败", "exception": result.error}}
            result.logs.append(f"响应: {result.response['body']}")
            return result
        if isinstance(url, str) and url.strip() and not re.match(r"^https?://", url.strip(), re.I):
            result.success = False
            result.error = f"URL 缺少协议（http/https）：{url}"
            result.request = {"method": api_cfg.get("method"), "url": url}
            result.response = {"code": 500, "body": {"msg": "接口请求失败", "exception": result.error}}
            result.logs.append(f"响应: {result.response['body']}")
            return result

        # 前置操作
        before_ops = api_cfg.get("before") or []
        before_list: List[Dict] = []
        if before_ops:
            before_list = await ApiAutomationService._pre_request(
                db=self.db, ops=before_ops, env_id=self.env_id, user_id=self.user_id
            )
        for item in before_list:
            if item.get("message"):
                result.logs.append(str(item["message"]))

        # 发送请求
        res = await ApiAutomationService._send_request(
            method=int(api_cfg.get("method") or 2),
            url=str(url),
            headers=headers,
            params=params,
            body_type=int(api_cfg.get("body_type") or 2),
            body=body,
            form_data=form_data,
            form_urlencoded=form_urlencoded,
            file_paths=file_paths,
            config=config,
        )
        result.logs.append(f"响应: {str(res.get('body', ''))[:200]}")

        # 后置操作
        after_ops = api_cfg.get("after") or []
        after_list: List[Dict] = []
        if after_ops:
            after_list = await ApiAutomationService._after_request(
                db=self.db, ops=after_ops, res=res,
                header=headers, body=body,
                env_id=self.env_id, user_id=self.user_id,
            )
        for item in after_list:
            if item.get("message"):
                result.logs.append(str(item["message"]))

        # 提取变量
        extracts = step.get("extracts") or []
        result.extracts = self.ctx.apply_extracts(extracts, res)

        # 断言
        validators = step.get("validators") or api_cfg.get("assert") or []
        result.validators = _run_validators(validators, res, self.ctx)
        assert_ok = all(v.get("result") == "pass" for v in result.validators)

        result.success = (
            int(res.get("code") or 0) < 400
            and assert_ok
            and all(int(i.get("status") or 0) == 1 for i in before_list)
            and all(int(i.get("status") or 0) == 1 for i in after_list)
        )
        result.request = {
            "method": api_cfg.get("method"),
            "url": url,
            "headers": headers,
            "params": params,
            "body": body,
        }
        result.response = res
        return result


    # -----------------------------------------------------------------------
    # _exec_sql — SQL 查询步骤
    # -----------------------------------------------------------------------

    async def _exec_sql(self, step: Dict) -> StepResult:
        result = StepResult(name=step.get("name", ""), step_type="sql")
        req = step.get("request") or {}
        db_id = req.get("db_id")
        sql = self.ctx.resolve(req.get("sql") or "")
        variable_name = req.get("variable_name") or ""

        if not db_id:
            result.success = False
            result.error = "sql 步骤缺少 db_id"
            return result
        if not sql.strip():
            result.success = False
            result.error = "sql 步骤缺少 sql 语句"
            return result

        db_row = (
            await self.db.execute(
                select(ApiDatabaseModel).where(
                    ApiDatabaseModel.id == int(db_id),
                    ApiDatabaseModel.enabled_flag == 1,
                )
            )
        ).scalar_one_or_none()
        if not db_row:
            result.success = False
            result.error = f"数据库配置 id={db_id} 不存在"
            return result

        cfg = db_row.config or {}
        host = cfg.get("host") or db_row.host
        port = int(cfg.get("port") or db_row.port or 3306)
        user = cfg.get("user") or cfg.get("username") or db_row.username
        password = cfg.get("password") or db_row.password
        database = cfg.get("database") or db_row.database_name or ""

        result.request = {
            "db_id": db_id,
            "host": host,
            "port": port,
            "user": user,
            "database": database,
            "sql": sql,
        }

        conn = None
        try:
            conn = pymysql.connect(
                host=host, port=port, user=user,
                password=password, database=database,
                charset="utf8mb4", connect_timeout=10,
                cursorclass=pymysql.cursors.DictCursor,
            )
            with conn.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
            rows = [dict(r) for r in rows]

            result.response = {"body": rows, "code": 200}
            result.logs.append(f"SQL 执行成功，返回 {len(rows)} 行")

            # 提取变量
            if variable_name and rows:
                self.ctx.set(variable_name, rows[0] if len(rows) == 1 else rows)
                result.logs.append(f"变量 {variable_name} 已赋值")

            # 通用提取规则
            extracts = step.get("extracts") or []
            result.extracts = self.ctx.apply_extracts(extracts, result.response)

            # 断言
            validators = step.get("validators") or []
            result.validators = _run_validators(validators, result.response, self.ctx)
            result.success = all(v.get("result") == "pass" for v in result.validators)

        except Exception as e:
            result.success = False
            result.error = str(e)[:500]
            result.logs.append(f"SQL 执行失败: {e}")
        finally:
            if conn:
                conn.close()

        return result


    # -----------------------------------------------------------------------
    # _exec_script — 沙盒（默认）或原生宿主进程
    # -----------------------------------------------------------------------

    async def _exec_script(self, step: Dict) -> StepResult:
        result = StepResult(name=step.get("name", ""), step_type="script")
        req = step.get("request") or {}
        code = req.get("script_content") or ""
        script_id = req.get("script_id")
        exec_mode = resolve_exec_mode(req.get("exec_mode") or req.get("script_exec_mode"))
        language = normalize_language(req.get("language") or req.get("script_lang") or "python")

        # Load public script code if script_id is provided
        public_code = ""
        if script_id:
            try:
                from .model import NtestScriptModel
                from sqlalchemy import select as _select
                row = (await self.db.execute(
                    _select(NtestScriptModel).where(
                        NtestScriptModel.id == int(script_id),
                        NtestScriptModel.enabled_flag == 1,
                    )
                )).scalars().first()
                if row and row.code:
                    public_code = row.code
                    # 公共脚本自带语言时优先采用
                    script_lang = getattr(row, "language", None)
                    if script_lang:
                        language = normalize_language(script_lang)
                else:
                    result.logs.append(f"警告：未找到 script_id={script_id} 对应的公共脚本，跳过")
            except Exception as e:
                result.logs.append(f"警告：加载公共脚本失败: {e}")

        if not code.strip() and not public_code.strip():
            result.success = False
            result.error = "script 步骤缺少 script_content"
            return result

        parts = [p for p in [public_code, code] if p and p.strip()]
        full_code = "\n\n".join(parts)

        # JS 只能走原生
        if language == "javascript":
            exec_mode = "native"

        ntest = NtestContext(self.ctx)
        try:
            if exec_mode == "native":
                run_res = await asyncio.to_thread(
                    run_native,
                    full_code,
                    language=language,
                    session_vars=dict(self.ctx.session_vars),
                    env_vars=dict(self.ctx.env_vars),
                )
            else:
                run_res = await asyncio.to_thread(run_sandbox, full_code, ntest=ntest)

            result.logs.extend(run_res.logs or [])
            if run_res.success:
                for k, v in (run_res.vars or {}).items():
                    self.ctx.set(k, v)
                    ntest.exported_vars[k] = v
                result.response = {
                    "body": {
                        "output": run_res.output or "",
                        "vars": run_res.vars or {},
                        "exec_mode": run_res.mode,
                        "language": language,
                    },
                    "code": 200,
                }
                result.success = True
            else:
                result.success = False
                result.error = run_res.error or "脚本执行失败"
                result.response = {
                    "body": {
                        "output": run_res.output or "",
                        "vars": run_res.vars or {},
                        "exception": result.error,
                        "exec_mode": run_res.mode,
                        "language": language,
                    },
                    "code": 500,
                }
        except Exception as e:
            result.success = False
            result.error = str(e)[:500]
            result.logs.append(f"脚本执行失败: {traceback.format_exc()[:300]}")

        result.request = {
            "script_content": code,
            "script_id": script_id,
            "exec_mode": exec_mode,
            "language": language,
        }
        return result

    # -----------------------------------------------------------------------
    # _exec_if — 条件控制器
    # -----------------------------------------------------------------------

    async def _exec_if(self, step: Dict) -> StepResult:
        result = StepResult(name=step.get("name", "条件控制器"), step_type="if")
        req = step.get("request") or {}
        check = self.ctx.resolve(req.get("check") or "")
        expect = self.ctx.resolve(req.get("expect") or "")
        comparator = req.get("comparator") or "eq"

        matched = _compare(check, comparator, expect)
        result.request = {"check": check, "comparator": comparator, "expect": expect}
        result.logs.append(f"条件判断: {check!r} {comparator} {expect!r} → {'满足' if matched else '不满足'}")

        if matched:
            children = step.get("children_steps") or []
            child_results = await self.execute_steps(children)
            result.children = child_results
            result.success = all(r.success or r.skipped for r in child_results)
        else:
            result.success = True  # 条件不满足，跳过子步骤，父步骤仍成功

        result.response = {"body": {"matched": matched}, "code": 200}
        return result

    # -----------------------------------------------------------------------
    # _exec_loop — 循环控制器（count / for / while）
    # -----------------------------------------------------------------------

    async def _exec_loop(self, step: Dict) -> StepResult:
        result = StepResult(name=step.get("name", "循环控制器"), step_type="loop")
        req = step.get("request") or {}
        loop_type = (req.get("loop_type") or "count").lower()
        children = step.get("children_steps") or []

        result.request = req
        all_children: List[StepResult] = []

        try:
            if loop_type == "count":
                count = min(int(req.get("count_number") or 1), 100)
                sleep_time = float(req.get("count_sleep_time") or 0)
                result.logs.append(f"次数循环: {count} 次")
                for i in range(count):
                    if self._is_cancelled():
                        break
                    child_results = await self.execute_steps(children)
                    all_children.extend(child_results)
                    result.logs.append(f"第 {i+1} 次完成")
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)

            elif loop_type == "for":
                var_name = req.get("for_variable_name") or "_item"
                iterable_raw = self.ctx.resolve(req.get("for_variable") or "[]")
                sleep_time = float(req.get("for_sleep_time") or 0)
                try:
                    iterable = iterable_raw if isinstance(iterable_raw, (list, tuple)) else \
                               __import__("json").loads(iterable_raw)
                except Exception:
                    iterable = []
                result.logs.append(f"for 循环: 遍历 {len(iterable)} 项")
                for item in iterable:
                    if self._is_cancelled():
                        break
                    self.ctx.set(var_name, item)
                    child_results = await self.execute_steps(children)
                    all_children.extend(child_results)
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)

            elif loop_type == "while":
                while_var = req.get("while_variable") or ""
                while_val = req.get("while_value") or ""
                comparator = req.get("while_comparator") or "eq"
                timeout = float(req.get("while_timeout") or 60)
                sleep_time = float(req.get("while_sleep_time") or 1)
                deadline = time.time() + timeout
                result.logs.append(f"while 循环: 超时 {timeout}s")
                while True:
                    if self._is_cancelled() or time.time() > deadline:
                        result.logs.append("while 循环超时或被取消")
                        break
                    check_val = self.ctx.resolve(while_var)
                    exp_val = self.ctx.resolve(while_val)
                    if _compare(check_val, comparator, exp_val):
                        result.logs.append("while 条件满足，退出循环")
                        break
                    child_results = await self.execute_steps(children)
                    all_children.extend(child_results)
                    await asyncio.sleep(sleep_time)

            result.children = all_children
            result.success = all(r.success or r.skipped for r in all_children)
            result.response = {"body": {"iterations": len(all_children)}, "code": 200}

        except Exception as e:
            result.success = False
            result.error = str(e)[:500]

        return result

    # -----------------------------------------------------------------------
    # _exec_wait — 等待控制器
    # -----------------------------------------------------------------------

    async def _exec_wait(self, step: Dict) -> StepResult:
        result = StepResult(name=step.get("name", "等待控制器"), step_type="wait")
        req = step.get("request") or {}
        wait_time = float(req.get("wait_time") or 1)
        result.request = {"wait_time": wait_time}
        result.logs.append(f"等待 {wait_time} 秒")
        await asyncio.sleep(wait_time)
        result.response = {"body": {"waited": wait_time}, "code": 200}
        result.success = True
        return result


# ---------------------------------------------------------------------------
# 模块级工具函数
# ---------------------------------------------------------------------------

def _compare(actual: Any, comparator: str, expected: Any) -> bool:
    """13 种比较器。"""
    import re as _re
    c = comparator.lower().replace("-", "_")
    try:
        if c in ("eq", "equals", "equal"):
            return str(actual) == str(expected)
        if c in ("ne", "not_equal", "neq"):
            return str(actual) != str(expected)
        if c in ("gt", "greater_than"):
            return float(actual) > float(expected)
        if c in ("gte", "greater_or_equals", "ge"):
            return float(actual) >= float(expected)
        if c in ("lt", "less_than"):
            return float(actual) < float(expected)
        if c in ("lte", "less_or_equals", "le"):
            return float(actual) <= float(expected)
        if c == "contains":
            return str(expected) in str(actual)
        if c == "not_contains":
            return str(expected) not in str(actual)
        if c == "startswith":
            return str(actual).startswith(str(expected))
        if c == "endswith":
            return str(actual).endswith(str(expected))
        if c in ("regex", "regex_match"):
            return bool(_re.search(str(expected), str(actual)))
        if c in ("is_null", "is_none"):
            return actual is None or actual == "" or actual == "null"
        if c in ("not_null", "not_none"):
            return actual is not None and actual != "" and actual != "null"
    except (ValueError, TypeError):
        pass
    return False


def _run_validators(validators: List[Dict], response: Dict, ctx: VariableContext) -> List[Dict]:
    """执行断言列表，返回带结果的列表。"""
    results = []
    for v in validators:
        check_expr = v.get("check") or ""
        comparator = v.get("comparator") or "eq"
        expect = ctx.resolve(v.get("expect"))
        mode = (v.get("mode") or "jmespath").lower()

        result = dict(v)
        try:
            # 从响应中取值
            if mode == "jmespath":
                meta = {
                    "status_code": response.get("code"),
                    "headers": response.get("headers", {}),
                    "body": response.get("body"),
                }
                actual = jmespath.search(check_expr, meta)
            elif mode == "jsonpath":
                matches = jsonpath_parse(check_expr).find(response.get("body"))
                actual = matches[0].value if matches else None
            else:
                actual = ctx.resolve(check_expr)

            passed = _compare(actual, comparator, expect)
            result["actual"] = actual
            result["result"] = "pass" if passed else "fail"
            if not passed:
                result["message"] = f"断言失败: {actual!r} {comparator} {expect!r}"
        except Exception as e:
            result["result"] = "fail"
            result["message"] = str(e)
        results.append(result)
    return results
