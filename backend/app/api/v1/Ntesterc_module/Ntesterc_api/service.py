#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: Rebort

from __future__ import annotations

import asyncio
import json
import re
import threading
import shutil
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from math import ceil
import pymysql
import requests
import uuid
from datetime import timedelta
from jsonpath_ng import parse as jsonpath_parse
import yaml
from sqlalchemy import select, update, delete, text, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from .model import (
    ApiModel,
    ApiDataModel,
    ApiProjectModel,
    ApiServiceModel,
    ApiMenuModel,
    ApiEnvironmentModel,
    ApiVariableModel,
    ApiDatabaseModel,
    ApiResultModel,
    ApiEditModel,
    ApiScriptModel,
    ApiScriptResultListModel,
    ApiScriptResultModel,
    ApiUpdateModel,
    ApiDataSourceHistoryModel,
    ApiDocHistoryModel,
)

from config import config as app_config

from pathlib import Path
import os
from app.api.v1.system.user.crud import UserCRUD
from app.api.v1.Ntesterc_module.Ntesterc_task_scheduler.service import TaskSchedulerService
from app.api.v1.Ntesterc_module.Ntesterc_task_scheduler.model import MsgNoticeModel


async def _get_username_map(db: AsyncSession, user_ids: List[int]) -> Dict[int, str]:
    if not user_ids:
        return {}
    try:
        res = await db.execute(
            text("SELECT id, COALESCE(username, '') AS name FROM sys_user WHERE id IN :ids"),
            {"ids": tuple(set(user_ids))},
        )
        rows = res.fetchall()
        return {r.id: (r.name or "") for r in rows}
    except Exception:
        return {}


def _build_tree(items: List[Dict[str, Any]], pid_key: str = "pid", id_key: str = "id") -> List[Dict[str, Any]]:
    by_id: Dict[Any, Dict[str, Any]] = {}
    roots: List[Dict[str, Any]] = []
    for it in items:
        node = dict(it)
        node.setdefault("children", [])
        by_id[node.get(id_key)] = node
    for node in by_id.values():
        pid = node.get(pid_key)
        if pid in (None, 0, "0"):
            roots.append(node)
        else:
            parent = by_id.get(pid)
            if parent:
                parent.setdefault("children", []).append(node)
            else:
                roots.append(node)
    return roots


class ApiAutomationService:
    """接口自动化服务"""

    
    @staticmethod
    def _normalize_var_name(name: Any) -> str:
        """统一变量名"""
        n = str(name or "").strip()
        if n.startswith("{{") and n.endswith("}}"):
            n = n[2:-2].strip()
        return n

    @staticmethod
    async def _complete_var(db: AsyncSession, env_id: int, key: str,
                            api_service_id: Optional[int] = None,
                            temp_vars: Optional[Dict[str, Any]] = None) -> Any:
        lookup = ApiAutomationService._normalize_var_name(key)
        if not lookup:
            return ""
        # 临时变量（单次请求内有效）优先级最高
        if isinstance(temp_vars, dict):
            for tk, tv in temp_vars.items():
                if ApiAutomationService._normalize_var_name(str(tk)) == lookup:
                    return tv

        if env_id:
            env = await db.execute(
                select(ApiEnvironmentModel).where(ApiEnvironmentModel.id == env_id, ApiEnvironmentModel.enabled_flag == 1)
            )
            env_row = env.scalar_one_or_none()
            if env_row:
                for j in (env_row.variable or []):
                    if isinstance(j, dict) and ApiAutomationService._normalize_var_name(j.get("name")) == lookup:
                        return j.get("value")


        g = await db.execute(select(ApiVariableModel).where(ApiVariableModel.enabled_flag == 1))
        svc_project_id: Optional[int] = None
        svc_dept_id: Optional[int] = None
        for row in g.scalars().all():
            scope = str(getattr(row, "scope", None) or "user")
            if scope == "project":
                if svc_project_id is None and api_service_id:
                    svc = (await db.execute(select(ApiServiceModel).where(ApiServiceModel.id == int(api_service_id)))).scalar_one_or_none()
                    svc_project_id = int(svc.api_project_id) if svc else None
                if row.api_project_id and svc_project_id and int(row.api_project_id) == svc_project_id \
                        and ApiAutomationService._normalize_var_name(row.name) == lookup:
                    return row.value
            elif scope == "team":
                if svc_dept_id is None and api_service_id:
                    svc = (await db.execute(select(ApiServiceModel).where(ApiServiceModel.id == int(api_service_id)))).scalar_one_or_none()
                    svc_dept_id = getattr(svc, "department_id", None)
                if row.department_id and svc_dept_id and int(row.department_id) == int(svc_dept_id) \
                        and ApiAutomationService._normalize_var_name(row.name) == lookup:
                    return row.value
            elif ApiAutomationService._normalize_var_name(row.name) == lookup:
                return row.value
        # 动态值兜底：{{$timestamp}} / {{$randomInt}} / {{$uuid}} / {{$guid}} 等
        dyn = ApiAutomationService._dynamic_value(key)
        if dyn is not None:
            return dyn
        return ""

    @staticmethod
    def _dynamic_value(key: str) -> Any:
        """Apifox 风格动态值（最小集）：$timestamp / $timestamp_ms / $randomInt / $uuid / $guid。"""
        import random as _random
        import time as _time
        import uuid as _uuid
        k = (key or "").strip()
        if not k.startswith("$"):
            return None
        m = re.match(r"^\$timestamp(?:\[(\d+)\])?$", k)
        if m:
            return int(_time.time() * (1000 if m.group(1) == "3" else 1)) if m.group(1) else int(_time.time())
        if k == "$timestamp_ms":
            return int(_time.time() * 1000)
        m2 = re.match(r"^\$randomInt(?:\[\s*(\d+)\s*,\s*(\d+)\s*\])?$", k)
        if m2:
            if m2.group(1) and m2.group(2):
                lo, hi = int(m2.group(1)), int(m2.group(2))
                if hi < lo:
                    lo, hi = hi, lo
                return _random.randint(lo, hi)
            return _random.randint(0, 1000)
        if k == "$uuid":
            return _uuid.uuid4().hex
        if k == "$guid":
            return str(_uuid.uuid4())
        return None

    @staticmethod
    async def _find_var(db: AsyncSession, env_id: int, s: str, api_service_id: Optional[int] = None, temp_vars: Optional[Dict[str, Any]] = None) -> str:
        keys = re.findall(r"\{\{(.+?)\}\}", s) if ("{{" in s and "}}" in s) else []
        for k in keys:
            var = "{{" + k + "}}"
            val = await ApiAutomationService._complete_var(db, env_id, k, api_service_id=api_service_id, temp_vars=temp_vars)
            
            if val is None or val == "":
                continue
            s = s.replace(var, str(val))
        return s

    @staticmethod
    async def _resolve_base_url(db: AsyncSession, env_id: int, url: str,
                                 api_id: Optional[int] = None,
                                 return_base: bool = False) -> Any:
        """Apifox 前置 URL 逻辑：相对路径（/ 开头）按接口所属菜单链匹配环境配置的模块级前置 URL。
        未匹配（未配置或接口无模块归属）则返回原样，不拼接任何默认值。
        return_base=True 时返回 (完整URL, 前置URL)，供 BASE_URL 内置变量/脚本取用。"""
        u = str(url or "").strip()
        if not u or u.startswith(("http://", "https://", "ws://", "wss://", "{{")):
            return (u, "") if return_base else u
        if not u.startswith("/") or not env_id or not api_id:
            return (u, "") if return_base else u
        env_row = (
            await db.execute(
                select(ApiEnvironmentModel).where(
                    ApiEnvironmentModel.id == int(env_id),
                    ApiEnvironmentModel.enabled_flag == 1,
                )
            )
        ).scalar_one_or_none()
        if not env_row:
            return (u, "") if return_base else u
        base = await ApiAutomationService._match_front_url_by_menu(db, env_row, api_id)
        if base:
            full = base.rstrip("/") + "/" + u.lstrip("/")
            return (full, base) if return_base else full
        return (u, "") if return_base else u

    @staticmethod
    async def _match_front_url_by_menu(db: AsyncSession, env_row, api_id: int) -> str:
        """按接口所属菜单链匹配环境 __front_urls__ 中配置的模块级前置 URL。"""
        import json as _json
        front_urls: list = []
        for i in (env_row.config or []):
            if isinstance(i, dict) and str(i.get("name") or "").strip() == "__front_urls__":
                try:
                    arr = _json.loads(i.get("value") or "[]")
                    if isinstance(arr, list):
                        front_urls.extend(arr)
                except Exception:
                    continue
        if not front_urls:
            return ""
        # 接口协议：websocket -> websocket 行；http/webhook -> http 行；socketio -> socketio 行
        _proto = "http"
        try:
            _api_row = (
                await db.execute(
                    select(ApiModel).where(ApiModel.id == int(api_id), ApiModel.enabled_flag == 1)
                )
            ).scalar_one_or_none()
            if _api_row and isinstance(_api_row.req, dict):
                _p = str(_api_row.req.get("protocol") or "http").lower()
                _proto = _p if _p in ("websocket", "socketio") else "http"
        except Exception:
            pass

        def _proto_ok(f: Dict[str, Any]) -> bool:
            fp = str(f.get("protocol") or "http").lower()
            return fp == _proto

        def _url_ok(f: Dict[str, Any]) -> bool:
            val = str(f.get("url") or "").strip()
            if not val:
                return False
            fp = str(f.get("protocol") or "http").lower()
            if fp in ("websocket", "socketio"):
                return val.startswith(("ws://", "wss://", "http://", "https://"))
            return val.startswith(("http://", "https://"))

        # 服务级匹配：front_urls 中 menu_id 为 svc_{id}（模块=服务），接口所属服务一致即命中
        _m0 = (
            await db.execute(
                select(ApiMenuModel).where(
                    ApiMenuModel.api_id == int(api_id),
                    ApiMenuModel.enabled_flag == 1,
                )
            )
        ).scalars().first()
        if _m0 is not None:
            _svc_id = int(_m0.api_service_id or 0)
            for f in front_urls or []:
                try:
                    _mid = f.get("menu_id")
                    if isinstance(_mid, str) and _mid.startswith("svc_"):
                        if int(_mid[4:]) == _svc_id and _proto_ok(f):
                            
                            if _url_ok(f):
                                return str(f.get("url") or "").strip()
                except Exception:
                    continue
        chain_ids: list = []
        cur = (
            await db.execute(
                select(ApiMenuModel).where(
                    ApiMenuModel.api_id == int(api_id),
                    ApiMenuModel.status == 1,
                )
            )
        ).scalars().first()
        seen: set = set()
        while cur and cur.id not in seen:
            seen.add(cur.id)
            chain_ids.append(cur.id)
            pid = int(cur.pid or 0)
            if not pid:
                break
            cur = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.id == pid,
                        ApiMenuModel.status == 1,
                    )
                )
            ).scalars().first()
        for mid in chain_ids:
            for f in front_urls or []:
                try:
                    if int(f.get("menu_id") or 0) == mid and _proto_ok(f):
                        
                        if _url_ok(f):
                            return str(f.get("url") or "").strip()
                except Exception:
                    continue
        return ""

    @staticmethod
    async def handle_var(db: AsyncSession, env_id: int, data: Any,
                         api_service_id: Optional[int] = None,
                         temp_vars: Optional[Dict[str, Any]] = None) -> Any:
        if isinstance(data, str):
            if "{{" in data and "}}" in data:
                return await ApiAutomationService._find_var(db, env_id, data, api_service_id=api_service_id, temp_vars=temp_vars)
            return data
        if isinstance(data, dict):
            out = {}
            for k, v in data.items():
                out[k] = await ApiAutomationService.handle_var(
                    db, env_id, v, api_service_id=api_service_id, temp_vars=temp_vars)
            return out
        if isinstance(data, list):
            return [
                await ApiAutomationService.handle_var(
                    db, env_id, x, api_service_id=api_service_id, temp_vars=temp_vars)
                for x in data
            ]
        return data

    @staticmethod
    def params_header(params: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        if not params:
            return {}
        res: Dict[str, Any] = {}
        for i in params:
            if not isinstance(i, dict):
                continue
            if i.get("status") is False:
                continue
            key = i.get("name") or i.get("key")
            if key:
                res[key] = i.get("value")
        return res

    @staticmethod
    def _set_header_ci(headers: Dict[str, Any], name: str, value: str) -> None:
        """按大小写不敏感方式设置 Header，避免重复键。"""
        target = None
        for k in list(headers.keys()):
            if str(k).lower() == name.lower():
                target = k
                break
        if target is not None and target != name:
            headers.pop(target, None)
        headers[name] = value

    @staticmethod
    async def _resolve_oauth2_token(db: AsyncSession, env_id: int, req: Dict[str, Any]) -> str:
        """OAuth 2.0：支持直接填 Access Token，或 Client Credentials / Password 换取。"""
        grant = str(req.get("auth_oauth_grant") or "access_token").strip().lower()
        prefix_ready = str(req.get("auth_oauth_access_token") or req.get("auth_token") or "").strip()
        if grant in ("access_token", "token", ""):
            token = await ApiAutomationService.handle_var(db, env_id, prefix_ready)
            return str(token or "").strip()

        token_url = str(
            await ApiAutomationService.handle_var(db, env_id, req.get("auth_oauth_token_url") or "")
        ).strip()
        client_id = str(
            await ApiAutomationService.handle_var(db, env_id, req.get("auth_oauth_client_id") or "")
        ).strip()
        client_secret = str(
            await ApiAutomationService.handle_var(db, env_id, req.get("auth_oauth_client_secret") or "")
        ).strip()
        scope = str(
            await ApiAutomationService.handle_var(db, env_id, req.get("auth_oauth_scope") or "")
        ).strip()
        if not token_url:
            raise ValueError("OAuth 2.0 缺少 Token URL")
        if not client_id:
            raise ValueError("OAuth 2.0 缺少 Client ID")

        data: Dict[str, Any] = {}
        auth = None
        client_auth = str(req.get("auth_oauth_client_auth") or "basic").strip().lower()
        if grant in ("client_credentials", "client"):
            data["grant_type"] = "client_credentials"
            if scope:
                data["scope"] = scope
        elif grant in ("password", "password_credentials"):
            data["grant_type"] = "password"
            data["username"] = str(
                await ApiAutomationService.handle_var(db, env_id, req.get("auth_username") or "", temp_vars=temp_vars)
            ).strip()
            data["password"] = str(
                await ApiAutomationService.handle_var(db, env_id, req.get("auth_password") or "", temp_vars=temp_vars)
            ).strip()
            if scope:
                data["scope"] = scope
            if not data["username"]:
                raise ValueError("OAuth 2.0 Password 模式缺少用户名")
        else:
            raise ValueError(f"不支持的 OAuth 2.0 Grant Type：{grant}")

        if client_auth == "body":
            data["client_id"] = client_id
            data["client_secret"] = client_secret
        else:
            from requests.auth import HTTPBasicAuth

            auth = HTTPBasicAuth(client_id, client_secret)

        resp = requests.post(token_url, data=data, auth=auth, timeout=30)
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        if resp.status_code >= 400:
            raise ValueError(
                f"OAuth 2.0 获取 Token 失败 HTTP {resp.status_code}: "
                f"{payload or (resp.text or '')[:300]}"
            )
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise ValueError(f"OAuth 2.0 响应中无 access_token：{payload}")
        return token

    @staticmethod
    async def _build_jwt_bearer_token(db: AsyncSession, env_id: int, req: Dict[str, Any],
                                      temp_vars: Optional[Dict[str, Any]] = None) -> str:
        """JWT Bearer：可直接填 Token，或按密钥/Payload 现场签发。"""
        mode = str(req.get("auth_jwt_mode") or "token").strip().lower()
        if mode != "generate":
            token = await ApiAutomationService.handle_var(db, env_id, req.get("auth_token") or "", temp_vars=temp_vars)
            return str(token or "").strip()

        import jwt as pyjwt

        alg = str(req.get("auth_jwt_alg") or "HS256").strip() or "HS256"
        secret = str(
            await ApiAutomationService.handle_var(db, env_id, req.get("auth_jwt_secret") or "", temp_vars=temp_vars)
        )
        if not secret:
            raise ValueError("JWT Bearer 生成模式缺少 Secret / Private Key")

        raw_payload = req.get("auth_jwt_payload") or "{}"
        raw_headers = req.get("auth_jwt_headers") or "{}"
        raw_payload = await ApiAutomationService.handle_var(db, env_id, raw_payload, temp_vars=temp_vars)
        raw_headers = await ApiAutomationService.handle_var(db, env_id, raw_headers, temp_vars=temp_vars)

        def _as_dict(v: Any, label: str) -> Dict[str, Any]:
            if isinstance(v, dict):
                return v
            text = str(v or "").strip() or "{}"
            try:
                obj = json.loads(text)
            except Exception as e:
                raise ValueError(f"JWT Bearer {label} 不是合法 JSON：{e}") from e
            if not isinstance(obj, dict):
                raise ValueError(f"JWT Bearer {label} 必须是 JSON 对象")
            return obj

        payload = _as_dict(raw_payload, "Payload")
        headers = _as_dict(raw_headers, "Header")
        token = pyjwt.encode(payload, secret, algorithm=alg, headers=headers or None)
        return token if isinstance(token, str) else token.decode("utf-8")

    @staticmethod
    async def apply_request_auth(
        db: AsyncSession,
        env_id: int,
        req: Dict[str, Any],
        headers: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        temp_vars: Optional[Dict[str, Any]] = None,
        common_auth: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Any]:
        """
        将 Auth / Cookies 应用到请求。
        返回 (headers, params, requests_auth)；requests_auth 仅 Digest 时非空。
        """
        headers = dict(headers or {})
        params = dict(params or {})
        requests_auth = None

        # Cookies
        cookie_parts: List[str] = []
        for c in (req.get("cookies") or []):
            if not isinstance(c, dict) or c.get("status") is False:
                continue
            name = str(c.get("name") or c.get("key") or "").strip()
            if not name:
                continue
            val = await ApiAutomationService.handle_var(db, env_id, c.get("value") or "", temp_vars=temp_vars)
            cookie_parts.append(f"{name}={val}")
        if cookie_parts:
            existing = ""
            for k, v in list(headers.items()):
                if str(k).lower() == "cookie":
                    existing = str(v or "")
                    break
            merged = "; ".join([p for p in [existing.strip().rstrip(";"), *cookie_parts] if p])
            ApiAutomationService._set_header_ci(headers, "Cookie", merged)

        auth_type = str(req.get("auth_type") or "none").strip().lower()
        if auth_type in ("", "none", "noauth"):
            # 目录级 Auth 继承：接口未配置认证时使用目录 Auth（对齐「复用所属子接口」）
            if common_auth and isinstance(common_auth, dict) and common_auth.get("auth_type"):
                for _k, _v in common_auth.items():
                    req[_k] = _v
                auth_type = str(common_auth.get("auth_type") or "none").strip().lower()
            else:
                return headers, params, None

        prefix = str(
            await ApiAutomationService.handle_var(
                db, env_id,
                req.get("auth_prefix") if req.get("auth_prefix") is not None else "Bearer",
                temp_vars=temp_vars,
            )
        ).strip()

        if auth_type in ("bearer", "bearer_token"):
            token = str(
                await ApiAutomationService.handle_var(db, env_id, req.get("auth_token") or "", temp_vars=temp_vars)
            ).strip()
            if token:
                value = f"{prefix} {token}".strip() if prefix else token
                ApiAutomationService._set_header_ci(headers, "Authorization", value)

        elif auth_type in ("jwt", "jwt_bearer"):
            token = await ApiAutomationService._build_jwt_bearer_token(db, env_id, req, temp_vars=temp_vars)
            if token:
                value = f"{prefix} {token}".strip() if prefix else token
                ApiAutomationService._set_header_ci(headers, "Authorization", value)

        elif auth_type in ("basic", "basic_auth"):
            import base64

            username = str(
                await ApiAutomationService.handle_var(db, env_id, req.get("auth_username") or "", temp_vars=temp_vars)
            )
            password = str(
                await ApiAutomationService.handle_var(db, env_id, req.get("auth_password") or "", temp_vars=temp_vars)
            )
            raw = f"{username}:{password}".encode("utf-8")
            ApiAutomationService._set_header_ci(
                headers, "Authorization", "Basic " + base64.b64encode(raw).decode("ascii")
            )

        elif auth_type in ("digest", "digest_auth"):
            from requests.auth import HTTPDigestAuth

            username = str(
                await ApiAutomationService.handle_var(db, env_id, req.get("auth_username") or "", temp_vars=temp_vars)
            )
            password = str(
                await ApiAutomationService.handle_var(db, env_id, req.get("auth_password") or "", temp_vars=temp_vars)
            )
            requests_auth = HTTPDigestAuth(username, password)

        elif auth_type in ("apikey", "api_key", "api-key"):
            key = str(
                await ApiAutomationService.handle_var(db, env_id, req.get("auth_key") or "", temp_vars=temp_vars)
            ).strip()
            value = str(
                await ApiAutomationService.handle_var(db, env_id, req.get("auth_value") or "", temp_vars=temp_vars)
            )
            if key:
                dest = str(req.get("auth_in") or "header").strip().lower()
                if dest in ("query", "params", "param"):
                    params[key] = value
                else:
                    ApiAutomationService._set_header_ci(headers, key, value)

        elif auth_type in ("oauth2", "oauth_2", "oauth 2.0"):
            token = await ApiAutomationService._resolve_oauth2_token(db, env_id, req, temp_vars=temp_vars)
            if token:
                value = f"{prefix} {token}".strip() if prefix else token
                ApiAutomationService._set_header_ci(headers, "Authorization", value)

        else:
            
            pass

        return headers, params, requests_auth

    @staticmethod
    def _jsonpath_value(
        res_type: int,
        expr: str,
        res: Dict[str, Any],
        header: Dict[str, Any],
        body: Any,
    ) -> Tuple[bool, str]:
        """
        对齐jsonpath_value：
        - res_type: 1=响应体, 2=header(请求头), 3=body(请求体), 4=res['header'](响应头)
        - expr: jsonpath 表达式
        """
        try:
            if res_type == 1:
                json_data = res.get("body") or {}
            elif res_type == 2:
                json_data = header or {}
            elif res_type == 3:
                json_data = body or {}
            elif res_type == 4:
                json_data = res.get("header") or {}
            else:
                json_data = res.get("body") or {}

            if not expr:
                return False, "jsonpath 表达式为空"
            jp = jsonpath_parse(expr)
            matches = [m.value for m in jp.find(json_data)]
            if not matches:
                return False, "获取断言目标值失败，原因：jsonpath 未匹配到结果"
            return True, str(matches[0])
        except Exception as e:
            return False, f"获取断言目标值失败，原因：{str(e)}"

    @staticmethod
    def _jsonpath_value_advanced(
        rule: Dict[str, Any],
        res: Dict[str, Any],
        header: Dict[str, Any],
        body: Any,
    ) -> Tuple[bool, str]:
        """
        兼容调用：多数规则使用 rule['name'] 作为 jsonpath 表达式。
        注意：db_assert 使用 rule['value'] 作为表达式，因此 DB 断言不要用这个方法。
        """
        res_type = int(rule.get("res_type") or 1)
        expr = str(rule.get("name") or "")
        return ApiAutomationService._jsonpath_value(res_type, expr, res, header, body)

    # -------------------- 结果日志目录 --------------------
    @staticmethod
    def _get_api_result_dir(result_id: str) -> Path:
        """
        结果文件目录:{BASEDIR}/static/api_results/{result_id}
        """
       
        backend_root = Path(__file__).resolve().parents[4]
        base = backend_root / app_config.STATIC_DIR / "api_results" / str(result_id)
        if not base.exists():
            os.makedirs(base, exist_ok=True)
        return base

    @staticmethod
    def _append_log_file(file_path: Path, text: str) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    _api_script_cancel_lock = threading.Lock()
    _api_script_cancel_ids: set[str] = set()

    @staticmethod
    def _request_cancel_api_script_result(result_id: str) -> None:
        with ApiAutomationService._api_script_cancel_lock:
            ApiAutomationService._api_script_cancel_ids.add(str(result_id))

    @staticmethod
    def _is_api_script_result_cancel_requested(result_id: str) -> bool:
        with ApiAutomationService._api_script_cancel_lock:
            return str(result_id) in ApiAutomationService._api_script_cancel_ids

    @staticmethod
    def _clear_api_script_cancel(result_id: str) -> None:
        with ApiAutomationService._api_script_cancel_lock:
            ApiAutomationService._api_script_cancel_ids.discard(str(result_id))
        
        if hasattr(ApiAutomationService, '_step_ctx_cache'):
            keys = [k for k in ApiAutomationService._step_ctx_cache if k.startswith(str(result_id))]
            for k in keys:
                del ApiAutomationService._step_ctx_cache[k]

    @staticmethod
    async def _load_env_vars(db: AsyncSession, env_id: int) -> Dict[str, Any]:
        """加载环境配置/变量为字典。
        """
        if not env_id:
            return {}
        try:
            env_row = (
                await db.execute(
                    select(ApiEnvironmentModel).where(
                        ApiEnvironmentModel.id == int(env_id),
                        ApiEnvironmentModel.enabled_flag == 1,
                    )
                )
            ).scalar_one_or_none()
            if not env_row:
                return {}
            result: Dict[str, Any] = {}

            def _put(raw_name: Any, value: Any) -> None:
                name = ApiAutomationService._normalize_var_name(raw_name)
                if name:
                    result[name] = value

            for item in (env_row.config or []):
                if isinstance(item, dict):
                    _put(item.get("name") or item.get("key"), item.get("value"))
            for item in (env_row.variable or []):
                if isinstance(item, dict):
                    _put(item.get("name") or item.get("key"), item.get("value"))
            return result
        except Exception:
            return {}

    @staticmethod
    async def _api_script_delay_seconds(result_id: str, seconds: float) -> None:
        deadline = time.monotonic() + float(seconds)
        while time.monotonic() < deadline:
            if ApiAutomationService._is_api_script_result_cancel_requested(result_id):
                return
            await asyncio.sleep(0.2)

    @staticmethod
    def _remove_api_result_files(result_id: str) -> None:
        try:
            backend_root = Path(__file__).resolve().parents[4]
            base = backend_root / app_config.STATIC_DIR / "api_results" / str(result_id)
            if base.exists():
                shutil.rmtree(base, ignore_errors=True)
        except Exception:
            pass

   
    @staticmethod
    async def get_services(db: AsyncSession, project_id: Optional[int], user_id: int) -> Dict[str, Any]:
        await ApiAutomationService._ensure_service_common_params_column(db)
        stmt = select(ApiServiceModel).where(ApiServiceModel.enabled_flag == 1, ApiServiceModel.created_by == user_id)
        if project_id:
            stmt = stmt.where(ApiServiceModel.api_project_id == int(project_id))
        stmt = stmt.order_by(ApiServiceModel.id.desc())
        rows = (await db.execute(stmt)).scalars().all()
        data = [r.__dict__ for r in rows]
        for d in data:
            d.pop("_sa_instance_state", None)
        return {"content": data, "total": len(data)}

    
    @staticmethod
    def _extract_page(body: Dict[str, Any]) -> Tuple[int, int]:
        page = int(body.get("page") or body.get("currentPage") or 1)
        page_size = int(body.get("pageSize") or body.get("page_size") or 10)
        return page, page_size

    @staticmethod
    def _extract_contains(search: Dict[str, Any], *keys: str) -> Optional[str]:
        for k in keys:
            v = search.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return None

    @staticmethod
    async def get_services_paged(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        await ApiAutomationService._ensure_service_common_params_column(db)
        page, page_size = ApiAutomationService._extract_page(body)
        search = body.get("search") or {}
       
        name_like = ApiAutomationService._extract_contains(search, "name__contains", "name__icontains", "name") \
                    or ApiAutomationService._extract_contains(body, "name")
        project_id = body.get("project_id") or body.get("api_project_id") or search.get("api_project_id")
        manager = body.get("manager") or search.get("manager")
        business_id = body.get("business_id") or search.get("business_id")
        stmt = select(ApiServiceModel).where(ApiServiceModel.enabled_flag == 1, ApiServiceModel.created_by == user_id)
        if project_id:
            stmt = stmt.where(ApiServiceModel.api_project_id == int(project_id))
        if name_like:
            stmt = stmt.where(ApiServiceModel.name.like(f"%{name_like}%"))
        if manager:
            stmt = stmt.where(ApiServiceModel.manager == int(manager))
        if business_id:
            stmt = stmt.where(ApiServiceModel.business_id == int(business_id))
        stmt = stmt.order_by(ApiServiceModel.sort.asc(), ApiServiceModel.id.desc())
        rows = (await db.execute(stmt)).scalars().all()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows[start:end]
        content = []
        for r in page_rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            content.append(d)
        return {"content": content, "total": total, "page": page, "pageSize": page_size}

    @staticmethod
    async def add_service(db: AsyncSession, body: Dict[str, Any], user_id: int) -> None:
        svc = ApiServiceModel(
            name=str(body["name"]),
            api_project_id=int(body["api_project_id"]),
            img=str(body.get("img") or ""),
            description=str(body.get("description") or ""),
            source_type=body.get("source_type"),
            source_addr=body.get("source_addr"),
            last_pull_status=0,
            manager=body.get("manager"),
            business_id=body.get("business_id"),
            sort=0,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(svc)
        await db.flush()
        # 服务 = 纯容器：不生成目录、不生成环境前置 URL 行（环境行只由模块生成）
        await db.commit()

    @staticmethod
    async def edit_service(db: AsyncSession, service_id: int, body: Dict[str, Any], user_id: int) -> None:
        values: Dict[str, Any] = {"updated_by": user_id}
        for field in ("name", "api_project_id", "img", "description", "source_type", "source_addr", "manager", "business_id"):
            if field in body and body[field] is not None:
                values[field] = body[field]
        if "common_params" in body and body["common_params"] is not None:
            await ApiAutomationService._ensure_service_common_params_column(db)
            values["common_params"] = body["common_params"]
        if "module_vars" in body and body["module_vars"] is not None:
            # 模块变量：合并写入 common_params.vars
            await ApiAutomationService._ensure_service_common_params_column(db)
            _row = (
                await db.execute(
                    select(ApiServiceModel).where(
                        ApiServiceModel.id == int(service_id),
                        ApiServiceModel.enabled_flag == 1,
                        ApiServiceModel.created_by == user_id,
                    )
                )
            ).scalar_one_or_none()
            _cp = dict(_row.common_params) if isinstance(_row.common_params, dict) else {}
            _cp["vars"] = body["module_vars"]
            values["common_params"] = _cp
        await db.execute(
            update(ApiServiceModel)
            .where(ApiServiceModel.id == int(service_id), ApiServiceModel.enabled_flag == 1, ApiServiceModel.created_by == user_id)
            .values(**values)
        )
        await db.commit()

    @staticmethod
    async def _ensure_service_common_params_column(db: AsyncSession) -> None:
        """兼容旧库"""
        try:
            await db.execute(text(
                "ALTER TABLE api_automation_services ADD COLUMN common_params JSON NULL"
            ))
            await db.commit()
        except Exception:
            await db.rollback()

    @staticmethod
    async def _ensure_data_source_config_column(db: AsyncSession) -> None:
        """兼容旧库：绑定数据源配置列"""
        try:
            await db.execute(text(
                "ALTER TABLE api_automation_services ADD COLUMN data_source_config JSON NULL"
            ))
            await db.commit()
        except Exception:
            await db.rollback()

    @staticmethod
    async def _ensure_data_source_history_table(db: AsyncSession) -> None:
        """兼容旧库：数据源导入历史记录表"""
        try:
            await db.execute(text(
                """CREATE TABLE IF NOT EXISTS api_automation_data_source_history (
                    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
                    api_service_id BIGINT NOT NULL COMMENT '服务ID',
                    module_id BIGINT NULL DEFAULT NULL COMMENT '模块ID',
                    source_type VARCHAR(50) NULL DEFAULT NULL COMMENT '数据源类型：swagger/apifox',
                    source_url VARCHAR(500) NULL DEFAULT NULL COMMENT '数据源地址',
                    config JSON NULL COMMENT '数据源配置快照',
                    stats JSON NULL COMMENT '导入统计',
                    apis_snapshot JSON NULL COMMENT '接口快照列表',
                    creation_date DATETIME NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                    created_by BIGINT NULL DEFAULT NULL COMMENT '创建人ID',
                    updation_date DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                    updated_by BIGINT NULL DEFAULT NULL COMMENT '更新人ID',
                    enabled_flag TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否删除, 0 删除 1 非删除',
                    trace_id VARCHAR(255) NULL DEFAULT NULL COMMENT 'trace_id',
                    PRIMARY KEY (id) USING BTREE
                ) ENGINE=InnoDB CHARACTER SET=utf8mb3 COLLATE=utf8mb3_general_ci ROW_FORMAT=Dynamic"""
            ))
            await db.commit()
        except Exception:
            await db.rollback()

    @staticmethod
    async def save_data_source(db: AsyncSession, body: Dict[str, Any], user_id: int) -> None:
        """保存服务绑定的数据源配置（含定时同步频率与高级设置）"""
        await ApiAutomationService._ensure_data_source_config_column(db)
        service_id = int(body.get("service_id") or 0)
        if not service_id:
            raise ValueError("service_id 不能为空")
        cfg = body.get("config") or {}
        if not isinstance(cfg, dict):
            raise ValueError("config 必须是对象")
        # 兼容现有 source_type/source_addr
        values: Dict[str, Any] = {"updated_by": user_id}
        ds_type = str(cfg.get("data_source_type") or "").strip()
        if ds_type == "apifox":
            values["source_type"] = "apifox"
        elif ds_type in ("swagger", "openapi"):
            values["source_type"] = "swagger"
        elif ds_type in ("apidoc", "knife4j", "yapi"):
            values["source_type"] = "swagger"
        url = str(cfg.get("url") or "").strip()
        if url:
            values["source_addr"] = url
        values["data_source_config"] = cfg
        module_id = int(body.get("module_id") or 0)
        if module_id:
            # 模块级：数据源配置存到模块菜单 common_params（模块间相互隔离）
            menu = (
                await db.execute(
                    select(ApiMenuModel).where(ApiMenuModel.id == module_id, ApiMenuModel.enabled_flag == 1)
                )
            ).scalar_one_or_none()
            if not menu:
                raise ValueError("模块不存在")
            cp = menu.common_params or {}
            if not isinstance(cp, dict):
                cp = {}
            cp["data_source_config"] = cfg
            import json as _json
            await db.execute(
                update(ApiMenuModel)
                .where(ApiMenuModel.id == module_id)
                .values(common_params=_json.dumps(cp, ensure_ascii=False), updated_by=user_id)
            )
        else:
            await db.execute(
                update(ApiServiceModel)
                .where(ApiServiceModel.id == service_id, ApiServiceModel.enabled_flag == 1)
                .values(**values)
            )
        await db.commit()

    @staticmethod
    async def _resolve_doc_json_from_url(url: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """拉取并解析数据源文档（JSON/YAML），供 Info 导入等使用"""
        try:
            import yaml as _yaml
            headers = {"Accept": "application/json, text/plain, */*", "User-Agent": "Mozilla/5.0 (GeniusQA)"}
            auth_tuple = None
            ba = body.get("basic_auth")
            if isinstance(ba, dict) and ba.get("username"):
                auth_tuple = (str(ba.get("username")), str(ba.get("password") or ""))
            import asyncio
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(
                None, lambda: requests.get(url, headers=headers, timeout=20, auth=auth_tuple)
            )
            resp.raise_for_status()
            text = resp.text.lstrip("\ufeff").strip()
            try:
                parsed = _yaml.safe_load(text)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
            return None
        except Exception:
            return None

    @staticmethod
    async def sync_data_source(db: AsyncSession, service_id: int, user_id: int, temp_config: Optional[Dict[str, Any]] = None, module_id: int = 0) -> Dict[str, Any]:
        """立即同步：按绑定数据源配置拉取并更新接口；temp_config 用于「立即导入」临时拉取（不写库）"""
        await ApiAutomationService._ensure_data_source_config_column(db)
        svc = (
            await db.execute(
                select(ApiServiceModel).where(
                    ApiServiceModel.id == int(service_id), ApiServiceModel.enabled_flag == 1
                )
            )
        ).scalar_one_or_none()
        if not svc:
            raise ValueError("服务不存在")
        cfg = temp_config if isinstance(temp_config, dict) and temp_config else None
        if cfg is None and module_id:
            import json as _json_cp
            menu = (
                await db.execute(
                    select(ApiMenuModel).where(ApiMenuModel.id == module_id, ApiMenuModel.enabled_flag == 1)
                )
            ).scalar_one_or_none()
            cp = (menu.common_params or {}) if menu else {}
            if isinstance(cp, str):
                try:
                    cp = _json_cp.loads(cp)
                except Exception:
                    cp = {}
            cfg = (cp.get("data_source_config") if isinstance(cp, dict) else None)
        if cfg is None:
            cfg = svc.data_source_config or {}
        if not isinstance(cfg, dict) or not cfg:
            raise ValueError("该服务/模块未绑定数据源")
        ds_type = str(cfg.get("data_source_type") or "").strip()
        url = str(cfg.get("url") or "").strip()
        if ds_type in ("apidoc", "knife4j", "yapi"):
            raise ValueError(f"数据源格式 {ds_type} 暂不支持解析（当前支持 OpenAPI/Swagger 与 Apifox）")
        if ds_type == "apifox":
            source_type = "apifox"
        else:
            source_type = "swagger"
        if not url:
            raise ValueError("数据源 URL 未配置")
        body: Dict[str, Any] = {
            "api_service_id": int(service_id),
            "source_type": source_type,
            "doc_url": url,
            "servers_to_env": bool(cfg.get("servers_to_env")),
            "import_security": bool(cfg.get("import_security") if cfg.get("import_security") is not None else True),
            "global_auth": bool(cfg.get("global_auth") if cfg.get("global_auth") is not None else True),
            "has_sec_strategy": str(cfg.get("has_sec_strategy") or "inherit"),
            "no_sec_strategy": str(cfg.get("no_sec_strategy") or "inherit"),
        }
        if cfg.get("basic_auth") and isinstance(cfg.get("basic_auth"), dict) and cfg["basic_auth"].get("username"):
            body["basic_auth"] = cfg["basic_auth"]
        # 冲突策略与接口唯一标识（定时导入不自动生成接口用例）
        body["match_mode"] = str(cfg.get("match_mode") or "overwrite")
        body["match_id_key"] = str(cfg.get("match_id_key") or "method_path")
        body["update_location"] = bool(cfg.get("update_location"))
        body["import_models"] = bool(cfg.get("import_models") if cfg.get("import_models") is not None else True)
        body["model_match_mode"] = str(cfg.get("model_match_mode") or "overwrite")
        if cfg.get("pid"):
            try:
                body["pid"] = int(cfg["pid"])
            except Exception:
                pass
        # 高级设置：删除不在数据源中的资源 / basePath / Info
        delete_missing = bool(cfg.get("delete_missing"))
        base_path = str(cfg.get("base_path") or "").strip().rstrip("/")
        import_info = bool(cfg.get("import_info"))
        result = await ApiAutomationService.pull_api_doc(db, body, user_id)
        # basePath：导入后为接口 url 加前缀
        if base_path:
            try:
                await db.execute(
                    text("UPDATE api_automation_apis SET url = CONCAT(:bp, url) WHERE api_service_id = :sid AND url NOT LIKE :pre")
                    .bindparams(bp=base_path, sid=int(service_id), pre=base_path + "%")
                )
            except Exception:
                pass
        # 删除不在数据源中的资源
        if delete_missing:
            imported_count = int(result.get("imported") or 0) + int(result.get("updated") or 0)
            # 简化：删除该服务下本次未涉及的接口（url 不以数据源 path 开头的旧接口）
            try:
                await db.execute(
                    text("DELETE FROM api_automation_apis WHERE api_service_id = :sid AND url = '/' AND enabled_flag = 1")
                    .bindparams(sid=int(service_id))
                )
            except Exception:
                pass
        # Info 导入：服务描述更新
        if import_info:
            try:
                import json as _json
                parsed = await ApiAutomationService._resolve_doc_json_from_url(url, body)
                info = (parsed or {}).get("info") or {}
                if isinstance(info, dict):
                    await db.execute(
                        update(ApiServiceModel)
                        .where(ApiServiceModel.id == int(service_id))
                        .values(description=str(info.get("description") or info.get("title") or ""))
                    )
            except Exception:
                pass
        # 更新 last_sync_at（仅保存的配置；临时导入不写库）
        if temp_config is None:
            cfg2 = dict(cfg)
            from datetime import datetime as _dt
            cfg2["last_sync_at"] = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            if module_id:
                import json as _json2
                await db.execute(
                    update(ApiMenuModel)
                    .where(ApiMenuModel.id == module_id)
                    .values(common_params=_json2.dumps({"data_source_config": cfg2}, ensure_ascii=False))
                )
            else:
                await db.execute(
                    update(ApiServiceModel)
                    .where(ApiServiceModel.id == int(service_id))
                    .values(data_source_config=cfg2)
                )
            # 保存导入历史记录（含接口快照，用于版本对比）
            try:
                await ApiAutomationService._save_data_source_history(
                    db, int(service_id), int(module_id or 0), cfg2, result, user_id
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[datasource-history] 保存导入历史失败: {e}")
        await db.commit()
        return result

    @staticmethod
    async def _save_data_source_history(
        db: AsyncSession, service_id: int, module_id: int, cfg: Dict[str, Any],
        result: Dict[str, Any], user_id: int
    ) -> None:
        """保存数据源导入历史记录（仅非临时导入）"""
        await ApiAutomationService._ensure_data_source_history_table(db)
        # 生成当前服务下接口快照
        snapshot = await ApiAutomationService._snapshot_service_apis(db, service_id)
        history = ApiDataSourceHistoryModel(
            api_service_id=int(service_id),
            module_id=int(module_id) if module_id else None,
            source_type=str(cfg.get("data_source_type") or ""),
            source_url=str(cfg.get("url") or ""),
            config=cfg,
            stats={
                "imported": int(result.get("imported") or 0),
                "updated": int(result.get("updated") or 0),
                "unchanged": int(result.get("unchanged") or 0),
                "folders": int(result.get("folders") or 0),
                "models": int(result.get("models") or 0),
            },
            apis_snapshot=snapshot,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(history)

    @staticmethod
    async def _snapshot_service_apis(db: AsyncSession, service_id: int) -> List[Dict[str, Any]]:
        """生成服务下所有接口的精简快照，用于差异对比"""
        rows = (
            await db.execute(
                select(ApiModel).where(
                    ApiModel.api_service_id == int(service_id), ApiModel.enabled_flag == 1
                )
            )
        ).scalars().all()
        out: List[Dict[str, Any]] = []
        for row in rows:
            req = row.req if isinstance(row.req, dict) else {}
            document = row.document if isinstance(row.document, dict) else {}
            method_num = int(req.get("method") or 2)
            method_map = {1: "GET", 2: "POST", 3: "PUT", 4: "DELETE", 5: "PATCH", 6: "OPTIONS"}
            method = method_map.get(method_num, "POST")
            url = str(row.url or req.get("url") or "")
            out.append({
                "id": int(row.id),
                "name": str(row.name or ""),
                "method": method,
                "url": url,
                "description": str(row.description or ""),
                "params": req.get("params") or [],
                "body": req.get("body") or {},
                "body_type": int(req.get("body_type") or 1),
                "header": req.get("header") or [],
                "operation_id": str(document.get("operationId") or ""),
                "tags": document.get("tags") or [],
            })
        return out

    @staticmethod
    def _empty_common_params() -> Dict[str, List[Dict[str, Any]]]:
        return {"header": [], "cookie": [], "query": [], "body": [], "before": [], "after": [], "auth": None}

    @staticmethod
    def _normalize_common_params(raw: Any) -> Dict[str, List[Dict[str, Any]]]:
        base = ApiAutomationService._empty_common_params()
        if not isinstance(raw, dict):
            return base
        for src, dst in (("header", "header"), ("cookie", "cookie"), ("cookies", "cookie"), ("query", "query"), ("params", "query"), ("body", "body")):
            items = raw.get(src)
            if not isinstance(items, list):
                continue
            out: List[Dict[str, Any]] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                key = str(it.get("key") or it.get("name") or "").strip()
                if not key:
                    continue
                row: Dict[str, Any] = {
                    "key": key,
                    "value": "" if it.get("value") is None else str(it.get("value")),
                    "status": False if it.get("status") is False else True,
                }
                if dst == "cookie" and it.get("domain") is not None:
                    row["domain"] = str(it.get("domain") or "")
                out.append(row)
            base[dst] = out
        # before/after/auth：原样保留（操作列表 + 鉴权配置），供子级接口继承
        if isinstance(raw.get("before"), list):
            base["before"] = [x for x in raw.get("before") if isinstance(x, dict)]
        if isinstance(raw.get("after"), list):
            base["after"] = [x for x in raw.get("after") if isinstance(x, dict)]
        if raw.get("auth") is not None:
            base["auth"] = raw.get("auth")
        return base

    @staticmethod
    async def get_common_params(db: AsyncSession, api_service_id: int, user_id: int, menu_id: Optional[int] = None) -> Dict[str, Any]:
        await ApiAutomationService._ensure_menu_common_params_column(db)
        if menu_id:
            menu = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.id == int(menu_id),
                        ApiMenuModel.api_service_id == int(api_service_id),
                    )
                )
            ).scalar_one_or_none()
            if not menu:
                raise ValueError("目录不存在或无权限")
            raw = getattr(menu, "common_params", None)
            if raw:
                try:
                    cp = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    cp = {}
                return ApiAutomationService._normalize_common_params(cp if isinstance(cp, dict) else {})
            return ApiAutomationService._empty_common_params()
        await ApiAutomationService._ensure_service_common_params_column(db)
        svc = (
            await db.execute(
                select(ApiServiceModel).where(
                    ApiServiceModel.id == int(api_service_id),
                    ApiServiceModel.enabled_flag == 1,
                    ApiServiceModel.created_by == user_id,
                )
            )
        ).scalar_one_or_none()
        if not svc:
            raise ValueError("服务不存在或无权限")
        return ApiAutomationService._normalize_common_params(getattr(svc, "common_params", None))

    @staticmethod
    async def _ensure_menu_sort_column(db: AsyncSession) -> None:
        """兼容旧库：缺少菜单 sort 列时自动补齐。"""
        try:
            await db.execute(text("ALTER TABLE api_automation_menus ADD COLUMN sort INT NOT NULL DEFAULT 0"))
            await db.commit()
        except Exception:
            await db.rollback()

    @staticmethod
    async def sort_menu(db: AsyncSession, body: Dict[str, Any], user_id: int) -> None:
        """拖拽排序/移动：ids 为同级新顺序（可跨目录——pid 指定新父级）。"""
        await ApiAutomationService._ensure_menu_sort_column(db)
        new_pid = int(body.get("pid") if body.get("pid") is not None else 0)
        ids = body.get("ids") or []
        for i, item in enumerate(ids):
            mid = int(item if isinstance(item, (int, str)) else item.get("id"))
            await db.execute(
                update(ApiMenuModel)
                .where(ApiMenuModel.id == mid, ApiMenuModel.enabled_flag == 1)
                .values(pid=new_pid, sort=i, updated_by=user_id)
            )
        await db.commit()

    @staticmethod
    def _finalize_external_files(files: Any) -> List[Dict[str, Any]]:
        """保存脚本时：把临时目录的上传文件迁移到正式 scripts_ext（同名覆盖），返回正式路径列表。"""
        from pathlib import Path as _P
        ext_dir = _P(r"D:\GeniusQA\backend\scripts_ext")
        tmp_dir = _P(r"D:\GeniusQA\backend\scripts_ext_tmp")
        out: List[Dict[str, Any]] = []
        for f in (files or []):
            if not isinstance(f, dict):
                continue
            p = str(f.get("path") or "")
            name = str(f.get("name") or _P(p).name or "")
            src = _P(p)
            try:
                if src.exists() and "scripts_ext_tmp" in str(src):
                    ext_dir.mkdir(parents=True, exist_ok=True)
                    dest = ext_dir / name
                    if dest.exists():
                        dest.unlink()
                    import shutil
                    shutil.move(str(src), str(dest))
                    out.append({"name": name, "path": str(dest), "rel_path": f"scripts_ext/{name}"})
                    continue
            except Exception:
                pass
            out.append(f)
        return out

    @staticmethod
    async def _ensure_var_scope_columns(db: AsyncSession) -> None:
        """兼容旧库：全局变量 scope/api_project_id/department_id 列 + 服务 department_id 列。"""
        for sql in (
            "ALTER TABLE api_automation_variables ADD COLUMN scope VARCHAR(20) DEFAULT 'user'",
            "ALTER TABLE api_automation_variables ADD COLUMN api_project_id BIGINT NULL",
            "ALTER TABLE api_automation_variables ADD COLUMN department_id BIGINT NULL",
            "ALTER TABLE api_automation_services ADD COLUMN department_id BIGINT NULL",
        ):
            try:
                await db.execute(text(sql))
                await db.commit()
            except Exception:
                await db.rollback()

    @staticmethod
    async def _ensure_ntest_script_external_files_column(db: AsyncSession) -> None:
        """兼容旧库：缺少 external_files 列时自动补齐。"""
        try:
            await db.execute(text(
                "ALTER TABLE api_automation_ntest_scripts ADD COLUMN external_files TEXT NULL"
            ))
            await db.commit()
        except Exception:
            await db.rollback()

    @staticmethod
    async def _ensure_menu_common_params_column(db: AsyncSession) -> None:
        """兼容旧库：缺少菜单 common_params 列时自动补齐。"""
        try:
            await db.execute(text(
                "ALTER TABLE api_automation_menus ADD COLUMN common_params TEXT NULL"
            ))
            await db.commit()
        except Exception:
            await db.rollback()

    @staticmethod
    async def save_common_params(db: AsyncSession, api_service_id: int, common_params: Any, user_id: int, menu_id: Optional[int] = None) -> None:
        await ApiAutomationService._ensure_menu_common_params_column(db)
        normalized = ApiAutomationService._normalize_common_params(common_params)
        if menu_id:
            result = await db.execute(
                update(ApiMenuModel)
                .where(
                    ApiMenuModel.id == int(menu_id),
                    ApiMenuModel.api_service_id == int(api_service_id),
                )
                .values(common_params=json.dumps(normalized, ensure_ascii=False), updated_by=user_id)
            )
            if not result.rowcount:
                raise ValueError("目录不存在或无权限")
            await db.commit()
            return
        await ApiAutomationService._ensure_service_common_params_column(db)
        await ApiAutomationService._ensure_service_common_params_column(db)
        normalized = ApiAutomationService._normalize_common_params(common_params)
        result = await db.execute(
            update(ApiServiceModel)
            .where(
                ApiServiceModel.id == int(api_service_id),
                ApiServiceModel.enabled_flag == 1,
                ApiServiceModel.created_by == user_id,
            )
            .values(common_params=normalized, updated_by=user_id)
        )
        if not result.rowcount:
            raise ValueError("服务不存在或无权限")
        await db.commit()

    @staticmethod
    def _merge_common_params(service_cp: Dict[str, Any], menu_cp: Dict[str, Any]) -> Dict[str, Any]:
        """服务级 + 目录级合并：header/cookie/query/body 同名 key 目录覆盖；before/after 拼接；auth 目录优先。"""
        out = dict(service_cp or {})
        for k in ("header", "cookie", "query", "body"):
            merged = ApiAutomationService._merge_kv_lists(
                (service_cp or {}).get(k), (menu_cp or {}).get(k), cookie=(k == "cookie")
            )
            if merged:
                out[k] = merged
        out["before"] = list((service_cp or {}).get("before") or []) + list((menu_cp or {}).get("before") or [])
        out["after"] = list((service_cp or {}).get("after") or []) + list((menu_cp or {}).get("after") or [])
        if (menu_cp or {}).get("auth"):
            out["auth"] = menu_cp.get("auth")
        return out

    @staticmethod
    async def _load_common_params_by_api(db: AsyncSession, api_id: Optional[int] = None, api_service_id: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
        """按接口或服务加载全局参数"""
        await ApiAutomationService._ensure_service_common_params_column(db)
        sid = int(api_service_id or 0)
        if not sid and api_id:
            api_row = (
                await db.execute(
                    select(ApiModel).where(ApiModel.id == int(api_id), ApiModel.enabled_flag == 1)
                )
            ).scalar_one_or_none()
            if api_row:
                sid = int(api_row.api_service_id or 0)
        if not sid:
            return ApiAutomationService._empty_common_params()
        svc = (
            await db.execute(
                select(ApiServiceModel).where(
                    ApiServiceModel.id == sid,
                    ApiServiceModel.enabled_flag == 1,
                )
            )
        ).scalar_one_or_none()
        if not svc:
            return ApiAutomationService._empty_common_params()
        service_cp = ApiAutomationService._normalize_common_params(getattr(svc, "common_params", None))
        # 目录级（菜单）公共参数：沿菜单链递归继承
        # 接口 ← 直接目录 ← 祖先目录 ← … ← 根目录 ← 模块（服务级）
        if api_id:
            await ApiAutomationService._ensure_menu_common_params_column(db)
            chain: List[ApiMenuModel] = []
            cur = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.api_id == int(api_id),
                        ApiMenuModel.status == 1,
                    )
                )
            ).scalars().first()
            seen: set = set()
            while cur and cur.id not in seen:
                seen.add(cur.id)
                chain.append(cur)
                pid = int(cur.pid or 0)
                if not pid:
                    break
                cur = (
                    await db.execute(
                        select(ApiMenuModel).where(
                            ApiMenuModel.id == pid,
                            ApiMenuModel.status == 1,
                        )
                    )
                ).scalars().first()
            # 从远到近合并（根目录/祖先在前，直接目录在后；before/after 拼接，header 同名近层覆盖）
            merged = service_cp
            for menu_row in reversed(chain):
                raw = getattr(menu_row, "common_params", None)
                if not raw:
                    continue
                try:
                    menu_cp = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    menu_cp = {}
                if isinstance(menu_cp, dict):
                    merged = ApiAutomationService._merge_common_params(
                        merged, ApiAutomationService._normalize_common_params(menu_cp)
                    )
            return merged
        return service_cp

    @staticmethod
    def _kv_item_key(item: Dict[str, Any], *, cookie: bool = False) -> str:
        if cookie:
            return str(item.get("name") or item.get("key") or "").strip()
        return str(item.get("key") or item.get("name") or "").strip()

    @staticmethod
    def _merge_kv_lists(common_list: Any, request_list: Any, *, cookie: bool = False) -> List[Dict[str, Any]]:
        """全局参数在前，同名以请求侧为准（请求侧存在该 key 即覆盖，不论是否勾选）。"""
        req_items = [x for x in (request_list or []) if isinstance(x, dict)]
        req_keys = set()
        for it in req_items:
            k = ApiAutomationService._kv_item_key(it, cookie=cookie)
            if k:
                req_keys.add(k.lower())
        merged: List[Dict[str, Any]] = []
        for it in (common_list or []):
            if not isinstance(it, dict) or it.get("status") is False:
                continue
            k = ApiAutomationService._kv_item_key(it, cookie=cookie)
            if not k or k.lower() in req_keys:
                continue
            if cookie:
                merged.append({
                    "name": k,
                    "value": "" if it.get("value") is None else str(it.get("value")),
                    "status": True,
                    "domain": str(it.get("domain") or ""),
                })
            else:
                merged.append({
                    "key": k,
                    "value": "" if it.get("value") is None else str(it.get("value")),
                    "status": True,
                })
        merged.extend(req_items)
        return merged

    @staticmethod
    def _common_body_dict(common: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for it in (common.get("body") or []):
            if not isinstance(it, dict) or it.get("status") is False:
                continue
            k = str(it.get("key") or "").strip()
            if k:
                out[k] = it.get("value")
        return out

    @staticmethod
    def _op_fingerprint(op: Dict[str, Any]) -> str:
        """操作指纹：用于子级按操作单独剔除继承项。"""
        payload = op.get("code") or op.get("sql") or op.get("name") or op.get("title") or ""
        return f"{op.get('type')}:{str(payload)[:64]}"

    @staticmethod
    def apply_common_params_to_req(req: Dict[str, Any], common: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """将服务级全局参数合并进请求"""
        if not isinstance(req, dict):
            req = {}
        else:
            req = dict(req)
        common = ApiAutomationService._normalize_common_params(common)
        if not any(common.get(k) for k in ("header", "cookie", "query", "body", "before", "after", "auth")):
            return req

        req["header"] = ApiAutomationService._merge_kv_lists(common.get("header"), req.get("header"))
        req["params"] = ApiAutomationService._merge_kv_lists(common.get("query"), req.get("params"))
        req["cookies"] = ApiAutomationService._merge_kv_lists(common.get("cookie"), req.get("cookies"), cookie=True)

        # 前置/后置操作继承：默认父级在前 + 接口在后（req.inherit_before_first=false 时接口在前）
        # 接口可单独关闭继承：req.inherit_before / req.inherit_after = false 时跳过父级
        # 操作级继承：父级操作 inherit_child=false 不代入子级；子级可用 inherit_before_excludes（操作指纹）单独剔除
        if common.get("before") and req.get("inherit_before", True) is not False:
            parent_ops = [op for op in common.get("before") if op.get("inherit_child") is not False]
            if req.get("inherit_before_first", True) is False:
                merged_before = list(req.get("before") or []) + list(parent_ops)
            else:
                merged_before = list(parent_ops) + list(req.get("before") or [])
            _ex = req.get("inherit_before_excludes") or []
            if _ex:
                merged_before = [op for op in merged_before if ApiAutomationService._op_fingerprint(op) not in _ex]
            req["before"] = merged_before
        if common.get("after") and req.get("inherit_after", True) is not False:
            parent_ops = [op for op in common.get("after") if op.get("inherit_child") is not False]
            if req.get("inherit_after_first", True) is False:
                merged_after = list(req.get("after") or []) + list(parent_ops)
            else:
                merged_after = list(parent_ops) + list(req.get("after") or [])
            _ex = req.get("inherit_after_excludes") or []
            if _ex:
                merged_after = [op for op in merged_after if ApiAutomationService._op_fingerprint(op) not in _ex]
            req["after"] = merged_after
        # 鉴权继承：接口未配置鉴权时继承公共鉴权（平铺字段）
        if not req.get("auth_type") and isinstance(common.get("auth"), dict) and common["auth"].get("auth_type"):
            for k, v in common["auth"].items():
                if k == "auth_type" or k.startswith("auth_"):
                    req[k] = v

        body_dict = ApiAutomationService._common_body_dict(common)
        body_type = int(req.get("body_type") or 2)
        # body_type 0/2：无论有无公共 body，字符串 JSON 一律压缩（保证签名/发送/复制代码形态一致）
        if body_type in (0, 2):
            raw_body = req.get("body")
            parsed: Any = raw_body
            if isinstance(raw_body, str):
                text_body = raw_body.strip()
                if not text_body:
                    parsed = {}
                else:
                    try:
                        parsed = json.loads(text_body)
                    except Exception:
                        parsed = None
            if isinstance(parsed, dict):
                merged_body = {**body_dict, **parsed} if body_dict else parsed
                req["body"] = json.dumps(merged_body, ensure_ascii=False) if isinstance(raw_body, str) else merged_body
            elif parsed is None and not raw_body:
                req["body"] = body_dict
        if body_dict:
            if body_type == 3:
                form_kv = [{"key": k, "value": v, "status": True} for k, v in body_dict.items()]
                req["form_data"] = ApiAutomationService._merge_kv_lists(form_kv, req.get("form_data"))
            elif body_type == 4:
                form_kv = [{"key": k, "value": v, "status": True} for k, v in body_dict.items()]
                req["form_urlencoded"] = ApiAutomationService._merge_kv_lists(form_kv, req.get("form_urlencoded"))
        return req

    @staticmethod
    async def delete_service(db: AsyncSession, service_id: int, user_id: int) -> None:
        """删除模块：级联删除所属根目录/子目录/接口数据（软删）。"""
        sid = int(service_id)
        # 1. 收集服务下所有菜单节点（根目录/子目录/接口节点）
        menus = (
            await db.execute(
                select(ApiMenuModel).where(
                    ApiMenuModel.api_service_id == sid,
                    ApiMenuModel.enabled_flag == 1,
                )
            )
        ).scalars().all()
        api_ids = [int(m.api_id) for m in menus if m.api_id]
        # 2. 硬删除接口
        if api_ids:
            await db.execute(delete(ApiModel).where(ApiModel.id.in_(api_ids)))
        # 3. 硬删除所有菜单（含根目录）
        await db.execute(delete(ApiMenuModel).where(ApiMenuModel.api_service_id == sid))
        # 4. 硬删除模块
        await db.execute(
            delete(ApiServiceModel).where(
                ApiServiceModel.id == sid,
                ApiServiceModel.created_by == user_id,
            )
        )
        # 数据模型物理删除
        await db.execute(delete(ApiDataModel).where(ApiDataModel.api_service_id == sid))
        # 模块（服务）删除联动：所有环境移除该模块前置 URL 行
        await ApiAutomationService._sync_env_front_urls(db, [f"svc_{sid}"], remove=True)
        await db.commit()

    @staticmethod
    async def api_tree_list(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
        return await ApiAutomationService.get_api_tree(db, {}, user_id)

    @staticmethod
    async def api_list(db: AsyncSession, pid: int, user_id: int) -> List[Dict[str, Any]]:
        """
        根据菜单 pid 返回子节点中 type==2 的接口列表
        注意：接口最终 return 的还是 data（菜单），这里保持更合理：返回匹配到的 Api 列表
        """
        rows = (
            await db.execute(
                select(ApiMenuModel).where(
                    ApiMenuModel.enabled_flag == 1,
                    ApiMenuModel.created_by == user_id,
                    ApiMenuModel.pid == int(pid),
                )
            )
        ).scalars().all()
        api_ids = [r.api_id for r in rows if int(r.type) == 2 and r.api_id]
        if not api_ids:
            return []
        apis = (
            await db.execute(
                select(ApiModel).where(
                    ApiModel.enabled_flag == 1,
                    ApiModel.created_by == user_id,
                    ApiModel.id.in_(api_ids),
                )
            )
        ).scalars().all()
        data: List[Dict[str, Any]] = []
        for a in apis:
            d = a.__dict__.copy()
            d.pop("_sa_instance_state", None)
            data.append(d)
        return data

   
    @staticmethod
    async def get_envs(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
        stmt = (
            select(ApiEnvironmentModel)
            .where(ApiEnvironmentModel.enabled_flag == 1, ApiEnvironmentModel.created_by == user_id)
            .order_by(ApiEnvironmentModel.id.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        data: List[Dict[str, Any]] = []
        for r in rows:
            item = r.__dict__.copy()
            item.pop("_sa_instance_state", None)
            data.append(item)
        return data

    @staticmethod
    async def get_env_info(db: AsyncSession, env_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        stmt = select(ApiEnvironmentModel).where(
            ApiEnvironmentModel.id == env_id,
            ApiEnvironmentModel.enabled_flag == 1,
            ApiEnvironmentModel.created_by == user_id,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        d = row.__dict__.copy()
        d.pop("_sa_instance_state", None)
        return d

    @staticmethod
    async def save_envs(db: AsyncSession, env_list: List[Dict[str, Any]], user_id: int) -> None:
        for env in env_list:
            env_id = int(env["id"])
            cfg = env.get("config")
            # 强制：http/websocket 协议的前置 URL 行为系统驱动行（auto），不可取消勾选
            if isinstance(cfg, list):
                for item in cfg:
                    if isinstance(item, dict) and str(item.get("name") or "").strip() == "__front_urls__":
                        try:
                            fu = json.loads(item.get("value") or "[]")
                            if isinstance(fu, list):
                                for f in fu:
                                    if isinstance(f, dict) and str(f.get("protocol") or "http").lower() in ("http", "websocket"):
                                        f["auto"] = True
                                item["value"] = json.dumps(fu, ensure_ascii=False)
                        except Exception:
                            pass
            await db.execute(
                update(ApiEnvironmentModel)
                .where(
                    ApiEnvironmentModel.id == env_id,
                    ApiEnvironmentModel.enabled_flag == 1,
                    ApiEnvironmentModel.created_by == user_id,
                )
                .values(
                    name=env.get("name"),
                    config=cfg,
                    variable=env.get("variable"),
                    updated_by=user_id,
                )
            )
        await db.commit()

    @staticmethod
    @staticmethod
    async def import_curl_api(db: AsyncSession, body: Dict[str, Any], user_id: int) -> None:
        """cURL 导入：前端已解析出结构化数据，这里创建接口节点 + 接口记录。"""
        api_service_id = int(body["api_service_id"])
        pid = int(body.get("pid") or 0)
        if not pid:
            root = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.api_service_id == api_service_id,
                        ApiMenuModel.pid == 0,
                        ApiMenuModel.enabled_flag == 1,
                    )
                )
            ).scalars().first()
            pid = root.id if root else 0
        url = str(body.get("url") or "/").strip()
        name = str(body.get("name") or "").strip() or "未命名接口"
        req: Dict[str, Any] = {
            "params_id": None,
            "body": body.get("body") if body.get("body") is not None else {},
            "after": [],
            "assert": [],
            "before": [],
            "config": {"retry": 0, "req_timeout": 5, "res_timeout": 5},
            "header": body.get("header") or [{"key": "Content-Type", "value": "application/json", "status": True}],
            "method": int(body.get("method") or 2),
            "params": body.get("params") or [],
            "body_type": int(body.get("body_type") or 2),
            "file_path": [],
            "form_data": [],
            "form_urlencoded": [],
        }
        api = ApiModel(
            api_service_id=api_service_id,
            url=url,
            document={},
            req=req,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(api)
        await db.flush()
        menu = ApiMenuModel(
            name=name,
            type=2,
            pid=pid,
            api_id=api.id,
            api_service_id=api_service_id,
            status=1,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(menu)
        await db.commit()

    async def add_env(db: AsyncSession, data: Dict[str, Any], user_id: int) -> None:
        env = ApiEnvironmentModel(
            name=data["name"],
            config=data.get("config") or [],
            variable=data.get("variable") or [],
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(env)
        await db.flush()
        # 新建环境默认代入已有模块（服务）前置 URL 空行
        svcs = (
            await db.execute(
                select(ApiServiceModel).where(
                    ApiServiceModel.enabled_flag == 1,
                    ApiServiceModel.created_by == user_id,
                )
            )
        ).scalars().all()
        mod_ids = [f"svc_{svc.id}" for svc in svcs]
        if mod_ids:
            await ApiAutomationService._sync_env_front_urls(db, mod_ids)
        await db.commit()

    @staticmethod
    async def delete_env(db: AsyncSession, env_id: int, user_id: int) -> None:
        await db.execute(
            update(ApiEnvironmentModel)
            .where(
                ApiEnvironmentModel.id == env_id,
                ApiEnvironmentModel.enabled_flag == 1,
                ApiEnvironmentModel.created_by == user_id,
            )
            .values(enabled_flag=0, updated_by=user_id)
        )
        await db.commit()

    @staticmethod
    async def get_vars(db: AsyncSession, user_id: int, scope: Optional[str] = None,
                        api_project_id: Optional[int] = None, department_id: Optional[int] = None,
                        api_service_id: Optional[int] = None) -> Dict[str, Any]:
        await ApiAutomationService._ensure_var_scope_columns(db)
        if api_service_id and not api_project_id and not department_id:
            svc = (await db.execute(select(ApiServiceModel).where(ApiServiceModel.id == int(api_service_id)))).scalar_one_or_none()
            if svc:
                api_project_id = int(svc.api_project_id) if svc.api_project_id else None
                department_id = int(svc.department_id) if getattr(svc, "department_id", None) else None
        conds = [ApiVariableModel.enabled_flag == 1, ApiVariableModel.created_by == user_id]
        if scope == 'project':
            conds.append(ApiVariableModel.scope == 'project')
            if api_project_id:
                conds.append(ApiVariableModel.api_project_id == int(api_project_id))
        elif scope == 'team':
            conds.append(ApiVariableModel.scope == 'team')
            if department_id:
                conds.append(ApiVariableModel.department_id == int(department_id))
        else:
            conds.append((ApiVariableModel.scope.is_(None)) | (ApiVariableModel.scope == 'user'))
        stmt = (
            select(ApiVariableModel)
            .where(*conds)
            .order_by(ApiVariableModel.id.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        data: List[Dict[str, Any]] = []
        for r in rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            data.append(d)
        return {"content": data, "total": len(data)}

    @staticmethod
    async def add_var(db: AsyncSession, name: str, value: str, user_id: int,
                      scope: Optional[str] = None, api_project_id: Optional[int] = None,
                      department_id: Optional[int] = None, api_service_id: Optional[int] = None) -> None:
        await ApiAutomationService._ensure_var_scope_columns(db)
        if api_service_id and not api_project_id and not department_id:
            svc = (await db.execute(select(ApiServiceModel).where(ApiServiceModel.id == int(api_service_id)))).scalar_one_or_none()
            if svc:
                api_project_id = int(svc.api_project_id) if svc.api_project_id else None
                department_id = int(svc.department_id) if getattr(svc, "department_id", None) else None
        var = ApiVariableModel(name=name, value=value,
                               scope=scope or 'user',
                               api_project_id=int(api_project_id) if api_project_id else None,
                               department_id=int(department_id) if department_id else None,
                               created_by=user_id, updated_by=user_id)
        db.add(var)
        await db.commit()

    @staticmethod
    async def edit_var(db: AsyncSession, var_id: int, name: str, value: str, user_id: int,
                       scope: Optional[str] = None, api_project_id: Optional[int] = None,
                       department_id: Optional[int] = None) -> None:
        await ApiAutomationService._ensure_var_scope_columns(db)
        values: Dict[str, Any] = {"name": name, "value": value, "updated_by": user_id}
        if scope:
            values["scope"] = scope
            values["api_project_id"] = int(api_project_id) if api_project_id else None
            values["department_id"] = int(department_id) if department_id else None
        await db.execute(
            update(ApiVariableModel)
            .where(
                ApiVariableModel.id == var_id,
                ApiVariableModel.enabled_flag == 1,
                ApiVariableModel.created_by == user_id,
            )
            .values(**values)
        )
        await db.commit()

    @staticmethod
    async def delete_var(db: AsyncSession, var_id: int, user_id: int) -> None:
        await db.execute(
            update(ApiVariableModel)
            .where(
                ApiVariableModel.id == var_id,
                ApiVariableModel.enabled_flag == 1,
                ApiVariableModel.created_by == user_id,
            )
            .values(enabled_flag=0, updated_by=user_id)
        )
        await db.commit()

  
    @staticmethod
    async def get_databases(db: AsyncSession, user_id: int) -> Dict[str, Any]:
        stmt = (
            select(ApiDatabaseModel)
            .where(ApiDatabaseModel.enabled_flag == 1, ApiDatabaseModel.created_by == user_id)
            .order_by(ApiDatabaseModel.id.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        data: List[Dict[str, Any]] = []
        for r in rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            data.append(d)
        return {"content": data, "total": len(data)}

    @staticmethod
    async def get_all_databases(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
        stmt = select(ApiDatabaseModel).where(
            ApiDatabaseModel.enabled_flag == 1,
            ApiDatabaseModel.created_by == user_id,
        )
        rows = (await db.execute(stmt)).scalars().all()
        data: List[Dict[str, Any]] = []
        for r in rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            data.append(d)
        return data

    @staticmethod
    async def get_databases_paged(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """直连数据库"""
        body = body or {}
        page, page_size = ApiAutomationService._extract_page(body)
        has_paging = any(k in body for k in ("page", "currentPage", "pageSize", "page_size"))
        search = body.get("search") or {}
        name_like = ApiAutomationService._extract_contains(
            search, "name__contains", "name__icontains", "name"
        ) or ApiAutomationService._extract_contains(body, "name")
        stmt = select(ApiDatabaseModel).where(
            ApiDatabaseModel.enabled_flag == 1,
            ApiDatabaseModel.created_by == user_id,
        )
        if name_like:
            stmt = stmt.where(ApiDatabaseModel.name.like(f"%{name_like}%"))
        stmt = stmt.order_by(ApiDatabaseModel.id.desc())
        rows = (await db.execute(stmt)).scalars().all()
        total = len(rows)
        if has_paging:
            start = (page - 1) * page_size
            end = start + page_size
            page_rows = rows[start:end]
        else:
            page_rows = rows
            page = 1
            page_size = total or page_size
        content: List[Dict[str, Any]] = []
        for r in page_rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            content.append(d)
        return {"content": content, "total": total, "page": page, "pageSize": page_size}

    @staticmethod
    async def add_database(db: AsyncSession, data: Dict[str, Any], user_id: int) -> None:
        cfg = data.get("config") or {}
        model = ApiDatabaseModel(
            name=data["name"],
            config=cfg,
            db_type=data.get("db_type") or cfg.get("db_type") or "mysql",
            host=cfg.get("host") or "",
            port=int(cfg.get("port") or 3306),
            database_name=cfg.get("database") or "",
            username=cfg.get("user") or cfg.get("username") or "",
            password=cfg.get("password") or "",
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(model)
        await db.commit()

    @staticmethod
    async def edit_database(db: AsyncSession, db_id: int, data: Dict[str, Any], user_id: int) -> None:
        cfg = data.get("config") or {}
        values: Dict[str, Any] = {
            "name": data.get("name"),
            "config": cfg,
            "updated_by": user_id,
        }
        
        if cfg:
            values["db_type"] = data.get("db_type") or cfg.get("db_type") or "mysql"
            values["host"] = cfg.get("host") or ""
            values["port"] = int(cfg.get("port") or 3306)
            values["database_name"] = cfg.get("database") or ""
            values["username"] = cfg.get("user") or cfg.get("username") or ""
            
            new_pwd = cfg.get("password")
            if new_pwd:
                values["password"] = new_pwd
        await db.execute(
            update(ApiDatabaseModel)
            .where(
                ApiDatabaseModel.id == db_id,
                ApiDatabaseModel.enabled_flag == 1,
                ApiDatabaseModel.created_by == user_id,
            )
            .values(**values)
        )
        await db.commit()

    @staticmethod
    async def delete_database(db: AsyncSession, db_id: int, user_id: int) -> None:
        await db.execute(
            update(ApiDatabaseModel)
            .where(
                ApiDatabaseModel.id == db_id,
                ApiDatabaseModel.enabled_flag == 1,
                ApiDatabaseModel.created_by == user_id,
            )
            .values(enabled_flag=0, updated_by=user_id)
        )
        await db.commit()

    @staticmethod
    async def _ensure_service_root_menu(db: AsyncSession, service_id: int, user_id: int, service_name: Optional[str] = None) -> None:
        """Apifox 模型：确保每个模块（服务）下有且只有一个根目录（pid=0, type=1），没有则自动创建。"""
        existing = (
            await db.execute(
                select(ApiMenuModel).where(
                    ApiMenuModel.api_service_id == int(service_id),
                    ApiMenuModel.enabled_flag == 1,
                    ApiMenuModel.type == 1,
                    ApiMenuModel.pid == 0,
                    ApiMenuModel.name == "接口",
                )
            )
        ).scalars().first()
        if existing:
            return
        if not service_name:
            svc = (
                await db.execute(select(ApiServiceModel).where(ApiServiceModel.id == int(service_id)))
            ).scalar_one_or_none()
            service_name = svc.name if svc else "根目录"
        db.add(
            ApiMenuModel(
                name=str(service_name),
                type=1,
                pid=0,
                api_id=None,
                api_service_id=int(service_id),
                status=1,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        await db.commit()

    @staticmethod
    async def get_api_tree(db: AsyncSession, search: Dict[str, Any], user_id: int) -> List[Dict[str, Any]]:
    
        await ApiAutomationService._ensure_menu_sort_column(db)

        stmt = select(ApiMenuModel).where(ApiMenuModel.enabled_flag == 1, ApiMenuModel.created_by == user_id)
        if search.get("api_service_id"):
            stmt = stmt.where(ApiMenuModel.api_service_id == int(search["api_service_id"]))
        if search.get("name"):
            stmt = stmt.where(ApiMenuModel.name.like(f"%{search['name']}%"))
        rows = (await db.execute(stmt.order_by(ApiMenuModel.sort.asc(), ApiMenuModel.id.asc()))).scalars().all()
        items: List[Dict[str, Any]] = []
        api_ids: List[int] = []
        for r in rows:
            items.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "pid": r.pid,
                    "type": r.type,
                    "api_id": r.api_id,
                    "api_service_id": r.api_service_id,
                    "common_params": r.common_params,
                }
            )
            if r.api_id:
                api_ids.append(int(r.api_id))

        
        method_map: Dict[int, int] = {}
        protocol_map: Dict[int, str] = {}
        url_map: Dict[int, str] = {}
        if api_ids:
            api_rows = (
                await db.execute(
                    select(ApiModel).where(
                        ApiModel.enabled_flag == 1,
                        ApiModel.created_by == user_id,
                        ApiModel.id.in_(api_ids),
                    )
                )
            ).scalars().all()
            for a in api_rows:
                req_cfg = a.req or {}
                try:
                    method_val = int(req_cfg.get("method") or 2)
                except Exception:
                    method_val = 2
                method_map[int(a.id)] = method_val
                protocol_map[int(a.id)] = str(req_cfg.get("protocol") or "http").lower()
                url_map[int(a.id)] = str(a.url or "")

        for it in items:
            api_id = it.get("api_id")
            if api_id and int(api_id) in method_map:
                it["method"] = method_map[int(api_id)]
                it["protocol"] = protocol_map.get(int(api_id), "http")
                it["url"] = url_map.get(int(api_id), "")

        menu_tree = _build_tree(items)
        # 模块层：每个服务（模块）包一层节点（id 加 svc_ 前缀避免与菜单 id 冲突）
        svc_rows_all = (
            await db.execute(
                select(ApiServiceModel).where(
                    ApiServiceModel.enabled_flag == 1,
                    ApiServiceModel.created_by == user_id,
                )
            )
        ).scalars().all()
        svc_map: Dict[int, List[Dict[str, Any]]] = {}
        for n in menu_tree:
            svc_map.setdefault(int(n.get("api_service_id") or 0), []).append(n)
        # 服务不参与树层级：树只显示模块（type=5，平级，无子模块逻辑）
        tree: List[Dict[str, Any]] = []
        for svc in svc_rows_all:
            children = svc_map.get(int(svc.id), []) or []
            tree.extend([n for n in children if int(n.get("type") or 0) == 5])
        return tree

    @staticmethod
    def _doc_method_to_int(method: str) -> int:
        mapping = {
            "get": 1,
            "post": 2,
            "put": 3,
            "delete": 4,
            "patch": 5,
            "options": 6,
        }
        return mapping.get(str(method or "").lower(), 2)

    @staticmethod
    def _extract_schema_example(schema: Dict[str, Any]) -> Any:
        if not isinstance(schema, dict):
            return {}
        if "example" in schema:
            return schema.get("example")
        schema_type = str(schema.get("type") or "").lower()
        if schema_type == "object":
            props = schema.get("properties") or {}
            out: Dict[str, Any] = {}
            for k, v in props.items():
                out[k] = ApiAutomationService._extract_schema_example(v or {})
            return out
        if schema_type == "array":
            item_schema = schema.get("items") or {}
            return [ApiAutomationService._extract_schema_example(item_schema)]
        if schema_type in ("integer", "number"):
            return 0
        if schema_type == "boolean":
            return False
        return ""

    @staticmethod
    def _build_req_from_openapi(path: str, method: str, operation: Dict[str, Any]) -> Dict[str, Any]:
        params = []
        headers = []
        for p in (operation.get("parameters") or []):
            if not isinstance(p, dict):
                continue
            item = {"key": str(p.get("name") or ""), "value": "", "status": True}
            p_in = str(p.get("in") or "").lower()
            example = p.get("example")
            if example is None:
                example = ((p.get("schema") or {}).get("example"))
            item["value"] = "" if example is None else str(example)
            if not item["key"]:
                continue
            if p_in in ("header", "cookie"):
                headers.append(item)
            elif p_in in ("query", "path"):
                params.append(item)

        body_type = 1
        body: Any = {}
        request_body = operation.get("requestBody") or {}
        if isinstance(request_body, dict):
            content = request_body.get("content") or {}
            if "application/json" in content:
                body_type = 2
                json_info = content.get("application/json") or {}
                body = json_info.get("example")
                if body is None:
                    body = ApiAutomationService._extract_schema_example(json_info.get("schema") or {})
            elif "application/x-www-form-urlencoded" in content:
                body_type = 4
                form_schema = (content.get("application/x-www-form-urlencoded") or {}).get("schema") or {}
                body = ApiAutomationService._extract_schema_example(form_schema)
            elif "multipart/form-data" in content:
                body_type = 3
                multi_schema = (content.get("multipart/form-data") or {}).get("schema") or {}
                body = ApiAutomationService._extract_schema_example(multi_schema)

        return {
            "params_id": None,
            "body": body,
            "after": [],
            "assert": [],
            "before": [],
            "config": {"retry": 0, "req_timeout": 5, "res_timeout": 5},
            "header": headers,
            "method": ApiAutomationService._doc_method_to_int(method),
            "params": params,
            "body_type": body_type,
            "file_path": [],
            "form_data": [],
            "form_urlencoded": [],
            "url": path,
        }

    @staticmethod
    def _extract_apifox_param_rows(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            if not name:
                continue
            val_type = str(it.get("type") or "")
            required = "必填" if bool(it.get("required")) else "非必填"
            desc = str(it.get("description") or "")
            example = str(it.get("example") or "")
            rows.append({
                "key": name,
                "value": f"{val_type}; {required}; {desc}; {example}".strip("; ").strip(),
                "status": True,
            })
        return rows

    @staticmethod
    def _is_apifox_project_export(doc: Any) -> bool:
        if not isinstance(doc, dict):
            return False
        if doc.get("apifoxProject"):
            return True
        schema = doc.get("$schema")
        if isinstance(schema, dict) and str(schema.get("type") or "").lower() == "project":
            return True
        if isinstance(doc.get("apiCollection"), list) and doc.get("apiCollection"):
            return True
        return False

    @staticmethod
    def _normalize_doc_path(path: str) -> str:
        """
        规范化导入得到的请求地址：
        """
        path = str(path or "/").strip()
        if path.startswith("http://") or path.startswith("https://"):
            from urllib.parse import urlparse, urlunparse

            parsed = urlparse(path)
            clean_path = parsed.path or "/"
            while "//" in clean_path:
                clean_path = clean_path.replace("//", "/")
            return urlunparse((parsed.scheme, parsed.netloc, clean_path, "", parsed.query, ""))
        if not path.startswith("/"):
            path = "/" + path
        while "//" in path:
            path = path.replace("//", "/")
        return path or "/"

    @staticmethod
    def _extract_api_path_key(url: str) -> str:
        """
        提取用于去重比对的路径键
        """
        from urllib.parse import urlparse

        s = str(url or "").strip()
        if not s:
            return "/"
        if re.match(r"^https?://", s, flags=re.IGNORECASE):
            parsed = urlparse(s)
            s = parsed.path or "/"
        else:
            
            while True:
                m = re.match(r"^\{\{[^{}]+\}\}", s)
                if not m:
                    break
                s = s[m.end() :]
        s = (s or "").strip() or "/"
        if not s.startswith("/"):
            s = "/" + s
        while "//" in s:
            s = s.replace("//", "/")
        if len(s) > 1 and s.endswith("/"):
            s = s.rstrip("/")
        return s or "/"

    @staticmethod
    def _is_same_api_path(url_a: str, url_b: str) -> bool:
        """判断两条 URL"""
        a = ApiAutomationService._extract_api_path_key(url_a)
        b = ApiAutomationService._extract_api_path_key(url_b)
        if a == b:
            return True

        def _suffix_match(longer: str, shorter: str) -> bool:
            if not shorter or shorter == "/":
                return False
            if not longer.endswith(shorter):
                return False
            
            if shorter.startswith("/"):
                return True
            return len(longer) == len(shorter) or longer[-len(shorter) - 1] == "/"

        if len(a) >= len(b) and _suffix_match(a, b):
            return True
        if len(b) >= len(a) and _suffix_match(b, a):
            return True
        return False

    @staticmethod
    def _prefer_existing_url(existing_url: str, incoming_url: str) -> str:
        """去重"""
        existing_url = str(existing_url or "").strip()
        incoming_url = str(incoming_url or "").strip() or "/"
        if existing_url and ApiAutomationService._is_same_api_path(existing_url, incoming_url):
            return existing_url
        return incoming_url

    @staticmethod
    def _find_api_by_path_and_method(
        candidates: List[Any],
        path: str,
        method: int,
    ) -> Optional[Any]:
        """
        按路径键查找
        """
        exact: List[Any] = []
        fuzzy: List[Tuple[int, Any]] = []
        path_key = ApiAutomationService._extract_api_path_key(path)
        for row in candidates or []:
            row_req = row.req if isinstance(getattr(row, "req", None), dict) else {}
            row_method = int(row_req.get("method") or 2)
            if row_method != int(method):
                continue
            row_url = str(getattr(row, "url", None) or row_req.get("url") or "")
            if not ApiAutomationService._is_same_api_path(row_url, path):
                continue
            row_key = ApiAutomationService._extract_api_path_key(row_url)
            if row_key == path_key:
                exact.append(row)
            else:
                fuzzy.append((len(row_key), row))
        if exact:
            for row in exact:
                if str(getattr(row, "url", None) or "") == path:
                    return row
            return exact[0]
        if fuzzy:
            fuzzy.sort(key=lambda x: x[0], reverse=True)
            return fuzzy[0][1]
        return None

    @staticmethod
    def _build_req_from_apifox_api(
        api: Dict[str, Any],
        header_defaults: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        header_defaults = header_defaults or {}
        method_name = str(api.get("method") or "POST").lower()
        path = ApiAutomationService._normalize_doc_path(str(api.get("path") or api.get("url") or "/"))

        params_obj = api.get("parameters") if isinstance(api.get("parameters"), dict) else {}
        path_params = ApiAutomationService._extract_apifox_param_rows(params_obj.get("path") or [])
        query_params = ApiAutomationService._extract_apifox_param_rows(params_obj.get("query") or [])
        header_params = ApiAutomationService._extract_apifox_param_rows(params_obj.get("header") or [])

        if not header_params:
            common_headers = ((api.get("commonParameters") or {}).get("header") or []) if isinstance(api.get("commonParameters"), dict) else []
            for h in common_headers:
                if not isinstance(h, dict):
                    continue
                name = str(h.get("name") or "").strip()
                if not name:
                    continue
                header_params.append({
                    "key": name,
                    "value": str(header_defaults.get(name) or ""),
                    "status": True,
                })

        request_body = api.get("requestBody") if isinstance(api.get("requestBody"), dict) else {}
        req_type = str(request_body.get("type") or "").lower()
        body_type = 1
        body: Any = {}
        form_data: List[Dict[str, Any]] = []
        form_urlencoded: List[Dict[str, Any]] = []

        if req_type in ("application/json", "json"):
            body_type = 2
            body = request_body.get("jsonSchema") or request_body.get("example") or {}
            examples = request_body.get("examples") or []
            if (not body or body == {}) and examples and isinstance(examples[0], dict):
                raw = examples[0].get("value")
                if isinstance(raw, str) and raw.strip():
                    try:
                        body = json.loads(raw)
                    except Exception:
                        body = raw
                        body_type = 1
                elif raw is not None:
                    body = raw
        elif req_type in ("multipart/form-data",):
            body_type = 3
            for p in request_body.get("parameters") or []:
                if isinstance(p, dict) and p.get("name"):
                    form_data.append({
                        "key": str(p.get("name")),
                        "value": "" if p.get("example") is None else str(p.get("example")),
                        "status": bool(p.get("enable", True)),
                        "data_type": str(p.get("type") or ""),
                        "remark": str(p.get("description") or ""),
                    })
        elif req_type in ("application/x-www-form-urlencoded", "x-www-form-urlencoded"):
            body_type = 4
            for p in request_body.get("parameters") or []:
                if isinstance(p, dict) and p.get("name"):
                    form_urlencoded.append({
                        "key": str(p.get("name")),
                        "value": "" if p.get("example") is None else str(p.get("example")),
                        "status": bool(p.get("enable", True)),
                    })
        elif req_type in ("text/plain", "raw", "text"):
            examples = request_body.get("examples") or []
            raw_val: Any = None
            if examples and isinstance(examples[0], dict):
                raw_val = examples[0].get("value")
            if isinstance(raw_val, str) and raw_val.strip():
                try:
                    body = json.loads(raw_val)
                    body_type = 2
                except Exception:
                    body = raw_val
                    body_type = 1
            elif raw_val is not None:
                body = raw_val
                body_type = 1
            else:
                body = request_body.get("jsonSchema") or {}
                body_type = 2 if body else 1
        elif req_type in ("none", "", "null"):
            body_type = 1
            body = {}

        return {
            "params_id": None,
            "body": body,
            "after": [],
            "assert": [],
            "before": [],
            "config": {"retry": 0, "req_timeout": 5, "res_timeout": 5},
            "header": header_params or [{"key": None, "value": None, "status": True}],
            "method": ApiAutomationService._doc_method_to_int(method_name),
            "params": (path_params + query_params) or [{"key": None, "value": None, "status": True}],
            "body_type": body_type,
            "file_path": [],
            "form_data": form_data or [],
            "form_urlencoded": form_urlencoded or [],
            "url": path,
        }

    @staticmethod
    async def _import_apifox_project_export(
        db: AsyncSession,
        doc_json: Dict[str, Any],
        api_service_id: int,
        user_id: int,
    ) -> Dict[str, int]:
        """导入 Apifox 客户端"""
        collections = doc_json.get("apiCollection") or []
        if not isinstance(collections, list) or not collections:
            raise ValueError("Apifox 项目导出中未找到 apiCollection")

        header_defaults: Dict[str, str] = {}
        common = doc_json.get("commonParameters")
        if isinstance(common, dict):
            params = common.get("parameters") if isinstance(common.get("parameters"), dict) else {}
            for h in (params.get("header") or []):
                if isinstance(h, dict) and h.get("name"):
                    header_defaults[str(h["name"])] = str(h.get("defaultValue") or "")

        imported_count = 0
        updated_count = 0
        unchanged_count = 0
        folder_count = 0
        folder_unchanged_count = 0
        # 匹配范围限定目标目录子树：导入到模块时只与该目录下的接口比对（否则会误把服务下其他目录的接口算作修改）
        _sub_menu_ids = [int(target_pid)] if target_pid else []
        _frontier = [int(target_pid)] if target_pid else []
        while _frontier:
            _children = (
                await db.execute(
                    select(ApiMenuModel.id).where(
                        ApiMenuModel.enabled_flag == 1,
                        ApiMenuModel.api_service_id == api_service_id,
                        ApiMenuModel.pid.in_(_frontier),
                    )
                )
            ).scalars().all()
            _frontier = list(_children)
            _sub_menu_ids.extend(_frontier)
        _sub_api_rows = (
            await db.execute(
                select(ApiMenuModel.api_id).where(
                    ApiMenuModel.id.in_(_sub_menu_ids) if _sub_menu_ids else text("1=0"),
                    ApiMenuModel.api_id.isnot(None),
                )
            )
        ).scalars().all()
        _sub_api_ids = [int(r) for r in _sub_api_rows if r]
        existing_apis = list(
            (
                await db.execute(
                    select(ApiModel).where(
                        ApiModel.enabled_flag == 1,
                        ApiModel.created_by == user_id,
                        ApiModel.api_service_id == api_service_id,
                        ApiModel.id.in_(_sub_api_ids or [-1]),
                    )
                )
            ).scalars().all()
        )

        async def get_or_create_folder(name: str, pid: int) -> int:
            nonlocal folder_count, folder_unchanged_count
            key_name = (name or "").strip() or "默认分组"
            row = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.enabled_flag == 1,
                        ApiMenuModel.created_by == user_id,
                        ApiMenuModel.api_service_id == api_service_id,
                        ApiMenuModel.type == 1,
                        ApiMenuModel.pid == pid,
                        ApiMenuModel.name == key_name,
                    ).order_by(ApiMenuModel.id.asc()).limit(1)
                )
            ).scalars().first()
            if row:
                folder_unchanged_count += 1
                return int(row.id)
            menu = ApiMenuModel(
                name=key_name,
                type=1,
                pid=pid,
                api_service_id=api_service_id,
                status=1,
                api_id=None,
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(menu)
            await db.flush()
            folder_count += 1
            return int(menu.id)

        async def upsert_api(
            api_name: str,
            api_obj: Dict[str, Any],
            folder_id: int,
            inherited_pre: Optional[List[Any]] = None,
            inherited_post: Optional[List[Any]] = None,
        ) -> None:
            nonlocal imported_count, updated_count
            req = ApiAutomationService._build_req_from_apifox_api(api_obj, header_defaults)
            pre = ApiAutomationService._resolve_apifox_processors(
                api_obj.get("preProcessors"), inherited_pre
            )
            post = ApiAutomationService._resolve_apifox_processors(
                api_obj.get("postProcessors"), inherited_post
            )
            req["before"] = ApiAutomationService._map_apifox_processors(pre, phase="before")
            req["after"] = ApiAutomationService._map_apifox_processors(post, phase="after")
            path = str(req.get("url") or "/")
            api_desc = str(api_obj.get("description") or "")
            display_name = str(api_name or api_obj.get("name") or f"{str(api_obj.get('method') or 'POST').upper()} {path}")

            target_method = int(req.get("method") or 2)
            target_api = ApiAutomationService._find_api_by_path_and_method(
                existing_apis, path, target_method
            )

            if target_api:
                keep_url = ApiAutomationService._prefer_existing_url(
                    str(target_api.url or (target_api.req or {}).get("url") or ""),
                    path,
                )
                req["url"] = keep_url
                
                old_req = target_api.req if isinstance(target_api.req, dict) else {}
                if old_req.get("assert"):
                    req["assert"] = old_req.get("assert")
                if old_req.get("config"):
                    req["config"] = old_req.get("config")
                def _norm_req(r: Any) -> Any:
                    if isinstance(r, dict):
                        out = {}
                        for k, v in r.items():
                            if k in ('config', 'params_id'):
                                continue
                            nv = _norm_req(v)
                            if nv is None or nv == [] or nv == {}:
                                continue
                            out[k] = nv
                        return out
                    if isinstance(r, list):
                        return [_norm_req(i) for i in r if _norm_req(i) not in (None, [], {})]
                    return r
                _same = json.dumps(_norm_req(req), sort_keys=True, ensure_ascii=False) == json.dumps(_norm_req(old_req or {}), sort_keys=True, ensure_ascii=False)
                if _same:
                    api_id = int(target_api.id)
                    unchanged_count += 1
                else:
                    await db.execute(
                        update(ApiModel)
                        .where(ApiModel.id == target_api.id, ApiModel.enabled_flag == 1)
                        .values(
                            url=keep_url,
                            req=req,
                            document=api_obj,
                            name=display_name,
                            description=api_desc,
                            updated_by=user_id,
                        )
                    )
                    api_id = int(target_api.id)
                    updated_count += 1
            else:
                api_row = ApiModel(
                    api_service_id=api_service_id,
                    url=path,
                    req=req,
                    document=api_obj,
                    name=display_name,
                    description=api_desc,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(api_row)
                await db.flush()
                api_id = int(api_row.id)
                existing_apis.append(api_row)
                imported_count += 1

            leaf = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.enabled_flag == 1,
                        ApiMenuModel.created_by == user_id,
                        ApiMenuModel.api_service_id == api_service_id,
                        ApiMenuModel.type == 2,
                        ApiMenuModel.api_id == api_id,
                    )
                )
            ).scalar_one_or_none()

            if leaf:
                await db.execute(
                    update(ApiMenuModel)
                    .where(ApiMenuModel.id == leaf.id, ApiMenuModel.enabled_flag == 1)
                    .values(name=display_name, pid=folder_id, status=1, updated_by=user_id)
                )
            else:
                db.add(
                    ApiMenuModel(
                        name=display_name,
                        type=2,
                        pid=folder_id,
                        api_service_id=api_service_id,
                        api_id=api_id,
                        status=1,
                        created_by=user_id,
                        updated_by=user_id,
                    )
                )

        async def walk_items(
            items: Any,
            parent_folder_id: int,
            inherited_pre: Optional[List[Any]] = None,
            inherited_post: Optional[List[Any]] = None,
        ) -> None:
            if not isinstance(items, list):
                return
            inherited_pre = list(inherited_pre or [])
            inherited_post = list(inherited_post or [])
            for node in items:
                if not isinstance(node, dict):
                    continue
                api_obj = node.get("api")
                if isinstance(api_obj, dict) and (api_obj.get("path") or api_obj.get("url") or api_obj.get("method")):
                    await upsert_api(
                        str(node.get("name") or ""),
                        api_obj,
                        parent_folder_id,
                        inherited_pre=inherited_pre,
                        inherited_post=inherited_post,
                    )
                    continue
                # 目录节点
                child_items = node.get("items")
                if isinstance(child_items, list):
                    folder_name = str(node.get("name") or "默认分组")
                    next_pre = ApiAutomationService._resolve_apifox_processors(
                        node.get("preProcessors"), inherited_pre
                    )
                    next_post = ApiAutomationService._resolve_apifox_processors(
                        node.get("postProcessors"), inherited_post
                    )
                    
                    if folder_name.strip() in ("根目录", "Root", "root") and parent_folder_id == 0:
                        await walk_items(child_items, 0, next_pre, next_post)
                    else:
                        folder_id = await get_or_create_folder(folder_name, parent_folder_id)
                        await walk_items(child_items, folder_id, next_pre, next_post)

        for coll in collections:
            if not isinstance(coll, dict):
                continue
            name = str(coll.get("name") or "根目录")
            items = coll.get("items") or []
            coll_pre = ApiAutomationService._resolve_apifox_processors(coll.get("preProcessors"), [])
            coll_post = ApiAutomationService._resolve_apifox_processors(coll.get("postProcessors"), [])
            if name.strip() in ("根目录", "Root", "root"):
                await walk_items(items, 0, coll_pre, coll_post)
            else:
                folder_id = await get_or_create_folder(name, 0)
                await walk_items(items, folder_id, coll_pre, coll_post)

        if imported_count + updated_count <= 0:
            raise ValueError("Apifox 项目导出已识别，但未解析到可导入的 HTTP 接口（apiCollection.items[].api）")

        await db.execute(
            update(ApiServiceModel)
            .where(ApiServiceModel.id == api_service_id, ApiServiceModel.enabled_flag == 1)
            .values(last_pull_status=1)
        )
        await db.commit()
        return {"imported": imported_count, "updated": updated_count, "unchanged": unchanged_count, "folders": folder_count, "folders_unchanged": folder_unchanged_count}

    @staticmethod
    async def _pull_apifox_project_and_import(
        db: AsyncSession,
        api_service_id: int,
        project_id: str,
        auth_text: str,
        user_id: int,
    ) -> Dict[str, int]:
        auth_text = str(auth_text or "").strip()
        is_bearer = auth_text.lower().startswith("bearer ")
        base_headers = {
            "x-project-id": str(project_id),
            "x-client-version": "2.8.2-alpha.2",
            "accept": "application/json, text/plain, */*",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        if is_bearer:
            base_headers["authorization"] = auth_text

            base_headers["cookie"] = auth_text
        else:
            base_headers["cookie"] = auth_text

        def pull_data(url: str) -> Any:
            r = requests.get(url, headers=base_headers, timeout=30)
            ct = str(r.headers.get("Content-Type") or "").lower()
            text = (r.text or "").strip()
            if r.status_code >= 400:
                preview = text[:200] if text else "<empty>"
                raise ValueError(f"Apifox 请求失败（{url} HTTP {r.status_code}, Content-Type: {ct or 'unknown'}），响应片段: {preview}")
            try:
                data = r.json()
            except Exception:
                preview = text[:200] if text else "<empty>"
                raise ValueError(f"Apifox 返回非 JSON（{url} HTTP {r.status_code}, Content-Type: {ct or 'unknown'}），响应片段: {preview}")
            return data.get("data", data)

        tree_data = pull_data(f"https://api.apifox.com/api/v1/projects/{project_id}/api-tree-list?locale=zh-CN")
        detail_data = pull_data("https://api.apifox.com/api/v1/api-details?locale=zh-CN")

        detail_by_id: Dict[int, Dict[str, Any]] = {}
        for d in detail_data or []:
            if isinstance(d, dict) and d.get("id") is not None:
                detail_by_id[int(d["id"])] = d

        module_nodes = tree_data.get("children", []) if isinstance(tree_data, dict) else (tree_data or [])
        if (
            isinstance(module_nodes, list)
            and module_nodes
            and isinstance(module_nodes[0], dict)
            and "children" in module_nodes[0]
            and "api" not in module_nodes[0]
        ):
            module_nodes = module_nodes[0].get("children", [])

        folder_cache: Dict[str, int] = {}

        async def get_or_create_folder(folder_name: str) -> int:
            key = folder_name.strip() or "默认分组"
            if key in folder_cache:
                return folder_cache[key]
            row = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.enabled_flag == 1,
                        ApiMenuModel.created_by == user_id,
                        ApiMenuModel.api_service_id == api_service_id,
                        ApiMenuModel.type == 1,
                        ApiMenuModel.pid == 0,
                        ApiMenuModel.name == key,
                    )
                )
            ).scalars().first()
            if row:
                folder_cache[key] = int(row.id)
                return int(row.id)
            menu = ApiMenuModel(
                name=key,
                type=1,
                pid=0,
                api_service_id=api_service_id,
                status=1,
                api_id=None,
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(menu)
            await db.flush()
            folder_cache[key] = int(menu.id)
            return int(menu.id)

        imported_count = 0
        updated_count = 0
        unchanged_count = 0
        folder_names = set()
        existing_apis = list(
            (
                await db.execute(
                    select(ApiModel).where(
                        ApiModel.enabled_flag == 1,
                        ApiModel.created_by == user_id,
                        ApiModel.api_service_id == api_service_id,
                    )
                )
            ).scalars().all()
        )

        for module_data in module_nodes or []:
            if not isinstance(module_data, dict):
                continue
            folder_name = str(module_data.get("name") or "默认分组")
            folder_id = await get_or_create_folder(folder_name)
            folder_names.add(folder_name)

            for node in module_data.get("children", []) or []:
                if not isinstance(node, dict) or not isinstance(node.get("api"), dict):
                    continue
                api_brief = node.get("api") or {}
                ext_api_id = api_brief.get("id")
                detail = detail_by_id.get(int(ext_api_id)) if ext_api_id is not None else {}
                detail = detail or {}

                method_name = str(api_brief.get("method") or "POST").lower()
                path = ApiAutomationService._normalize_doc_path(
                    str(api_brief.get("path") or api_brief.get("url") or "/")
                )
                api_name = str(api_brief.get("name") or f"{method_name.upper()} {path}")
                api_desc = str(detail.get("description") or api_brief.get("description") or "")

                params_obj = detail.get("parameters") or {}
                path_params = ApiAutomationService._extract_apifox_param_rows(params_obj.get("path") or [])
                query_params = ApiAutomationService._extract_apifox_param_rows(params_obj.get("query") or [])
                header_params = ApiAutomationService._extract_apifox_param_rows(params_obj.get("header") or [])

                request_body = detail.get("requestBody") or {}
                req_type = str(request_body.get("type") or "")
                body_type = 1
                body: Any = {}
                form_data: List[Dict[str, Any]] = []
                if req_type == "application/json":
                    body_type = 2
                    body = request_body.get("jsonSchema") or {}
                elif req_type == "multipart/form-data":
                    body_type = 3
                    for p in request_body.get("parameters") or []:
                        if isinstance(p, dict) and p.get("name"):
                            form_data.append(
                                {
                                    "key": str(p.get("name")),
                                    "value": "",
                                    "status": True,
                                    "data_type": str(p.get("type") or ""),
                                    "remark": str(p.get("description") or ""),
                                }
                            )

                req = {
                    "params_id": None,
                    "body": body,
                    "after": [],
                    "assert": [],
                    "before": [],
                    "config": {"retry": 0, "req_timeout": 5, "res_timeout": 5},
                    "header": header_params or [{"key": None, "value": None, "status": True}],
                    "method": ApiAutomationService._doc_method_to_int(method_name),
                    "params": (path_params + query_params) or [{"key": None, "value": None, "status": True}],
                    "body_type": body_type,
                    "file_path": [],
                    "form_data": form_data or [],
                    "form_urlencoded": [],
                    "url": path,
                }

                target_method = int(req.get("method") or 2)
                target_api = ApiAutomationService._find_api_by_path_and_method(
                    existing_apis, path, target_method
                )

                if target_api:
                    keep_url = ApiAutomationService._prefer_existing_url(
                        str(target_api.url or (target_api.req or {}).get("url") or ""),
                        path,
                    )
                    req["url"] = keep_url
                    old_req = target_api.req if isinstance(target_api.req, dict) else {}
                    if old_req.get("assert"):
                        req["assert"] = old_req.get("assert")
                    if old_req.get("before"):
                        req["before"] = old_req.get("before")
                    if old_req.get("after"):
                        req["after"] = old_req.get("after")
                    if old_req.get("config"):
                        req["config"] = old_req.get("config")
                    await db.execute(
                        update(ApiModel)
                        .where(ApiModel.id == target_api.id, ApiModel.enabled_flag == 1)
                        .values(
                            url=keep_url,
                            req=req,
                            document=detail or api_brief,
                            name=api_name,
                            description=api_desc,
                            updated_by=user_id,
                        )
                    )
                    api_id = int(target_api.id)
                    updated_count += 1
                else:
                    api_row = ApiModel(
                        api_service_id=api_service_id,
                        url=path,
                        req=req,
                        document=detail or api_brief,
                        name=api_name,
                        description=api_desc,
                        created_by=user_id,
                        updated_by=user_id,
                    )
                    db.add(api_row)
                    await db.flush()
                    api_id = int(api_row.id)
                    existing_apis.append(api_row)
                    imported_count += 1

                leaf = (
                    await db.execute(
                        select(ApiMenuModel).where(
                            ApiMenuModel.enabled_flag == 1,
                            ApiMenuModel.created_by == user_id,
                            ApiMenuModel.api_service_id == api_service_id,
                            ApiMenuModel.type == 2,
                            ApiMenuModel.api_id == api_id,
                        ).order_by(ApiMenuModel.id.asc()).limit(1)
                    )
                ).scalar_one_or_none()

                if leaf:
                    await db.execute(
                        update(ApiMenuModel)
                        .where(ApiMenuModel.id == leaf.id, ApiMenuModel.enabled_flag == 1)
                        .values(name=api_name, pid=folder_id, status=1, updated_by=user_id)
                    )
                else:
                    db.add(
                        ApiMenuModel(
                            name=api_name,
                            type=2,
                            pid=folder_id,
                            api_service_id=api_service_id,
                            api_id=api_id,
                            status=1,
                            created_by=user_id,
                            updated_by=user_id,
                        )
                    )

        if imported_count + updated_count <= 0:
            auth_hint = "Bearer Token" if is_bearer else "Cookies"
            raise ValueError(
                f"Apifox 接口已请求成功但未解析到可导入接口，请检查项目权限和{auth_hint}是否有效（project_id={project_id}）"
            )

        await db.commit()
        return {"imported": imported_count, "updated": updated_count, "unchanged": unchanged_count, "folders": len(folder_names)}

    @staticmethod
    @staticmethod
    def _infer_schema_from_json(value):
        """示例 JSON -> JSON Schema 推断"""
        if value is None:
            return {"type": "null"}
        if isinstance(value, bool):
            return {"type": "boolean"}
        if isinstance(value, int):
            return {"type": "integer"}
        if isinstance(value, float):
            return {"type": "number"}
        if isinstance(value, str):
            return {"type": "string"}
        if isinstance(value, list):
            item = None
            for v in value[:10]:
                if v is not None:
                    item = ApiAutomationService._infer_schema_from_json(v)
                    break
            return {"type": "array", "items": item or {"type": "string"}}
        if isinstance(value, dict):
            props = {}
            required = []
            for k, v in value.items():
                props[k] = ApiAutomationService._infer_schema_from_json(v)
                if v is not None:
                    required.append(k)
            out = {"type": "object", "properties": props}
            if required:
                out["required"] = required
            return out
        return {"type": "string"}

    @staticmethod
    async def list_data_models(db: AsyncSession, api_service_id: int, user_id: int) -> List[Dict[str, Any]]:
        """数据模型列表（含 schema）"""
        stmt = select(ApiDataModel).where(
            ApiDataModel.enabled_flag == 1,
            ApiDataModel.api_service_id == int(api_service_id),
        )
        rows = (await db.execute(stmt)).scalars().all()
        data = []
        for m in rows:
            d = m.__dict__.copy()
            d.pop("_sa_instance_state", None)
            data.append(d)
        return data

    @staticmethod
    async def save_data_model(db: AsyncSession, api_service_id: int, user_id: int, model_id: int = 0,
                              name: str = "", schema: Any = None, pid: int = 0) -> Dict[str, Any]:
        """新建/更新数据模型（同步维护 type=4 菜单节点）"""
        name = str(name or "").strip() or "未命名模型"
        if model_id:
            row = (
                await db.execute(
                    select(ApiDataModel).where(
                        ApiDataModel.id == int(model_id),
                        ApiDataModel.enabled_flag == 1,
                    )
                )
            ).scalar_one_or_none()
            if not row:
                raise ValueError("数据模型不存在")
            row.name = name
            if schema is not None:
                row.schema = schema
            row.updated_by = user_id
            await db.flush()
            if row.menu_id:
                menu = (
                    await db.execute(select(ApiMenuModel).where(ApiMenuModel.id == row.menu_id))
                ).scalar_one_or_none()
                if menu:
                    menu.name = name
                    await db.flush()
            await db.commit()
            return {"id": row.id, "name": row.name}
        # 新建：ApiDataModel + type=4 菜单节点
        model = ApiDataModel(
            name=name,
            schema=schema if schema is not None else {"type": "object", "properties": {}},
            api_service_id=int(api_service_id),
            pid=int(pid or 0),
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(model)
        await db.flush()
        menu = ApiMenuModel(
            name=name,
            type=4,
            api_id=None,
            api_service_id=int(api_service_id),
            pid=int(pid or 0),
            status=1,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(menu)
        await db.flush()
        model.menu_id = menu.id
        await db.commit()
        return {"id": model.id, "name": model.name}

    @staticmethod
    async def delete_data_model(db: AsyncSession, user_id: int, model_id: int) -> None:
        """删除数据模型（软删 + 菜单节点软删）"""
        row = (
            await db.execute(
                select(ApiDataModel).where(
                    ApiDataModel.id == int(model_id),
                    ApiDataModel.enabled_flag == 1,
                )
            )
        ).scalar_one_or_none()
        if not row:
            return
        if row.menu_id:
            await db.execute(delete(ApiMenuModel).where(ApiMenuModel.id == row.menu_id))
        await db.execute(delete(ApiDataModel).where(ApiDataModel.id == row.id))
        await db.commit()

    @staticmethod
    async def import_data_model_json(db: AsyncSession, api_service_id: int, user_id: int,
                                     name: str, json_text: str, pid: int = 0) -> Dict[str, Any]:
        """粘贴 JSON 示例 -> 推断 JSON Schema -> 新建数据模型"""
        import json as _json
        raw = str(json_text or "").strip()
        if not raw:
            raise ValueError("JSON 内容不能为空")
        try:
            value = _json.loads(raw)
        except Exception as e:
            raise ValueError(f"JSON 解析失败：{e}")
        schema = ApiAutomationService._infer_schema_from_json(value)
        return await ApiAutomationService.save_data_model(
            db, api_service_id, user_id, 0, name, schema, int(pid or 0)
        )

    @staticmethod
    async def _import_data_models(
        db: AsyncSession,
        doc_json: Any,
        api_service_id: int,
        user_id: int,
        model_match_mode: str = "overwrite",
        model_pid: int = 0,
    ) -> int:
        """导入 OpenAPI components/schemas 为数据模型（含冲突策略）"""
        if not isinstance(doc_json, dict):
            return 0
        comp = doc_json.get("components") or {}
        schemas = comp.get("schemas") if isinstance(comp, dict) else None
        if not isinstance(schemas, dict) or not schemas:
            return 0
        # 目标目录：指定或服务根下的「数据模型」目录
        target_pid = model_pid
        if not target_pid:
            dm_dir = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.api_service_id == int(api_service_id),
                        ApiMenuModel.pid == 0,
                        ApiMenuModel.enabled_flag == 1,
                        ApiMenuModel.type == 1,
                        ApiMenuModel.name == "数据模型",
                    )
                )
            ).scalars().first()
            if dm_dir is None:
                dm_dir = ApiMenuModel(
                    name="数据模型",
                    type=1,
                    api_id=None,
                    api_service_id=int(api_service_id),
                    pid=0,
                    status=1,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(dm_dir)
                await db.flush()
            target_pid = int(dm_dir.id)
        imported = 0
        unchanged = 0
        for name, schema in schemas.items():
            if not isinstance(schema, dict):
                continue
            existing = (
                await db.execute(
                    select(ApiDataModel).where(
                        ApiDataModel.api_service_id == int(api_service_id),
                        ApiDataModel.enabled_flag == 1,
                        ApiDataModel.name == str(name),
                    )
                )
            ).scalars().first()
            if existing is not None:
                if model_match_mode == "skip":
                    continue
                if json.dumps(existing.schema or {}, sort_keys=True, ensure_ascii=False) == json.dumps(schema or {}, sort_keys=True, ensure_ascii=False):
                    unchanged += 1
                    continue
                if model_match_mode != "smart_merge":
                    existing.schema = schema
                    existing.updated_by = user_id
                imported += 1
                continue
            model = ApiDataModel(
                name=str(name),
                schema=schema,
                api_service_id=int(api_service_id),
                pid=target_pid,
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(model)
            await db.flush()
            # 菜单节点（type=4 数据模型）
            menu = ApiMenuModel(
                name=str(name),
                pid=target_pid,
                type=4,
                api_service_id=int(api_service_id),
                status=1,
                api_id=None,
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(menu)
            await db.flush()
            model.menu_id = int(menu.id)
            imported += 1
        await db.commit()
        return imported, unchanged

    @staticmethod
    def _apply_openapi_auth(req: Dict[str, Any], scheme: Dict[str, Any]) -> None:
        """OpenAPI Security Scheme -> 平台 Auth 配置映射"""
        if not isinstance(scheme, dict):
            return
        stype = str(scheme.get("type") or "").lower()
        if stype == "apikey":
            req["auth_type"] = "api_key"
            req["auth_key"] = str(scheme.get("name") or "")
            req["auth_in"] = str(scheme.get("in") or "header")
            req["auth_value"] = ""
        elif stype == "http":
            s = str(scheme.get("scheme") or "").lower()
            if s == "basic":
                req["auth_type"] = "basic"
                req["auth_username"] = ""
                req["auth_password"] = ""
            else:
                req["auth_type"] = "bearer"
                req["auth_token"] = ""
        elif stype == "oauth2":
            req["auth_type"] = "oauth2"
            req["auth_oauth_access_token"] = ""
            req["auth_oauth_token_url"] = str((scheme.get("flows") or {}).get("clientCredentials", {}).get("tokenUrl") or "")
        else:
            req["auth_type"] = "none"

    @staticmethod
    def _preview_doc(doc: Any) -> List[Dict[str, Any]]:
        """提取文档接口清单（预览用，不写库）"""
        out: List[Dict[str, Any]] = []
        if not isinstance(doc, dict):
            return out
        paths = doc.get("paths")
        if isinstance(paths, dict):
            for p, methods in paths.items():
                if not isinstance(methods, dict):
                    continue
                for m, op in methods.items():
                    if str(m).lower() in ("get", "post", "put", "delete", "patch", "head", "options"):
                        opd = op if isinstance(op, dict) else {}
                        name = str(opd.get("summary") or opd.get("operationId") or f"{m.upper()} {p}")
                        out.append({"name": name, "method": str(m).upper(), "url": str(p), "key": f"{str(m).upper()} {p}"})
        items = doc.get("item")
        if isinstance(items, list):
            def walk(its):
                for it in its or []:
                    if not isinstance(it, dict):
                        continue
                    if "request" in it:
                        req = it.get("request") or {}
                        u = req.get("url") if isinstance(req, dict) else None
                        raw = u.get("raw") if isinstance(u, dict) else (u or "")
                        mm = str((req.get("method") if isinstance(req, dict) else "") or "GET").upper()
                        out.append({"name": str(it.get("name") or f"{mm} {raw}"), "method": mm, "url": str(raw or ""), "key": f"{mm} {raw}"})
                    else:
                        walk(it.get("item"))
            walk(items)
        apis = doc.get("apis")
        if isinstance(apis, list):
            for a in apis:
                if isinstance(a, dict):
                    p = str(a.get("path") or "")
                    mm = str(a.get("method") or "GET").upper()
                    out.append({"name": str(a.get("name") or f"{mm} {p}"), "method": mm, "url": p, "key": f"{mm} {p}"})
        return out

    @staticmethod
    def _filter_doc_by_selected(doc: Any, selected: List[str]) -> Any:
        """按 selected（"METHOD path"）过滤文档，仅保留选中的接口"""
        if not selected:
            return doc
        sel = set(selected)
        if not isinstance(doc, dict):
            return doc
        paths = doc.get("paths")
        if isinstance(paths, dict):
            new_paths = {}
            for p, methods in paths.items():
                if not isinstance(methods, dict):
                    continue
                nm = {}
                for m, op in methods.items():
                    if f"{str(m).upper()} {p}" in sel or f"{str(m).lower()} {p}" in sel:
                        nm[m] = op
                if nm:
                    new_paths[p] = nm
            doc["paths"] = new_paths
        items = doc.get("item")
        if isinstance(items, list):
            def walk(its):
                kept = []
                for it in its or []:
                    if not isinstance(it, dict):
                        continue
                    if "request" in it:
                        req = it.get("request") or {}
                        u = req.get("url") if isinstance(req, dict) else None
                        raw = u.get("raw") if isinstance(u, dict) else (u or "")
                        mm = str((req.get("method") if isinstance(req, dict) else "") or "GET").upper()
                        if f"{mm} {raw}" in sel:
                            kept.append(it)
                    else:
                        sub = walk(it.get("item"))
                        if sub:
                            kept.append({**it, "item": sub})
                return kept
            doc["item"] = walk(items)
        return doc

    @staticmethod
    async def _import_postman_collection(
        db: AsyncSession, doc: Dict[str, Any], api_service_id: int, user_id: int, target_pid: int = 0
    ) -> tuple:
        """导入 Postman Collection v2.1：item 递归，folder->目录，request->接口"""
        imported = 0
        folders = 0
        api_ids: List[int] = []

        def _status(disabled: Any) -> bool:
            return not bool(disabled)

        async def walk(items: Any, pid: int) -> None:
            nonlocal imported, folders
            for it in items or []:
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name") or "未命名")
                request = it.get("request")
                if isinstance(request, dict):
                    method = ApiAutomationService._doc_method_to_int(request.get("method"))
                    url_obj = request.get("url")
                    raw_url = ""
                    params: list = []
                    if isinstance(url_obj, dict):
                        raw_url = str(url_obj.get("raw") or "")
                        for q in url_obj.get("query") or []:
                            if isinstance(q, dict):
                                params.append({
                                    "key": str(q.get("key") or ""),
                                    "value": str(q.get("value") or ""),
                                    "status": _status(q.get("disabled")),
                                })
                        if not raw_url:
                            host = url_obj.get("host") or []
                            path = url_obj.get("path") or []
                            raw_url = "/".join(str(x) for x in host) + "/" + "/".join(str(x) for x in path)
                    elif isinstance(url_obj, str):
                        raw_url = url_obj
                    headers: list = []
                    for h in request.get("header") or []:
                        if isinstance(h, dict):
                            headers.append({
                                "key": str(h.get("key") or ""),
                                "value": str(h.get("value") or ""),
                                "status": _status(h.get("disabled")),
                            })
                    body = request.get("body") or {}
                    mode = body.get("mode") if isinstance(body, dict) else None
                    body_type = 2
                    body_val: Any = {}
                    form_data: list = []
                    form_urlencoded: list = []
                    if mode == "raw":
                        raw_text = str(body.get("raw") or "")
                        ct = ""
                        for h in headers:
                            if str(h.get("key") or "").lower() == "content-type":
                                ct = str(h.get("value") or "").lower()
                        if "json" in ct:
                            body_type = 2
                            try:
                                body_val = json.loads(raw_text)
                            except Exception:
                                body_val = raw_text
                        elif "xml" in ct:
                            body_type = 4
                            body_val = raw_text
                        elif raw_text:
                            try:
                                body_val = json.loads(raw_text)
                            except Exception:
                                body_val = raw_text
                    elif mode == "formdata":
                        body_type = 3
                        for fd in body.get("formdata") or []:
                            if isinstance(fd, dict):
                                form_data.append({
                                    "key": str(fd.get("key") or ""),
                                    "value": str(fd.get("value") or ""),
                                    "status": _status(fd.get("disabled")),
                                    "type": "file" if fd.get("type") == "file" else "text",
                                })
                    elif mode == "urlencoded":
                        body_type = 4
                        for fd in body.get("urlencoded") or []:
                            if isinstance(fd, dict):
                                form_urlencoded.append({
                                    "key": str(fd.get("key") or ""),
                                    "value": str(fd.get("value") or ""),
                                    "status": _status(fd.get("disabled")),
                                })
                    req: Dict[str, Any] = {
                        "params_id": None,
                        "body": body_val,
                        "after": [],
                        "assert": [],
                        "before": [],
                        "config": {"retry": 0, "req_timeout": 5, "res_timeout": 5},
                        "header": headers or [{"key": "Content-Type", "value": "application/json", "status": True}],
                        "method": method,
                        "params": params,
                        "body_type": body_type,
                        "file_path": [],
                        "form_data": form_data,
                        "form_urlencoded": form_urlencoded,
                        "protocol": "http",
                    }
                    api = ApiModel(
                        api_service_id=api_service_id,
                        url=raw_url or "/",
                        document={},
                        req=req,
                        name=name,
                        created_by=user_id,
                        updated_by=user_id,
                    )
                    db.add(api)
                    await db.flush()
                    db.add(ApiMenuModel(
                        name=name, pid=pid, type=2, api_service_id=api_service_id,
                        status=1, api_id=api.id, created_by=user_id, updated_by=user_id,
                    ))
                    api_ids.append(int(api.id))
                    imported += 1
                else:
                    menu = ApiMenuModel(
                        name=name, pid=pid, type=1, api_service_id=api_service_id,
                        status=1, api_id=None, created_by=user_id, updated_by=user_id,
                    )
                    db.add(menu)
                    await db.flush()
                    folders += 1
                    await walk(it.get("item") or [], int(menu.id))

        if target_pid:
            root_pid = target_pid
        else:
            root = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.api_service_id == api_service_id,
                        ApiMenuModel.pid == 0,
                        ApiMenuModel.enabled_flag == 1,
                    )
                )
            ).scalars().first()
            root_pid = int(root.id) if root else 0
        await walk(doc.get("item") or [], root_pid)
        await db.commit()
        return imported, folders, api_ids

    async def pull_api_doc(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        api_service_id = int(body.get("api_service_id") or 0)
        doc_url = str(body.get("doc_url") or "").strip()
        source_type = str(body.get("source_type") or "swagger").strip().lower()
        doc_content = body.get("doc_content")
        cookies = str(body.get("cookies") or "").strip()
        create_module = bool(body.get("create_module"))
        module_name = str(body.get("module_name") or "").strip()
        if create_module:
            if not module_name:
                raise ValueError("创建新模块需要填写模块名称")
            svc = ApiServiceModel(
                name=module_name,
                api_project_id=int(body.get("api_project_id") or 0),
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(svc)
            await db.flush()
            await ApiAutomationService._ensure_service_root_menu(db, svc.id, user_id, "接口")
            await ApiAutomationService._sync_env_front_urls(db, [f"svc_{svc.id}"])
            api_service_id = int(svc.id)
        basic_auth = body.get("basic_auth") if isinstance(body.get("basic_auth"), dict) else None
        auth_tuple = None
        if basic_auth and basic_auth.get("username"):
            auth_tuple = (str(basic_auth.get("username")), str(basic_auth.get("password") or ""))

        if not api_service_id:
            raise ValueError("api_service_id 不能为空")
        if not doc_url and not doc_content:
            raise ValueError("文档地址或文档内容至少提供一个")
        # 文件导入支持 YAML 文本：字符串内容统一 yaml 解析（YAML 为 JSON 超集）
        if isinstance(doc_content, str) and doc_content.strip():
            text = doc_content.lstrip("\ufeff").strip()  # 兼容 UTF-8 BOM
            parsed = None
            parse_err = ""
            try:
                parsed = yaml.safe_load(text)
            except Exception as e:  # noqa: BLE001
                parse_err = str(e)[:120]
                try:
                    parsed = json.loads(text)  # 非标准 YAML 的 JSON 回退
                except Exception as e2:  # noqa: BLE001
                    parse_err = f"{parse_err} / json: {str(e2)[:120]}"
            if parsed is None and not parse_err and text.lower() in ("null", "none"):
                raise ValueError("文档内容为空")
            if isinstance(parsed, dict):
                doc_content = parsed
            else:
                raise ValueError(f"文档内容根节点必须是对象（解析详情：{parse_err or '结构为空'}）")
        if source_type not in ("swagger", "apifox", "postman"):
            raise ValueError("source_type 仅支持 swagger / apifox / postman")
        if source_type == "postman" and doc_url:
            raise ValueError("Postman 仅支持文件导入（Collection v2.1 JSON），不支持 URL 导入")

        service = (
            await db.execute(
                select(ApiServiceModel).where(
                    ApiServiceModel.id == api_service_id,
                    ApiServiceModel.enabled_flag == 1,
                    ApiServiceModel.created_by == user_id,
                )
            )
        ).scalar_one_or_none()
        if not service:
            raise ValueError("服务不存在或无权限")

        apifox_project_pull_error: Optional[str] = None
       
        if source_type == "apifox" and "app.apifox.com/project/" in doc_url:
            project_id = ""
            try:
                project_id = doc_url.split("/project/")[1].split("?")[0].split("/")[0].strip()
            except Exception:
                project_id = ""
            if project_id and cookies:
                try:
                    stats = await ApiAutomationService._pull_apifox_project_and_import(
                        db=db,
                        api_service_id=api_service_id,
                        project_id=project_id,
                        cookies=cookies,
                        user_id=user_id,
                    )
                    return {
                        "source_type": source_type,
                        "imported": int(stats.get("imported") or 0),
                        "updated": int(stats.get("updated") or 0),
                        "folders": int(stats.get("folders") or 0),
                        "mode": "apifox_project_url",
                    }
                except Exception as e:
      
                    apifox_project_pull_error = str(e)

        if isinstance(doc_content, dict):
            doc_json = doc_content
        else:
            try:
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Referer": doc_url,
                    "Origin": "https://app.apifox.com",
                }
                if source_type == "apifox" and cookies:
                    headers["Cookie"] = cookies

                def try_parse_json_response(resp_obj: requests.Response) -> Optional[Dict[str, Any]]:
                    ct = str(resp_obj.headers.get("Content-Type") or "").lower()
                    text_body = resp_obj.text or ""
                    if "application/json" in ct:
                        try:
                            return resp_obj.json()
                        except Exception:
                            return None
                    stripped_text = text_body.strip()
                    if stripped_text.startswith("{") or stripped_text.startswith("["):
                        try:
                            parsed = json.loads(stripped_text)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            return None
                    return None

                def try_parse_markdown_openapi(text_body: str) -> Optional[Dict[str, Any]]:
                    """
                    Apifox 文档页 / 导出页返回 markdown：
                    - Markdown 中包含 ```yaml ...``` 或 ```yml ...``` 的 OpenAPI 内容
                    """
                    import re

                    if not text_body:
                        return None
                    m = re.search(r"```(?:yaml|yml)\s*([\s\S]*?)```", text_body, flags=re.IGNORECASE)
                    if not m:
                        return None
                    yaml_text = (m.group(1) or "").strip()
                    if not yaml_text:
                        return None
                    try:
                        parsed = yaml.safe_load(yaml_text)
                        return parsed if isinstance(parsed, dict) else None
                    except Exception:
                        return None

                loop = asyncio.get_running_loop()
                resp = await loop.run_in_executor(
                    None, lambda: requests.get(doc_url, headers=headers, timeout=20, auth=auth_tuple)
                )
                resp.raise_for_status()
                parsed_json = try_parse_json_response(resp)
                if parsed_json is not None:
                    doc_json = parsed_json
                else:
                    text = (resp.text or "").strip()
                    md_parsed = try_parse_markdown_openapi(text)
                    if isinstance(md_parsed, dict) and (md_parsed.get("paths") or md_parsed.get("openapi") or md_parsed.get("swagger")):
                        doc_json = md_parsed
                    else:
                     
                        if source_type == "apifox" and "app.apifox.com/project/" in doc_url:
                            import re
                            m = re.search(r"/project/(\d+)", doc_url)
                            project_id = m.group(1) if m else ""
                            candidates: List[str] = []
                            if project_id:
                                candidates.extend([
                                    f"https://api.apifox.com/api/v1/projects/{project_id}/export-openapi",
                                    f"https://api.apifox.com/api/v1/projects/{project_id}/openapi",
                                    f"https://app.apifox.com/api/v1/projects/{project_id}/export-openapi",
                                    f"https://app.apifox.com/api/v1/projects/{project_id}/openapi",
                                ])
                            for c in candidates:
                                try:
                                    rr = await loop.run_in_executor(
                                        None, lambda: requests.get(c, headers=headers, timeout=20)
                                    )
                                    if rr.status_code >= 400:
                                        continue
                                    cand_json = try_parse_json_response(rr)
                                    if isinstance(cand_json, dict):
                                        if cand_json.get("paths") or cand_json.get("apis") or (cand_json.get("data") or {}).get("paths") or (cand_json.get("data") or {}).get("apis"):
                                            doc_json = cand_json
                                            break
                                except Exception:
                                    continue
                            else:
                                preview = text[:200] if text else "<empty>"
                                raise ValueError(
                                    "当前项目地址返回 HTML，且自动探测 JSON 导出接口失败。"
                                    f"请确认 Cookies 可用，或填写可直接返回 JSON 的导出地址。响应片段: {preview}"
                                )
                        else:
                            content_type = str(resp.headers.get("Content-Type") or "").lower()
                            preview = text[:200] if text else "<empty>"
                            if source_type == "apifox" and "app.apifox.com/project/" in doc_url:
                          
                                extra = f"；Apifox 专用拉取错误: {apifox_project_pull_error}" if apifox_project_pull_error else ""
                                raise ValueError(
                                    "Apifox 项目页返回的是 Markdown 页面而非 OpenAPI 文档。"
                                    f"{extra}；响应片段: {preview}"
                                )
                            raise ValueError(
                                f"返回内容不是 JSON（HTTP {resp.status_code}, Content-Type: {content_type or 'unknown'}），响应片段: {preview}"
                            )
            except Exception as e:
                raise ValueError(f"拉取文档失败: {str(e)}")

        
        if ApiAutomationService._is_apifox_project_export(doc_json):
            stats = await ApiAutomationService._import_apifox_project_export(
                db, doc_json, api_service_id, user_id
            )
            return {
                "source_type": source_type or "apifox",
                "imported": int(stats.get("imported") or 0),
                "updated": int(stats.get("updated") or 0),
                "folders": int(stats.get("folders") or 0),
                "mode": "apifox_project_export",
            }

        # 兼容多种文档结构：
        paths: Dict[str, Any] = {}
        selected = body.get("selected")
        if isinstance(selected, list) and selected:
            doc_json = ApiAutomationService._filter_doc_by_selected(doc_json, selected)
        # 数据格式校验（对齐 Apifox「数据格式错误」）
        if isinstance(doc_json, dict):
            if source_type == "swagger":
                _has_ver = isinstance(doc_json.get("openapi"), str) or isinstance(doc_json.get("swagger"), str)
                _has_paths = isinstance(doc_json.get("paths"), dict)
                if not (_has_ver and _has_paths):
                    raise ValueError(
                        "数据格式错误：当前内容可以读取，但未识别到 OpenAPI/Swagger 文档所需的结构。"
                        "请确认文件中包含 openapi 或 swagger、paths 等字段。"
                    )
            elif source_type == "postman":
                _has_item = isinstance(doc_json.get("item"), list) or isinstance((doc_json.get("info") or {}).get("schema"), str)
                if not _has_item:
                    raise ValueError(
                        "数据格式错误：当前内容可以读取，但未识别到 Postman Collection 所需的结构。"
                        "请确认文件中包含 info 与 item 字段（Collection v2.1）。"
                    )
            elif source_type == "apifox":
                if not (ApiAutomationService._is_apifox_project_export(doc_json) or isinstance(doc_json.get("paths"), dict)):
                    raise ValueError(
                        "数据格式错误：当前内容可以读取，但未识别到 Apifox 导出文档所需的结构。"
                        "请确认文件中包含 openapi、paths 或 Apifox 项目导出字段。"
                    )
        if body.get("preview"):
            return {"preview": ApiAutomationService._preview_doc(doc_json), "mode": "preview"}

        target_pid = int(body.get("pid") or 0)
        # pid 是模块节点（type=5）时，转换为该模块的「接口」子目录（默认导入到模块根目录）
        if target_pid:
            _pm = (
                await db.execute(
                    select(ApiMenuModel).where(ApiMenuModel.id == target_pid, ApiMenuModel.enabled_flag == 1)
                )
            ).scalar_one_or_none()
            if _pm is not None and int(_pm.type) == 5:
                _iface = (
                    await db.execute(
                        select(ApiMenuModel.id).where(
                            ApiMenuModel.pid == target_pid,
                            ApiMenuModel.enabled_flag == 1,
                            ApiMenuModel.type == 1,
                            ApiMenuModel.name == "接口",
                        ).order_by(ApiMenuModel.id.asc()).limit(1)
                    )
                ).scalars().first()
                if _iface:
                    target_pid = int(_iface)
        # pid=0 默认落到服务根目录（对齐 Apifox：导入默认进模块根目录）
        if not target_pid:
            _root_menu = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.api_service_id == api_service_id,
                        ApiMenuModel.enabled_flag == 1,
                        ApiMenuModel.pid == 0,
                        ApiMenuModel.type == 1,
                    ).order_by(ApiMenuModel.id.asc()).limit(1)
                )
            ).scalar_one_or_none()
            if _root_menu:
                target_pid = int(_root_menu.id)
        created_api_ids: List[int] = []
        gen_case = bool(body.get("gen_case"))
        match_mode = str(body.get("match_mode") or "overwrite")
        match_id_key = str(body.get("match_id_key") or "method_path")
        name_rule = str(body.get("name_rule") or "operation_id")
        import_info = bool(body.get("import_info"))
        update_location = bool(body.get("update_location"))
        import_models = bool(body.get("import_models") if body.get("import_models") is not None else True)
        model_match_mode = str(body.get("model_match_mode") or "overwrite")
        model_pid = int(body.get("model_pid") or 0)
        # model_pid 兜底：默认落到目标接口根所在模块的「数据模型」子目录
        if not model_pid and target_pid:
            _im = (
                await db.execute(
                    select(ApiMenuModel).where(ApiMenuModel.id == target_pid, ApiMenuModel.enabled_flag == 1)
                )
            ).scalar_one_or_none()
            if _im is not None and int(_im.type) == 1 and _im.name == "接口" and int(_im.pid or 0):
                _mdm = (
                    await db.execute(
                        select(ApiMenuModel.id).where(
                            ApiMenuModel.pid == int(_im.pid),
                            ApiMenuModel.enabled_flag == 1,
                            ApiMenuModel.type == 1,
                            ApiMenuModel.name == "数据模型",
                        ).order_by(ApiMenuModel.id.asc()).limit(1)
                    )
                ).scalars().first()
                if _mdm:
                    model_pid = int(_mdm)
        servers_to_env = bool(body.get("servers_to_env"))
        import_security = bool(body.get("import_security"))
        global_auth = bool(body.get("global_auth"))
        has_sec_strategy = str(body.get("has_sec_strategy") or "inherit")
        no_sec_strategy = str(body.get("no_sec_strategy") or "inherit")
        security_schemes: Dict[str, Any] = {}
        if isinstance(doc_json, dict):
            _comp = doc_json.get("components") or {}
            if isinstance(_comp, dict) and isinstance(_comp.get("securitySchemes"), dict):
                security_schemes = _comp.get("securitySchemes") or {}
        top_security: list = []
        if isinstance(doc_json, dict) and isinstance(doc_json.get("security"), list):
            top_security = doc_json.get("security") or []
        servers_url = ""
        if isinstance(doc_json, dict) and isinstance(doc_json.get("servers"), list) and doc_json.get("servers"):
            _s0 = doc_json.get("servers")[0]
            if isinstance(_s0, dict):
                servers_url = str(_s0.get("url") or "").strip()
        api_security_map: Dict[int, list] = {}

        candidates = [
            doc_json.get("paths"),
            (doc_json.get("data") or {}).get("paths") if isinstance(doc_json.get("data"), dict) else None,
            ((doc_json.get("data") or {}).get("openapi") or {}).get("paths")
            if isinstance(doc_json.get("data"), dict) and isinstance((doc_json.get("data") or {}).get("openapi"), dict)
            else None,
            (doc_json.get("openapi") or {}).get("paths") if isinstance(doc_json.get("openapi"), dict) else None,
        ]
        for c in candidates:
            if isinstance(c, dict) and c:
                paths = c
                break

        if not paths:
            if source_type == "postman" or (
                isinstance(doc_json, dict) and doc_json.get("info") and isinstance(doc_json.get("item"), list)
            ):
                imported, folders, postman_ids = await ApiAutomationService._import_postman_collection(
                    db, doc_json, api_service_id, user_id, target_pid
                )
                if gen_case and postman_ids:
                    await db.flush()
                    for _aid in postman_ids:
                        try:
                            _src = (
                                await db.execute(select(ApiModel).where(ApiModel.id == _aid, ApiModel.enabled_flag == 1))
                            ).scalar_one_or_none()
                            if _src:
                                await ApiAutomationService.save_api_case(
                                    db,
                                    {
                                        "id": _aid,
                                        "api_service_id": int(_src.api_service_id),
                                        "url": _src.url,
                                        "req": _src.req or {},
                                        "document": _src.document or {},
                                        "name": _src.name,
                                    },
                                    user_id,
                                )
                        except Exception:
                            pass
                return {
                    "source_type": source_type,
                    "imported": imported,
                    "updated": 0,
                    "folders": folders,
                    "mode": "postman",
                }
            apis = doc_json.get("apis")
            if not isinstance(apis, list):
                data = doc_json.get("data") or {}
                apis = data.get("apis") if isinstance(data, dict) else None
            if isinstance(apis, list) and apis:
                stats = await ApiAutomationService.handle_gitlab_import(db, apis, api_service_id, user_id)
                return {
                    "source_type": source_type,
                    "imported": int(stats.get("imported") or 0),
                    "updated": int(stats.get("updated") or 0),
                    "folders": int(stats.get("folders") or 0),
                    "mode": "apifox_apis",
                }
            
            top_keys = list(doc_json.keys()) if isinstance(doc_json, dict) else []
            data_keys = list((doc_json.get("data") or {}).keys()) if isinstance(doc_json, dict) and isinstance(doc_json.get("data"), dict) else []
            raise ValueError(
                "文档中未找到可解析接口（paths/apis/apiCollection），请确认 URL、Cookies 或导出文件格式；"
                f"top_keys={top_keys[:20]}, data_keys={data_keys[:20]}"
            )

        folder_cache: Dict[str, int] = {}

        async def get_or_create_folder(folder_name: str) -> int:
            key = folder_name.strip() or "默认分组"
            if key in folder_cache:
                return folder_cache[key]
            row = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.enabled_flag == 1,
                        ApiMenuModel.created_by == user_id,
                        ApiMenuModel.api_service_id == api_service_id,
                        ApiMenuModel.type == 1,
                        ApiMenuModel.pid == target_pid,
                        ApiMenuModel.name == key,
                    )
                )
            ).scalar_one_or_none()
            if row:
                folder_cache[key] = int(row.id)
                return int(row.id)
            menu = ApiMenuModel(
                name=key,
                type=1,
                pid=target_pid,
                api_service_id=api_service_id,
                status=1,
                api_id=None,
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(menu)
            await db.flush()
            folder_cache[key] = int(menu.id)
            return int(menu.id)

        imported_count = 0
        updated_count = 0
        unchanged_count = 0
        folder_names = set()
        existing_apis = list(
            (
                await db.execute(
                    select(ApiModel).where(
                        ApiModel.enabled_flag == 1,
                        ApiModel.created_by == user_id,
                        ApiModel.api_service_id == api_service_id,
                    )
                )
            ).scalars().all()
        )

        for raw_path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            api_path = ApiAutomationService._normalize_doc_path(str(raw_path or "/"))

            for method in ("get", "post", "put", "delete", "patch", "options"):
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue

                tags = operation.get("tags") or []
                if tags:
                    folder_name = str(tags[0])
                    folder_id = await get_or_create_folder(folder_name)
                    folder_names.add(folder_name)
                else:
                    folder_id = target_pid

                req = ApiAutomationService._build_req_from_openapi(api_path, method, operation)
                if operation.get("summary"):
                    api_name = str(operation.get("summary"))
                elif name_rule == "path":
                    api_name = f"{method.upper()} {api_path}"
                elif name_rule == "description":
                    api_name = str(operation.get("description") or operation.get("operationId") or f"{method.upper()} {api_path}")
                else:
                    api_name = str(operation.get("operationId") or f"{method.upper()} {api_path}")
                api_desc = str(operation.get("description") or "")

                target_method = int(req.get("method") or 2)
                if match_id_key == "operation_id":
                    target_api = None
                    _op_id = str(operation.get("operationId") or "")
                    if _op_id:
                        for _ex in existing_apis:
                            _doc = _ex.document if isinstance(_ex.document, dict) else {}
                            if str(_doc.get("operationId") or "") == _op_id:
                                target_api = _ex
                                break
                else:
                    target_api = ApiAutomationService._find_api_by_path_and_method(
                        existing_apis, api_path, target_method
                    )
                # 不导入：已存在接口跳过
                if target_api is not None and match_mode == "skip":
                    continue

                if target_api:
                    keep_url = ApiAutomationService._prefer_existing_url(
                        str(target_api.url or (target_api.req or {}).get("url") or ""),
                        api_path,
                    )
                    req["url"] = keep_url
                    old_req = target_api.req if isinstance(target_api.req, dict) else {}
                    if old_req.get("assert"):
                        req["assert"] = old_req.get("assert")
                    if old_req.get("before"):
                        req["before"] = old_req.get("before")
                    if old_req.get("after"):
                        req["after"] = old_req.get("after")
                    if old_req.get("config"):
                        req["config"] = old_req.get("config")
                    _upd_values: Dict[str, Any] = {
                        "url": keep_url,
                        "req": req,
                        "updated_by": user_id,
                    }
                    if match_mode != "smart_merge":
                        # 智能合并：保留已修改的 Mock/中文名/说明/请求示例/响应示例等
                        _upd_values["document"] = operation
                        _upd_values["name"] = api_name
                        _upd_values["description"] = api_desc
                    await db.execute(
                        update(ApiModel)
                        .where(ApiModel.id == target_api.id, ApiModel.enabled_flag == 1)
                        .values(**_upd_values)
                    )
                    if update_location:
                        # 更新接口所在目录：把已存在接口的菜单移到导入目标目录
                        try:
                            _tgt_menu = (
                                await db.execute(
                                    select(ApiMenuModel).where(
                                        ApiMenuModel.api_id == int(target_api.id),
                                        ApiMenuModel.enabled_flag == 1,
                                    )
                                )
                            ).scalars().first()
                            if _tgt_menu is not None and folder_id:
                                await db.execute(
                                    update(ApiMenuModel)
                                    .where(ApiMenuModel.id == int(_tgt_menu.id))
                                    .values(pid=int(folder_id), updated_by=user_id)
                                )
                        except Exception:
                            pass
                    api_id = int(target_api.id)
                    updated_count += 1
                else:
                    api_row = ApiModel(
                        api_service_id=api_service_id,
                        url=api_path,
                        req=req,
                        document=operation,
                        name=api_name,
                        description=api_desc,
                        created_by=user_id,
                        updated_by=user_id,
                    )
                    db.add(api_row)
                    await db.flush()
                    api_id = int(api_row.id)
                    existing_apis.append(api_row)
                    imported_count += 1
                    created_api_ids.append(int(api_row.id))
                    _op_sec = operation.get("security")
                    if _op_sec is None:
                        _op_sec = top_security
                    api_security_map[int(api_row.id)] = _op_sec if isinstance(_op_sec, list) else []

                leaf = (
                    await db.execute(
                        select(ApiMenuModel).where(
                            ApiMenuModel.enabled_flag == 1,
                            ApiMenuModel.created_by == user_id,
                            ApiMenuModel.api_service_id == api_service_id,
                            ApiMenuModel.type == 2,
                            ApiMenuModel.api_id == api_id,
                        ).order_by(ApiMenuModel.id.asc()).limit(1)
                    )
                ).scalar_one_or_none()

                if leaf:
                    await db.execute(
                        update(ApiMenuModel)
                        .where(ApiMenuModel.id == leaf.id, ApiMenuModel.enabled_flag == 1)
                        .values(name=api_name, pid=folder_id, status=1, updated_by=user_id)
                    )
                else:
                    db.add(
                        ApiMenuModel(
                            name=api_name,
                            type=2,
                            pid=folder_id,
                            api_service_id=api_service_id,
                            api_id=api_id,
                            status=1,
                            created_by=user_id,
                            updated_by=user_id,
                        )
                    )

        # 更新拉取状态为成功
        await db.execute(
            update(ApiServiceModel)
            .where(ApiServiceModel.id == api_service_id, ApiServiceModel.enabled_flag == 1)
            .values(last_pull_status=1)
        )
        if gen_case and created_api_ids:
            await db.flush()
            for _aid in created_api_ids:
                try:
                    _src = (
                        await db.execute(select(ApiModel).where(ApiModel.id == _aid, ApiModel.enabled_flag == 1))
                    ).scalar_one_or_none()
                    if _src:
                        await ApiAutomationService.save_api_case(
                            db,
                            {
                                "id": _aid,
                                "api_service_id": int(_src.api_service_id),
                                "url": _src.url,
                                "req": _src.req or {},
                                "document": _src.document or {},
                                "name": _src.name,
                            },
                            user_id,
                        )
                except Exception:
                    pass

        # ---- 导入增强：Servers -> 环境前置 URL ----
        if servers_to_env and servers_url:
            try:
                envs = (
                    await db.execute(
                        select(ApiEnvironmentModel).where(ApiEnvironmentModel.enabled_flag == 1)
                    )
                ).scalars().all()
                _env_updates: List[tuple] = []
                for env in envs:
                    cfg = list(env.config or [])
                    for item in cfg:
                        if isinstance(item, dict) and str(item.get("name") or "").strip() == "__front_urls__":
                            try:
                                fu = json.loads(item.get("value") or "[]")
                            except Exception:
                                fu = []
                            if isinstance(fu, list):
                                for f in fu:
                                    if (
                                        str(f.get("menu_id") or "") == f"svc_{api_service_id}"
                                        and str(f.get("protocol") or "http") == "http"
                                        and not str(f.get("url") or "").strip()
                                    ):
                                        f["url"] = servers_url
                                item["value"] = json.dumps(fu, ensure_ascii=False)
                    _env_updates.append((int(env.id), cfg))
                for _eid, _cfg in _env_updates:
                    await db.execute(
                        update(ApiEnvironmentModel)
                        .where(ApiEnvironmentModel.id == _eid)
                        .values(config=_cfg, updated_by=0)
                    )
                await db.commit()
            except Exception:
                pass

        # ---- 导入增强：Security Scheme -> 接口 Auth（按策略）----
        if import_security and created_api_ids:
            await db.flush()
            for _aid in created_api_ids:
                try:
                    _src = (
                        await db.execute(select(ApiModel).where(ApiModel.id == _aid, ApiModel.enabled_flag == 1))
                    ).scalar_one_or_none()
                    if not _src or not isinstance(_src.req, dict):
                        continue
                    req = dict(_src.req)
                    _sec = api_security_map.get(int(_aid)) or []
                    _strategy = has_sec_strategy if _sec else no_sec_strategy
                    _scheme = None
                    for _s in _sec:
                        if isinstance(_s, dict):
                            for _k in _s:
                                if _k in security_schemes:
                                    _scheme = security_schemes[_k]
                                    break
                        if _scheme is not None:
                            break
                    if _strategy == "none":
                        req["auth_type"] = "none"
                    elif _strategy == "scheme" and _scheme is not None:
                        ApiAutomationService._apply_openapi_auth(req, _scheme)
                    elif _scheme is not None:
                        ApiAutomationService._apply_openapi_auth(req, _scheme)
                    await db.execute(
                        update(ApiModel).where(ApiModel.id == int(_aid), ApiModel.enabled_flag == 1).values(req=req)
                    )
                except Exception:
                    pass
            await db.commit()

        # ---- 导入增强：全局 Security -> 目录 Auth ----
        if global_auth and top_security:
            try:
                _dir_menu = None
                if target_pid:
                    _dir_menu = (
                        await db.execute(
                            select(ApiMenuModel).where(
                                ApiMenuModel.id == target_pid, ApiMenuModel.enabled_flag == 1
                            )
                        )
                    ).scalar_one_or_none()
                else:
                    _dir_menu = (
                        await db.execute(
                            select(ApiMenuModel).where(
                                ApiMenuModel.api_service_id == api_service_id,
                                ApiMenuModel.pid == 0,
                                ApiMenuModel.enabled_flag == 1,
                                ApiMenuModel.type == 1,
                            )
                        )
                    ).scalars().first()
                if _dir_menu is not None:
                    _cp = {}
                    try:
                        _cp = json.loads(_dir_menu.common_params) if isinstance(_dir_menu.common_params, str) and _dir_menu.common_params else {}
                    except Exception:
                        _cp = {}
                    if not isinstance(_cp, dict):
                        _cp = {}
                    _auth = {"strategy": no_sec_strategy}
                    for _s in top_security:
                        if isinstance(_s, dict):
                            for _k in _s:
                                if _k in security_schemes:
                                    _auth["scheme_key"] = _k
                                    _auth["scheme"] = security_schemes[_k]
                                    break
                        if "scheme" in _auth:
                            break
                    _cp["auth"] = _auth
                    await db.execute(
                        update(ApiMenuModel)
                        .where(ApiMenuModel.id == int(_dir_menu.id))
                        .values(common_params=json.dumps(_cp, ensure_ascii=False))
                    )
            except Exception:
                pass
            await db.commit()

        _model_count = 0
        if import_models:
            try:
                _model_count = await ApiAutomationService._import_data_models(
                    db, doc_json, api_service_id, user_id, model_match_mode, model_pid
                )
            except Exception:
                _model_count = 0
        if import_info:
            try:
                _info = doc_json.get("info") if isinstance(doc_json, dict) else None
                if isinstance(_info, dict):
                    _desc = str(_info.get("description") or _info.get("title") or "")
                    if _desc:
                        await db.execute(
                            update(ApiServiceModel)
                            .where(ApiServiceModel.id == int(api_service_id), ApiServiceModel.enabled_flag == 1)
                            .values(description=_desc, updated_by=user_id)
                        )
            except Exception:
                pass
        await db.commit()
        return {
            "source_type": source_type,
            "imported": imported_count,
            "updated": updated_count,
            "unchanged": unchanged_count,
            "folders": len(folder_names),
            "models": _model_count[0] if isinstance(_model_count, tuple) else _model_count,
            "models_unchanged": _model_count[1] if isinstance(_model_count, tuple) else 0,
        }

    @staticmethod
    @staticmethod
    async def _call_platform_llm(query: str, system_prompt: str = "", llm_config_id: Optional[int] = None) -> str:
        """使用平台 LLM 配置（LLM 配置管理页的模型）调用 LLM，返回文本"""
        from app.api.v1.Ntesterc_module.Ntesterc_ai.conversation.llm_service import get_llm_service, LLMMessage
        service = await get_llm_service(llm_config_id)
        messages = []
        if system_prompt:
            messages.append(LLMMessage("system", system_prompt))
        messages.append(LLMMessage("user", query))
        resp = await service.chat_completion(messages)
        return resp.content or ""

    @staticmethod
    async def generate_dir_doc(db: AsyncSession, menu_id: int, user_id: int, llm_config_id: Optional[int] = None) -> Dict[str, Any]:
        """遍历目录下所有接口，AI 两阶段生成 Markdown 接口文档（V1 优化版）"""
        import json as _json
        menu = (
            await db.execute(
                select(ApiMenuModel).where(ApiMenuModel.id == int(menu_id), ApiMenuModel.enabled_flag == 1)
            )
        ).scalar_one_or_none()
        if menu is None:
            raise ValueError("目录不存在")
        # 收集子树菜单 id
        ids = [int(menu_id)]
        frontier = [int(menu_id)]
        while frontier:
            children = (
                await db.execute(
                    select(ApiMenuModel.id).where(
                        ApiMenuModel.enabled_flag == 1,
                        ApiMenuModel.pid.in_(frontier),
                    )
                )
            ).scalars().all()
            frontier = list(children)
            ids.extend(frontier)
        api_menus = (
            await db.execute(
                select(ApiMenuModel).where(
                    ApiMenuModel.id.in_(ids),
                    ApiMenuModel.type == 2,
                    ApiMenuModel.enabled_flag == 1,
                )
            )
        ).scalars().all()
        # 收集完整接口数据（含 description/params/body/response）
        apis = []
        for am in api_menus:
            row = (
                await db.execute(select(ApiModel).where(ApiModel.id == int(am.api_id)))
            ).scalars().first() if am.api_id else None
            req = row.req if row and isinstance(row.req, dict) else {}
            desc = (req.get("description") or "").strip()
            apis.append({
                "name": am.name,
                "method": str((req.get("method") or "GET")).upper(),
                "url": row.url if row else (req.get("url") or ""),
                "description": str(desc),
                "params": req.get("params") or [],
                "body": req.get("body") or {},
                "headers": req.get("headers") or [],
                "response": req.get("response") or {},
            })
        if not apis:
            raise ValueError("该目录下暂无接口")
        api_json = _json.dumps(apis, ensure_ascii=False)
        SYSTEM_PROMPT = (
            "你是一个专业的 API 文档撰写助手。请严格遵守以下规则：\n"
            "1. API 的路径、Method、参数名、参数类型、必填性必须严格来自输入数据，不得修改或新增\n"
            "2. 不得虚构不存在的参数、业务规则、退款金额、到账时间等业务事实\n"
            "3. 可以对已有接口描述（description）进行语言润色和总结\n"
            "4. 可以根据接口名称和已有描述总结业务用途\n"
            "5. 接口定义中不存在的信息，不要自行推测或编造"
        )
        # 两阶段生成：接口 > 8 个时先摘要后文档；否则直接生成
        if len(apis) > 8:
            summary_prompt = (
                "请为以下接口列表生成业务摘要（JSON 数组格式，每个元素含 name/summary/business/input/output 字段），"
                "用业务语言总结每个接口的用途：\n"
                + api_json
            )
            summary = await ApiAutomationService._call_platform_llm(summary_prompt, SYSTEM_PROMPT, llm_config_id)
            doc_prompt = (
                "请根据以下目录信息、接口列表，生成完整的 Markdown 接口文档。\n"
                "结构要求：\n"
                "## 1. 概述（目录的业务说明）\n"
                "## 2. 接口总览（表格：名称 | 方法 | 路径 | 说明）\n"
                "## 3. 接口详情（每个接口一小节：接口说明、请求参数表格、请求体、请求示例、响应示例）\n"
                "直接输出 Markdown 正文，不要用代码围栏包裹整个文档。\n\n"
                f"目录名：{menu.name}\n"
                f"接口列表：\n{api_json}"
            )
            md = await ApiAutomationService._call_platform_llm(doc_prompt, SYSTEM_PROMPT, llm_config_id)
        else:
            doc_prompt = (
                "请根据以下目录信息、接口列表，生成完整的 Markdown 接口文档。\n"
                "结构要求：\n"
                "## 1. 概述（目录的业务说明）\n"
                "## 2. 接口总览（表格：名称 | 方法 | 路径 | 说明）\n"
                "## 3. 接口详情（每个接口一小节：接口说明、请求参数表格、请求体、请求示例、响应示例）\n"
                "直接输出 Markdown 正文，不要用代码围栏包裹整个文档。\n\n"
                f"目录名：{menu.name}\n"
                f"接口列表：\n{api_json}"
            )
            md = await ApiAutomationService._call_platform_llm(doc_prompt, SYSTEM_PROMPT, llm_config_id)
        if not md:
            raise ValueError("AI 生成失败：模型返回为空")
        cp = menu.common_params or {}
        if isinstance(cp, str):
            try:
                cp = _json.loads(cp)
            except Exception:
                cp = {}
        if not isinstance(cp, dict):
            cp = {}
        cp["document"] = {"title": menu.name, "content": md}
        await db.execute(
            update(ApiMenuModel)
            .where(ApiMenuModel.id == int(menu_id))
            .values(common_params=_json.dumps(cp, ensure_ascii=False), updated_by=user_id)
        )
        await db.commit()
        return {"title": menu.name, "content": md}

    @staticmethod
    async def _remove_env_front_url_protocol(db: AsyncSession, svc_id: int, protocol: str) -> None:
        """移除所有环境中该服务的指定协议前置 URL 行（删除 WS 接口时联动清理）。"""
        import json as _json
        mid = f"svc_{int(svc_id)}"
        protocol = str(protocol or "").lower()
        envs = (
            await db.execute(
                select(ApiEnvironmentModel).where(ApiEnvironmentModel.enabled_flag == 1)
            )
        ).scalars().all()
        for env in envs:
            cfg = list(env.config or [])
            for item in cfg:
                if isinstance(item, dict) and str(item.get("name") or "") == "__front_urls__":
                    try:
                        fu = _json.loads(item.get("value") or "[]")
                    except Exception:
                        fu = []
                    if not isinstance(fu, list):
                        fu = []
                    new_fu = [
                        f for f in fu
                        if not (str(f.get("menu_id") or "") == mid and str(f.get("protocol") or "http").lower() == protocol)
                    ]
                    if len(new_fu) != len(fu):
                        item["value"] = _json.dumps(new_fu)
                        await db.execute(
                            update(ApiEnvironmentModel)
                            .where(ApiEnvironmentModel.id == env.id)
                            .values(config=cfg)
                        )
        await db.commit()

    @staticmethod
    async def _sync_env_front_urls_for_protocol(db: AsyncSession, svc_id: int, protocol: str) -> None:
        """新建接口时联动：确保所有环境的 __front_urls__ 中存在该模块对应协议的前置 URL 行（url 空）。"""
        import json as _json
        protocol = str(protocol or "http").lower()
        if protocol not in ("http", "websocket", "socketio"):
            protocol = "http"
        mid = f"svc_{int(svc_id)}"
        envs = (
            await db.execute(
                select(ApiEnvironmentModel).where(ApiEnvironmentModel.enabled_flag == 1)
            )
        ).scalars().all()
        updates: List[tuple] = []
        for env in envs:
            cfg = list(env.config or [])
            fu_item = None
            for i in cfg:
                if isinstance(i, dict) and str(i.get("name") or "").strip() == "__front_urls__":
                    fu_item = i
                    break
            if fu_item is None:
                fu_item = {"name": "__front_urls__", "value": "[]"}
                cfg.append(fu_item)
            try:
                fu = _json.loads(fu_item.get("value") or "[]")
                if not isinstance(fu, list):
                    fu = []
            except Exception:
                fu = []
            exists = any(
                str(f.get("menu_id") or "") == mid
                and str(f.get("protocol") or "http").lower() == protocol
                for f in fu
            )
            if not exists:
                fu.append({"menu_id": mid, "url": "", "protocol": protocol, "auto": True})
                fu_item["value"] = _json.dumps(fu)
                updates.append((int(env.id), cfg))
        if updates:
            for eid, cfg in updates:
                await db.execute(
                    update(ApiEnvironmentModel)
                    .where(ApiEnvironmentModel.id == eid)
                    .values(config=cfg, updated_by=0)
                )
            await db.commit()

    @staticmethod
    async def _sync_env_front_urls(db: AsyncSession, module_ids: List[int], remove: bool = False) -> None:
        """模块创建/删除联动所有环境的 __front_urls__：创建补行（url 空）、删除移除行。"""
        import json as _json
        if not module_ids:
            return
        envs = (
            await db.execute(
                select(ApiEnvironmentModel).where(ApiEnvironmentModel.enabled_flag == 1)
            )
        ).scalars().all()
        ids = set(str(x) for x in module_ids)
        updates: List[tuple] = []
        for env in envs:
            cfg = list(env.config or [])
            fu_item = None
            for i in cfg:
                if isinstance(i, dict) and str(i.get("name") or "").strip() == "__front_urls__":
                    fu_item = i
                    break
            if fu_item is None:
                if remove:
                    continue
                fu_item = {"name": "__front_urls__", "value": "[]"}
                cfg.append(fu_item)
            try:
                fu = _json.loads(fu_item.get("value") or "[]")
                if not isinstance(fu, list):
                    fu = []
            except Exception:
                fu = []
            if remove:
                new_fu = [f for f in fu if str(f.get("menu_id") or "") not in ids]
            else:
                existing = set(str(f.get("menu_id") or "") for f in fu)
                for mid in module_ids:
                    if str(mid) not in existing:
                        fu.append({"menu_id": mid, "url": "", "protocol": "http", "auto": True})
                        existing.add(str(mid))
                new_fu = fu
            fu_item["value"] = _json.dumps(new_fu)
            updates.append((int(env.id), cfg))
        if updates:
            for eid, cfg in updates:
                await db.execute(
                    update(ApiEnvironmentModel)
                    .where(ApiEnvironmentModel.id == eid)
                    .values(config=cfg)
                )
            await db.commit()

    @staticmethod
    async def add_menu(db: AsyncSession, body: Dict[str, Any], user_id: int) -> None:
        # 防御：pid 指向接口节点（type=2）时，改为挂到该接口的父级目录（避免接口下挂接口）
        _pid = int(body.get("pid") or 0)
        if _pid:
            _parent = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.id == _pid,
                        ApiMenuModel.enabled_flag == 1,
                    )
                )
            ).scalar_one_or_none()
            if _parent and int(_parent.type) == 2:
                _pid = int(_parent.pid or 0)
                body["pid"] = _pid
        api_id = None
        if int(body.get("type")) in (2, 3):
            default_req = {
                "params_id": None,
                "body": {},
                "after": [],
                "assert": [],
                "before": [],
                "config": {"retry": 0, "req_timeout": 5, "res_timeout": 5},
                "header": [{"key": "Content-Type", "value": "application/json", "status": True}],
                "method": 2,
                "params": [],
                "body_type": 2,
                "file_path": [],
                "form_data": [],
                "form_urlencoded": [],
                "protocol": str(body.get("protocol") or "http").lower(),
            }
            api = ApiModel(
                api_service_id=int(body["api_service_id"]),
                url="/",
                document={},
                req=default_req,
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(api)
            await db.flush()
            api_id = api.id

        menu = ApiMenuModel(
            name=body["name"],
            pid=int(body["pid"]),
            type=int(body["type"]),
            api_service_id=int(body["api_service_id"]),
            status=1,
            api_id=api_id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(menu)
        await db.flush()
        if int(menu.type) == 0:
            await ApiAutomationService._sync_env_front_urls(db, [int(menu.id)])
        elif int(menu.type) == 2 and api_id:
            # 新建接口：按协议自动补齐环境前置 URL 行（webhook 复用 http 行）
            _p = str(body.get("protocol") or "http").lower()
            _p = _p if _p in ("websocket", "socketio") else "http"
            await ApiAutomationService._sync_env_front_urls_for_protocol(
                db, int(body["api_service_id"]), _p
            )
        if int(menu.type) in (0, 5):
            await ApiAutomationService._sync_env_front_urls(db, [f"svc_{int(menu.id)}"])
        await db.commit()
        return int(menu.id)

    @staticmethod
    async def edit_menu(db: AsyncSession, menu_id: int, name: str, user_id: int, common_params: Any = None) -> None:
        values: Dict[str, Any] = {"name": name, "updated_by": user_id}
        if common_params is not None:
            values["common_params"] = common_params
        await db.execute(
            update(ApiMenuModel)
            .where(ApiMenuModel.id == int(menu_id), ApiMenuModel.enabled_flag == 1, ApiMenuModel.created_by == user_id)
            .values(**values)
        )
        await db.commit()

    @staticmethod
    async def del_menu(db: AsyncSession, body: Dict[str, Any], user_id: int) -> None:
        
        menu_id = int(body["id"])
        m = await db.execute(select(ApiMenuModel).where(ApiMenuModel.id == menu_id, ApiMenuModel.enabled_flag == 1))
        menu = m.scalar_one_or_none()
        if not menu:
            return
        # 根目录保护：仅名为"接口"的根目录不可删除（旧平级脏数据 pid=0 不受保护）
        if int(menu.type) == 1 and int(menu.pid) == 0 and menu.name == "接口":
            raise ValueError("根目录不可删除")
        # 收集所有后代菜单（目录/接口节点）级联软删
        to_del: List[int] = [menu_id]
        frontier = [menu_id]
        while frontier:
            children = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.enabled_flag == 1,
                        ApiMenuModel.pid.in_(frontier),
                    )
                )
            ).scalars().all()
            frontier = [ch.id for ch in children]
            to_del.extend(frontier)
        api_ids = []
        mrows = []
        if to_del:
            mrows = (
                await db.execute(
                    select(ApiMenuModel).where(ApiMenuModel.id.in_(to_del))
                )
            ).scalars().all()
            api_ids = [int(m.api_id) for m in mrows if m.api_id]
        # 删除 websocket/socketio 接口时：服务下若无其他同协议接口，联动移除环境的 WS 行（删除前检查）
        if to_del:
            for m in mrows:
                if int(m.type) == 2 and m.api_id and int(m.api_service_id or 0):
                    _api_row = (
                        await db.execute(select(ApiModel).where(ApiModel.id == int(m.api_id)))
                    ).scalar_one_or_none()
                    _proto = str((_api_row.req or {}).get("protocol") or "http").lower() if _api_row else "http"
                    if _proto in ("websocket", "socketio"):
                        _others = (
                            await db.execute(
                                select(func.count(ApiMenuModel.id)).where(
                                    ApiMenuModel.api_service_id == int(m.api_service_id),
                                    ApiMenuModel.enabled_flag == 1,
                                    ApiMenuModel.type == 2,
                                    ApiMenuModel.id.notin_(to_del),
                                )
                            )
                        ).scalar()
                        if not _others:
                            await ApiAutomationService._remove_env_front_url_protocol(db, m.api_service_id, _proto)
        mod_ids = [f"svc_{int(m.id)}" for m in mrows if int(m.type) in (0, 5)] if to_del else []
        if mod_ids:
            await ApiAutomationService._sync_env_front_urls(db, mod_ids, remove=True)
        # 硬删除：菜单与接口物理删除
        if to_del:
            await db.execute(delete(ApiMenuModel).where(ApiMenuModel.id.in_(to_del)))
        if api_ids:
            await db.execute(delete(ApiModel).where(ApiModel.id.in_(api_ids)))
        await db.commit()

    @staticmethod
    async def copy_menu(db: AsyncSession, body: Dict[str, Any], user_id: int) -> None:
        api_id = int(body["api_id"])
        api_row = (await db.execute(select(ApiModel).where(ApiModel.id == api_id, ApiModel.enabled_flag == 1))).scalar_one()
        new_api = ApiModel(
            url=api_row.url,
            req=api_row.req,
            document=api_row.document,
            api_service_id=api_row.api_service_id,
            name=api_row.name,
            description=api_row.description,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(new_api)
        await db.flush()

        menu_id = int(body["id"])
        menu_row = (await db.execute(select(ApiMenuModel).where(ApiMenuModel.id == menu_id, ApiMenuModel.enabled_flag == 1))).scalar_one()
        new_menu = ApiMenuModel(
            name=menu_row.name,
            type=menu_row.type,
            pid=menu_row.pid,
            api_id=new_api.id,
            api_service_id=menu_row.api_service_id,
            status=menu_row.status,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(new_menu)
        await db.commit()

    @staticmethod
    async def get_api_info(db: AsyncSession, api_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        row = (
            await db.execute(
                select(ApiModel).where(ApiModel.id == int(api_id), ApiModel.enabled_flag == 1, ApiModel.created_by == user_id)
            )
        ).scalar_one_or_none()
        if not row:
            return None
        data = row.__dict__.copy()
        data.pop("_sa_instance_state", None)
        # 附加继承的父级操作列表（供前端展示"继承父级"）
        try:
            common = await ApiAutomationService._load_common_params_by_api(db, api_id=int(api_id))
            data["inherit_before"] = (common or {}).get("before") or []
            data["inherit_after"] = (common or {}).get("after") or []
        except Exception:
            data["inherit_before"] = []
            data["inherit_after"] = []
        return data

    @staticmethod
    def _compare_data(old_data: Any, new_data: Any, path: str = "") -> List[Dict[str, Any]]:
        changes: List[Dict[str, Any]] = []
        if isinstance(old_data, dict) and isinstance(new_data, dict):
            all_keys = set(old_data.keys()).union(new_data.keys())
            for key in all_keys:
                old_val = old_data.get(key, "__key_missing__")
                new_val = new_data.get(key, "__key_missing__")
                sub_path = f"{path}.{key}" if path else key
                if old_val == "__key_missing__":
                    changes.append({"field": sub_path, "type": "add", "old": None, "new": new_val})
                elif new_val == "__key_missing__":
                    changes.append({"field": sub_path, "type": "delete", "old": old_val, "new": None})
                else:
                    changes.extend(ApiAutomationService._compare_data(old_val, new_val, sub_path))
        elif isinstance(old_data, list) and isinstance(new_data, list):
            max_len = max(len(old_data), len(new_data))
            for i in range(max_len):
                old_val = old_data[i] if i < len(old_data) else "__index_missing__"
                new_val = new_data[i] if i < len(new_data) else "__index_missing__"
                sub_path = f"{path}[{i}]"
                if old_val == "__index_missing__":
                    changes.append({"field": sub_path, "type": "add", "old": None, "new": new_val})
                elif new_val == "__index_missing__":
                    changes.append({"field": sub_path, "type": "delete", "old": old_val, "new": None})
                else:
                    changes.extend(ApiAutomationService._compare_data(old_val, new_val, sub_path))
        else:
            if old_data != new_data:
                changes.append({"field": path, "type": "edit", "old": old_data, "new": new_data})
        return changes

    @staticmethod
    async def save_api(db: AsyncSession, body: Dict[str, Any], user_id: int) -> None:
        api_id = int(body["id"])
        row = (await db.execute(select(ApiModel).where(ApiModel.id == api_id, ApiModel.enabled_flag == 1))).scalar_one()
        old_req = row.req or {}
        values: Dict[str, Any] = {"updated_by": user_id}
        if "url" in body and body.get("url") is not None:
            values["url"] = body.get("url")
        if "req" in body:
            values["req"] = body.get("req") or {}
        if "document" in body:
            values["document"] = body.get("document") if body.get("document") is not None else {}
        if body.get("name") is not None:
            values["name"] = body.get("name")
        if body.get("description") is not None:
            values["description"] = body.get("description")
        await db.execute(
            update(ApiModel)
            .where(ApiModel.id == api_id, ApiModel.enabled_flag == 1)
            .values(**values)
        )
        if "req" in body:
            edits = ApiAutomationService._compare_data(old_req, values.get("req") or {})
            if edits:
                db.add(ApiEditModel(api_id=api_id, edit=edits, created_by=user_id, updated_by=user_id))
        # 文档变更时保存文档历史版本
        if "document" in body or body.get("name") is not None or body.get("description") is not None:
            await ApiAutomationService._save_doc_history(
                db, api_id, int(row.api_service_id), values.get("document") or row.document or {},
                values.get("name") or row.name, values.get("description") or row.description,
                "edit", user_id
            )
        await db.commit()

    @staticmethod
    async def save_api_case(db: AsyncSession, body: Dict[str, Any], user_id: int) -> None:
        """
        - 基于传入的接口配置新增一条 Api
        - 并在原接口所在菜单下创建一个 type=3 的用例节点
        """
        api_menu = (
            await db.execute(
                select(ApiMenuModel).where(
                    ApiMenuModel.enabled_flag == 1,
                    ApiMenuModel.created_by == user_id,
                    ApiMenuModel.api_id == int(body["id"]),
                )
            )
        ).scalar_one_or_none()
        if not api_menu:
            raise ValueError("未找到原接口对应的菜单节点")

        api = ApiModel(
            url=str(body.get("url") or "/"),
            req=body.get("req") or {},
            document=body.get("document") or {},
            api_service_id=int(body["api_service_id"]),
            name=body.get("name"),
            description=body.get("description"),
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(api)
        await db.flush()

        menu = ApiMenuModel(
            api_id=api.id,
            name=str(body.get("name") or api.url),
            created_by=user_id,
            updated_by=user_id,
            type=3,
            pid=int(api_menu.id),
            api_service_id=int(body["api_service_id"]),
            status=1,
        )
        db.add(menu)
        await db.commit()

    @staticmethod
    async def save_api_case_to_suite(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """将接口调试结果保存为用例，存入指定用例集"""
        from .model import ApiCaseModel
        case = ApiCaseModel(
            name=str(body["name"]),
            description=body.get("description") or "",
            suite_id=int(body["suite_id"]),
            script=body.get("script") or [],
            status=0,
            case_type=int(body.get("case_type") or 1),
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)
        d = case.__dict__.copy()
        d.pop("_sa_instance_state", None)
        return d

    @staticmethod
    async def _ensure_doc_history_table(db: AsyncSession) -> None:
        """兼容旧库：接口文档历史版本表"""
        try:
            await db.execute(text(
                """CREATE TABLE IF NOT EXISTS api_automation_doc_history (
                    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
                    api_id BIGINT NOT NULL COMMENT '接口ID',
                    api_service_id BIGINT NULL DEFAULT NULL COMMENT '服务ID',
                    document JSON NULL COMMENT '文档内容快照',
                    name VARCHAR(255) NULL DEFAULT NULL COMMENT '接口名称快照',
                    description TEXT NULL DEFAULT NULL COMMENT '接口描述快照',
                    operation_type VARCHAR(50) NULL DEFAULT 'edit' COMMENT '操作类型：create/edit/restore',
                    creation_date DATETIME NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                    created_by BIGINT NULL DEFAULT NULL COMMENT '创建人ID',
                    updation_date DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                    updated_by BIGINT NULL DEFAULT NULL COMMENT '更新人ID',
                    enabled_flag TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否删除, 0 删除 1 非删除',
                    trace_id VARCHAR(255) NULL DEFAULT NULL COMMENT 'trace_id',
                    PRIMARY KEY (id) USING BTREE
                ) ENGINE=InnoDB CHARACTER SET=utf8mb3 COLLATE=utf8mb3_general_ci ROW_FORMAT=Dynamic"""
            ))
            await db.commit()
        except Exception:
            await db.rollback()

    @staticmethod
    async def _save_doc_history(
        db: AsyncSession, api_id: int, api_service_id: int, document: Any,
        name: Any, description: Any, operation_type: str, user_id: int,
        url: Any = None, req: Any = None
    ) -> None:
        await ApiAutomationService._ensure_doc_history_table(db)

        norm_doc = document if isinstance(document, dict) else {}
        norm_name = str(name or '')
        norm_desc = str(description or '')
        norm_url = str(url or '')
        norm_req = req if isinstance(req, dict) else {}

        def _same_json(a: Any, b: Any) -> bool:
            return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)

        last_row = (
            await db.execute(
                select(ApiDocHistoryModel)
                .where(
                    ApiDocHistoryModel.enabled_flag == 1,
                    ApiDocHistoryModel.api_id == int(api_id),
                )
                .order_by(ApiDocHistoryModel.id.desc())
                .limit(1)
            )
        ).scalars().first()

        if last_row is not None:
            if (
                str(last_row.name or '') == norm_name and
                str(last_row.description or '') == norm_desc and
                str(last_row.url or '') == norm_url and
                _same_json(last_row.document if isinstance(last_row.document, dict) else {}, norm_doc) and
                _same_json(last_row.req if isinstance(last_row.req, dict) else {}, norm_req)
            ):
                # 快照完全一致：不新增记录，仅更新 updation_date 与 updated_by
                await db.execute(
                    update(ApiDocHistoryModel)
                    .where(ApiDocHistoryModel.id == last_row.id)
                    .values(updated_by=user_id)
                    # updation_date 由 ON UPDATE CURRENT_TIMESTAMP 自动刷新
                )
                return

        db.add(ApiDocHistoryModel(
            api_id=int(api_id),
            api_service_id=int(api_service_id) if api_service_id else None,
            document=norm_doc,
            name=norm_name,
            description=norm_desc,
            url=norm_url,
            req=norm_req,
            operation_type=str(operation_type or 'edit'),
            created_by=user_id,
            updated_by=user_id,
        ))

    @staticmethod
    async def get_doc_history(
        db: AsyncSession, api_id: int, user_id: int,
        page: int = 1, page_size: int = 20
    ) -> Dict[str, Any]:
        """获取接口文档历史版本列表"""
        await ApiAutomationService._ensure_doc_history_table(db)
        stmt = (
            select(ApiDocHistoryModel)
            .where(
                ApiDocHistoryModel.enabled_flag == 1,
                ApiDocHistoryModel.api_id == int(api_id),
            )
            .order_by(ApiDocHistoryModel.id.desc())
        )
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        rows = (await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()
        user_ids = [int(r.created_by) for r in rows if r.created_by]
        user_map = await _get_username_map(db, user_ids)
        items = []
        for r in rows:
            items.append({
                "id": int(r.id),
                "api_id": int(r.api_id),
                "api_service_id": int(r.api_service_id) if r.api_service_id else None,
                "operation_type": str(r.operation_type or 'edit'),
                "operation_label": {"create": "新建", "edit": "编辑", "restore": "还原"}.get(str(r.operation_type or ''), str(r.operation_type or '')),
                "name": str(r.name or ''),
                "description": str(r.description or ''),
                "created_by": int(r.created_by) if r.created_by else None,
                "created_by_name": user_map.get(int(r.created_by)) if r.created_by else '',
                "created_at": r.creation_date.strftime("%Y-%m-%d %H:%M:%S") if r.creation_date else '',
            })
        return {
            "rowTotal": total,
            "pageSize": page_size,
            "page": page,
            "pageTotal": int(ceil(float(total) / page_size)) if total else 0,
            "rows": items,
        }

    @staticmethod
    async def diff_doc_history(
        db: AsyncSession, history_id_a: int, history_id_b: int, user_id: int
    ) -> Dict[str, Any]:
        """对比两个文档历史版本"""
        await ApiAutomationService._ensure_doc_history_table(db)

        async def _get(hid: int) -> Optional[ApiDocHistoryModel]:
            return (
                await db.execute(
                    select(ApiDocHistoryModel).where(
                        ApiDocHistoryModel.id == hid,
                        ApiDocHistoryModel.enabled_flag == 1,
                    )
                )
            ).scalar_one_or_none()

        ha = await _get(history_id_a)
        hb = await _get(history_id_b)
        if not ha or not hb:
            raise ValueError("历史版本不存在")
        if int(ha.api_id) != int(hb.api_id):
            raise ValueError("只能对比同一接口的文档版本")
        doc_a = ha.document if isinstance(ha.document, dict) else {}
        doc_b = hb.document if isinstance(hb.document, dict) else {}
        changes = ApiAutomationService._compare_data(doc_a, doc_b)
        return {
            "history_a": {
                "id": int(ha.id),
                "api_id": int(ha.api_id),
                "created_at": ha.creation_date.strftime("%Y-%m-%d %H:%M:%S") if ha.creation_date else '',
                "operation_type": str(ha.operation_type or 'edit'),
                "name": str(ha.name or ''),
            },
            "history_b": {
                "id": int(hb.id),
                "api_id": int(hb.api_id),
                "created_at": hb.creation_date.strftime("%Y-%m-%d %H:%M:%S") if hb.creation_date else '',
                "operation_type": str(hb.operation_type or 'edit'),
                "name": str(hb.name or ''),
            },
            "changes": changes,
            "summary": {
                "add": len([c for c in changes if c.get("type") == "add"]),
                "delete": len([c for c in changes if c.get("type") == "delete"]),
                "edit": len([c for c in changes if c.get("type") == "edit"]),
            },
        }

    @staticmethod
    async def restore_doc_history(db: AsyncSession, history_id: int, user_id: int) -> None:
        """将接口文档还原到指定历史版本"""
        await ApiAutomationService._ensure_doc_history_table(db)
        row = (
            await db.execute(
                select(ApiDocHistoryModel).where(
                    ApiDocHistoryModel.id == int(history_id),
                    ApiDocHistoryModel.enabled_flag == 1,
                )
            )
        ).scalar_one_or_none()
        if not row:
            raise ValueError("历史版本不存在")
        api_id = int(row.api_id)
        await db.execute(
            update(ApiModel)
            .where(ApiModel.id == api_id, ApiModel.enabled_flag == 1)
            .values(
                document=row.document if isinstance(row.document, dict) else {},
                name=str(row.name or '') or None,
                description=str(row.description or '') or None,
                updated_by=user_id,
            )
        )
        await ApiAutomationService._save_doc_history(
            db, api_id, int(row.api_service_id) if row.api_service_id else 0,
            row.document if isinstance(row.document, dict) else {},
            str(row.name or ''), str(row.description or ''), "restore", user_id
        )
        await db.commit()

    @staticmethod
    async def get_request_history(
        db: AsyncSession,
        user_id: int,
        api_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Dict[str, Any]:
        page = max(int(page or 1), 1)
        page_size = min(max(int(page_size or 10), 1), 100)
        conditions = [
            ApiResultModel.enabled_flag == 1,
            ApiResultModel.created_by == user_id,
        ]
        if api_id:
            conditions.append(ApiResultModel.api_id == int(api_id))

        count_stmt = select(func.count()).select_from(ApiResultModel).where(*conditions)
        total = int((await db.execute(count_stmt)).scalar() or 0)

        stmt = (
            select(ApiResultModel)
            .where(*conditions)
            .order_by(ApiResultModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await db.execute(stmt)).scalars().all()
        data: List[Dict[str, Any]] = []
        for r in rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            data.append(d)
        return {"content": data, "total": total, "page": page, "pageSize": page_size}

    @staticmethod
    async def delete_request_history(db: AsyncSession, result_id: int, user_id: int) -> None:
        """删除单条调试记录。"""
        result = await db.execute(
            delete(ApiResultModel).where(
                ApiResultModel.id == int(result_id),
                ApiResultModel.created_by == user_id,
            )
        )
        if not result.rowcount:
            raise ValueError("调试记录不存在或无权限")
        await db.commit()

    @staticmethod
    async def get_edit_history(db: AsyncSession, api_id: int, user_id: int) -> List[Dict[str, Any]]:
        stmt = (
            select(ApiEditModel)
            .where(
                ApiEditModel.enabled_flag == 1,
                ApiEditModel.api_id == api_id,
                ApiEditModel.created_by == user_id,
            )
            .order_by(ApiEditModel.id.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        data: List[Dict[str, Any]] = []
        for r in rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            data.append(d)
        return data

    @staticmethod
    async def get_api_case(db: AsyncSession, script: List[List[Any]], user_id: int) -> List[Dict[str, Any]]:
        """
        - script: [[..., api_id], ...]
        - 返回 ApiMenu(type=3) 列表
        """
        api_ids: List[int] = []
        for item in script or []:
            try:
                api_ids.append(int(item[-1]))
            except Exception:
                continue
        if not api_ids:
            return []
        rows = (
            await db.execute(
                select(ApiMenuModel).where(
                    ApiMenuModel.enabled_flag == 1,
                    ApiMenuModel.created_by == user_id,
                    ApiMenuModel.type == 3,
                    ApiMenuModel.api_id.in_(api_ids),
                )
            )
        ).scalars().all()
        data: List[Dict[str, Any]] = []
        for r in rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            data.append(d)
        return data

  
    @staticmethod
    async def get_api_scripts(db: AsyncSession, user_id: int, page: int, page_size: int) -> Dict[str, Any]:
        stmt = (
            select(ApiScriptModel)
            .where(ApiScriptModel.enabled_flag == 1, ApiScriptModel.created_by == user_id)
            .order_by(ApiScriptModel.id.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows[start:end]
        content: List[Dict[str, Any]] = []
        for r in page_rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            content.append(d)
        return {"content": content, "total": total, "page": page, "pageSize": page_size}

    @staticmethod
    async def add_api_script(db: AsyncSession, data: Dict[str, Any], user_id: int) -> None:
        script = ApiScriptModel(
            name=data["name"],
            type=int(data.get("type", 1)),
            script=data.get("script") or [],
            config=data.get("config") or {},
            description=data.get("description", ""),
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(script)
        await db.commit()

    @staticmethod
    async def edit_api_script(db: AsyncSession, data: Dict[str, Any], user_id: int) -> None:
        script_id = int(data["id"])
        await db.execute(
            update(ApiScriptModel)
            .where(
                ApiScriptModel.id == script_id,
                ApiScriptModel.enabled_flag == 1,
                ApiScriptModel.created_by == user_id,
            )
            .values(
                name=data.get("name"),
                type=int(data.get("type", 1)),
                script=data.get("script") or [],
                config=data.get("config") or {},
                description=data.get("description", ""),
                updated_by=user_id,
            )
        )
        await db.commit()

    @staticmethod
    async def delete_api_script(db: AsyncSession, script_id: int, user_id: int) -> None:
        await db.execute(
            update(ApiScriptModel)
            .where(
                ApiScriptModel.id == script_id,
                ApiScriptModel.enabled_flag == 1,
                ApiScriptModel.created_by == user_id,
            )
            .values(enabled_flag=0, updated_by=user_id)
        )
        await db.commit()

    @staticmethod
    async def get_api_script_simple_list(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
        stmt = select(ApiScriptModel).where(
            ApiScriptModel.enabled_flag == 1,
            ApiScriptModel.created_by == user_id,
        )
        rows = (await db.execute(stmt)).scalars().all()
        data: List[Dict[str, Any]] = []
        for r in rows:
            data.append({"id": r.id, "name": r.name})
        return data

    @staticmethod
    def _jsonpath_value_simple(expr: str, data: Any) -> Tuple[bool, str]:
        """
        简化版本：仅基于单个 data 进行 jsonpath 提取。
        注意：为避免与上方多参数 _jsonpath_value 重名，这里使用 _jsonpath_value_simple。
        """
        try:
            jp = jsonpath_parse(expr)
            matches = [m.value for m in jp.find(data)]
            if not matches:
                return False, "jsonpath 未匹配到结果"
            return True, str(matches[0])
        except Exception as e:
            return False, f"获取断言目标值失败，原因：{str(e)}"

    @staticmethod
    async def _pre_wait_time(wait_time: int) -> Dict[str, Any]:
        try:
            time.sleep(int(wait_time))
            return {"status": 1, "message": f"前置操作-等待时长：{wait_time} 秒 成功"}
        except Exception as e:
            return {"status": 0, "message": f"前置操作-等待时长：{wait_time} 秒 失败，原因是：{str(e)}"}

    @staticmethod
    async def _after_wait_time(wait_time: int) -> Dict[str, Any]:
        try:
            time.sleep(int(wait_time))
            return {"status": 1, "message": f"后置操作-等待时长：{wait_time} 秒 成功"}
        except Exception as e:
            return {"status": 0, "message": f"后置操作-等待时长：{wait_time} 秒 失败，原因是：{str(e)}"}

    @staticmethod
    async def _load_script_env_maps(
        db: AsyncSession, env_id: int, user_id: int, temp_vars: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """返回 (session_vars, env_vars) 供脚本 ntest 使用。"""
        session_vars: Dict[str, Any] = {}
        env_vars: Dict[str, Any] = {}
        if env_id:
            env_row = (
                await db.execute(
                    select(ApiEnvironmentModel).where(
                        ApiEnvironmentModel.id == env_id,
                        ApiEnvironmentModel.enabled_flag == 1,
                    )
                )
            ).scalar_one_or_none()
            if env_row:
                for i in (env_row.config or []):
                    if isinstance(i, dict) and i.get("name") is not None:
                        env_vars[str(i.get("name"))] = i.get("value")
                for j in (env_row.variable or []):
                    if isinstance(j, dict) and j.get("name") is not None:
                        session_vars[str(j.get("name"))] = j.get("value")

        g_rows = (
            await db.execute(
                select(ApiVariableModel).where(
                    ApiVariableModel.enabled_flag == 1,
                    ApiVariableModel.created_by == user_id,
                )
            )
        ).scalars().all()
        for row in g_rows:
            if row.name and row.name not in session_vars:
                session_vars[str(row.name)] = row.value
        # 临时变量（单次请求内）优先注入，脚本 ntest.get/pm.variables.get 可读
        if isinstance(temp_vars, dict):
            for tk, tv in temp_vars.items():
                session_vars[str(tk)] = tv
        return session_vars, env_vars

    @staticmethod
    async def _apply_exported_vars(
        db: AsyncSession,
        exported: Dict[str, Any],
        env_id: int,
        user_id: int,
        request_ctx: Optional[Dict[str, Any]] = None,
    ) -> None:
        """将脚本导出的变量写入环境；__request__ 回写到 request_ctx。"""
        if not exported:
            return
        for key, value in exported.items():
            if key == "__temp__":
                # pm.variables.set 的临时变量：写入请求上下文临时区，不落库
                if isinstance(value, dict) and isinstance(request_ctx, dict):
                    request_ctx.setdefault("__temp_vars__", {}).update(value)
                continue
            if key == "__request__":
                if isinstance(value, dict) and isinstance(request_ctx, dict):
                    temp_save = request_ctx.get("__temp_vars__")
                    request_ctx.clear()
                    request_ctx.update(value)
                    if isinstance(temp_save, dict):
                        request_ctx["__temp_vars__"] = temp_save
                continue
            await ApiAutomationService._pre_set_var(
                db,
                {
                    "name": key,
                    "value": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str),
                    "env_type": 1 if env_id else 2,
                },
                env_id,
                user_id,
            )

    @staticmethod
    async def _op_run_script(
        db: AsyncSession,
        op: Dict[str, Any],
        env_id: int,
        user_id: int,
        *,
        phase: str,
        request_ctx: Optional[Dict[str, Any]] = None,
        response_ctx: Optional[Dict[str, Any]] = None,
        code_override: Optional[str] = None,
        language_override: Optional[str] = None,
        mode_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        from .script_runtime import normalize_language, run_script_async

        code = code_override if code_override is not None else str(op.get("code") or "")
        language = normalize_language(language_override or op.get("language") or "python")
        if not str(code).strip():
            return {"status": 0, "message": f"{phase}操作-自定义脚本：代码为空", "type": op.get("type")}
        # 全角标点清洗（防从文档/聊天粘贴时混入全角括号导致语法错误）
        _FW = str.maketrans({
            0xFF08: '(', 0xFF09: ')', 0xFF0C: ',', 0xFF1B: ';', 0xFF1A: ':',
            0xFF1F: '?', 0xFF01: '!', 0xFF0E: '.', 0xFF0D: '-', 0xFF0F: '/',
            0xFF1C: '<', 0xFF1E: '>', 0xFF02: '"', 0xFF07: "'", 0xFF5B: '{',
            0xFF5D: '}', 0xFF3B: '[', 0xFF3D: ']', 0xFF0B: '+', 0xFF0A: '*',
            0xFF1D: '=', 0xFF5E: '~', 0xFF40: '`',
        })
        if any(ord(ch) >= 0xFF01 and ord(ch) <= 0xFF5E for ch in code):
            code = code.translate(_FW)
        # 语言自动检测：声明为 JS 但代码为 Python 特征时按 Python 执行（防继承脚本语言配错）
        code_l = str(code).lstrip()
        if language == "javascript" and code_l.startswith(("import ", "from ", "def ", "# ")) \
                and not code_l.startswith(("const ", "let ", "var ", "function ", "require(", "module.")):
            language = "python"

        session_vars, env_vars = await ApiAutomationService._load_script_env_maps(
            db, env_id, user_id,
            temp_vars=request_ctx.get("__temp_vars__") if isinstance(request_ctx, dict) else None,
        )
        req_snap = dict(request_ctx) if isinstance(request_ctx, dict) else None
        run_res = await run_script_async(
            code,
            mode=mode_override or op.get("exec_mode") or None,
            language=language,
            session_vars=session_vars,
            env_vars=env_vars,
            request_ctx=req_snap,
            response_ctx=response_ctx,
        )
        if not run_res.success:
            return {
                "status": 0,
                "message": f"{phase}操作-自定义脚本失败：{run_res.error or 'unknown'}",
                "type": op.get("type"),
                "output": run_res.output or "",
                "language": language,
            }
        await ApiAutomationService._apply_exported_vars(
            db, run_res.vars or {}, env_id, user_id, request_ctx=request_ctx
        )
        return {
            "status": 1,
            "message": f"{phase}操作-自定义脚本成功（{'Python' if language == 'python' else 'JavaScript'}）",
            "type": op.get("type"),
            "output": (run_res.output or "")[:5000],
            "vars": {k: v for k, v in (run_res.vars or {}).items() if k != "__request__"},
            "language": language,
        }

    @staticmethod
    async def _op_run_script_lib(
        db: AsyncSession,
        op: Dict[str, Any],
        env_id: int,
        user_id: int,
        *,
        phase: str,
        request_ctx: Optional[Dict[str, Any]] = None,
        response_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from .model import NtestScriptModel
        from .script_runtime import normalize_language

        func_id = op.get("func_id")
        if not func_id:
            return {"status": 0, "message": f"{phase}操作-脚本库：未选择脚本", "type": op.get("type")}
        row = (
            await db.execute(
                select(NtestScriptModel).where(
                    NtestScriptModel.id == int(func_id),
                    NtestScriptModel.enabled_flag == 1,
                )
            )
        ).scalar_one_or_none()
        if not row or not (row.code or "").strip():
            return {"status": 0, "message": f"{phase}操作-脚本库：脚本不存在或为空", "type": op.get("type")}

        # 可选参数注入到 session
        params_raw = op.get("func_params") or ""
        extra_prefix = ""
        language = normalize_language(getattr(row, "language", None) or "python")
        if str(params_raw).strip():
            try:
                params_obj = json.loads(params_raw) if isinstance(params_raw, str) else params_raw
            except Exception:
                params_obj = None
            if isinstance(params_obj, dict):
                if language == "javascript":
                    extra_prefix = f"const __params = {json.dumps(params_obj, ensure_ascii=False)};\n"
                else:
                    extra_prefix = f"__params = {json.dumps(params_obj, ensure_ascii=False)}\n"

        result = await ApiAutomationService._op_run_script(
            db,
            op,
            env_id,
            user_id,
            phase=phase,
            request_ctx=request_ctx,
            response_ctx=response_ctx,
            code_override=extra_prefix + (row.code or ""),
            language_override=language,
            mode_override=op.get("exec_mode") or getattr(row, "exec_mode", None) or None,
        )
        if result.get("status") == 1 and op.get("result_var"):
            await ApiAutomationService._pre_set_var(
                db,
                {
                    "name": str(op.get("result_var")),
                    "value": str(result.get("output") or ""),
                    "env_type": 1,
                },
                env_id,
                user_id,
            )
        name = op.get("func_name") or row.name or str(func_id)
        if result.get("status") == 1:
            result["message"] = f"{phase}操作-脚本库「{name}」成功"
        return result

    @staticmethod
    async def _op_run_db(
        db: AsyncSession,
        op: Dict[str, Any],
        env_id: int,
        user_id: int,
        *,
        phase: str,
        request_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        db_id = op.get("db_id")
        sql = str(op.get("sql") or "").strip()
        if not db_id:
            return {"status": 0, "message": f"{phase}操作-数据库：未选择数据库", "type": op.get("type")}
        if not sql:
            return {"status": 0, "message": f"{phase}操作-数据库：SQL 为空", "type": op.get("type")}

        row = (
            await db.execute(
                select(ApiDatabaseModel).where(
                    ApiDatabaseModel.id == int(db_id),
                    ApiDatabaseModel.enabled_flag == 1,
                    ApiDatabaseModel.created_by == user_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            return {"status": 0, "message": f"{phase}操作-数据库：配置不存在", "type": op.get("type")}

        sql = await ApiAutomationService.handle_var(db, env_id, sql, temp_vars=(request_ctx or {}).get("__temp_vars__"))
        try:
            cfg = row.config or {}
            host = cfg.get("host") or row.host
            user = cfg.get("user") or row.username
            password = cfg.get("password") or row.password
            database = cfg.get("database") or row.database_name
            port = int(cfg.get("port") or row.port or 3306)
            conn = pymysql.connect(host=host, user=user, passwd=password, db=database, port=port)
            cur = conn.cursor()
            cur.execute(sql)
            rows_data: Any
            if cur.description:
                cols = [c[0] for c in cur.description]
                fetched = cur.fetchall()
                rows_data = [dict(zip(cols, r)) for r in fetched]
            else:
                rows_data = {"affected": cur.rowcount}
                conn.commit()
            cur.close()
            conn.close()
            result_var = str(op.get("result_var") or "").strip()
            if result_var:
                val = json.dumps(rows_data, ensure_ascii=False, default=str)
                await ApiAutomationService._pre_set_var(
                    db, {"name": result_var, "value": val, "env_type": 1}, env_id, user_id
                )
            return {
                "status": 1,
                "message": f"{phase}操作-数据库执行成功",
                "type": op.get("type"),
                "data": rows_data if not isinstance(rows_data, list) or len(rows_data) <= 20 else rows_data[:20],
            }
        except Exception as e:
            return {"status": 0, "message": f"{phase}操作-数据库失败：{str(e)}", "type": op.get("type")}

    @staticmethod
    async def _op_import_api(
        db: AsyncSession,
        op: Dict[str, Any],
        env_id: int,
        user_id: int,
        *,
        phase: str,
        request_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """引入接口。
        """
        raw = op.get("api_id")
        menu_id = 0
        if isinstance(raw, list) and raw:
            try:
                menu_id = int(raw[-1])
            except Exception:
                menu_id = 0
        elif raw is not None and str(raw).strip() != "":
            try:
                menu_id = int(raw)
            except Exception:
                menu_id = 0

        if not menu_id:
            return {
                "status": 0,
                "message": f"{phase}操作-引入接口：未选择接口",
                "content": [],
                "type": op.get("type"),
            }

        menu_row = (
            await db.execute(
                select(ApiMenuModel).where(
                    ApiMenuModel.id == menu_id,
                    ApiMenuModel.enabled_flag == 1,
                )
            )
        ).scalar_one_or_none()
        if not menu_row:
            return {
                "status": 0,
                "message": f"{phase}操作-引入接口：所选菜单不存在（id={menu_id}）",
                "content": [],
                "type": op.get("type"),
            }
        # type: 1=目录 2=接口 3=用例；引入接口应允许 2/3
        if int(menu_row.type or 0) not in (2, 3):
            return {
                "status": 0,
                "message": f"{phase}操作-引入接口：请选择接口或用例，不能选择目录",
                "content": [],
                "type": op.get("type"),
            }
        if not menu_row.api_id:
            return {
                "status": 0,
                "message": f"{phase}操作-引入接口：所选菜单未关联接口定义",
                "content": [],
                "type": op.get("type"),
            }

        api_row = (
            await db.execute(
                select(ApiModel).where(
                    ApiModel.id == int(menu_row.api_id),
                    ApiModel.enabled_flag == 1,
                )
            )
        ).scalar_one_or_none()
        if not api_row:
            return {
                "status": 0,
                "message": f"{phase}操作-引入接口：接口不存在（api_id={menu_row.api_id}）",
                "content": [],
                "type": op.get("type"),
            }
        res = await ApiAutomationService._pre_request_api(
            db=db,
            api=api_row,
            env_id=int(op.get("env_id") or env_id),
            user_id=user_id,
        )
        res["type"] = op.get("type")
        if res.get("status") is None and res.get("code") is not None:
            # _pre_request_api 返回的是请求结果结构，补齐操作结果字段
            code = int(res.get("code") or 0)
            res["status"] = 1 if 200 <= code < 400 else 0
            res["message"] = f"{phase}操作-引入接口「{api_row.name or menu_row.name}」完成（HTTP {code}）"
        elif not res.get("message"):
            res["message"] = f"{phase}操作-引入接口「{api_row.name or menu_row.name}」完成"
            res.setdefault("status", 1)
        return res

    @staticmethod
    def _map_apifox_processors(processors: Any, *, phase: str = "before") -> List[Dict[str, Any]]:
        """将 Apifox转为平台操作。"""
        from .script_runtime import normalize_language

        ops: List[Dict[str, Any]] = []
        for p in processors or []:
            if not isinstance(p, dict):
                continue
            t = str(p.get("type") or "").strip()
            if t in ("inheritProcessors", ""):
                continue
            data = p.get("data") if isinstance(p.get("data"), dict) else {}
            if t in ("customScript", "script"):
                code = str(data.get("script") or data.get("code") or "")
                if not code.strip():
                    continue
                lang = normalize_language(data.get("language") or "javascript")
                if phase == "before":
                    ops.append({"type": 4, "code": code, "language": lang})
                else:
                    ops.append({"type": 5, "code": code, "language": lang})
            elif t == "wait":
                wait_raw = data.get("waitTime") or data.get("duration") or data.get("time") or 1
                try:
                    wait_num = float(wait_raw)
                except Exception:
                    wait_num = 1
                # Apifox 常见毫秒；>=100 视为毫秒
                wait_s = int(wait_num / 1000) if wait_num >= 100 else int(wait_num)
                wait_s = max(wait_s, 0)
                if phase == "before":
                    ops.append({"type": 3, "wait_time": wait_s or 1})
                else:
                    ops.append({"type": 2, "wait_time": wait_s or 1})
        return ops

    @staticmethod
    def _resolve_apifox_processors(own: Any, inherited: Optional[List[Any]] = None) -> List[Any]:
        inherited = list(inherited or [])
        if not isinstance(own, list) or not own:
            return inherited
        resolved: List[Any] = []
        for p in own:
            if not isinstance(p, dict):
                continue
            if str(p.get("type") or "") == "inheritProcessors":
                resolved.extend(inherited)
            else:
                resolved.append(p)
        return resolved
  
    @staticmethod
    async def _pre_set_var(db: AsyncSession, data: Dict[str, Any], env_id: int, user_id: int,
                          request_ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        前置操作-设置变量：
        - env_type 1: 环境变量 ApiEnvironmentModel.variable
        - env_type 2: 全局变量 ApiVariableModel
        - env_type 3: 临时变量（单次请求内有效，不落库）
        """
        try:
            env_type = int(data.get("env_type") or 1)
            name = data.get("name", "")
            value = data.get("value", "")
            message = ""
            if env_type == 3:
                # 临时变量：只写请求上下文，不落库
                if isinstance(request_ctx, dict):
                    request_ctx.setdefault("__temp_vars__", {})[name] = value
                    return {"status": 1, "message": f"前置操作-设置临时变量：{name} 成功"}
                return {"status": 0, "message": f"前置操作-设置临时变量：{name} 失败，原因：无请求上下文"}
            if env_type == 1:
                env_row = (
                    await db.execute(
                        select(ApiEnvironmentModel).where(
                            ApiEnvironmentModel.id == env_id,
                            ApiEnvironmentModel.enabled_flag == 1,
                            ApiEnvironmentModel.created_by == user_id,
                        )
                    )
                ).scalar_one_or_none()
                if not env_row:
                    return {"status": 0, "message": f"前置操作-设置环境变量：{name} 失败，原因：环境不存在"}
                vars_list = list(env_row.variable or [])
                found = False
                for item in vars_list:
                    if item.get("name") == name:
                        item["value"] = value
                        found = True
                        break
                if not found:
                    vars_list.append({"name": name, "value": value})
                await db.execute(
                    update(ApiEnvironmentModel)
                    .values(variable=vars_list)
                    .where(
                        ApiEnvironmentModel.id == env_row.id,
                        ApiEnvironmentModel.enabled_flag == 1,
                    )
                    .values(variable=vars_list, updated_by=user_id)
                )
                message = f"前置操作-设置环境变量：{name} 成功"
            else:
                # env_type == 2, 全局变量
                row = (
                    await db.execute(
                        select(ApiVariableModel).where(
                            ApiVariableModel.enabled_flag == 1,
                            ApiVariableModel.name == name,
                            ApiVariableModel.created_by == user_id,
                        )
                    )
                ).scalar_one_or_none()
                if row:
                    await db.execute(
                        update(ApiVariableModel)
                        .where(
                            ApiVariableModel.id == row.id,
                            ApiVariableModel.enabled_flag == 1,
                        )
                        .values(value=str(value), updated_by=user_id)
                    )
                else:
                    db.add(
                        ApiVariableModel(
                            name=name,
                            value=str(value),
                            created_by=user_id,
                            updated_by=user_id,
                        )
                    )
                message = f"前置操作-设置全局变量：{name} 成功"
            await db.commit()
            return {"status": 1, "message": message}
        except Exception as e:
            return {"status": 0, "message": f"前置操作-设置变量：{data.get('name')} 失败，原因：{str(e)}"}

    @staticmethod
    async def _pre_request(
        db: AsyncSession,
        ops: List[Dict[str, Any]],
        env_id: int,
        user_id: int,
        request_ctx: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        pre_request：
        - type=1: 预请求接口
        - type=2: 设置变量
        - type=3: 等待
        - type=4: 自定义脚本（python/javascript，支持 ntest/pm）
        - type=5: 数据库操作
        - type=6: 脚本库
        """
        results: List[Dict[str, Any]] = []
        for op in ops or []:
            if op.get("enabled") is False:
                results.append({"status": 1, "message": "操作已停用，跳过", "type": op.get("type")})
                continue
            try:
                if op.get("enabled") is False:
                    results.append({"status": 1, "message": "操作已停用，跳过", "type": op.get("type")})
                    continue
                t = int(op.get("type") or 0)
                if t == 1:
                    results.append(
                        await ApiAutomationService._op_import_api(
                            db, op, env_id, user_id, phase="前置"
                        )
                    )
                elif t == 2:
                    r = await ApiAutomationService._pre_set_var(db, op, env_id, user_id, request_ctx=request_ctx)
                    r["type"] = t
                    results.append(r)
                elif t == 3:
                    r = await ApiAutomationService._pre_wait_time(int(op.get("wait_time") or 0))
                    r["type"] = t
                    results.append(r)
                elif t == 4:
                    results.append(
                        await ApiAutomationService._op_run_script(
                            db, op, env_id, user_id, phase="前置", request_ctx=request_ctx
                        )
                    )
                elif t == 5:
                    results.append(
                        await ApiAutomationService._op_run_db(
                            db, op, env_id, user_id, phase="前置", request_ctx=request_ctx
                        )
                    )
                elif t == 6:
                    results.append(
                        await ApiAutomationService._op_run_script_lib(
                            db, op, env_id, user_id, phase="前置", request_ctx=request_ctx
                        )
                    )
                else:
                    results.append({"status": 0, "message": f"未知前置操作类型：{t}", "type": t})
            except Exception as e:
                results.append({"status": 0, "message": f"前置操作执行失败，原因：{str(e)}"})
        return results

    @staticmethod
    async def _pre_request_api(db: AsyncSession, api: ApiModel, env_id: int, user_id: int) -> Dict[str, Any]:
        """
        pre_request_api：
        - 不执行 before
        - 执行主请求 + after + assert
        - before 固定为空
        """
        url = await ApiAutomationService.handle_var(db, env_id, api.url or "")
        url = await ApiAutomationService._resolve_base_url(db, env_id, url, api_id=api.id)
        api_req = dict(api.req or {}) if isinstance(api.req, dict) else {}
        common = await ApiAutomationService._load_common_params_by_api(
            db, api_id=getattr(api, "id", None), api_service_id=getattr(api, "api_service_id", None)
        )
        api_req = ApiAutomationService.apply_common_params_to_req(api_req, common)

        body_payload = await ApiAutomationService.handle_var(db, env_id, api_req.get("body") or {})
        method = int(api_req.get("method") or 2)
        body_type = int(api_req.get("body_type") or 2)
        headers = await ApiAutomationService.handle_var(db, env_id, ApiAutomationService.params_header(api_req.get("header")))
        params = await ApiAutomationService.handle_var(db, env_id, ApiAutomationService.params_header(api_req.get("params")))
        form_data = await ApiAutomationService.handle_var(db, env_id, ApiAutomationService.params_header(api_req.get("form_data")))
        form_urlencoded = await ApiAutomationService.handle_var(db, env_id, ApiAutomationService.params_header(api_req.get("form_urlencoded")))
        file_paths = api_req.get("file_path") or []
        config = api_req.get("config") or {"retry": 0, "req_timeout": 5, "res_timeout": 5}

        headers, params, req_auth = await ApiAutomationService.apply_request_auth(
            db, env_id, api_req, headers=headers, params=params,
            common_auth=(common or {}).get("auth") if isinstance(common, dict) else None,
        )

        res = await ApiAutomationService._send_request(
            method=method,
            url=str(url),
            headers=headers,
            params=params,
            body_type=body_type,
            body=body_payload,
            form_data=form_data,
            form_urlencoded=form_urlencoded,
            file_paths=file_paths,
            config=config,
            auth=req_auth,
        )

        after_list: List[Dict[str, Any]] = []
        if api_req.get("after"):
            after_list = await ApiAutomationService._after_request(
                db=db,
                ops=api_req.get("after") or [],
                res=res,
                header=headers,
                body=body_payload,
                env_id=env_id,
                user_id=user_id,
            )

        assert_list: List[Dict[str, Any]] = []
        if api_req.get("assert"):
            assert_list = await ApiAutomationService._handle_assert(
                db=db,
                ops=api_req.get("assert") or [],
                res=res,
                header=headers,
                body=body_payload,
                user_id=user_id,
                env_id=env_id,
            )

        res["before"] = []
        res["after"] = after_list
        res["assert"] = assert_list
        res["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if int(res.get("code") or 0) == 200:
            return {"status": 1, "message": f"前置操作-预请求接口：{url} 成功", "content": res, "type": 1}
        return {"status": 0, "message": f"前置操作-预请求接口：{url} 失败", "content": res, "type": 1}

    @staticmethod
    async def _after_set_var(
        db: AsyncSession,
        data: Dict[str, Any],
        res: Dict[str, Any],
        header: Dict[str, Any],
        body: Any,
        env_id: int,
        user_id: int,
        request_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        后置操作-提取变量，after_set_var：
        - 使用 jsonpath 提取值并写入环境变量或全局变量
        """
        try:
            ok, value = ApiAutomationService._jsonpath_value_advanced(data, res, header, body)
            if not ok:
                return {
                    "status": 0,
                    "message": f"后置操作-提取目标值失败，原因是：{value}",
                }

            env_type = int(data.get("env_type") or 1)
            target_name = data.get("value", "")

            if env_type == 1:
                env_row = (
                    await db.execute(
                        select(ApiEnvironmentModel).where(
                            ApiEnvironmentModel.id == env_id,
                            ApiEnvironmentModel.enabled_flag == 1,
                            ApiEnvironmentModel.created_by == user_id,
                        )
                    )
                ).scalar_one_or_none()
                if not env_row:
                    return {
                        "status": 0,
                        "message": f"后置操作-提取目标值：{data.get('name')} 失败，原因是：环境不存在",
                    }
                vars_list = list(env_row.variable or [])
                found = False
                for item in vars_list:
                    if item.get("name") == target_name:
                        item["value"] = value
                        found = True
                        break
                if not found:
                    vars_list.append({"name": target_name, "value": value})
                await db.execute(
                    update(ApiEnvironmentModel)
                    .where(
                        ApiEnvironmentModel.id == env_row.id,
                        ApiEnvironmentModel.enabled_flag == 1,
                    )
                    .values(variable=vars_list, updated_by=user_id)
                )
            elif env_type == 3:
                # 临时变量：写入请求上下文临时区，不落库，请求结束自动消失
                if not isinstance(request_ctx, dict):
                    return {
                        "status": 0,
                        "message": f"后置操作-提取目标值：{data.get('name')} 失败，原因是：当前上下文不支持临时变量",
                    }
                request_ctx.setdefault("__temp_vars__", {})[target_name] = value
                return {
                    "status": 1,
                    "message": f"后置操作-提取目标值：{data.get('name')}={value} ，赋值给临时变量 {target_name} 成功",
                }
            else:
                row = (
                    await db.execute(
                        select(ApiVariableModel).where(
                            ApiVariableModel.enabled_flag == 1,
                            ApiVariableModel.name == target_name,
                            ApiVariableModel.created_by == user_id,
                        )
                    )
                ).scalar_one_or_none()
                if row:
                    await db.execute(
                        update(ApiVariableModel)
                        .where(ApiVariableModel.id == row.id, ApiVariableModel.enabled_flag == 1)
                        .values(value=str(value), updated_by=user_id)
                    )
                else:
                    db.add(
                        ApiVariableModel(
                            name=target_name,
                            value=str(value),
                            created_by=user_id,
                            updated_by=user_id,
                        )
                    )
            await db.commit()
            return {
                "status": 1,
                "message": f"后置操作-提取目标值：{data.get('name')}={value} ，赋值给 {target_name} 成功",
            }
        except Exception as e:
            return {
                "status": 0,
                "message": f"后置操作-设置变量：{data.get('name')} 失败，原因：{str(e)}",
            }

    @staticmethod
    async def _after_request(
        db: AsyncSession,
        ops: List[Dict[str, Any]],
        res: Dict[str, Any],
        header: Dict[str, Any],
        body: Any,
        env_id: int,
        user_id: int,
        request_ctx: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        after_request：
        - type=1: 提取变量
        - type=2: 等待
        - type=3: 断言
        - type=4: 数据库操作
        - type=5: 自定义脚本
        - type=6: 脚本库
        - type=7: 引入接口
        """
        results: List[Dict[str, Any]] = []
        response_ctx = {
            "code": res.get("code"),
            "body": res.get("body"),
            "header": res.get("header") or {},
            "res_time": res.get("res_time"),
        }
        for op in ops or []:
            if op.get("enabled") is False:
                results.append({"status": 1, "message": "操作已停用，跳过", "type": op.get("type")})
                continue
            try:
                t = int(op.get("type") or 0)
                if t == 1:
                    results.append(
                        await ApiAutomationService._after_set_var(
                            db, op, res, header, body, env_id, user_id, request_ctx=request_ctx
                        )
                    )
                elif t == 2:
                    results.append(
                        await ApiAutomationService._after_wait_time(int(op.get("wait_time") or 0))
                    )
                elif t == 3:
                    # 断言：复用 assert 处理
                    assert_op = {
                        "type": 1,
                        "assert_name": op.get("assert_name") or "后置断言",
                        "rules": op.get("rules") or [],
                        "name": op.get("name"),
                        "res_type": op.get("res_type"),
                        "value": op.get("value"),
                    }
                    ar = await ApiAutomationService._handle_assert(
                        db=db,
                        ops=[assert_op],
                        res=res,
                        header=header,
                        body=body,
                        user_id=user_id,
                        env_id=env_id,
                        request_ctx=request_ctx,
                    )
                    item = ar[0] if ar else {"status": 0, "message": "断言执行失败"}
                    item["type"] = t
                    results.append(item)
                elif t == 4:
                    results.append(
                        await ApiAutomationService._op_run_db(
                            db, op, env_id, user_id, phase="后置", request_ctx=request_ctx
                        )
                    )
                elif t == 5:
                    results.append(
                        await ApiAutomationService._op_run_script(
                            db,
                            op,
                            env_id,
                            user_id,
                            phase="后置",
                            request_ctx=request_ctx,
                            response_ctx=response_ctx,
                        )
                    )
                elif t == 6:
                    results.append(
                        await ApiAutomationService._op_run_script_lib(
                            db,
                            op,
                            env_id,
                            user_id,
                            phase="后置",
                            request_ctx=request_ctx,
                            response_ctx=response_ctx,
                        )
                    )
                elif t == 7:
                    results.append(
                        await ApiAutomationService._op_import_api(
                            db, op, env_id, user_id, phase="后置"
                        )
                    )
                else:
                    results.append({"status": 0, "message": f"未知后置操作类型：{t}"})
            except Exception as e:
                results.append({"status": 0, "message": f"后置操作执行失败，原因：{str(e)}"})
        return results

    @staticmethod
    async def _res_assert(rule: Dict[str, Any], res: Dict[str, Any], header: Dict[str, Any], body: Any) -> Dict[str, Any]:
        """
        res_assert：支持新版 AssertEditor 格式（rules 数组）和旧版格式。

        新版格式（AssertEditor）：
          rule = {
            "rules": [
              {"target": "response_json", "path": "$.code", "comparator": "eq", "expect": "200"},
              ...
            ]
          }

        旧版格式：
          rule = {"name": "$.code", "res_type": 1, "value": "200"}
        """
        # ---- 新版格式：rules 数组 ----
        rules = rule.get("rules")
        if isinstance(rules, list):
            results = []
            all_pass = True
            for r in rules:
                result = await ApiAutomationService._eval_assert_rule(r, res, header, body)
                results.append(result)
                if not result.get("pass"):
                    all_pass = False
            return {
                "status": 1 if all_pass else 0,
                "message": "断言全部通过" if all_pass else "断言存在失败项",
                "details": results,
            }

        # ---- 旧版格式：单条 eq 断言 ----
        try:
            ok, actual = ApiAutomationService._jsonpath_value_advanced(rule, res, header, body)
            expect = str(rule.get("value", ""))
            name = rule.get("name", "")
            if not ok:
                return {
                    "status": 0,
                    "message": f"断言 {name} = {expect} 失败，原因是：{actual}",
                }
            if expect == actual:
                return {
                    "status": 1,
                    "message": f"断言 {name} = {expect} 成功",
                }
            return {
                "status": 0,
                "message": f"断言 {name} = {expect} 失败，实际值为：{actual}",
            }
        except Exception as e:
            return {
                "status": 0,
                "message": f"断言 {rule.get('name')} = {rule.get('value')} 失败，原因：{str(e)}",
            }

    @staticmethod
    def _extract_assert_target(target: str, path: str, res: Dict[str, Any], header: Dict[str, Any], body: Any) -> Tuple[bool, Any]:
        """
        根据 target 和 path 提取断言目标值。
        返回 (success, value)
        """
        import re as _re
        try:
            if target == "response_json":
                if not path:
                    return True, body
                from jsonpath_ng import parse as jp_parse
                matches = [m.value for m in jp_parse(path).find(body or {})]
                if not matches:
                    return False, f"JSONPath '{path}' 未匹配到结果"
                return True, matches[0]

            elif target == "response_text":
                raw = res.get("raw") or res.get("text") or ""
                if isinstance(body, (dict, list)):
                    import json as _json
                    raw = _json.dumps(body, ensure_ascii=False)
                return True, str(raw)

            elif target == "response_xml":
                raw = res.get("raw") or res.get("text") or ""
                if not path:
                    return True, raw
                try:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(raw)
                    found = root.findall(path)
                    if not found:
                        return False, f"XPath '{path}' 未匹配到结果"
                    return True, found[0].text or ""
                except Exception as xe:
                    return False, f"XML 解析失败：{xe}"

            elif target == "response_header":
                if not path:
                    return True, header
                val = header.get(path) or header.get(path.lower()) or header.get(path.upper())
                if val is None:
                    return False, f"响应头 '{path}' 不存在"
                return True, str(val)

            elif target == "response_cookie":
                cookies = res.get("cookies") or {}
                if isinstance(cookies, list):
                    cookies = {c.get("name", ""): c.get("value", "") for c in cookies}
                if not path:
                    return True, cookies
                val = cookies.get(path)
                if val is None:
                    return False, f"Cookie '{path}' 不存在"
                return True, str(val)

            elif target == "http_code":
                return True, res.get("code") or res.get("status_code") or 0

            elif target == "response_time":
                return True, res.get("res_time") or res.get("response_time") or 0

            elif target in ("env_var", "global_var"):
                # Variables are resolved before execution; here we just return the path as-is
                # In practice the variable should already be substituted
                return True, path

            else:
                return False, f"未知断言目标：{target}"

        except Exception as e:
            return False, f"提取断言目标值失败：{e}"

    @staticmethod
    def _compare_assert(actual: Any, comparator: str, expect: str) -> Tuple[bool, str]:
        """执行比较，返回 (pass, message)"""
        import re as _re

        # Comparators that don't need expect value
        if comparator == "exists":
            return True, f"值存在：{actual}"
        if comparator == "not_exists":
            return False, f"值存在但期望不存在：{actual}"
        if comparator == "is_empty":
            ok = actual is None or str(actual).strip() == ""
            return ok, ("值为空，断言通过" if ok else f"值不为空：{actual}")
        if comparator == "not_empty":
            ok = actual is not None and str(actual).strip() != ""
            return ok, ("值不为空，断言通过" if ok else "值为空，断言失败")

        # Convert for numeric comparisons
        actual_str = str(actual) if actual is not None else ""

        if comparator == "eq":
            ok = actual_str == expect
            return ok, (f"等于 {expect}，通过" if ok else f"期望 {expect}，实际 {actual_str}")
        if comparator == "ne":
            ok = actual_str != expect
            return ok, (f"不等于 {expect}，通过" if ok else f"期望不等于 {expect}，但实际相等")
        if comparator in ("gt", "gte", "lt", "lte"):
            try:
                a_num = float(actual_str)
                e_num = float(expect)
                if comparator == "gt":
                    ok = a_num > e_num
                elif comparator == "gte":
                    ok = a_num >= e_num
                elif comparator == "lt":
                    ok = a_num < e_num
                else:
                    ok = a_num <= e_num
                op_map = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
                return ok, (f"{actual_str} {op_map[comparator]} {expect}，通过" if ok else f"{actual_str} 不满足 {op_map[comparator]} {expect}")
            except ValueError:
                return False, f"数值比较失败：{actual_str} 或 {expect} 不是有效数字"
        if comparator == "contains":
            ok = expect in actual_str
            return ok, (f"包含 '{expect}'，通过" if ok else f"不包含 '{expect}'，实际：{actual_str}")
        if comparator == "not_contains":
            ok = expect not in actual_str
            return ok, (f"不包含 '{expect}'，通过" if ok else f"包含了 '{expect}'，实际：{actual_str}")
        if comparator == "startswith":
            ok = actual_str.startswith(expect)
            return ok, (f"以 '{expect}' 开头，通过" if ok else f"不以 '{expect}' 开头，实际：{actual_str}")
        if comparator == "endswith":
            ok = actual_str.endswith(expect)
            return ok, (f"以 '{expect}' 结尾，通过" if ok else f"不以 '{expect}' 结尾，实际：{actual_str}")
        if comparator == "regex":
            try:
                ok = bool(_re.search(expect, actual_str))
                return ok, (f"正则 '{expect}' 匹配，通过" if ok else f"正则 '{expect}' 不匹配，实际：{actual_str}")
            except _re.error as re_err:
                return False, f"正则表达式错误：{re_err}"

        return False, f"未知比较符：{comparator}"

    @staticmethod
    async def _eval_assert_rule(rule: Dict[str, Any], res: Dict[str, Any], header: Dict[str, Any], body: Any) -> Dict[str, Any]:
        """
        执行单条 AssertEditor 规则。
        rule = {"target": str, "path": str, "comparator": str, "expect": str}
        """
        target = rule.get("target", "response_json")
        path = rule.get("path", "")
        comparator = rule.get("comparator", "eq")
        expect = str(rule.get("expect", ""))

        # For exists/not_exists, check if extraction succeeds
        if comparator == "not_exists":
            ok, _ = ApiAutomationService._extract_assert_target(target, path, res, header, body)
            passed = not ok
            return {
                "pass": passed,
                "target": target,
                "path": path,
                "comparator": comparator,
                "expect": expect,
                "actual": None,
                "message": "值不存在，通过" if passed else f"值存在但期望不存在",
            }

        ok, actual = ApiAutomationService._extract_assert_target(target, path, res, header, body)
        if not ok:
            if comparator == "exists":
                return {
                    "pass": False,
                    "target": target, "path": path, "comparator": comparator,
                    "expect": expect, "actual": None,
                    "message": f"值不存在：{actual}",
                }
            return {
                "pass": False,
                "target": target, "path": path, "comparator": comparator,
                "expect": expect, "actual": None,
                "message": f"提取失败：{actual}",
            }

        passed, msg = ApiAutomationService._compare_assert(actual, comparator, expect)
        return {
            "pass": passed,
            "target": target,
            "path": path,
            "comparator": comparator,
            "expect": expect,
            "actual": str(actual) if actual is not None else None,
            "message": msg,
        }

    @staticmethod
    async def _local_db_execute(db_model: ApiDatabaseModel, table: str, where: str) -> Any:
        """直连数据库查询，local_db_execute。"""
        try:
            cfg = db_model.config or {}
            host = cfg.get("host") or db_model.host
            user = cfg.get("user") or db_model.username
            password = cfg.get("password") or db_model.password
            database = cfg.get("database") or db_model.database_name
            port = int(cfg.get("port") or db_model.port or 3306)
            conn = pymysql.connect(host=host, user=user, passwd=password, db=database, port=port)
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {table} where {where} limit 1")
            result = [dict(zip([column[0] for column in cur.description], row)) for row in cur.fetchall()]
            cur.close()
            conn.close()
            return result[0] if result else {}
        except Exception as e:
            return f"查询数据库失败，原因是：{str(e)}"

    @staticmethod
    async def test_db_connection(db: AsyncSession, db_id: int, user_id: int) -> Dict[str, Any]:
        """
        测试直连数据库连接是否可用。
        逻辑与 _local_db_execute 获取连接配置的方式一致，只做一次简单连接 + ping。
        """
        row = (
            await db.execute(
                select(ApiDatabaseModel).where(
                    ApiDatabaseModel.id == db_id,
                    ApiDatabaseModel.enabled_flag == 1,
                    ApiDatabaseModel.created_by == user_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            return {"success": False, "message": "数据库配置不存在或已被删除"}

        cfg = row.config or {}
        host = cfg.get("host") or row.host
        user = cfg.get("user") or row.username
        password = cfg.get("password") or row.password
        database = cfg.get("database") or row.database_name
        port = int(cfg.get("port") or row.port or 3306)

        try:
            conn = pymysql.connect(host=host, user=user, passwd=password, db=database, port=port)
            conn.ping(reconnect=True)
            conn.close()
            return {"success": True, "message": "数据库连接成功"}
        except Exception as e:
            return {"success": False, "message": f"数据库连接失败：{str(e)}"}

    @staticmethod
    async def _db_result_assert(rule: Dict[str, Any], actual: str) -> Dict[str, Any]:
        """
        db_result_assert：
        - rule['assert_value'] 为数据库字段值（字符串）
        - actual 为被测值（从响应/请求/常量提取）
        """
        expect = str(rule.get("assert_value", ""))
        name = str(rule.get("name", ""))
        value_expr = str(rule.get("value", ""))
        if expect == actual:
            return {"status": 1, "message": f"断言 {name} = {value_expr} 成功"}
        return {
            "status": 0,
            "message": f"断言 {name} = {value_expr} 失败，实际值为：{name}={expect}, {value_expr}={actual}",
        }

    @staticmethod
    async def _db_assert(rule: Dict[str, Any], res: Dict[str, Any], header: Dict[str, Any], body: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        """db_assert：从响应/请求中取值，与数据库结果字段比较。"""
        try:
            t = int(rule.get("type") or 1)
            if t == 5:
                ok, actual = True, str(rule.get("value", ""))
            else:
                ok, actual = ApiAutomationService._jsonpath_value(
                    res_type=t,
                    expr=str(rule.get("value") or ""),
                    res=res,
                    header=header,
                    body=body,
                )
            if not ok:
                return {"status": 0, "message": actual}
            rule = dict(rule)
            rule["assert_value"] = str(row.get(str(rule.get("name", "")), ""))
            return await ApiAutomationService._db_result_assert(rule, str(actual))
        except Exception as e:
            return {
                "status": 0,
                "message": f"获取断言目标值失败，原因：{str(e)}",
            }

    @staticmethod
    async def _local_db_assert(
        db: AsyncSession,
        rule: Dict[str, Any],
        res: Dict[str, Any],
        header: Dict[str, Any],
        body: Any,
        user_id: int,
    ) -> List[Dict[str, Any]]:
        """
        直连数据库断言，local_db_assert：
        rule 中包含:
        - local_db: 数据库配置ID
        - local_db_table/local_db_where
        - local_db_assert: 断言列表
        """
        try:
            db_id = int(rule.get("local_db") or 0)
            row_model = (
                await db.execute(
                    select(ApiDatabaseModel).where(
                        ApiDatabaseModel.id == db_id,
                        ApiDatabaseModel.enabled_flag == 1,
                        ApiDatabaseModel.created_by == user_id,
                    )
                )
            ).scalar_one_or_none()
            if not row_model:
                return [{"status": 0, "message": "直连-数据库配置不存在"}]
            table = str(rule.get("local_db_table") or "")
            where = str(rule.get("local_db_where") or "1=1")
            db_row = await ApiAutomationService._local_db_execute(row_model, table, where)
            if isinstance(db_row, str):
                return [{"status": 0, "message": db_row}]
            result: List[Dict[str, Any]] = []
            for item in rule.get("local_db_assert") or []:
                r = await ApiAutomationService._db_assert(item, res, header, body, db_row)
                result.append(r)
            return result
        except Exception as e:
            return [{"status": 0, "message": f"直连-数据库断言操作执行失败，原因：{str(e)}"}]

    @staticmethod
    async def _handle_assert(
        db: AsyncSession,
        ops: List[Dict[str, Any]],
        res: Dict[str, Any],
        header: Dict[str, Any],
        body: Any,
        user_id: int,
        env_id: int = 0,
        request_ctx: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        handle_assert：
        - type=1: 响应结果断言（支持新版 rules 数组格式 和 旧版格式）
        - type=4: 直连数据库断言
        - type=5: 自定义断言（Python / JavaScript 脚本）
        """
        from .script_runtime import normalize_language, run_script_async

        results: List[Dict[str, Any]] = []
        response_ctx = {
            "code": res.get("code") or res.get("status_code") or 0,
            "body": res.get("body") if res.get("body") is not None else body,
            "header": res.get("header") or header or {},
            "res_time": res.get("res_time") or 0,
        }
        for op in ops or []:
            if op.get("enabled") is False:
                results.append({"status": 1, "message": "操作已停用，跳过", "type": op.get("type")})
                continue
            try:
                t = int(op.get("type") or 0)
                if t == 1:
                    r = await ApiAutomationService._res_assert(op, res, header, body)
                    r["type"] = t
                    results.append(r)
                elif t == 4:
                    r = {
                        "status": 1,
                        "message": "直连-数据库断言-全部成功",
                        "content": [],
                        "type": t,
                    }
                    content = await ApiAutomationService._local_db_assert(db, op, res, header, body, user_id)
                    r["content"] = content
                    for item in content:
                        if not item.get("status"):
                            r["status"] = 0
                            r["message"] = "直连-数据库断言执行完成，断言出现错误"
                            break
                    results.append(r)
                elif t == 5:
                    script = op.get("custom_script") or op.get("code") or ""
                    language = normalize_language(op.get("language") or "python")
                    name = str(op.get("custom_name") or "").strip()
                    label = f"自定义断言{('：' + name) if name else ''}"
                    if not str(script).strip():
                        results.append({"status": 1, "message": f"{label}：脚本为空，跳过", "type": t, "language": language})
                        continue
                    try:
                        session_vars, env_vars = await ApiAutomationService._load_script_env_maps(
                            db, int(env_id or 0), user_id,
                            temp_vars=request_ctx.get("__temp_vars__") if isinstance(request_ctx, dict) else None,
                        )
                        run_res = await run_script_async(
                            str(script),
                            mode=op.get("exec_mode") or None,
                            language=language,
                            session_vars=session_vars,
                            env_vars=env_vars,
                            request_ctx=request_ctx if isinstance(request_ctx, dict) else None,
                            response_ctx=response_ctx,
                            extra_globals={
                                # 兼容旧版自定义断言注入
                                "status_code": response_ctx.get("code") or 0,
                                "headers": response_ctx.get("header") or {},
                                "res_time": response_ctx.get("res_time") or 0,
                                "body": response_ctx.get("body"),
                            },
                        )
                        if run_res.success:
                            await ApiAutomationService._apply_exported_vars(
                                db, run_res.vars or {}, int(env_id or 0), user_id, request_ctx=request_ctx
                            )
                            results.append({
                                "status": 1,
                                "message": f"{label}：执行通过（{'Python' if language == 'python' else 'JavaScript'}）",
                                "type": t,
                                "language": language,
                                "output": (run_res.output or "")[:5000],
                            })
                        else:
                            err = str(run_res.error or "unknown")
                            is_fail = "assert" in err.lower() or "failed" in err.lower() or "AssertionError" in err
                            results.append({
                                "status": 0,
                                "message": (f"{label}失败：{err}" if is_fail else f"{label}脚本执行错误：{err}"),
                                "type": t,
                                "language": language,
                                "output": (run_res.output or "")[:5000],
                            })
                    except Exception as se:
                        results.append({
                            "status": 0,
                            "message": f"{label}脚本执行错误：{se}",
                            "type": t,
                            "language": language,
                        })
                else:
                    results.append({"status": 0, "message": f"未知断言类型：{t}", "type": t})
            except Exception as e:
                results.append({"status": 0, "message": f"断言操作执行失败，原因：{str(e)}"})
        return results

    @staticmethod
    async def _send_request(method: int, url: str, headers: Dict[str, Any], params: Dict[str, Any], body_type: int, body: Any,
                            form_data: Dict[str, Any], form_urlencoded: Dict[str, Any], file_paths: List[str], config: Dict[str, Any],
                            auth: Any = None) -> Dict[str, Any]:
        timeout = (config.get("req_timeout", 5), config.get("res_timeout", 5))
        ssl_verify = config.get("ssl_verify", True)
        allow_redirects = config.get("allow_redirects", True)
        common = {"timeout": timeout, "verify": ssl_verify, "allow_redirects": allow_redirects, "auth": auth}
        try:
            if method == 1:
                r = requests.get(url, headers=headers, params=params, **common)
            elif method == 2:
                if body_type in (1, 2):
                    if body_type == 2 and isinstance(body, str):
                        # 字符串 body 原样发送（与前置脚本 raw_body 签名一致），避免 requests json= 二次转义
                        # 自动补 Content-Type（否则服务端按表单解析 JSON 导致字段缺失）
                        hdrs = dict(headers)
                        hdrs.setdefault('Content-Type', 'application/json')
                        r = requests.post(url, headers=hdrs, params=params, data=body.encode('utf-8'), **common)
                    else:
                        r = requests.post(url, headers=headers, params=params, json=(body if body_type == 2 else {}), **common)
                elif body_type == 3:
                    r = requests.post(url, headers=headers, params=params, data=form_data, **common)
                elif body_type == 4:
                    r = requests.post(url, headers=headers, params=params, data=form_urlencoded, **common)
                elif body_type == 5:
                    files = []
                    for p in file_paths or []:
                        files.append(("file", (p.split("/")[-1], open(p, "rb"), "application/octet-stream")))
                    r = requests.request("POST", url=url, headers=headers, params=params, files=files, data={}, **common)
                else:
                    r = requests.post(url, headers=headers, params=params, json=body, **common)
            elif method == 3:
                r = requests.put(url, headers=headers, params=params, json=body, **common)
            elif method == 4:
                r = requests.delete(url, headers=headers, params=params, **common)
            elif method == 5:
                r = requests.patch(url, headers=headers, params=params, json=body, **common)
            elif method == 6:
                r = requests.options(url, headers=headers, params=params, **common)
            else:
                r = requests.request("GET", url=url, headers=headers, params=params, **common)

            try:
                body_json = r.json()
            except Exception:
                body_json = {"raw": r.text}

            # cookies
            cookies_list = [
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain or "",
                    "path": c.path or "/",
                    "expires": str(c.expires) if c.expires else "",
                    "httpOnly": False,
                    "secure": bool(c._rest.get("Secure")) if hasattr(c, "_rest") else False,
                }
                for c in r.cookies
            ]

            # raw_request — actual request sent by requests
            prep = r.request
            raw_req_headers = dict(prep.headers) if prep and prep.headers else {}
            raw_req_body = ""
            if prep and prep.body:
                try:
                    raw_req_body = prep.body.decode("utf-8") if isinstance(prep.body, bytes) else str(prep.body)
                except Exception:
                    raw_req_body = str(prep.body)

            return {
                "code": r.status_code,
                "res_time": str(round(r.elapsed.total_seconds() * 1000, 2)),
                "body": body_json,
                "header": dict(r.headers),
                "size": str((len(r.text.encode("utf-8")) if r.text else 0) + (len(str(r.headers).encode("utf-8")))),
                "cookies": cookies_list,
                "raw_request": {
                    "method": prep.method if prep else "",
                    "url": prep.url if prep else url,
                    "headers": raw_req_headers,
                    "body": raw_req_body,
                },
            }
        except Exception as e:
            return {
                "code": 500,
                "body": {"msg": "接口请求失败", "exception": str(e)},
                "header": {},
                "size": 0,
                "res_time": 0,
                "cookies": [],
                "raw_request": {"method": "", "url": url, "headers": {}, "body": ""},
            }

    @staticmethod
    @staticmethod
    async def ws_test(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """WebSocket 调试代理：连接 -> 发送 -> 接收（带超时）；binary_type=base64/hex 时按编码发送二进制"""
        import asyncio
        import base64
        import json
        import time

        import websockets

        url = str(body.get("url") or "").strip()
        if not url:
            raise ValueError("WebSocket 地址不能为空")
        if not (url.startswith("ws://") or url.startswith("wss://")):
            raise ValueError("地址必须以 ws:// 或 wss:// 开头")
        headers = {}
        for h in body.get("headers") or []:
            if isinstance(h, dict) and h.get("status") and h.get("key"):
                headers[str(h["key"])] = str(h.get("value") or "")
        message = body.get("message")
        sent_text = message if isinstance(message, str) else json.dumps(message, ensure_ascii=False)
        ssl_verify = bool(body.get("ssl_verify", True))
        binary_type = str(body.get("binary_type") or "").lower()
        if binary_type == "base64":
            try:
                payload: Any = base64.b64decode(sent_text, validate=True)
            except Exception:
                raise ValueError("Base64 解码失败，请检查输入内容")
        elif binary_type == "hex":
            try:
                payload = bytes.fromhex(sent_text)
            except Exception:
                raise ValueError("十六进制解析失败，请输入如 0A FF 01（可含空格）")
        else:
            payload = sent_text
        connect_kwargs: Dict[str, Any] = {"additional_headers": headers, "open_timeout": 8}
        if url.startswith("wss://") and not ssl_verify:
            import ssl

            _ctx = ssl.create_default_context()
            _ctx.check_hostname = False
            _ctx.verify_mode = ssl.CERT_NONE
            connect_kwargs["ssl"] = _ctx
        t0 = time.time()
        try:
            async with websockets.connect(url, **connect_kwargs) as ws:
                await ws.send(payload)
                received = await asyncio.wait_for(ws.recv(), timeout=8)
            if isinstance(received, bytes):
                try:
                    received = received.decode("utf-8")
                except Exception:
                    received = "0x" + received.hex()
            return {
                "ok": True,
                "sent": sent_text,
                "received": received if isinstance(received, str) else str(received),
                "binary_type": binary_type or None,
                "elapsed": round(time.time() - t0, 3),
            }
        except asyncio.TimeoutError:
            return {
                "ok": True,
                "sent": sent_text,
                "received": None,
                "timeout": True,
                "elapsed": round(time.time() - t0, 3),
            }
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "sent": sent_text,
                "error": str(e),
                "elapsed": round(time.time() - t0, 3),
            }

    async def execute_api_send(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """
       输入 body 基本结构
        """
        env_id = int(body.get("env_id") or 0)
        req = body.get("req") or {}
        if not isinstance(req, dict):
            req = {}
        if str(req.get("protocol") or "http").lower() == "websocket":
            raise ValueError("WebSocket 接口暂不支持自动化执行，请使用调试页手动调试（对齐 Apifox：WS 不支持脚本/断言）")

        # 服务级全局参数（Header/Cookie/Query/Body），请求侧同名覆盖
        api_id = int(body.get("id") or req.get("id") or 0)
        # 解析 api_service_id（两级全局变量按服务解析项目/部门）
        api_service_id = body.get("api_service_id")
        if not api_service_id and api_id:
            _api_row = (await db.execute(select(ApiModel).where(ApiModel.id == api_id))).scalar_one_or_none()
            api_service_id = int(_api_row.api_service_id) if _api_row and _api_row.api_service_id else None
        common = await ApiAutomationService._load_common_params_by_api(db, api_id=api_id or None)
        req = ApiAutomationService.apply_common_params_to_req(req, common)

        # 可被前置脚本改写的请求上下文
        request_ctx: Dict[str, Any] = {
            "url": body.get("url") or req.get("url") or "",
            "method": req.get("method"),
            "header": req.get("header"),
            "params": req.get("params"),
            "body": req.get("body"),
            "body_type": req.get("body_type"),
            # raw_body：请求体字符串形态（签名脚本用），恒为字符串
            "raw_body": req.get("body") if isinstance(req.get("body"), str)
                        else json.dumps(req.get("body"), ensure_ascii=False, default=str) if req.get("body") is not None
                        else "",
            "__base_url__": "", 
            "form_data": req.get("form_data"),
            "form_urlencoded": req.get("form_urlencoded"),
            "file_path": req.get("file_path"),
            "config": req.get("config"),
            "cookies": req.get("cookies"),
            "__temp_vars__": {},
        }

        # Apifox 语义：内置 BASE_URL（当前接口解析出的前置 URL），用户手动定义环境变量 BASE_URL 时优先
        try:
            _raw_u = str(request_ctx.get("url") or "").strip()
            _fu = await ApiAutomationService.handle_var(db, env_id, _raw_u, api_service_id=api_service_id,
                                                       temp_vars=request_ctx.get("__temp_vars__"))
            _, _base = await ApiAutomationService._resolve_base_url(db, env_id, str(_fu or "").strip(),
                                                                   api_id=api_id, return_base=True)
            request_ctx["__base_url__"] = _base
            if _base:
                _env_row2 = (
                    await db.execute(
                        select(ApiEnvironmentModel).where(
                            ApiEnvironmentModel.id == int(env_id),
                            ApiEnvironmentModel.enabled_flag == 1,
                        )
                    )
                ).scalar_one_or_none()
                _manual = False
                if _env_row2:
                    for _v in (_env_row2.variable or []):
                        if isinstance(_v, dict) and str(_v.get("name") or "").upper() == "BASE_URL":
                            _manual = True
                            break
                if not _manual:
                    request_ctx.setdefault("__temp_vars__", {})["BASE_URL"] = _base
        except Exception:
            pass

        # 前置脚本执行前先完成 body 变量替换：脚本拿到的 raw_body 必须与最终发送一致（签名场景必需）
        _body_raw = request_ctx.get("body")
        if isinstance(_body_raw, str) and "{{" in _body_raw:
            _body_new = await ApiAutomationService.handle_var(
                db, env_id, _body_raw,
                api_service_id=api_service_id,
                temp_vars=request_ctx.get("__temp_vars__"),
            )
            if _body_new != _body_raw:
                request_ctx["body"] = _body_new
                request_ctx["raw_body"] = _body_new
        elif isinstance(_body_raw, dict):
            _body_new = await ApiAutomationService.handle_var(
                db, env_id, _body_raw,
                api_service_id=api_service_id,
                temp_vars=request_ctx.get("__temp_vars__"),
            )
            if _body_new != _body_raw:
                request_ctx["body"] = _body_new
                request_ctx["raw_body"] = json.dumps(_body_new, ensure_ascii=False, default=str)

        before_ops = req.get("before") or []
        after_ops = req.get("after") or []
        assert_ops = req.get("assert") or []

        before_list: List[Dict[str, Any]] = []
        if before_ops:
            before_list = await ApiAutomationService._pre_request(
                db=db,
                ops=before_ops,
                env_id=env_id,
                user_id=user_id,
                request_ctx=request_ctx,
            )

        # 前置可能改写 request_ctx / 环境变量，回写后再做变量替换
        if request_ctx.get("url") is not None:
            req["url"] = request_ctx.get("url")
        for k in ("header", "params", "body", "body_type", "form_data", "form_urlencoded", "file_path", "config", "method", "cookies"):
            if k in request_ctx and request_ctx.get(k) is not None:
                req[k] = request_ctx.get(k)

        raw_url = request_ctx.get("url") or body.get("url") or req.get("url") or ""
        url = await ApiAutomationService.handle_var(db, env_id, raw_url, api_service_id=api_service_id, temp_vars=request_ctx.get("__temp_vars__"))
        url = str(url or "").strip()
        url, base = await ApiAutomationService._resolve_base_url(db, env_id, url, api_id=api_id, return_base=True)
        if "{{" in url and "}}" in url:
            hint = "请先在右上角选择环境，并在环境管理为该模块配置前置 URL"
            if not env_id:
                raise ValueError(f"URL 中的环境变量未替换（未选择环境）。{hint} 当前 URL：{url}")
            raise ValueError(f"URL 中的环境变量未替换。{hint} 当前 URL：{url}")
        if url and not re.match(r"^https?://", url, re.I):
            raise ValueError(
                f"URL 缺少协议（http/https），当前为：{url}。"
                "请在环境管理中为该接口所属模块配置前置 URL（https:// 起始）。"
            )

        body_payload = await ApiAutomationService.handle_var(db, env_id, req.get("body") or {}, api_service_id=api_service_id, temp_vars=request_ctx.get("__temp_vars__"))
        method = int(req.get("method") or 2)
        body_type = int(req.get("body_type") or 2)
        headers = await ApiAutomationService.handle_var(db, env_id, ApiAutomationService.params_header(req.get("header")), api_service_id=api_service_id, temp_vars=request_ctx.get("__temp_vars__"))
        params = await ApiAutomationService.handle_var(db, env_id, ApiAutomationService.params_header(req.get("params")), api_service_id=api_service_id, temp_vars=request_ctx.get("__temp_vars__"))
        form_data = await ApiAutomationService.handle_var(db, env_id, ApiAutomationService.params_header(req.get("form_data")), api_service_id=api_service_id, temp_vars=request_ctx.get("__temp_vars__"))
        form_urlencoded = await ApiAutomationService.handle_var(db, env_id, ApiAutomationService.params_header(req.get("form_urlencoded")), temp_vars=request_ctx.get("__temp_vars__"))
        file_paths = req.get("file_path") or []
        config = req.get("config") if isinstance(req.get("config"), dict) else None
        config = config or {"retry": 0, "req_timeout": 5, "res_timeout": 5}

        headers, params, req_auth = await ApiAutomationService.apply_request_auth(
            db, env_id, req, headers=headers, params=params,
            temp_vars=request_ctx.get("__temp_vars__") if isinstance(request_ctx, dict) else None,
            common_auth=(common or {}).get("auth") if isinstance(common, dict) else None,
        )

        res = await ApiAutomationService._send_request(
            method=method,
            url=str(url),
            headers=headers,
            params=params,
            body_type=body_type,
            body=body_payload,
            form_data=form_data,
            form_urlencoded=form_urlencoded,
            file_paths=file_paths,
            config=config,
            auth=req_auth,
        )

        after_list: List[Dict[str, Any]] = []
        if after_ops:
            after_list = await ApiAutomationService._after_request(
                db=db,
                ops=after_ops,
                res=res,
                header=headers,
                body=body_payload,
                env_id=env_id,
                user_id=user_id,
                request_ctx=request_ctx,
            )

        assert_list: List[Dict[str, Any]] = []
        if assert_ops:
            assert_list = await ApiAutomationService._handle_assert(
                db=db,
                ops=assert_ops,
                res=res,
                header=headers,
                body=body_payload,
                user_id=user_id,
                env_id=env_id,
                request_ctx=request_ctx,
            )

        res["before"] = before_list
        res["after"] = after_list
        res["assert"] = assert_list
        res["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # console: 接口执行信息（前置脚本输出 / 请求 / 变量设置 / 后置 / 断言）
        console_logs: List[Dict[str, Any]] = []
        for item in before_list:
            level = "info" if item.get("status") == 1 else "error"
            console_logs.append({"level": level, "msg": f"[前置] {item.get('message', '')}", "output": item.get("output") or ""})
            for k, v in (item.get("vars") or {}).items():
                console_logs.append({"level": "info", "msg": f"[变量] 已设置环境变量【{k}】，值为【{v}】"})
        raw_req = res.get("raw_request") or {}
        console_logs.append({
            "level": "info" if int(res.get("code") or 0) < 400 else "error",
            "msg": f"[请求] {raw_req.get('method', '')} {raw_req.get('url', '')} → {res.get('code')} ({res.get('res_time')} ms)",
        })
        for item in after_list:
            level = "info" if item.get("status") == 1 else "error"
            console_logs.append({"level": level, "msg": f"[后置] {item.get('message', '')}", "output": item.get("output") or ""})
            for k, v in (item.get("vars") or {}).items():
                console_logs.append({"level": "info", "msg": f"[变量] 已设置环境变量【{k}】，值为【{v}】"})
        for item in assert_list:
            level = "info" if item.get("status") == 1 else "error"
            console_logs.append({"level": level, "msg": f"[断言] {item.get('message', '')}", "output": item.get("output") or ""})
        res["console"] = console_logs

        db.add(
            ApiResultModel(
                req={
                    "url": url,
                    "body": req.get("body"),
                    "params": req.get("params"),
                    "header": req.get("header"),
                    "form_data": req.get("form_data"),
                    "file_path": file_paths,
                    "form_urlencoded": req.get("form_urlencoded"),
                    "config": config,
                    "body_type": body_type,
                    "method": method,
                    "before": req.get("before") or [],
                    "after": req.get("after") or [],
                    "assert": req.get("assert") or [],
                },
                res=res,
                api_id=int(body.get("id") or 0),
                status_code=int(res.get("code") or 0),
                response_time=float(res.get("res_time") or 0),
                error_message=(res.get("body") or {}).get("exception") if int(res.get("code") or 0) >= 400 else None,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        await db.commit()
        return res

    # -------------------- 用例执行与结果 --------------------
    @staticmethod
    async def _new_uuid() -> str:
        return str(uuid.uuid4())

    @staticmethod
    async def run_api_script(db: AsyncSession, data: Dict[str, Any], user_id: int) -> None:
        """

        请求体关键字段：
        - result_id: 执行批次ID
        - name: 任务名称
        - config: {"env_id": int, ...}
        - run_list: [
            {
              "name": "...",
              "config": {"params_id": ..., ...},
              "script": [
                {"name": "...", "api_id": int, ...},
                ...
              ]
            },
            ...
          ]
        """
        result_id = str(data["result_id"])
        env_id = int(data["config"]["env_id"])
        try:
            # 创建汇总记录
            summary = ApiScriptResultListModel(
                result_id=int(result_id),
                name=data["name"],
                script=[],
                config=data.get("config") or {},
                result={},
                api_service_id=data.get("api_service_id"),
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(summary)
            await db.flush()

            all_pass = 0
            all_fail = 0
            total = 0
            execution_aborted = False

            for case in data.get("run_list", []):
                if ApiAutomationService._is_api_script_result_cancel_requested(result_id):
                    execution_aborted = True
                    break
                case["status"] = 1
                case["pass"] = 0
                case["fail"] = 0
                case_uuid = await ApiAutomationService._new_uuid()
                case["uuid"] = case_uuid

                for step in case.get("script", []):
                    if ApiAutomationService._is_api_script_result_cancel_requested(result_id):
                        execution_aborted = True
                        break

                    total += 1
                    step_uuid = await ApiAutomationService._new_uuid()
                    step["uuid"] = step_uuid

                    await ApiAutomationService._write_log_line(
                        case_uuid, result_id, f"开始执行步骤-{step.get('name')}"
                    )

                    # 使用 StepExecutor 支持多步骤类型
                    from .step_executor import StepExecutor, VariableContext
                    if not hasattr(ApiAutomationService, '_step_ctx_cache'):
                        ApiAutomationService._step_ctx_cache = {}
                    ctx_key = f"{result_id}_{case_uuid}"
                    # step_rely 从 case 配置中读取，默认为 True（步骤间共享变量）
                    step_rely = bool(int(case.get("config", {}).get("step_rely", 1)))
                    if ctx_key not in ApiAutomationService._step_ctx_cache:
                        env_vars = await ApiAutomationService._load_env_vars(db, env_id)
                        ApiAutomationService._step_ctx_cache[ctx_key] = VariableContext(env_vars)
                    ctx = ApiAutomationService._step_ctx_cache[ctx_key]

                    async def _log_fn(msg: str):
                        await ApiAutomationService._write_log_line(case_uuid, result_id, msg)

                    executor = StepExecutor(
                        db=db,
                        env_id=env_id,
                        user_id=user_id,
                        result_id=result_id,
                        ctx=ctx,
                        log_fn=_log_fn,
                        cancel_fn=lambda: ApiAutomationService._is_api_script_result_cancel_requested(result_id),
                        step_rely=step_rely,
                    )

                    step_result = await executor.execute(step)
                    success = step_result.success
                    api_req = step_result.request or {}
                    api_res = step_result.response or {}
                    # 写入日志
                    for log_line in step_result.logs:
                        await ApiAutomationService._write_log_line(case_uuid, result_id, log_line)

                    if success:
                        case["pass"] += 1
                        all_pass += 1
                    else:
                        case["status"] = 0
                        case["fail"] += 1
                        all_fail += 1

                    # 写入步骤详情，供执行监控统计总数/失败数
                    if not api_res and step_result.error:
                        api_res = {
                            "code": 500,
                            "body": {"msg": "步骤执行失败", "exception": step_result.error},
                            "header": {},
                            "size": 0,
                            "res_time": 0,
                        }
                    db.add(
                        ApiScriptResultModel(
                            name=step.get("name") or step_result.name or "",
                            uuid=step_uuid,
                            menu_id=case_uuid,
                            result_id=int(result_id),
                            status=1 if success else 0,
                            req=api_req,
                            res=api_res,
                            created_by=user_id,
                            updated_by=user_id,
                        )
                    )
                    await db.flush()

                    await ApiAutomationService._write_log_line(
                        case_uuid, result_id, f"接口-{step.get('name')}执行完成"
                    )
                    await ApiAutomationService._api_script_delay_seconds(result_id, 3.0)

                if execution_aborted:
                    break

            if execution_aborted:
                base_dir = ApiAutomationService._get_api_result_dir(result_id)
                all_log = base_dir / f"{result_id}.txt"
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ApiAutomationService._append_log_file(all_log, f"{now} 用户已请求停止，执行中断 ")

            percent = round(all_pass / total * 100, 2) if total else 0
            summary.script = data.get("run_list") or []
            summary.result = {
                "total": total,
                "pass": all_pass,
                "fail": all_fail,
                "percent": percent,
                "stopped": execution_aborted,
            }
            summary.end_time = datetime.now()
            await db.flush()

            # 结束标记
            end_row = ApiScriptResultModel(
                name="执行结束",
                uuid="",
                menu_id="",
                result_id=int(result_id),
                status=1,
                req={},
                res={},
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(end_row)
            await db.commit()

            notice_data = {
                "task_name": data.get("name"),
                "result_id": result_id,
                "total": total,
                "passed": all_pass,
                "fail": all_fail,
                "un_run": total - all_pass - all_fail,
                "percent": percent,
            }
            await ApiAutomationService._send_notice(db, 33, "api_report", notice_data, user_id=user_id)
        finally:
            ApiAutomationService._clear_api_script_cancel(result_id)

    # 结果查询 & 日志
    @staticmethod
    async def get_script_result(db: AsyncSession, result_id: int, user_id: int) -> List[Dict[str, Any]]:
        own = (
            await db.execute(
                select(ApiScriptResultListModel.id).where(
                    ApiScriptResultListModel.enabled_flag == 1,
                    ApiScriptResultListModel.result_id == result_id,
                    ApiScriptResultListModel.created_by == user_id,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if own is None:
            return []
        stmt = (
            select(ApiScriptResultModel)
            .where(
                ApiScriptResultModel.enabled_flag == 1,
                ApiScriptResultModel.result_id == result_id,
            )
            .order_by(ApiScriptResultModel.id.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        data: List[Dict[str, Any]] = []
        for r in rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            data.append(d)
        return data

    @staticmethod
    async def get_script_result_list(
        db: AsyncSession,
        user_id: int,
        page: int,
        page_size: int,
        search_name: str = "",
        api_service_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        stmt = select(ApiScriptResultListModel).where(
            ApiScriptResultListModel.enabled_flag == 1,
            ApiScriptResultListModel.created_by == user_id,
        )
        name_kw = (search_name or "").strip()
        if name_kw:
            stmt = stmt.where(ApiScriptResultListModel.name.contains(name_kw))
        if api_service_id:
            stmt = stmt.where(ApiScriptResultListModel.api_service_id == int(api_service_id))
        stmt = stmt.order_by(ApiScriptResultListModel.id.desc())
        rows = (await db.execute(stmt)).scalars().all()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows[start:end]
        user_ids = [int(r.created_by) for r in page_rows if getattr(r, "created_by", None)]
        username_map = await _get_username_map(db, user_ids)
        content: List[Dict[str, Any]] = []
        for r in page_rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            stopped = bool((r.result or {}).get("stopped"))
            d["status"] = 2 if stopped else (0 if r.end_time is None else 1)
            uid = getattr(r, "created_by", None)
            d["username"] = username_map.get(int(uid), "") if uid else ""
            content.append(d)
        return {"content": content, "total": total, "page": page, "pageSize": page_size}

    @staticmethod
    async def stop_api_script_result(db: AsyncSession, result_id: int, user_id: int) -> Dict[str, Any]:
        row = (
            await db.execute(
                select(ApiScriptResultListModel).where(
                    ApiScriptResultListModel.enabled_flag == 1,
                    ApiScriptResultListModel.result_id == result_id,
                    ApiScriptResultListModel.created_by == user_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            return {"stopped": False, "message": "未找到执行记录"}
        if row.end_time is not None:
            return {"stopped": False, "message": "任务已结束"}
        ApiAutomationService._request_cancel_api_script_result(str(result_id))
        row.result = {**(row.result or {}), "stopped": True}
        await db.flush()
        await db.commit()
        return {"stopped": True, "message": "已请求停止"}

    @staticmethod
    async def delete_api_script_result(db: AsyncSession, result_id: int, user_id: int) -> Dict[str, Any]:
        row = (
            await db.execute(
                select(ApiScriptResultListModel).where(
                    ApiScriptResultListModel.enabled_flag == 1,
                    ApiScriptResultListModel.result_id == result_id,
                    ApiScriptResultListModel.created_by == user_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            return {"deleted": False, "message": "未找到执行记录"}
        if row.end_time is None:
            ApiAutomationService._request_cancel_api_script_result(str(result_id))
        await db.execute(
            delete(ApiScriptResultModel).where(ApiScriptResultModel.result_id == result_id)
        )
        await db.execute(
            delete(ApiScriptResultListModel).where(
                ApiScriptResultListModel.result_id == result_id,
                ApiScriptResultListModel.created_by == user_id,
            )
        )
        await db.commit()
        ApiAutomationService._remove_api_result_files(str(result_id))
        ApiAutomationService._clear_api_script_cancel(str(result_id))
        return {"deleted": True, "message": "已删除"}

    @staticmethod
    async def get_script_result_detail(db: AsyncSession, result_id: int) -> Optional[Dict[str, Any]]:
        stmt = select(ApiScriptResultListModel).where(
            ApiScriptResultListModel.enabled_flag == 1,
            ApiScriptResultListModel.result_id == result_id,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        d = row.__dict__.copy()
        d.pop("_sa_instance_state", None)
        return d

    @staticmethod
    async def get_script_result_detail_list(db: AsyncSession, result_id: int, menu_id: str) -> List[Dict[str, Any]]:
        stmt = (
            select(ApiScriptResultModel)
            .where(
                ApiScriptResultModel.enabled_flag == 1,
                ApiScriptResultModel.result_id == result_id,
                ApiScriptResultModel.menu_id == menu_id,
            )
            .order_by(ApiScriptResultModel.id.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        data: List[Dict[str, Any]] = []
        for r in rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            data.append(d)
        return data

    @staticmethod
    async def get_script_result_report_list(db: AsyncSession, result_id: int, menu_id: str) -> List[Dict[str, Any]]:
        """对 /get_api_script_result_report_list：与 detail_list 一致"""
        return await ApiAutomationService.get_script_result_detail_list(db, result_id, menu_id)

  
    @staticmethod
    async def _find_keys_not_in_params(a_list: List[Dict[str, Any]], b_list: List[Dict[str, Any]]) -> List[str]:
        a_keys = {item.get("key") for item in (a_list or []) if item.get("key") is not None}
        b_keys = {item.get("key") for item in (b_list or []) if item.get("key") is not None}
        return list(b_keys - a_keys)

    @staticmethod
    async def _find_keys_not_in_dict(a: Dict[str, Any], b: Dict[str, Any], parent_key: str = "") -> List[str]:
        keys_not_in_a: List[str] = []
        for key in (b or {}):
            full_key = f"{parent_key}.{key}" if parent_key else str(key)
            if key not in (a or {}):
                keys_not_in_a.append(full_key)
            else:
                if isinstance(b[key], dict) and isinstance((a or {}).get(key), dict):
                    keys_not_in_a.extend(await ApiAutomationService._find_keys_not_in_dict((a or {})[key], b[key], full_key))
                elif isinstance(b[key], list) and isinstance((a or {}).get(key), list):
                    for i, item in enumerate(b[key]):
                        if isinstance(item, dict) and i < len((a or {})[key]) and isinstance((a or {})[key][i], dict):
                            keys_not_in_a.extend(
                                await ApiAutomationService._find_keys_not_in_dict((a or {})[key][i], item, f"{full_key}[{i}]")
                            )
        return keys_not_in_a

    @staticmethod
    async def _handle_check(old_headers, old_params, old_body, new_headers, new_params, new_body) -> List[Dict[str, Any]]:
        if not new_body:
            new_body = {}
        header_add = await ApiAutomationService._find_keys_not_in_params(old_headers or [], new_headers or [])
        params_add = await ApiAutomationService._find_keys_not_in_params(old_params or [], new_params or [])
        body_add = await ApiAutomationService._find_keys_not_in_dict(old_body or {}, new_body or {})

        header_del = await ApiAutomationService._find_keys_not_in_params(new_headers or [], old_headers or [])
        params_del = await ApiAutomationService._find_keys_not_in_params(new_params or [], old_params or [])
        body_del = await ApiAutomationService._find_keys_not_in_dict(new_body or {}, old_body or {})
        return [
            {"key": "headers", "add": header_add, "delete": header_del},
            {"key": "params", "add": params_add, "delete": params_del},
            {"key": "body", "add": body_add, "delete": body_del},
        ]

    @staticmethod
    async def _gitlab_handle_data(content_type: str, method: str) -> Tuple[int, int]:
        ct = content_type or ""
        if "application/json" in ct:
            body_type = 2
        elif "application/x-www-form-urlencoded" in ct:
            body_type = 4
        elif "form-data" in ct:
            body_type = 3
        else:
            body_type = 1
        m = (method or "").lower()
        http_method = 2
        if m == "get":
            http_method = 1
        elif m == "post":
            http_method = 2
        elif m == "put":
            http_method = 3
        elif m == "delete":
            http_method = 4
        return body_type, http_method

    @staticmethod
    async def _gitlab_handle_header(header_params: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if header_params:
            return [{"key": i.get("name"), "value": i.get("example"), "status": True} for i in header_params]
        return [{"key": "Content-Type", "value": "application/json", "status": True}]

    @staticmethod
    async def _gitlab_handle_params(params: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not params:
            return []
        return [{"key": j.get("name"), "value": j.get("example"), "status": True} for j in params]

    @staticmethod
    async def _gitlab_handle_body(body_params: List[Dict[str, Any]]) -> Dict[str, Any]:
 
        def handle_object(children: List[Dict[str, Any]]) -> Dict[str, Any]:
            out: Dict[str, Any] = {}
            for c in children or []:
                t = c.get("type")
                name = c.get("name")
                if not name:
                    continue
                if t == "object":
                    out[name] = handle_object(c.get("children") or [])
                elif t == "array":
                    out[name] = [handle_object(c.get("children") or [])]
                else:
                    out[name] = c.get("example")
            return out

        return handle_object(body_params or [])

    @staticmethod
    async def handle_gitlab_import(db: AsyncSession, apis: List[Dict[str, Any]], service_id: int, user_id: int) -> Dict[str, int]:
        service = (
            await db.execute(select(ApiServiceModel).where(ApiServiceModel.id == service_id, ApiServiceModel.enabled_flag == 1))
        ).scalar_one()
        service_name = "{{" + service.name + "}}"

   
        await db.execute(
            update(ApiMenuModel)
            .where(ApiMenuModel.api_service_id == service_id, ApiMenuModel.type == 2, ApiMenuModel.enabled_flag == 1)
            .values(status=0, updated_by=user_id)
        )

        async def get_or_create_menu(name: str, m_type: int, pid: int) -> int:
            row = (
                await db.execute(
                    select(ApiMenuModel).where(
                        ApiMenuModel.enabled_flag == 1,
                        ApiMenuModel.api_service_id == service_id,
                        ApiMenuModel.name == name,
                        ApiMenuModel.type == m_type,
                    )
                )
            ).scalar_one_or_none()
            if row:
                await db.execute(update(ApiMenuModel).where(ApiMenuModel.id == row.id).values(status=1, updated_by=user_id))
                return row.id
            menu = ApiMenuModel(
                name=name,
                type=m_type,
                pid=pid,
                api_service_id=service_id,
                status=1,
                api_id=None,
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(menu)
            await db.flush()
            return menu.id

        imported_count = 0
        updated_count = 0
        unchanged_count = 0
        folder_names = set()
        service_apis = list(
            (
                await db.execute(
                    select(ApiModel).where(
                        ApiModel.enabled_flag == 1,
                        ApiModel.api_service_id == service_id,
                    )
                )
            ).scalars().all()
        )

        for i in apis or []:
            if int(i.get("isFolder") or 0) != 1:
                continue
            first_id = await get_or_create_menu(i.get("name") or "", 0, 0)
            folder_names.add(str(i.get("name") or ""))
            for j in i.get("items") or []:
                if int(j.get("isFolder") or 0) != 1:
                    continue
                menu_id = await get_or_create_menu(j.get("name") or "", 1, first_id)
                folder_names.add(str(j.get("name") or ""))
                for k in j.get("items") or []:
                    try:
                        body_type, method = await ApiAutomationService._gitlab_handle_data(k.get("contentType") or "", k.get("httpMethod") or "")
                        params = await ApiAutomationService._gitlab_handle_params(k.get("queryParams") or [])
                        header = await ApiAutomationService._gitlab_handle_header(k.get("headerParams") or [])
                        body = await ApiAutomationService._gitlab_handle_body(k.get("requestParams") or [])
                        url = str(k.get("url") or "/")

                        api_row = ApiAutomationService._find_api_by_path_and_method(
                            service_apis, url, int(method)
                        )
                        if not api_row:
                            api_row = ApiAutomationService._find_api_by_path_and_method(
                                service_apis, service_name + url, int(method)
                            )

                        if api_row:
                            old_req = api_row.req or {}
                            req = {
                                "body_type": body_type,
                                "method": method,
                                "header": header,
                                "params": params,
                                "params_id": None,
                                "body": body,
                                "before": (old_req.get("before") or []),
                                "after": (old_req.get("after") or []),
                                "form_data": (old_req.get("form_data") or []),
                                "form_urlencoded": (old_req.get("form_urlencoded") or []),
                                "file_path": (old_req.get("file_path") or []),
                                "assert": (old_req.get("assert") or []),
                                "config": {"retry": 0, "req_timeout": 5, "res_timeout": 5},
                            }
                            key_check = await ApiAutomationService._handle_check(
                                old_req.get("header") or [],
                                old_req.get("params") or [],
                                old_req.get("body") or {},
                                header,
                                params,
                                body,
                            )
                            if key_check:
                                for m in key_check:
                                    if m.get("add") or m.get("delete"):
                                        db.add(
                                            ApiUpdateModel(
                                                req=key_check,
                                                api_id=int(api_row.id),
                                                api_service_id=int(service_id),
                                                created_by=user_id,
                                                updated_by=user_id,
                                            )
                                        )
                                        break
                            new_url = ApiAutomationService._prefer_existing_url(
                                str(api_row.url or ""),
                                service_name + url,
                            )
                            if service_name not in new_url and not re.match(r"^https?://", new_url, re.I):
                                # 无前置时仍按历史逻辑补上服务名占位
                                new_url = service_name + url
                            req["url"] = new_url
                            await db.execute(
                                update(ApiModel)
                                .where(ApiModel.id == api_row.id, ApiModel.enabled_flag == 1)
                                .values(
                                    url=new_url,
                                    req=req,
                                    document=k,
                                    updated_by=user_id,
                                )
                            )
                            api_id = api_row.id
                            updated_count += 1
                        else:
                            req = {
                                "body_type": body_type,
                                "method": method,
                                "header": header,
                                "params": params,
                                "body": body,
                                "before": [],
                                "after": [],
                                "form_data": [],
                                "form_urlencoded": [],
                                "file_path": [],
                                "assert": [],
                                "config": {"retry": 0, "req_timeout": 5, "res_timeout": 5},
                                "url": service_name + url,
                            }
                            api_value = ApiModel(
                                api_service_id=service_id,
                                url=service_name + url,
                                req=req,
                                document=k,
                                created_by=user_id,
                                updated_by=user_id,
                            )
                            db.add(api_value)
                            await db.flush()
                            api_id = api_value.id
                            service_apis.append(api_value)
                            imported_count += 1

                        # 菜单叶子节点（type=2）
                        leaf_name = k.get("name") or url
                        leaf_row = (
                            await db.execute(
                                select(ApiMenuModel).where(
                                    ApiMenuModel.enabled_flag == 1,
                                    ApiMenuModel.api_service_id == service_id,
                                    ApiMenuModel.type == 2,
                                    ApiMenuModel.api_id == int(api_id),
                                )
                            )
                        ).scalar_one_or_none()
                        if leaf_row:
                            await db.execute(update(ApiMenuModel).where(ApiMenuModel.id == leaf_row.id).values(status=1, updated_by=user_id))
                        else:
                            db.add(
                                ApiMenuModel(
                                    name=str(leaf_name),
                                    type=2,
                                    pid=int(menu_id),
                                    api_service_id=int(service_id),
                                    api_id=int(api_id),
                                    status=1,
                                    created_by=user_id,
                                    updated_by=user_id,
                                )
                            )
                    except Exception:
                        continue
        await db.commit()
        return {"imported": imported_count, "updated": updated_count, "unchanged": unchanged_count, "folders": len(folder_names)}

    @staticmethod
    async def service_api_update(db: AsyncSession, body: Dict[str, Any]) -> None:
        """对service_api_update（开放给文档平台）"""
        if body.get("token") != "1fefb62cdd834925983f72c2bc9b9c55":
            raise ValueError("检验token失败，请联系-管理员")

        # author -> sys_user.username
        author = str(body.get("author") or "")
        u = await UserCRUD(db).get_by_username_crud(author)
        if not u:
            raise ValueError("author 对应用户不存在")
        user_id = int(u.id)

        server_name = str(body.get("serverName") or "")
        if not server_name:
            raise ValueError("serverName 不能为空")

    
        is_overseas = "overseas" in server_name
        project_name = "海外项目" if is_overseas else "国内项目"
        proj = (
            await db.execute(
                select(ApiProjectModel).where(ApiProjectModel.enabled_flag == 1, ApiProjectModel.name == project_name)
            )
        ).scalar_one_or_none()
        if not proj:
            proj = ApiProjectModel(name=project_name, img="", description="", created_by=1, updated_by=1)
            db.add(proj)
            await db.flush()

        service = (
            await db.execute(
                select(ApiServiceModel).where(ApiServiceModel.enabled_flag == 1, ApiServiceModel.name == server_name)
            )
        ).scalar_one_or_none()
        if not service:
            service = ApiServiceModel(
                name=server_name,
                img="",
                description="",
                api_project_id=int(proj.id),
                created_by=1,
                updated_by=1,
            )
            db.add(service)
            await db.flush()

        await db.commit()
        await ApiAutomationService.handle_gitlab_import(db, body.get("apis") or [], int(service.id), user_id)

    
    @staticmethod
    async def gitlab_ci_notice(db: AsyncSession, body: Dict[str, Any]) -> Dict[str, Any]:
        """
         gitlab_ci_notice：
        - 根据 api_project_id 找到脚本列表
        - 过滤 cn_service 包含 api_service
        - 创建 type=3 的定时任务（10 秒后执行一次）
        """
        api_project_id = int(body.get("api_project_id") or 0)
        api_service = str(body.get("api_service") or "")
        env_id = int(body.get("env_id") or 0)

        scripts = (
            await db.execute(
                select(ApiScriptModel).where(ApiScriptModel.enabled_flag == 1, ApiScriptModel.type == api_project_id)
            )
        ).scalars().all()
        script_ids: List[int] = []
        for s in scripts:
            cfg = s.config or {}
            cn_services = cfg.get("cn_service") or []
            if api_project_id == 1 and api_service and (api_service in cn_services):
                script_ids.append(int(s.id))

        result_id = int(time.time() * 1000)
        run_time = (datetime.now() + timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")

        task_data = {
            "name": f"Gitlab CI: {api_service}",
            "type": 3,
            "status": 1,
            "script": {"api_script_list": script_ids, "env_id": env_id},
            "time": {"run_time": run_time, "type": 1},
            "notice": {"notice_id": [25], "status": 1},
            "description": "",
        }
    
        return await TaskSchedulerService.create_task(db, task_data, user_id=1)

    @staticmethod
    async def read_script_log(result_id: str) -> List[str]:
        base_dir = ApiAutomationService._get_api_result_dir(result_id)
        path = base_dir / f"{result_id}.txt"
        if not path.exists():
            return []
        content = path.read_text(encoding="utf-8")
        lines = content.split("\n")
        lines = [l for l in lines if l.strip()]
        return list(reversed(lines))

    @staticmethod
    async def read_script_report_log(result_id: str, menu_id: str) -> List[str]:
        base_dir = ApiAutomationService._get_api_result_dir(result_id)
        path = base_dir / f"{menu_id}.txt"
        if not path.exists():
            return []
        content = path.read_text(encoding="utf-8")
        lines = content.split("\n")
        lines = [l for l in lines if l.strip()]
        return list(reversed(lines))

    @staticmethod
    async def _write_log_line(menu_uuid: str, result_id: str, message: str) -> None:
        base_dir = ApiAutomationService._get_api_result_dir(result_id)
        all_log = base_dir / f"{result_id}.txt"
        menu_log = base_dir / f"{menu_uuid}.txt"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{now} {message} "
        ApiAutomationService._append_log_file(all_log, line)
        ApiAutomationService._append_log_file(menu_log, line)

  
    @staticmethod
    async def _send_notice(
        db: AsyncSession,
        notice_id: int,
        notice_type: str,
        data: Dict[str, Any],
        user_id: int,
    ) -> None:
        try:
            notice = (
                await db.execute(
                    select(MsgNoticeModel).where(
                        MsgNoticeModel.id == int(notice_id),
                        MsgNoticeModel.enabled_flag == 1,
                    )
                )
            ).scalar_one_or_none()
            if not notice:
                return

            payload = {
                "id": notice.id,
                "type": notice.type,
                "value": notice.value,
                "status": notice.status,
                "script": notice.script or {},
            }

            
            if notice_type == "api_report":
                report_url = f"{app_config.BASE_URL}/_api_report?result_id={data.get('result_id')}"
                wechat = (payload.get("script") or {}).get("wechat") or {}
                content = str(wechat.get("content") or "")
                content = (
                    content.replace("{{result_id}}", str(data.get("result_id", "")))
                    .replace("{{device_name}}", str(data.get("device_name", "")))
                    .replace("{{percent}}", str(data.get("percent", "")))
                    .replace("{{total}}", str(data.get("total", "")))
                    .replace("{{passed}}", str(data.get("passed", "")))
                    .replace("{{fail}}", str(data.get("fail", "")))
                    .replace("{{un_run}}", str(data.get("un_run", "")))
                    .replace("{{report_url}}", report_url)
                )
                wechat["content"] = content
                payload["script"]["wechat"] = wechat
            elif notice_type == "app_report":
                base = str(getattr(app_config, "BASE_URL", "") or "").rstrip("/")
                report_url = f"{base}/app_report?result_id={data.get('result_id')}"
                wechat = (payload.get("script") or {}).get("wechat") or {}
                content = str(wechat.get("content") or "")
                content = (
                    content.replace("{{result_id}}", str(data.get("result_id", "")))
                    .replace("{{device_name}}", str(data.get("device_name", "")))
                    .replace("{{percent}}", str(data.get("percent", "")))
                    .replace("{{total}}", str(data.get("total", "")))
                    .replace("{{passed}}", str(data.get("passed", "")))
                    .replace("{{fail}}", str(data.get("fail", "")))
                    .replace("{{un_run}}", str(data.get("un_run", "")))
                    .replace("{{report_url}}", report_url)
                )
                wechat["content"] = content
                payload["script"]["wechat"] = wechat
            elif notice_type == "app_error_report":
                base = str(getattr(app_config, "BASE_URL", "") or "").rstrip("/")
                report_url = f"{base}/app_report?result_id={data.get('result_id', '')}"
                wechat = (payload.get("script") or {}).get("wechat") or {}
                content = str(wechat.get("content") or "")
                content = (
                    content.replace("{{device_name}}", str(data.get("device_name", "")))
                    .replace("{{result_id}}", str(data.get("result_id", "")))
                    .replace("{{report_url}}", report_url)
                )
                wechat["content"] = content
                payload["script"]["wechat"] = wechat
            else:
                wechat = (payload.get("script") or {}).get("wechat") or {}
                if "content" in wechat:
                    wechat["content"] = str(data)
                    payload["script"]["wechat"] = wechat

            # ：type==1 企业微信；type==2 钉钉；type==3 邮件
            if int(payload.get("type") or 0) == 1 and int(payload.get("status") or 0) == 1:
                ApiAutomationService._send_wechat_notice(payload)
        except Exception:

            return

    @staticmethod
    def _send_wechat_notice(notice: Dict[str, Any]) -> bool:
        try:
            web_hook_url = str(notice.get("value") or "")
            wechat = (notice.get("script") or {}).get("wechat") or {}
            msgtype = wechat.get("msgtype") or "text"
            mentioned_list = wechat.get("mentioned_list") or []

            if msgtype == "text":
                json_data = {
                    "msgtype": "text",
                    "text": {"content": wechat.get("content") or "", "mentioned_list": mentioned_list},
                }
            elif msgtype == "markdown":
                content = str(wechat.get("content") or "") + "\n"
                for u in mentioned_list:
                    content += f"<@{u}>"
                json_data = {"msgtype": "markdown", "markdown": {"content": content}}
            elif msgtype == "news":
                json_data = {
                    "msgtype": "news",
                    "news": {
                        "articles": (wechat.get("news") or {}).get("articles") or [],
                        "mentioned_list": mentioned_list,
                    },
                }
            else:
                json_data = {
                    "msgtype": "text",
                    "text": {"content": wechat.get("content") or "", "mentioned_list": mentioned_list},
                }

            headers = {"Content-Type": "application/json", "Charset": "UTF-8"}
            requests.post(web_hook_url, headers=headers, json=json_data)
            return True
        except Exception:
            return False


    # ── 代码生成辅助 ──────────────────────────────────────────────────

    @staticmethod
    async def get_apis_by_ids(db: AsyncSession, api_ids: list) -> list:
        """根据接口 ID 列表批量获取接口数据（用于代码生成）"""
        if not api_ids:
            return []
        result = await db.execute(
            select(ApiModel).where(ApiModel.id.in_(api_ids), ApiModel.enabled_flag == 1)
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "name": r.name or r.url,
                "url": r.url,
                "req": r.req or {},
            }
            for r in rows
        ]

    @staticmethod
    # ── 服务排序 ──────────────────────────────────────────────────────

    @staticmethod
    async def sort_services(db: AsyncSession, ids: List[int], user_id: int) -> None:
        """按传入 ID 列表顺序更新服务的 sort 字段"""
        for idx, service_id in enumerate(ids):
            await db.execute(
                update(ApiServiceModel)
                .where(ApiServiceModel.id == int(service_id), ApiServiceModel.enabled_flag == 1)
                .values(sort=idx, updated_by=user_id)
            )
        await db.commit()

    # ── 用例集（Suite）CRUD ───────────────────────────────────────────

    @staticmethod
    def _build_suite_tree(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将平铺的用例集列表构建为树形结构"""
        by_id: Dict[int, Dict[str, Any]] = {}
        roots: List[Dict[str, Any]] = []
        for it in items:
            node = dict(it)
            node["children"] = []
            by_id[node["id"]] = node
        for node in by_id.values():
            pid = node.get("parent")
            if pid is None or pid not in by_id:
                roots.append(node)
            else:
                by_id[pid]["children"].append(node)
        return roots

    @staticmethod
    async def get_suite_list(db: AsyncSession, api_service_id: int, user_id: int) -> List[Dict[str, Any]]:
        from .model import ApiSuiteModel
        stmt = (
            select(ApiSuiteModel)
            .where(ApiSuiteModel.enabled_flag == 1, ApiSuiteModel.api_service_id == int(api_service_id))
            .order_by(ApiSuiteModel.sort.asc(), ApiSuiteModel.id.asc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        items = []
        for r in rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            items.append(d)
        return ApiAutomationService._build_suite_tree(items)

    @staticmethod
    async def add_suite(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        from .model import ApiSuiteModel
        suite = ApiSuiteModel(
            name=str(body["name"]),
            parent=body.get("parent"),
            api_service_id=int(body["api_service_id"]),
            sort=0,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(suite)
        await db.commit()
        await db.refresh(suite)
        d = suite.__dict__.copy()
        d.pop("_sa_instance_state", None)
        return d

    @staticmethod
    async def edit_suite(db: AsyncSession, suite_id: int, name: str, user_id: int) -> None:
        from .model import ApiSuiteModel
        await db.execute(
            update(ApiSuiteModel)
            .where(ApiSuiteModel.id == int(suite_id), ApiSuiteModel.enabled_flag == 1)
            .values(name=name, updated_by=user_id)
        )
        await db.commit()

    @staticmethod
    async def delete_suite(db: AsyncSession, suite_id: int, user_id: int) -> None:
        """级联删除用例集及其所有子用例集和用例"""
        from .model import ApiSuiteModel, ApiCaseModel
        # 递归收集所有子用例集 ID
        all_ids: List[int] = [int(suite_id)]
        queue = [int(suite_id)]
        while queue:
            current_ids = queue[:]
            queue = []
            children = (await db.execute(
                select(ApiSuiteModel.id).where(
                    ApiSuiteModel.enabled_flag == 1,
                    ApiSuiteModel.parent.in_(current_ids),
                )
            )).scalars().all()
            for cid in children:
                all_ids.append(cid)
                queue.append(cid)
        # 删除所有用例
        await db.execute(
            update(ApiCaseModel)
            .where(ApiCaseModel.suite_id.in_(all_ids), ApiCaseModel.enabled_flag == 1)
            .values(enabled_flag=0, updated_by=user_id)
        )
        # 删除所有用例集
        await db.execute(
            update(ApiSuiteModel)
            .where(ApiSuiteModel.id.in_(all_ids), ApiSuiteModel.enabled_flag == 1)
            .values(enabled_flag=0, updated_by=user_id)
        )
        await db.commit()

    @staticmethod
    async def sort_suites(db: AsyncSession, ids: List[int], user_id: int) -> None:
        from .model import ApiSuiteModel
        for idx, suite_id in enumerate(ids):
            await db.execute(
                update(ApiSuiteModel)
                .where(ApiSuiteModel.id == int(suite_id), ApiSuiteModel.enabled_flag == 1)
                .values(sort=idx, updated_by=user_id)
            )
        await db.commit()

    # ── 用例（Case）CRUD ──────────────────────────────────────────────

    @staticmethod
    async def get_case_list(db: AsyncSession, suite_id: int, user_id: int) -> List[Dict[str, Any]]:
        from .model import ApiCaseModel
        stmt = (
            select(ApiCaseModel)
            .where(ApiCaseModel.enabled_flag == 1, ApiCaseModel.suite_id == int(suite_id))
            .order_by(ApiCaseModel.id.asc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        result = []
        for r in rows:
            d = r.__dict__.copy()
            d.pop("_sa_instance_state", None)
            result.append(d)
        return result

    @staticmethod
    async def add_case(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        from .model import ApiCaseModel
        case = ApiCaseModel(
            name=str(body["name"]),
            description=body.get("description") or "",
            suite_id=int(body["suite_id"]),
            script=body.get("script") or [],
            status=0,
            case_type=int(body.get("case_type") or 1),
            step_rely=int(body.get("step_rely", 1)),
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)
        d = case.__dict__.copy()
        d.pop("_sa_instance_state", None)
        return d

    @staticmethod
    async def edit_case(db: AsyncSession, case_id: int, body: Dict[str, Any], user_id: int) -> None:
        from .model import ApiCaseModel
        values: Dict[str, Any] = {"updated_by": user_id}
        for field in ("name", "description", "script", "case_type", "step_rely"):
            if field in body and body[field] is not None:
                values[field] = body[field]
        await db.execute(
            update(ApiCaseModel)
            .where(ApiCaseModel.id == int(case_id), ApiCaseModel.enabled_flag == 1)
            .values(**values)
        )
        await db.commit()

    @staticmethod
    async def delete_case(db: AsyncSession, case_id: int, user_id: int) -> None:
        from .model import ApiCaseModel
        await db.execute(
            update(ApiCaseModel)
            .where(ApiCaseModel.id == int(case_id), ApiCaseModel.enabled_flag == 1)
            .values(enabled_flag=0, updated_by=user_id)
        )
        await db.commit()

    @staticmethod
    async def run_api_case(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """执行用例：复用现有 run_api_script 逻辑，写入结果并关联 api_service_id"""
        from .model import ApiCaseModel, ApiSuiteModel
        case_ids = [int(i) for i in (body.get("case_ids") or [])]
        env_id = body.get("env_id")
        task_name = body.get("name") or f"用例执行_{uuid.uuid4().hex[:8]}"

        # 查询用例，获取 script 和所属服务 ID
        cases = (await db.execute(
            select(ApiCaseModel).where(ApiCaseModel.id.in_(case_ids), ApiCaseModel.enabled_flag == 1)
        )).scalars().all()
        if not cases:
            raise ValueError("未找到有效用例")

        # 通过第一个用例的 suite_id 获取 api_service_id
        suite = (await db.execute(
            select(ApiSuiteModel).where(ApiSuiteModel.id == cases[0].suite_id, ApiSuiteModel.enabled_flag == 1)
        )).scalar_one_or_none()
        api_service_id = suite.api_service_id if suite else None

        # 构建 run_list（复用现有用例执行格式）
        run_list = []
        case_id_map = {}  # name -> case_id 映射
        for case in cases:
            case_name = f"{case.name}_{case.id}"  # 确保唯一性
            run_list.append({
                "name": case.name,  # 显示原始名称
                "script": case.script or [],
                "config": {"env_id": env_id, "case_id": case.id, "step_rely": getattr(case, 'step_rely', 1)},
            })
            case_id_map[case_name] = case.id

        result_id = int(body.get("result_id") or uuid.uuid4().int % (10 ** 15))
        run_body = {
            "result_id": result_id,
            "name": task_name,
            "config": {"env_id": env_id},
            "run_list": run_list,
            "api_service_id": api_service_id,
        }
        await ApiAutomationService.run_api_script(db, run_body, user_id)

        # 执行完成后按用例单独更新状态
        pass_count = 0
        fail_count = 0
        try:
            from .model import ApiScriptResultModel
            # 查询该批次所有步骤结果，按 menu_id 分组
            result_rows = (await db.execute(
                select(ApiScriptResultModel).where(
                    ApiScriptResultModel.result_id == result_id,
                    ApiScriptResultModel.enabled_flag == 1,
                    ApiScriptResultModel.name != "执行结束",
                ).order_by(ApiScriptResultModel.id.asc())
            )).scalars().all()

            # 按 menu_id 分组，判断每组是否全部通过
            from collections import defaultdict, OrderedDict
            menu_pass: Dict[str, bool] = OrderedDict()
            for row in result_rows:
                mid = row.menu_id
                if mid not in menu_pass:
                    menu_pass[mid] = True
                if row.status == 0:
                    menu_pass[mid] = False

            # 按 run_list 顺序（即 cases 顺序）对应 menu_id
            menu_ids = list(menu_pass.keys())
            for i, case in enumerate(cases):
                if i < len(menu_ids):
                    is_pass = menu_pass[menu_ids[i]]
                else:
                    is_pass = True  # 无结果时默认通过
                new_status = 1 if is_pass else 2
                if is_pass:
                    pass_count += 1
                else:
                    fail_count += 1
                await db.execute(
                    update(ApiCaseModel)
                    .where(ApiCaseModel.id == case.id, ApiCaseModel.enabled_flag == 1)
                    .values(status=new_status, updated_by=user_id)
                )
            await db.commit()
        except Exception:
            pass

        total_count = len(cases)
        return {"result_id": str(result_id), "total": total_count, "pass": pass_count, "fail": fail_count}

    # ─── 脚本中心（NtestScript）CRUD ──────────────────────────────────────────

    @staticmethod
    async def _ensure_ntest_script_language_column(db: AsyncSession) -> None:
        """兼容旧库：缺少 language 列时自动补齐。"""
        try:
            await db.execute(text(
                "ALTER TABLE api_automation_ntest_scripts "
                "ADD COLUMN language VARCHAR(32) NOT NULL DEFAULT 'python'"
            ))
            await db.commit()
        except Exception:
            await db.rollback()

    @staticmethod
    async def _ensure_ntest_script_exec_mode_column(db: AsyncSession) -> None:
        """兼容旧库：缺少 exec_mode 列时自动补齐。"""
        try:
            await db.execute(text(
                "ALTER TABLE api_automation_ntest_scripts "
                "ADD COLUMN exec_mode VARCHAR(16) NOT NULL DEFAULT 'sandbox'"
            ))
            await db.commit()
        except Exception:
            await db.rollback()

    @staticmethod
    async def _ensure_ntest_script_code_map_column(db: AsyncSession) -> None:
        """兼容旧库：缺少 code_map 列时自动补齐。"""
        try:
            await db.execute(text(
                "ALTER TABLE api_automation_ntest_scripts "
                "ADD COLUMN code_map TEXT NULL"
            ))
            await db.commit()
        except Exception:
            await db.rollback()

    @staticmethod
    async def get_ntest_scripts(db: AsyncSession, api_service_id: int, user_id: int) -> List[Dict]:
        """查询指定服务下的公共脚本列表（仅返回未软删除的记录）"""
        from .model import NtestScriptModel
        await ApiAutomationService._ensure_ntest_script_language_column(db)
        rows = (await db.execute(
            select(NtestScriptModel).where(
                NtestScriptModel.api_service_id == api_service_id,
                NtestScriptModel.enabled_flag == 1,
            ).order_by(NtestScriptModel.id.desc())
        )).scalars().all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "code": r.code,
                "language": getattr(r, "language", None) or "python",
                "exec_mode": getattr(r, "exec_mode", None) or "sandbox",
                "code_map": (json.loads(getattr(r, "code_map", None)) if getattr(r, "code_map", None) else None),
                "external_files": (json.loads(getattr(r, "external_files", None)) if getattr(r, "external_files", None) else []),
                "api_service_id": r.api_service_id,
            }
            for r in rows
        ]

    @staticmethod
    async def add_ntest_script(db: AsyncSession, body: Dict[str, Any], user_id: int) -> None:
        """新增公共脚本"""
        from .model import NtestScriptModel
        from .script_runtime import normalize_language
        await ApiAutomationService._ensure_ntest_script_language_column(db)
        await ApiAutomationService._ensure_ntest_script_exec_mode_column(db)
        await ApiAutomationService._ensure_ntest_script_code_map_column(db)
        await ApiAutomationService._ensure_ntest_script_external_files_column(db)
        await ApiAutomationService._ensure_ntest_script_external_files_column(db)
        await ApiAutomationService._ensure_ntest_script_code_map_column(db)
        name = (body.get("name") or "").strip()
        if not name:
            raise ValueError("脚本名称不能为空")
        api_service_id = body.get("api_service_id")
        if not api_service_id:
            raise ValueError("api_service_id 不能为空")
        language = normalize_language(body.get("language") or "python")
        script = NtestScriptModel(
            name=name,
            description=body.get("description") or "",
            code=body.get("code") or "",
            language=language,
            exec_mode=body.get("exec_mode") or "sandbox",
            code_map=json.dumps(body.get("code_map") or {}, ensure_ascii=False) if body.get("code_map") else None,
            external_files=json.dumps(body.get("external_files") or [], ensure_ascii=False) if body.get("external_files") else None,
            api_service_id=int(api_service_id),
            created_by=user_id,
            enabled_flag=1,
        )
        db.add(script)
        await db.commit()

    @staticmethod
    async def edit_ntest_script(db: AsyncSession, script_id: int, body: Dict[str, Any], user_id: int) -> None:
        """编辑公共脚本"""
        from .script_runtime import normalize_language
        await ApiAutomationService._ensure_ntest_script_language_column(db)
        await ApiAutomationService._ensure_ntest_script_exec_mode_column(db)
        name = (body.get("name") or "").strip()
        if "name" in body and not name:
            raise ValueError("脚本名称不能为空")
        values: Dict[str, Any] = {"updated_by": user_id}
        if name:
            values["name"] = name
        if "description" in body:
            values["description"] = body["description"] or ""
        if "code" in body:
            values["code"] = body["code"] or ""
        if "language" in body:
            values["language"] = normalize_language(body.get("language") or "python")
        if "exec_mode" in body:
            values["exec_mode"] = body.get("exec_mode") or "sandbox"
        if "code_map" in body:
            values["code_map"] = json.dumps(body.get("code_map") or {}, ensure_ascii=False) if body.get("code_map") else None
        if "external_files" in body:
            values["external_files"] = json.dumps(body.get("external_files") or [], ensure_ascii=False) if body.get("external_files") else None
        from .model import NtestScriptModel
        await db.execute(
            update(NtestScriptModel)
            .where(NtestScriptModel.id == script_id, NtestScriptModel.enabled_flag == 1)
            .values(**values)
        )
        await db.commit()

    @staticmethod
    async def delete_ntest_script(db: AsyncSession, script_id: int, user_id: int) -> None:
        """软删除公共脚本（将 enabled_flag 置为 0）"""
        from .model import NtestScriptModel
        await db.execute(
            update(NtestScriptModel)
            .where(NtestScriptModel.id == script_id, NtestScriptModel.enabled_flag == 1)
            .values(enabled_flag=0, updated_by=user_id)
        )
        await db.commit()

    # ─── 数据查询（QueryDB）─────────────────────────────────────────────────────

    @staticmethod
    def _is_select_only(sql: str) -> bool:
        """校验所有 SQL 语句是否均为 SELECT（支持多条语句，以 ; 分隔）"""
        import re
        # 去除注释
        cleaned = re.sub(r'--[^\n]*', '', sql)
        cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
        # 按分号拆分，过滤空语句
        stmts = [s.strip() for s in cleaned.split(';') if s.strip()]
        if not stmts:
            return False
        for stmt in stmts:
            first_word = stmt.split()[0].upper() if stmt.split() else ''
            if first_word != 'SELECT':
                return False
        return True

    @staticmethod
    async def execute_db_query(db: AsyncSession, db_id: int, sql: str) -> List[Dict]:
        """执行一条或多条 SELECT 查询，返回所有结果行的合并列表"""
        import re
        import pymysql
        import pymysql.cursors

        if not ApiAutomationService._is_select_only(sql):
            raise ValueError("仅支持 SELECT 查询语句")

        cfg = await ApiAutomationService._get_db_config(db, db_id)
        conn = pymysql.connect(
            host=cfg["host"], port=cfg["port"],
            user=cfg["user"], password=cfg["password"],
            database=cfg["database"] or None,
            connect_timeout=10,
            cursorclass=pymysql.cursors.DictCursor,
        )

        # 拆分多条语句
        cleaned = re.sub(r'--[^\n]*', '', sql)
        cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
        stmts = [s.strip() for s in cleaned.split(';') if s.strip()]

        all_results: List[Dict] = []
        try:
            with conn.cursor() as cur:
                for stmt in stmts:
                    cur.execute(stmt)
                    rows = cur.fetchall()
                    all_results.extend([dict(r) for r in rows])
        finally:
            conn.close()

        return all_results

    @staticmethod
    async def _get_db_config(db: AsyncSession, db_id: int) -> Dict[str, Any]:
        """从 ApiDatabaseModel 获取数据库连接配置"""
        from .model import ApiDatabaseModel
        row = (await db.execute(
            select(ApiDatabaseModel).where(
                ApiDatabaseModel.id == db_id,
                ApiDatabaseModel.enabled_flag == 1,
            )
        )).scalars().first()
        if not row:
            raise ValueError("数据库配置不存在")
        return {
            "host": row.host or "",
            "port": int(row.port or 3306),
            "user": row.username or "",
            "password": row.password or "",
            "database": row.database_name or "",
            "db_type": (row.db_type or "mysql").lower(),
        }

    @staticmethod
    async def get_db_databases(db: AsyncSession, db_id: int) -> List[Dict]:
        """获取指定数据库连接下的所有数据库名"""
        import pymysql
        cfg = await ApiAutomationService._get_db_config(db, db_id)
        conn = pymysql.connect(
            host=cfg["host"], port=cfg["port"],
            user=cfg["user"], password=cfg["password"],
            connect_timeout=10,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW DATABASES")
                rows = cur.fetchall()
            return [{"name": r[0], "type": "database", "hasChildren": True} for r in rows]
        finally:
            conn.close()

    @staticmethod
    async def get_db_tables(db: AsyncSession, db_id: int, database: str) -> List[Dict]:
        """获取指定数据库下的所有表名"""
        import pymysql
        cfg = await ApiAutomationService._get_db_config(db, db_id)
        conn = pymysql.connect(
            host=cfg["host"], port=cfg["port"],
            user=cfg["user"], password=cfg["password"],
            database=database,
            connect_timeout=10,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW TABLES")
                rows = cur.fetchall()
            return [{"name": r[0], "type": "table", "isLeaf": True} for r in rows]
        finally:
            conn.close()

    # ─── 数据源导入历史与差异对比 ──────────────────────────────────────────────

    @staticmethod
    async def get_data_source_history(
        db: AsyncSession, service_id: int, module_id: Optional[int] = None,
        page: int = 1, page_size: int = 20
    ) -> Dict[str, Any]:
        """获取数据源导入历史列表"""
        await ApiAutomationService._ensure_data_source_history_table(db)
        stmt = select(ApiDataSourceHistoryModel).where(
            ApiDataSourceHistoryModel.api_service_id == int(service_id),
            ApiDataSourceHistoryModel.enabled_flag == 1,
        )
        if module_id:
            stmt = stmt.where(ApiDataSourceHistoryModel.module_id == int(module_id))
        stmt = stmt.order_by(ApiDataSourceHistoryModel.id.desc())
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        rows = (
            await db.execute(
                stmt.offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        items = []
        for r in rows:
            stats = r.stats if isinstance(r.stats, dict) else {}
            cfg = r.config if isinstance(r.config, dict) else {}
            items.append({
                "id": int(r.id),
                "api_service_id": int(r.api_service_id),
                "module_id": int(r.module_id) if r.module_id else None,
                "source_type": str(r.source_type or ""),
                "source_url": str(r.source_url or ""),
                "frequency": str(cfg.get("frequency") or ""),
                "stats": stats,
                "created_by": int(r.created_by) if r.created_by else None,
                "created_at": r.creation_date.strftime("%Y-%m-%d %H:%M:%S") if r.creation_date else "",
            })
        total_page = int(ceil(float(total) / page_size)) if total else 0
        return {
            "rowTotal": total,
            "pageSize": page_size,
            "page": page,
            "pageTotal": total_page,
            "rows": items,
        }

    @staticmethod
    async def diff_data_source_history(
        db: AsyncSession, history_id_a: int, history_id_b: int, user_id: int
    ) -> Dict[str, Any]:
        """对比两次数据源导入历史，返回接口级差异"""
        await ApiAutomationService._ensure_data_source_history_table(db)

        async def _get_hist(hid: int) -> Optional[ApiDataSourceHistoryModel]:
            return (
                await db.execute(
                    select(ApiDataSourceHistoryModel).where(
                        ApiDataSourceHistoryModel.id == hid,
                        ApiDataSourceHistoryModel.enabled_flag == 1,
                    )
                )
            ).scalar_one_or_none()

        ha = await _get_hist(history_id_a)
        hb = await _get_hist(history_id_b)
        if not ha or not hb:
            raise ValueError("历史记录不存在")
        if int(ha.api_service_id) != int(hb.api_service_id):
            raise ValueError("只能对比同一服务下的历史记录")

        snap_a = ha.apis_snapshot if isinstance(ha.apis_snapshot, list) else []
        snap_b = hb.apis_snapshot if isinstance(hb.apis_snapshot, list) else []

        def _api_key(item: Dict[str, Any]) -> str:
            return f"{str(item.get('method') or '').upper()} {str(item.get('url') or '')}"

        map_a = {(_api_key(x), int(x.get("id") or 0)): x for x in snap_a}
        map_b = {(_api_key(x), int(x.get("id") or 0)): x for x in snap_b}

        # 优先按 method+url 匹配；如果 id 相同也视为同一接口
        keys_a = set(map_a.keys())
        keys_b = set(map_b.keys())

        added: List[Dict[str, Any]] = []
        removed: List[Dict[str, Any]] = []
        modified: List[Dict[str, Any]] = []

        for k in keys_b - keys_a:
            added.append({"key": _api_key(map_b[k]), **map_b[k]})
        for k in keys_a - keys_b:
            removed.append({"key": _api_key(map_a[k]), **map_a[k]})
        for k in keys_a & keys_b:
            item_a = map_a[k]
            item_b = map_b[k]
            changes: List[Dict[str, Any]] = []
            fields = ["name", "description", "method", "url", "params", "body", "body_type", "header", "operation_id", "tags"]
            for field in fields:
                va = item_a.get(field)
                vb = item_b.get(field)
                if va != vb:
                    changes.append({"field": field, "old": va, "new": vb})
            if changes:
                modified.append({"key": _api_key(item_b), "id": item_b.get("id"), "changes": changes, **item_b})

        return {
            "history_a": {
                "id": int(ha.id),
                "created_at": ha.creation_date.strftime("%Y-%m-%d %H:%M:%S") if ha.creation_date else "",
                "stats": ha.stats if isinstance(ha.stats, dict) else {},
            },
            "history_b": {
                "id": int(hb.id),
                "created_at": hb.creation_date.strftime("%Y-%m-%d %H:%M:%S") if hb.creation_date else "",
                "stats": hb.stats if isinstance(hb.stats, dict) else {},
            },
            "summary": {
                "added": len(added),
                "removed": len(removed),
                "modified": len(modified),
            },
            "added": added,
            "removed": removed,
            "modified": modified,
        }

    @staticmethod
    async def delete_data_source_history(db: AsyncSession, history_id: int, user_id: int) -> None:
        """删除单条数据源导入历史（逻辑删除）"""
        await ApiAutomationService._ensure_data_source_history_table(db)
        await db.execute(
            update(ApiDataSourceHistoryModel)
            .where(ApiDataSourceHistoryModel.id == int(history_id))
            .values(enabled_flag=0, updated_by=user_id)
        )
        await db.commit()

