#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: Rebort

from __future__ import annotations
from typing import List, Optional, Dict, Any, Tuple
import os
from datetime import datetime, timedelta
from pathlib import Path
import json
import subprocess
import signal
import multiprocessing
from sqlalchemy import select, func, text, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .model import (
    WebElementMenuModel,
    WebElementModel,
    WebMenuModel,
    WebScriptModel,
    WebGroupModel,
    WebResultListModel,
    WebResultDetailModel,
)

from config import config as app_config

from app.infra.db.sqlalchemy import async_session_factory

from .playwright_runner import run_web_async
from .web_worker import run_web_task_in_process


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


class WebManagementService:


    @staticmethod
    async def get_element_tree(db: AsyncSession, *, only_menu: bool = True) -> List[Dict[str, Any]]:

        result = await db.execute(
            select(
                WebElementMenuModel.id,
                WebElementMenuModel.name,
                WebElementMenuModel.pid,
                WebElementMenuModel.type,
                WebElementMenuModel.element_id,
            ).where(WebElementMenuModel.enabled_flag == 1)
        )
        rows = [
            {
                "id": r.id,
                "name": r.name,
                "pid": r.pid,
                "type": r.type,
                "element_id": r.element_id,
            }
            for r in result.fetchall()
        ]

        if only_menu:
            rows = [r for r in rows if r.get("type") != 2]

        return _build_tree(rows)

    @staticmethod
    async def add_menu(
        db: AsyncSession,
        *,
        name: str,
        pid: int,
        type: int,
        user_id: int,
    ) -> None:
        menu = WebElementMenuModel(
            name=name,
            pid=pid,
            type=type,
            created_by=user_id,
        )
        db.add(menu)
        await db.flush()

    @staticmethod
    async def edit_menu(db: AsyncSession, *, menu_id: int, name: str, user_id: int) -> None:
        result = await db.execute(
            select(WebElementMenuModel).where(
                WebElementMenuModel.id == menu_id,
                WebElementMenuModel.enabled_flag == 1,
            )
        )
        menu = result.scalar_one_or_none()
        if not menu:
            return
        menu.name = name
        menu.last_updated_by = user_id

    @staticmethod
    async def delete_menu(db: AsyncSession, *, menu_id: int) -> None:
        result = await db.execute(
            select(WebElementMenuModel).where(
                WebElementMenuModel.id == menu_id,
                WebElementMenuModel.enabled_flag == 1,
            )
        )
        menu = result.scalar_one_or_none()
        if not menu:
            return

        # 目录下仍有子节点时，不允许删除
        child_result = await db.execute(
            select(WebElementMenuModel.id).where(
                WebElementMenuModel.pid == menu_id,
                WebElementMenuModel.enabled_flag == 1,
            ).limit(1)
        )
        if child_result.scalar_one_or_none() is not None:
            raise Exception("删除失败，该菜单下仍存在子节点")

        # 若误传了元素叶子节点，顺便硬删除其元素记录
        if int(getattr(menu, "type", 0) or 0) == 2 and getattr(menu, "element_id", None):
            await db.execute(
                delete(WebElementModel).where(
                    WebElementModel.id == int(menu.element_id),
                )
            )

        await db.execute(
            delete(WebElementMenuModel).where(
                WebElementMenuModel.id == menu_id,
            )
        )

    @staticmethod
    async def get_element_list(
        db: AsyncSession,
        *,
        page: int,
        page_size: int,
        user_id: int,
        menu_id: Optional[int] = None,
        name_icontains: Optional[str] = None,
    ) -> Dict[str, Any]:

        if page <= 0:
            page = 1
        if page_size <= 0:
            page_size = 10

        conditions = [
            WebElementModel.enabled_flag == 1,
            WebElementModel.created_by == user_id,
        ]
        if menu_id is not None:
            conditions.append(WebElementModel.menu_id == int(menu_id))
        if name_icontains:
            conditions.append(WebElementModel.name.contains(name_icontains.strip()))

        base_query = (
            select(WebElementModel)
            .where(*conditions)
            .order_by(WebElementModel.id.desc())
        )

        total_result = await db.execute(base_query)
        all_rows = total_result.scalars().all()
        total = len(all_rows)

        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]

        user_ids: List[int] = []
        for r in page_rows:
            uid = getattr(r, "updated_by", None) or getattr(r, "created_by", None)
            if uid:
                user_ids.append(int(uid))
        username_map = await _get_username_map(db, user_ids)

        content = []
        for r in page_rows:
            uid = getattr(r, "updated_by", None) or getattr(r, "created_by", None)
            updation_date = getattr(r, "updation_date", None)
            if updation_date is not None and hasattr(updation_date, "strftime"):
                update_time = updation_date.strftime("%Y-%m-%d %H:%M:%S")
            else:
                update_time = str(updation_date) if updation_date is not None else ""
            content.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "element": r.element,
                    "menu_id": r.menu_id,
                    "creation_date": r.creation_date,
                    "update_time": update_time,
                    "username": username_map.get(int(uid), "") if uid else "",
                }
            )

        return {
            "content": content,
            "totalElements": total,
            "page": page,
            "pageSize": page_size,
        }

    @staticmethod
    async def add_element(
        db: AsyncSession,
        *,
        name: str,
        element: Dict[str, Any],
        menu_id: int,
        user_id: int,
    ) -> None:
        elem = WebElementModel(
            name=name,
            element=element,
            menu_id=menu_id,
            created_by=user_id,
        )
        db.add(elem)
        await db.flush()

        menu = WebElementMenuModel(
            name=name,
            pid=menu_id,
            type=2,
            element_id=elem.id,
            created_by=user_id,
        )
        db.add(menu)

    @staticmethod
    async def edit_element(
        db: AsyncSession,
        *,
        element_id: int,
        name: str,
        element: Dict[str, Any],
        user_id: int,
    ) -> None:
        result = await db.execute(
            select(WebElementModel).where(
                WebElementModel.id == element_id,
                WebElementModel.enabled_flag == 1,
            )
        )
        elem = result.scalar_one_or_none()
        if not elem:
            return

        elem.name = name
        elem.element = element
        elem.last_updated_by = user_id

        menu_result = await db.execute(
            select(WebElementMenuModel).where(
                WebElementMenuModel.element_id == element_id,
                WebElementMenuModel.enabled_flag == 1,
            )
        )
        menu = menu_result.scalar_one_or_none()
        if menu:
            menu.name = name
            menu.last_updated_by = user_id

    @staticmethod
    async def delete_element(db: AsyncSession, *, element_id: int) -> None:
        await db.execute(
            delete(WebElementMenuModel).where(
                WebElementMenuModel.element_id == element_id,
            )
        )
        await db.execute(
            delete(WebElementModel).where(
                WebElementModel.id == element_id,
            )
        )


    @staticmethod
    async def get_web_menu(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:

        result = await db.execute(
            select(
                WebMenuModel.id,
                WebMenuModel.name,
                WebMenuModel.pid,
                WebMenuModel.type,
            ).where(WebMenuModel.enabled_flag == 1)
        )
        rows = [
            {
                "id": r.id,
                "name": r.name,
                "pid": r.pid,
                "type": r.type,
            }
            for r in result.fetchall()
        ]
        return _build_tree(rows)

    @staticmethod
    async def create_web_menu(
        db: AsyncSession,
        *,
        name: str,
        pid: int,
        type: int,
        user_id: int,
    ) -> Dict[str, Any]:

        # 父子关系校验：脚本(2)只能挂在容器(脚本库1/文件夹0)下；
        # 容器(0/1)只能挂在根目录或其它容器下，不能直接挂在脚本下。
        if type == 2:
            if not pid or pid <= 0:
                raise Exception("脚本必须创建在脚本库下")
            parent = await db.get(WebMenuModel, pid)
            if not parent or parent.type == 2:
                raise Exception("脚本必须创建在脚本库下")
        else:
            if pid and pid > 0:
                parent = await db.get(WebMenuModel, pid)
                if not parent or parent.type == 2:
                    raise Exception("脚本库只能创建在根目录或其它脚本库下")

        menu = WebMenuModel(
            name=name,
            pid=pid,
            type=type,
            created_by=user_id,
        )
        db.add(menu)
        await db.flush()


        if type == 2:
            default_script = [
                {
                    "name": "打开",
                    "type": 0,
                    "children": [],
                    "action": {
                        "type": 1,
                        "input": "",
                        "assert": [],
                        "target": "",
                        "element": "",
                        "cookies": [],
                        "localstorage": [],
                        "locator": 1,
                        "up_type": 1,
                        "before_wait": 1,
                        "after_wait": 1,
                        "sway_type": 1,
                        "target_id": "",
                        "wait_time": 1,
                        "element_id": None,
                        "target_type": 1,
                        "locator_select": 1,
                        "target_locator": 1,
                        "target_locator_select": 1,
                        "timeout": 15,
                    },
                    "status": True,
                }
            ]
            script_row = WebScriptModel(
                script=default_script,
                menu_id=menu.id,
                created_by=user_id,
            )
            db.add(script_row)

        return {
            "id": menu.id,
            "name": name,
            "pid": pid,
            "type": type,
        }

    @staticmethod
    async def get_menu_script_list(db: AsyncSession, *, pid: int) -> List[Dict[str, Any]]:

        result = await db.execute(
            select(WebMenuModel).where(
                WebMenuModel.pid == pid,
                WebMenuModel.enabled_flag == 1,
            )
        )
        rows = result.scalars().all()
        return [{"id": r.id, "name": r.name, "type": r.type} for r in rows]

    @staticmethod
    async def delete_web_menu(
        db: AsyncSession,
        *,
        menu_id: int,
        type: int,
    ) -> Tuple[bool, str]:

        if type in (0, 1):
            child_res = await db.execute(
                select(WebMenuModel).where(
                    WebMenuModel.enabled_flag == 1,
                    WebMenuModel.pid == menu_id,
                )
            )
            if child_res.scalars().first():
                return False, "删除失败，该菜单下仍存在子节点"

        res = await db.execute(
            select(WebMenuModel).where(
                WebMenuModel.id == menu_id,
                WebMenuModel.enabled_flag == 1,
            )
        )
        menu = res.scalar_one_or_none()
        if not menu:
            return False, "菜单不存在或已删除"

        # 硬删除关联脚本与菜单
        await db.execute(
            delete(WebScriptModel).where(
                WebScriptModel.menu_id == menu_id,
            )
        )
        await db.execute(
            delete(WebMenuModel).where(
                WebMenuModel.id == menu_id,
            )
        )

        return True, "删除成功"

    @staticmethod
    async def rename_web_menu(
        db: AsyncSession,
        *,
        menu_id: int,
        name: str,
        user_id: int,
    ) -> None:
        res = await db.execute(
            select(WebMenuModel).where(
                WebMenuModel.id == menu_id,
                WebMenuModel.enabled_flag == 1,
            )
        )
        menu = res.scalar_one_or_none()
        if not menu:
            return
        menu.name = name
        menu.last_updated_by = user_id

    @staticmethod
    async def get_web_script(db: AsyncSession, menu_id: int, user_id: int) -> Optional[Dict[str, Any]]:

        result = await db.execute(
            select(WebScriptModel).where(
                WebScriptModel.menu_id == menu_id,
                WebScriptModel.enabled_flag == 1,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        uid = getattr(row, "updated_by", None) or getattr(row, "created_by", None)
        username_map = await _get_username_map(db, [int(uid)] if uid else [])
        updation_date = getattr(row, "updation_date", None)
        if updation_date is not None and hasattr(updation_date, "strftime"):
            update_time = updation_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            update_time = str(updation_date) if updation_date is not None else ""
        return {
            "id": row.id,
            "menu_id": row.menu_id,
            "script": row.script,
            "creation_date": row.creation_date,
            "update_time": update_time,
            "username": username_map.get(int(uid), "") if uid else "",
        }

    @staticmethod
    async def save_web_script(db: AsyncSession, script_data: Dict[str, Any], user_id: int) -> Dict[str, Any]:

        menu_id = int(script_data["id"])
        script = script_data["script"]

        result = await db.execute(
            select(WebScriptModel).where(
                WebScriptModel.menu_id == menu_id,
                WebScriptModel.enabled_flag == 1,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.script = script
            row.last_updated_by = user_id
        else:
            row = WebScriptModel(
                script=script,
                menu_id=menu_id,
                created_by=user_id,
            )
            db.add(row)

        return {"id": getattr(row, "id", None)}

    @staticmethod
    async def execute_web_script(
        db: AsyncSession,
        script_config: Dict[str, Any],
        browsers: List[str],
        user_id: int,
    ) -> Dict[str, Any]:
        """执行Web脚本"""
        result_id = str(script_config["result_id"])

        # 只检查同一个 result_id 是否正在执行，且超过30分钟的执行视为僵尸自动忽略
        from datetime import timedelta
        zombie_threshold = datetime.now() - timedelta(minutes=30)
        running = await db.execute(
            select(WebResultListModel).where(
                WebResultListModel.enabled_flag == 1,
                WebResultListModel.status == 0,
                WebResultListModel.result_id == result_id,
                WebResultListModel.start_time >= zombie_threshold,
            )
        )
        if running.scalars().first():
            raise Exception("执行失败，当前脚本正在执行中，请稍后再试")

        status, msg, script_list, browser_type = await WebManagementService.analysis_web_script(db, script_config)

        task_name = script_config.get("task_name") or ""

        row = WebResultListModel(
            task_name=task_name,
            result_id=result_id,
            script_list=script_config.get("script") or [],
            browser_list=script_config.get("browser") or [],
            result=[],
            status=0,
            created_by=user_id,
            start_time=datetime.now(),
            end_time=None,
        )
        db.add(row)
        await db.flush()
        await db.commit()

        pid_list: List[int] = []
        if status:

            ctx = multiprocessing.get_context("spawn")
            for item in script_list:
                p = ctx.Process(target=run_web_task_in_process, args=(item, browser_type), daemon=True)
                p.start()
                pid_list.append(int(p.pid or 0))

            # 回写 pid_list，便于 stop_web_script 使用
            refetch = await db.execute(
                select(WebResultListModel).where(WebResultListModel.enabled_flag == 1, WebResultListModel.id == row.id)
            )
            saved = refetch.scalar_one_or_none()
            if saved:
                saved.pid_list = pid_list
            await db.commit()

        # 最终状态由执行引擎在每个 browser 完成后更新
        return {"status": status, "message": msg, "result_id": result_id, "pid_list": pid_list}


    @staticmethod
    def _safe_join(base: Path, *parts: str) -> Path:
        p = base
        for part in parts:
            part = part.replace("\\", "/").lstrip("/")
            if ".." in part.split("/"):
                raise ValueError("非法路径")
            p = p / part
        return p

    @staticmethod
    async def _handle_element_value(data: List[Dict[str, Any]]) -> str:
        values = [item.get("value") for item in (data or []) if item.get("value") is not None]
        return ",".join([str(v) for v in values])

    @staticmethod
    async def _analysis_element(file_name: str, user_id: int, pid: int, data: List[Dict[str, Any]]) -> Tuple[bool, str, List[Dict[str, Any]]]:
        
        try:
            script: List[Dict[str, Any]] = []
            for i in data:
                script_info: Dict[str, Any] = {}
                action = i.get("action")
                if action == "open_page":
                    script_info.update(
                        {
                            "name": i.get("fill_name") or "打开",
                            "type": 0,
                            "children": [],
                            "action": {
                                "type": 1,
                                "input": "",
                                "assert": [],
                                "target": "",
                                "element": i.get("action_detail", {}).get("open_page", {}).get("url", ""),
                                "up_type": 1,
                                "sway_type": 1,
                                "target_id": "",
                                "locator": 1,
                                "locator_select": 1,
                                "target_locator": 1,
                                "target_locator_select": 1,
                                "wait_time": 1,
                                "element_id": None,
                                "target_type": 1,
                                "before_wait": 1,
                                "after_wait": 1,
                                "cookies": [],
                                "localstorage": [],
                                "timeout": 15,
                            },
                            "status": True,
                        }
                    )
                elif action == "mouse_clicking":
                    action_detail = i.get("action_detail", {}).get("mouse_clicking", {})
                    element = await WebManagementService._handle_element_value(
                        action_detail.get("element", {}).get("custom_locators") or []
                    )
                    click_type = action_detail.get("type")
                    if click_type == "single_click_left":
                        step_type = 1
                    elif click_type == "double_click":
           
                        step_type = 1
                    elif click_type == "single_click_right":
                        step_type = 16
                    else:
                        step_type = 1
                    script_info.update(
                        {
                            "name": i.get("fill_name") or "点击",
                            "type": step_type,
                            "children": [],
                            "action": {
                                "type": 1,
                                "input": "",
                                "assert": [],
                                "target": "",
                                "element": element,
                                "up_type": 1,
                                "sway_type": 1,
                                "target_id": "",
                                "wait_time": 1,
                                "locator": 1,
                                "locator_select": 1,
                                "target_locator": 1,
                                "target_locator_select": 1,
                                "element_id": None,
                                "target_type": 1,
                                "before_wait": 1,
                                "after_wait": 1,
                                "cookies": [],
                                "localstorage": [],
                                "timeout": 15,
                            },
                            "status": True,
                        }
                    )
                elif action == "input_operations":
                    action_detail = i.get("action_detail", {}).get("input_operations", {})
                    value = action_detail.get("input_content", "")
                    element = await WebManagementService._handle_element_value(
                        action_detail.get("element", {}).get("custom_locators") or []
                    )
                    if value != "":
                        step_type = 5
                        name = i.get("fill_name") or "输入"
                    else:
                        step_type = 7
                        name = "清空文本"
                    script_info.update(
                        {
                            "name": name,
                            "type": step_type,
                            "children": [],
                            "action": {
                                "type": 1,
                                "input": value,
                                "assert": [],
                                "target": "",
                                "element": element,
                                "up_type": 1,
                                "sway_type": 1,
                                "target_id": "",
                                "locator": 1,
                                "locator_select": 1,
                                "target_locator": 1,
                                "target_locator_select": 1,
                                "wait_time": 1,
                                "element_id": None,
                                "target_type": 1,
                                "before_wait": 1,
                                "after_wait": 1,
                                "cookies": [],
                                "localstorage": [],
                                "timeout": 15,
                            },
                            "status": True,
                        }
                    )

                if script_info:
                    script.append(script_info)
            return True, "文件导入解析成功", script
        except Exception as e:
            return False, str(e), []

    @staticmethod
    async def input_element_from_file(
        db: AsyncSession,
        *,
        file_url: str,
        file_name: str,
        pid: int,
        user_id: int,
    ) -> Dict[str, Any]:
       
        base = Path(app_config.BASEDIR)
        file_path = WebManagementService._safe_join(base, file_url, file_name)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        ok, msg, script = await WebManagementService._analysis_element(file_name, user_id, pid, data)
        if not ok:
            raise Exception(msg)

        menu = WebMenuModel(
            name=file_name,
            pid=pid,
            type=2,
            created_by=user_id,
        )
        db.add(menu)
        await db.flush()

        ws = WebScriptModel(
            script=script,
            menu_id=menu.id,
            created_by=user_id,
        )
        db.add(ws)
        await db.flush()
        return {"message": msg, "menu_id": menu.id}

 

    @staticmethod
    async def stop_web_script(pid: int) -> Dict[str, Any]:
       
        if pid <= 0:
            raise ValueError("pid 非法")
        try:
            if os.name == "nt":
                cp = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
                return {"pid": pid, "stopped": cp.returncode == 0, "stdout": cp.stdout, "stderr": cp.stderr}
            os.kill(pid, signal.SIGTERM)
            return {"pid": pid, "stopped": True}
        except Exception as e:
            # 再尝试强杀
            try:
                if os.name != "nt":
                    os.kill(pid, signal.SIGKILL)
                    return {"pid": pid, "stopped": True}
            except Exception as kill_error:
                return {"pid": pid, "stopped": False, "error": f"{str(e)}; SIGKILL失败: {str(kill_error)}"}
            return {"pid": pid, "stopped": False, "error": str(e)}

    @staticmethod
    async def stop_web_result(db: AsyncSession, *, result_id: str, user_id: int) -> Dict[str, Any]:
      
        res = await db.execute(
            select(WebResultListModel)
            .where(
                WebResultListModel.enabled_flag == 1,
                WebResultListModel.result_id == str(result_id),
                WebResultListModel.created_by == user_id,
            )
            .order_by(WebResultListModel.id.desc())
            .limit(1)
        )
        row = res.scalar_one_or_none()
        if not row:
            return {"result_id": result_id, "stopped": False, "message": "未找到执行记录"}

        pid_list = row.pid_list or []
        stopped_count = 0
        for pid in pid_list:
            try:
                r = await WebManagementService.stop_web_script(int(pid))
                if r.get("stopped") is True:
                    stopped_count += 1
            except Exception:
                continue

     
        row.status = 2
        row.end_time = datetime.now()
        
        await db.commit()

        return {
            "result_id": result_id,
            "stopped": True,
            "pid_total": len(pid_list),
            "pid_stopped": stopped_count,
        }

    @staticmethod
    async def del_web_result(db: AsyncSession, *, result_id: str, user_id: int) -> Dict[str, Any]:
      
        rid = str(result_id)
        res = await db.execute(
            select(WebResultListModel)
            .where(
                WebResultListModel.enabled_flag == 1,
                WebResultListModel.result_id == rid,
                WebResultListModel.created_by == user_id,
            )
            .order_by(WebResultListModel.id.desc())
            .limit(1)
        )
        row = res.scalar_one_or_none()
        if not row:
            return {"result_id": rid, "deleted": False, "message": "未找到执行记录"}

        # 若仍在执行中，先尝试停止所有进程
        if int(getattr(row, "status", 0) or 0) == 0:
            pid_list = row.pid_list or []
            for pid in pid_list:
                try:
                    await WebManagementService.stop_web_script(int(pid))
                except Exception:
                    continue

        # 硬删除明细
        await db.execute(
            WebResultDetailModel.__table__.delete().where(WebResultDetailModel.result_id == rid)
        )
        # 硬删除主记录
        await db.execute(
            WebResultListModel.__table__.delete().where(
                WebResultListModel.result_id == rid,
                WebResultListModel.created_by == user_id,
            )
        )
        await db.commit()

        return {"result_id": rid, "deleted": True}

    @staticmethod
    async def analysis_web_script(db: AsyncSession, data: Dict[str, Any]) -> Tuple[bool, str, List[Dict[str, Any]], int]:
        
        try:
            script: List[Dict[str, Any]] = []
            for i in data.get("script") or []:
                menu_id = int(i["id"])
                script_row = await db.execute(
                    select(WebScriptModel).where(WebScriptModel.menu_id == menu_id, WebScriptModel.enabled_flag == 1)
                )
                row = script_row.scalar_one_or_none()
                if not row:
                    continue
                ok, msg, result = await WebManagementService.analysis_web_script_detail(db, row.script or [], menu_id)
                if not ok:
                    return False, msg, [], int(data.get("browser_type") or 2)
                script.extend(result)

            script_list: List[Dict[str, Any]] = []
            for b in data.get("browser") or []:
                script_list.append(
                    {
                        "script": script,
                        "result_id": str(data["result_id"]),
                        "browser": int(b),
                        "width": data.get("width"),
                        "height": data.get("height"),
                    }
                )
            return True, "任务创建成功", script_list, int(data.get("browser_type") or 2)
        except Exception as e:
            return False, str(e), [], int(data.get("browser_type") or 2)

    @staticmethod
    async def analysis_web_script_detail(
        db: AsyncSession, script: List[Dict[str, Any]], menu_id: int
    ) -> Tuple[bool, str, List[Dict[str, Any]]]:
        
        try:
            result: List[Dict[str, Any]] = []
            for step in script:
                step["menu_id"] = menu_id

                # 目标元素处理（拖拽等）
                if step.get("type") == 4 and step.get("action", {}).get("target_type") == 2:
                    target_id_path = step["action"].get("target_id") or []
                    if target_id_path:
                        tid = int(target_id_path[-1])
                        el_res = await db.execute(
                            select(WebElementModel).where(WebElementModel.id == tid, WebElementModel.enabled_flag == 1)
                        )
                        web_el = el_res.scalar_one_or_none()
                        if web_el and web_el.element:
                            element = web_el.element
                            step["action"]["target"] = element.get("value")
                            if element.get("type") == 1:
                                step["action"]["target_locator"] = 1
                            if element.get("type") == 2:
                                if element.get("locator_type") == 3:
                                    step["action"]["type"] = 1
                                    step["action"]["target_locator"] = 1
                                elif element.get("locator_type") == 4:
                                    step["action"]["target_locator"] = 2
                                    step["action"]["target_locator_select"] = element.get("locator_select_type")
                                    step["action"]["role"] = element.get("locator_role_type")

                # 主元素处理
                if step.get("action", {}).get("type") == 2:
                    eid_path = step["action"].get("element_id") or []
                    if eid_path:
                        eid = int(eid_path[-1])
                        el_res = await db.execute(
                            select(WebElementModel).where(WebElementModel.id == eid, WebElementModel.enabled_flag == 1)
                        )
                        web_el = el_res.scalar_one_or_none()
                        if web_el and web_el.element:
                            element = web_el.element
                            step["action"]["element"] = element.get("value")
                            if element.get("type") == 1:
                                step["action"]["locator"] = 1
                            if element.get("type") == 2:
                                step["action"]["type"] = 1
                                if element.get("locator_type") == 3:
                                    step["action"]["locator"] = 1
                                elif element.get("locator_type") == 4:
                                    step["action"]["locator"] = 2
                                    step["action"]["locator_select"] = element.get("locator_select_type")
                                    step["action"]["role"] = element.get("locator_role_type")

                if step.get("children"):
                    ok, msg, child = await WebManagementService.analysis_web_script_detail(
                        db, step["children"], menu_id
                    )
                    if ok:
                        step["children"] = child
                result.append(step)
            return True, "任务创建成功", result
        except Exception as e:
            return False, str(e), []

    @staticmethod
    async def import_elements(db: AsyncSession, elements: List[Dict[str, Any]], user_id: int) -> Dict[str, Any]:

    
        created = 0
        updated = 0
        skipped = 0

        for item in elements or []:
            name = str(item.get("name") or item.get("fill_name") or "").strip()
            payload = item.get("element") if isinstance(item.get("element"), dict) else item
            if not name:
                skipped += 1
                continue

            
            res = await db.execute(
                select(WebElementModel).where(
                    WebElementModel.enabled_flag == 1,
                    WebElementModel.created_by == user_id,
                    WebElementModel.name == name,
                )
            )
            row = res.scalar_one_or_none()
            if row:
                row.element = payload
                row.last_updated_by = user_id
                updated += 1
            else:
                row = WebElementModel(
                    name=name,
                    element=payload if isinstance(payload, dict) else {"value": payload},
                    menu_id=item.get("menu_id"),
                    created_by=user_id,
                )
                db.add(row)
                await db.flush()

                # 同步创建 element menu 叶子节点（若提供 pid，则挂到 pid 下；否则不建菜单节点）
                pid = item.get("pid") or item.get("menu_id")
                if pid:
                    menu = WebElementMenuModel(
                        name=name,
                        pid=int(pid),
                        type=2,
                        element_id=row.id,
                        created_by=user_id,
                    )
                    db.add(menu)
                created += 1

        return {"created": created, "updated": updated, "skipped": skipped}

    @staticmethod
    async def get_web_result(
        db: AsyncSession, result_id: str, browser: int, user_id: int
    ) -> List[Dict[str, Any]]:
        result = await db.execute(
            select(WebResultDetailModel).where(
                WebResultDetailModel.enabled_flag == 1,
                WebResultDetailModel.result_id == result_id,
                WebResultDetailModel.browser == str(browser),
            ).order_by(WebResultDetailModel.id.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "result_id": r.result_id,
                "browser": r.browser,
                "log": r.log,
                "status": r.status,
                "before_img": r.before_img,
                "after_img": r.after_img,
                "video": r.video,
                "trace": r.trace,
                "assert_result": r.assert_result,
                "menu_id": r.menu_id,
                "creation_date": r.creation_date,
            }
            for r in rows
        ]

    @staticmethod
    def _playwright_base_dir() -> Path:
        
        backend_root = Path(__file__).resolve().parents[4]
        return backend_root / app_config.STATIC_DIR / "media" / "playwright"

    @staticmethod
    async def get_web_result_log(*, result_id: str, browser: int) -> List[str]:
        base_dir = WebManagementService._playwright_base_dir() / str(result_id) / str(browser)
        base_dir.mkdir(parents=True, exist_ok=True)
        path = base_dir / f"{browser}_result.txt"
        if not path.exists():
            return []
        content = path.read_text(encoding="utf-8", errors="ignore")
        log = content.split("\n")
        log_list = log[::-1]
        return log_list[1:]

    @staticmethod
    async def get_web_result_list(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        page = int(body.get("page") or 1)
        page_size = int(body.get("pageSize") or 10)
        if page <= 0:
            page = 1
        if page_size <= 0:
            page_size = 10

        q = select(WebResultListModel).where(
            WebResultListModel.enabled_flag == 1,
            WebResultListModel.created_by == user_id,
        ).order_by(WebResultListModel.id.desc())

        search = body.get("search") if isinstance(body.get("search"), dict) else {}
        task_name_kw = str(
            body.get("task_name__icontains")
            or search.get("task_name__icontains")
            or search.get("task_name")
            or ""
        ).strip()
        if task_name_kw:
            q = q.where(WebResultListModel.task_name.contains(task_name_kw))

        res = await db.execute(q)
        all_rows = res.scalars().all()
        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = all_rows[start:end]
        user_ids = [int(r.created_by) for r in page_rows if getattr(r, "created_by", None)]
        username_map = await _get_username_map(db, user_ids)
        content = []
        for r in page_rows:
            total_num = 0
            total_fail = 0
            for j in (r.result or []):
                total_num += int(j.get("total") or 0)
                total_fail += int(j.get("run_false") or 0)
            percent = round((total_num - total_fail) / total_num * 100, 2) if total_num > 0 else 0
            uid = getattr(r, "created_by", None)
            content.append(
                {
                    "id": r.id,
                    "task_name": r.task_name,
                    "result_id": r.result_id,
                    "script_list": r.script_list,
                    "browser_list": r.browser_list,
                    "pid_list": r.pid_list or [],
                    "result": r.result,
                    "start_time": r.start_time,
                    "end_time": r.end_time,
                    "status": r.status,
                    "percent": percent,
                    "username": username_map.get(int(uid), "") if uid else "",
                }
            )

        return {
            "content": content,
            "totalElements": total,
            "page": page,
            "pageSize": page_size,
        }

   

    @staticmethod
    async def get_web_result_report(db: AsyncSession, *, result_id: str, user_id: int) -> Dict[str, Any]:
      
        res = await db.execute(
            select(WebResultListModel).where(
                WebResultListModel.enabled_flag == 1,
                WebResultListModel.result_id == result_id,
                WebResultListModel.created_by == user_id,
            )
        )
        row = res.scalar_one_or_none()
        if not row:
            return {}

        result_list = row.result or []
        total = 0
        total_fail = 0
        for i in result_list:
            total += int(i.get("total") or 0)
            total_fail += int(i.get("run_false") or 0)

        percent = round((total - total_fail) / total * 100, 2) if total > 0 else 0

        # 标记 script_list 中每个脚本的整体 status
        script_list = list(row.script_list or [])
        for j in script_list:
            mid = int(j.get("id") or 0)
            if not mid:
                j["status"] = 1
                continue
            cnt = await db.execute(
                select(func.count(WebResultDetailModel.id)).where(
                    WebResultDetailModel.enabled_flag == 1,
                    WebResultDetailModel.result_id == result_id,
                    WebResultDetailModel.menu_id == mid,
                    WebResultDetailModel.status == 0,
                )
            )
            fail_num = int(cnt.scalar() or 0)
            j["status"] = 0 if fail_num > 0 else 1

        uid = getattr(row, "created_by", None)
        username_map = await _get_username_map(db, [int(uid)] if uid else [])
        username = username_map.get(int(uid), "") if uid else ""

        return {
            "id": row.id,
            "task_name": row.task_name,
            "result_id": row.result_id,
            "script_list": script_list,
            "browser_list": row.browser_list,
            "result": result_list,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "status": row.status,
            "percent": percent,
            "total": total,
            "total_fail": total_fail,
            "username": username,
        }

    @staticmethod
    def _parse_timestamp(line: str):
        try:
            timestamp_str = line.split(" ")[0] + " " + line.split(" ")[1]
            return True, int(datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").timestamp())
        except Exception as e:
            return False, e

    @staticmethod
    def _time_add_3s(t: str) -> str:
        try:
            original_time = datetime.strptime(str(t), "%Y-%m-%d %H:%M:%S")
            return (original_time + timedelta(seconds=3)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return t

    @staticmethod
    def _filter_by_time_range(lines: List[str], start_time: str, end_time: str) -> List[str]:
        start = int(datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").timestamp())
        end = int(datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").timestamp())
        filtered: List[str] = []
        for line in lines:
            ok, ts = WebManagementService._parse_timestamp(line)
            if ok and start <= ts <= end:
                filtered.append(line)
        return filtered

    @staticmethod
    async def get_web_result_detail(
        db: AsyncSession,
        *,
        result_id: str,
        browser: int,
        menu_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
       
        # media（执行结束记录上挂 video/trace）
        media_res = await db.execute(
            select(WebResultDetailModel).where(
                WebResultDetailModel.enabled_flag == 1,
                WebResultDetailModel.result_id == result_id,
                WebResultDetailModel.browser == str(browser),
                WebResultDetailModel.log == "执行结束",
            )
        )
        media = media_res.scalar_one_or_none()
        video = media.video if media else ""
        trace = media.trace if media else ""

        detail_res = await db.execute(
            select(WebResultDetailModel).where(
                WebResultDetailModel.enabled_flag == 1,
                WebResultDetailModel.result_id == result_id,
                WebResultDetailModel.browser == str(browser),
                WebResultDetailModel.menu_id == menu_id,
            ).order_by(WebResultDetailModel.id.desc())
        )
        rows = detail_res.scalars().all()
        content = [
            {
                "id": r.id,
                "name": r.name,
                "result_id": r.result_id,
                "browser": r.browser,
                "log": r.log,
                "status": r.status,
                "before_img": r.before_img,
                "after_img": r.after_img,
                "video": r.video,
                "trace": r.trace,
                "assert_result": r.assert_result,
                "menu_id": r.menu_id,
                "create_time": r.creation_date.strftime("%Y-%m-%d %H:%M:%S") if r.creation_date else "",
            }
            for r in rows
        ]

        # 日志按步骤时间范围过滤
        log_list: List[str] = []
        if content:
            start_time = content[-1]["create_time"]
            end_time = WebManagementService._time_add_3s(content[0]["create_time"])
            base_dir = WebManagementService._playwright_base_dir() / str(result_id) / str(browser)
            base_dir.mkdir(parents=True, exist_ok=True)
            log_path = base_dir / f"{browser}_result.txt"
            if log_path.exists():
                raw = log_path.read_text(encoding="utf-8", errors="ignore")
                lines = raw.split("\n")
                log_list = WebManagementService._filter_by_time_range(lines, start_time, end_time)[::-1]

        return {"content": content, "log": log_list, "video": video, "trace": trace}

    @staticmethod
    async def get_web_groups(
        db: AsyncSession,
        user_id: int,
        *,
        name_icontains: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Dict[str, Any]:

        if page <= 0:
            page = 1
        if page_size <= 0:
            page_size = 10

        conditions = [
            WebGroupModel.enabled_flag == 1,
            WebGroupModel.created_by == user_id,
        ]
        if name_icontains:
            conditions.append(WebGroupModel.name.contains(name_icontains.strip()))

        result = await db.execute(
            select(WebGroupModel)
            .where(*conditions)
            .order_by(WebGroupModel.id.desc())
        )
        rows = result.scalars().all()
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows[start:end]

        user_ids = []
        for r in page_rows:
            uid = getattr(r, "updated_by", None) or getattr(r, "created_by", None)
            if uid:
                user_ids.append(int(uid))
        username_map = await _get_username_map(db, user_ids)
        out = []
        for r in page_rows:
            uid = getattr(r, "updated_by", None) or getattr(r, "created_by", None)
            creation_date = getattr(r, "creation_date", None)
            updation_date = getattr(r, "updation_date", None)
            
            if creation_date is not None and hasattr(creation_date, "isoformat"):
                creation_date = creation_date.isoformat()
            if updation_date is not None and hasattr(updation_date, "isoformat"):
                updation_date = updation_date.isoformat()
            out.append({
                "id": r.id,
                "name": r.name or "",
                "script": r.script if r.script is not None else [],
                "description": r.description or "",
                "creation_date": creation_date,
                "updation_date": updation_date,
                "created_by": getattr(r, "created_by", None),
                "updated_by": getattr(r, "updated_by", None),
                "username": username_map.get(int(uid), "") if uid else "",
            })
        return {"content": out, "total": total, "page": page, "pageSize": page_size}

    @staticmethod
    async def create_web_group(db: AsyncSession, group_data: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """创建Web脚本集"""
        grp = WebGroupModel(
            name=group_data["name"],
            script=group_data.get("script") or [],
            description=group_data.get("description") or "",
            created_by=user_id,
        )
        db.add(grp)
        await db.flush()
        return {"id": grp.id}

    @staticmethod
    async def edit_web_group(db: AsyncSession, group_data: Dict[str, Any], user_id: int) -> None:

        result = await db.execute(
            select(WebGroupModel).where(
                WebGroupModel.id == int(group_data["id"]),
                WebGroupModel.enabled_flag == 1,
            )
        )
        grp = result.scalar_one_or_none()
        if not grp:
            return
        grp.name = group_data["name"]
        grp.script = group_data["script"]
        grp.description = group_data.get("description") or ""
        grp.last_updated_by = user_id

    @staticmethod
    async def delete_web_group(db: AsyncSession, group_id: int) -> None:

        result = await db.execute(
            select(WebGroupModel).where(
                WebGroupModel.id == group_id,
                WebGroupModel.enabled_flag == 1,
            )
        )
        grp = result.scalar_one_or_none()
        if not grp:
            return
        await db.execute(
            delete(WebGroupModel).where(
                WebGroupModel.id == group_id,
            )
        )

    @staticmethod
    async def get_web_group_all(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:

        result = await db.execute(
            select(WebGroupModel).where(
                WebGroupModel.enabled_flag == 1,
                WebGroupModel.created_by == user_id,
            ).order_by(WebGroupModel.id.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "script": r.script,
                "description": r.description,
            }
            for r in rows
        ]

    @staticmethod
    async def get_script_list(db: AsyncSession) -> List[Dict[str, Any]]:

        result = await db.execute(
            select(WebMenuModel).where(
                WebMenuModel.enabled_flag == 1,
                WebMenuModel.type == 2,
            )
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "pid": r.pid,
                "type": r.type,
            }
            for r in rows
        ]

    @staticmethod
    async def group_add_script(db: AsyncSession, web_list: List[List[int]]) -> List[Dict[str, Any]]:

        result: List[Dict[str, Any]] = []
        for path in web_list:
            if not path:
                continue
            menu_id = int(path[-1])
            row_res = await db.execute(
                select(WebMenuModel).where(
                    WebMenuModel.id == menu_id,
                    WebMenuModel.enabled_flag == 1,
                )
            )
            menu = row_res.scalar_one_or_none()
            if menu and menu.type == 2:
                result.append(
                    {
                        "id": menu.id,
                        "name": menu.name,
                        "pid": menu.pid,
                        "type": menu.type,
                    }
                )
        return result



    @staticmethod
    async def capture_screenshots(page, step_name: str) -> str:
        """捕获截图"""
        from pathlib import Path
        from datetime import datetime
        import re

        safe_step = re.sub(r"[^\w\u4e00-\u9fff\-_.]+", "_", str(step_name or "step"))[:60]
        
        base_dir = WebManagementService._playwright_base_dir() / "common"
        base_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe_step}.png"
        path = base_dir / filename
        await page.screenshot(path=path, full_page=True)
        return f"/media/playwright/common/{filename}"

    @staticmethod
    async def record_video(page, output_path: str) -> str:
        """录制视频"""
        import shutil
        from pathlib import Path

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        
        video = getattr(page, "video", None)
        if not video:
            raise ValueError("page.video 不存在：请确保创建 context 时开启 record_video_dir")
        src = Path(await video.path())
        shutil.copyfile(src, out)
        return str(out)

    @staticmethod
    async def save_trace(page, trace_path: str) -> str:
        """保存trace文件"""
        from pathlib import Path

        out = Path(trace_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        ctx = getattr(page, "context", None)
        tracing = getattr(ctx, "tracing", None) if ctx else None
        if not tracing:
            raise ValueError("page.context.tracing 不可用：请确保使用 Playwright BrowserContext")
        await tracing.stop(path=out)
        return str(out)

    @staticmethod
    async def validate_web_assertions(assertions: List[Dict[str, Any]], page) -> List[Dict[str, Any]]:
        """验证Web断言"""
        results: List[Dict[str, Any]] = []
        for a in assertions or []:
            item = dict(a)
            status = 1
            result_msg = "断言成功"
            try:
                t = int(item.get("type") or 1)
                expected = str(item.get("element") or "")

                if t in (1, 2):
          
                    locator = expected
                    el = page.locator(locator)
                    exists = await el.is_visible()
                    if (t == 1 and exists) or (t == 2 and (not exists)):
                        status = 1
                        result_msg = "断言成功"
                    else:
                        status = 0
                        result_msg = "断言失败"

                elif t in (3, 4):
                    # HTML 包含/不包含
                    html = await page.content()
                    contains = expected in html
                    if (t == 3 and contains) or (t == 4 and (not contains)):
                        status = 1
                        result_msg = "断言成功"
                    else:
                        status = 0
                        result_msg = "断言失败"

                elif t == 5:
                    # URL/Title 等于
                    page_type = int(item.get("page_type") or 1)  # 1 url, 2 title
                    if page_type == 1:
                        ok = (page.url == expected)
                    else:
                        ok = ((await page.title()) == expected)
                    status = 1 if ok else 0
                    result_msg = "断言成功" if ok else "断言失败"

                elif t == 6:
                    # eval 自定义脚本（提供 page）
                    from playwright.async_api import expect  # noqa: F401
                    eval(expected, {"page": page, "expect": expect})
                    status = 1
                    result_msg = "断言成功"

                else:

                    status = 1
                    result_msg = "断言跳过(未知类型)"

            except Exception as e:
                status = 0
                result_msg = f"断言失败，原因是：{str(e)}"

            item["status"] = status
            item["result"] = result_msg
            results.append(item)

        return results

    @staticmethod
    async def ai_generate_script(
        url: str,
        description: str,
        user_id: int,
        browser_type: str = "msedge",
        viewport_width: int = 1280,
        viewport_height: int = 720,
    ) -> Dict[str, Any]:
        """方案 B：启动 headless Playwright 打开目标页，截图 + 提取页面可交互元素，
        发给多模态 LLM，AI 根据真实页面信息生成平台脚本步骤 JSON。"""
        import base64
        import json as _json
        import platform as _platform
        from playwright.async_api import async_playwright
        from app.infra.db.sqlalchemy import async_session_factory
        from app.api.v1.Ntesterc_module.Ntesterc_ai.llm_config.model import LLMConfigModel
        from app.api.v1.Ntesterc_module.Ntesterc_intel.ai_model_service import AIModelService
        from sqlalchemy import select as _select

        # ---- 1. 获取默认多模态 LLM 配置 ----
        async with async_session_factory() as db:
            res = await db.execute(
                _select(LLMConfigModel).where(
                    LLMConfigModel.is_default == True,
                    LLMConfigModel.is_active == True,
                    LLMConfigModel.enabled_flag == 1,
                )
            )
            llm_config = res.scalar_one_or_none()
            if not llm_config:
                res2 = await db.execute(
                    _select(LLMConfigModel).where(
                        LLMConfigModel.is_active == True,
                        LLMConfigModel.enabled_flag == 1,
                    ).limit(1)
                )
                llm_config = res2.scalar_one_or_none()
        if not llm_config:
            raise RuntimeError("未找到可用的LLM配置，请在系统设置中配置支持视觉的AI模型（如GPT-4o/Claude/Gemini等）")

        # ---- 2. 启动 headless Playwright 打开页面 ----
        launch_config = {
            "chrome":  {"browser": "chromium", "channel": "chrome"},
            "msedge":  {"browser": "chromium", "channel": "msedge"},
            "firefox": {"browser": "firefox", "channel": None},
            "webkit":  {"browser": "webkit", "channel": None},
            "chromium":{"browser": "chromium", "channel": None},
        }
        cfg = launch_config.get(browser_type.lower(), launch_config["msedge"])
        _is_linux = _platform.system().lower() != "windows"
        # AI 生成脚本必须 headless，channel 在 headless 下不稳定（尤其 msedge/chrome 易退出），
        # 统一使用 Playwright 自带的 Chromium，不指定 channel。
        channel = None

        async with async_playwright() as pw:
            # 优先用 Playwright 自带浏览器；channel 仅用于 headed 录制场景，headless 生成脚本时避免
            browser_name = cfg["browser"]
            launch_kwargs: Dict[str, Any] = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            }
            try:
                browser = await getattr(pw, browser_name).launch(**launch_kwargs)
            except Exception as launch_err:
                err_msg = str(launch_err)
                if "Executable doesn't exist" in err_msg or "executable doesn't exist" in err_msg.lower():
                    raise RuntimeError(
                        f"Playwright {browser_name} 浏览器未安装。请在服务器执行：cd D:\\GeniusQA\\backend && .venv\\Scripts\\python.exe -m playwright install {browser_name}"
                    )
                raise RuntimeError(f"启动 Playwright 浏览器失败：{err_msg}")

            context = await browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
            )
            page = await context.new_page()
            try:
                await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass  # networkidle 不是必须的

                # 3. 截图
                screenshot_bytes = await page.screenshot(type="jpeg", quality=70)
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

                # 4. 提取页面可交互元素
                elements_js = await page.evaluate("""() => {
                    const selectors = 'button, a, input, select, textarea, [role], [data-testid], [aria-label], [placeholder]';
                    const seen = new Set();
                    return Array.from(document.querySelectorAll(selectors))
                        .filter(el => {
                            const rect = el.getBoundingClientRect();
                            if (rect.width === 0 || rect.height === 0) return false;
                            const style = getComputedStyle(el);
                            if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity) === 0) return false;
                            const text = (el.textContent || el.value || el.placeholder || '').trim().substring(0, 80);
                            const key = el.tagName + '|' + text;
                            if (seen.has(key)) return false;
                            seen.add(key);
                            return true;
                        })
                        .slice(0, 80)
                        .map(el => ({
                            tag: el.tagName.toLowerCase(),
                            text: (el.textContent || '').trim().substring(0, 60),
                            id: el.id || null,
                            name: el.getAttribute('name'),
                            type: el.getAttribute('type'),
                            placeholder: el.getAttribute('placeholder'),
                            role: el.getAttribute('role'),
                            ariaLabel: el.getAttribute('aria-label'),
                            testId: el.getAttribute('data-testid'),
                            title: el.getAttribute('title'),
                            className: (typeof el.className === 'string') ? el.className.split(' ').slice(0, 3).join(' ') : null,
                            href: el.tagName === 'A' ? el.getAttribute('href') : null,
                            value: el.tagName === 'INPUT' ? (el.value || '') : null,
                        }));
                }""")

                page_title = await page.title()
                page_url = page.url

            finally:
                await context.close()
                await browser.close()

        # ---- 5. 构造 prompt 发给多模态 LLM ----
        elements_text = _json.dumps(elements_js, ensure_ascii=False, indent=2)

        system_prompt = f"""你是一个 Web 自动化测试专家。用户会给你：
1. 一张网页截图
2. 页面可交互元素列表（JSON格式，含 tag/text/id/placeholder/role/ariaLabel/testId 等属性）
3. 测试需求描述

请分析截图和元素列表，生成一个平台可执行的测试脚本步骤数组。

【页面URL】{page_url}
【页面标题】{page_title}
【视口】{viewport_width}x{viewport_height}

【步骤格式要求】严格返回 JSON 数组，每个步骤格式如下：
{{
  "name": "步骤描述",
  "type": 步骤类型(整数),
  "action": {{
    "type": 1,
    "input": "输入文本（仅 type 5/6 需要）",
    "element": "定位值",
    "locator": 2,
    "locator_select": 定位策略(整数),
    "assert": [],
    "before_wait": 1,
    "after_wait": 1,
    "timeout": 15
  }}
}}

【type 枚举】
0=打开网页(element填URL), 1=点击, 2=双击, 3=长按,
5=直接输入, 6=追加输入, 7=清空输入框,
10=if条件, 11=for循环, 12=等待(秒),
13=打开新窗口, 14=切上一个窗口, 15=切下一个窗口,
16=右键点击, 17=自定义JS脚本, 20=刷新页面, 21=关闭标签页

【locator 枚举】1=从元素库(不用), 2=自定义选择器
【locator_select 枚举】1=id, 2=text, 3=label, 4=title, 5=placeholder, 6=alt, 7=role

【定位器选择规则】
- 优先用 id/data-testid（locator_select=1）
- 其次用 text（locator_select=2）
- 输入框用 placeholder（locator_select=5）
- 按钮/链接用 role（locator_select=7）配合element填role名称如"button"
- element 字段必须直接从下方元素列表中选取，不要凭空编造

只返回 JSON 数组，不要任何解释文字。"""

        user_text = (
            f"页面可交互元素列表：\n{elements_text}\n\n"
            f"测试需求：{description}\n\n"
            f"请根据截图和上面的元素列表，生成完整的测试脚本步骤 JSON 数组。"
            f"每个步骤的 element 定位值必须来自元素列表中的 text/placeholder/id/role/ariaLabel 字段，不要编造。"
        )

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}", "detail": "high"},
                    },
                    {"type": "text", "text": user_text},
                ],
            },
        ]

        # ---- 6. 调用 LLM ----
        try:
            resp = await AIModelService.call_openai_compatible_api(llm_config, messages, max_tokens=4096)
            content = resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise RuntimeError(f"LLM调用失败: {str(e)}")

        # 提取 JSON（用平衡括号扫描，避免多余文本/截断导致解析失败；脚本步骤预期是数组 []）
        block = WebManagementService._extract_json_block(content, prefer_list=True)
        if block is None:
            raise RuntimeError(f"AI未返回有效的步骤JSON（非JSON或被截断），原始回复前300字符：{content[:300]}")

        try:
            steps = _json.loads(block)
        except _json.JSONDecodeError as e:
            raise RuntimeError(f"AI返回的JSON解析失败: {str(e)}，原始回复：{content[:500]}")

        if not isinstance(steps, list):
            raise RuntimeError("AI返回的不是JSON数组")

        # ---- 7. 基本校验 & 补全默认值 ----
        validated = []
        for i, s in enumerate(steps):
            if not isinstance(s, dict):
                continue
            t = int(s.get("type", -1))
            # type 必须在已知范围内
            if t not in (0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,20,21):
                continue

            action = s.get("action") or {}
            step = {
                "name": s.get("name") or f"步骤{i+1}",
                "type": t,
                "children": s.get("children") or [],
                "status": True,
                "action": {
                    "type": int(action.get("type") or 1),
                    "input": str(action.get("input") or ""),
                    "element": str(action.get("element") or ""),
                    "locator": int(action.get("locator") or 2),
                    "locator_select": int(action.get("locator_select") or 2),
                    "assert": action.get("assert") or [],
                    "before_wait": int(action.get("before_wait") or 1),
                    "after_wait": int(action.get("after_wait") or 1),
                    "timeout": int(action.get("timeout") or 15),
                    "target": "",
                    "target_id": "",
                    "target_type": 1,
                    "target_locator": 1,
                    "target_locator_select": 1,
                    "element_id": None,
                    "cookies": [],
                    "localstorage": [],
                    "sway_type": 1,
                    "up_type": 1,
                    "wait_time": 1,
                },
            }
            validated.append(step)

        if not validated:
            raise RuntimeError("AI生成的步骤全部校验不通过，请检查需求描述或LLM配置")

        return {
            "steps": validated,
            "page_url": page_url,
            "page_title": page_title,
            "elements_count": len(elements_js),
        }

    # DOM 元素提取脚本（方案 B / B+ 共用）
    _DOM_EXTRACT_JS = """() => {
        const selectors = 'button, a, input, select, textarea, [role], [data-testid], [aria-label], [placeholder]';
        const seen = new Set();
        return Array.from(document.querySelectorAll(selectors))
            .filter(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return false;
                const style = getComputedStyle(el);
                if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity) === 0) return false;
                const text = (el.textContent || el.value || el.placeholder || '').trim().substring(0, 80);
                const key = el.tagName + '|' + text;
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
            })
            .slice(0, 80)
            .map(el => ({
                tag: el.tagName.toLowerCase(),
                text: (el.textContent || '').trim().substring(0, 60),
                id: el.id || null,
                name: el.getAttribute('name'),
                type: el.getAttribute('type'),
                placeholder: el.getAttribute('placeholder'),
                role: el.getAttribute('role'),
                ariaLabel: el.getAttribute('aria-label'),
                testId: el.getAttribute('data-testid'),
                title: el.getAttribute('title'),
                className: (typeof el.className === 'string') ? el.className.split(' ').slice(0, 3).join(' ') : null,
                href: el.tagName === 'A' ? el.getAttribute('href') : null,
                value: el.tagName === 'INPUT' ? (el.value || '') : null,
            }));
    }"""

    @staticmethod
    def _extract_json_block(text: str, prefer_object: bool = False, prefer_list: bool = False):
        """从可能含多余文本的 LLM 回复中，提取第一个括号平衡的 JSON 块（数组 [] 或对象 {}）。
        返回可传给 json.loads 的字符串；若找不到完整闭合块（被截断/无 JSON）则返回 None。
        prefer_object=True 时优先找 {}；prefer_list=True 时优先找 []。"""
        pairs = (("[", "]"), ("{", "}"))
        if prefer_object:
            pairs = (("{", "}"), ("[", "]"))
        elif prefer_list:
            pairs = (("[", "]"), ("{", "}"))

        for opener, closer in pairs:
            start = text.find(opener)
            if start == -1:
                continue
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(text)):
                c = text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                else:
                    if c == '"':
                        in_str = True
                    elif c == opener:
                        depth += 1
                    elif c == closer:
                        depth -= 1
                        if depth == 0:
                            return text[start:i + 1]
        return None

    @staticmethod
    async def ai_explore_and_generate_script(
        url: str,
        goal: str,
        user_id: int,
        account: str = "",
        password: str = "",
        browser_type: str = "msedge",
        viewport_width: int = 1280,
        viewport_height: int = 720,
        max_steps: int = 15,
    ) -> Dict[str, Any]:
        """方案 B+：多步自动探索。

        只给用户一个目标（和可选测试账号密码），AI 循环执行：
        截图 → 提取页面元素 → LLM 决策下一步 → 在真实页面执行 → 再截图 → ...
        直到 LLM 判定目标完成，或达到最大步数。
        """
        import base64
        import json as _json
        import platform as _platform
        from playwright.async_api import async_playwright
        from app.infra.db.sqlalchemy import async_session_factory
        from app.api.v1.Ntesterc_module.Ntesterc_ai.llm_config.model import LLMConfigModel
        from app.api.v1.Ntesterc_module.Ntesterc_intel.ai_model_service import AIModelService
        from sqlalchemy import select as _select

        # ---- 1. 获取默认多模态 LLM 配置 ----
        async with async_session_factory() as db:
            res = await db.execute(
                _select(LLMConfigModel).where(
                    LLMConfigModel.is_default == True,
                    LLMConfigModel.is_active == True,
                    LLMConfigModel.enabled_flag == 1,
                )
            )
            llm_config = res.scalar_one_or_none()
            if not llm_config:
                res2 = await db.execute(
                    _select(LLMConfigModel).where(
                        LLMConfigModel.is_active == True,
                        LLMConfigModel.enabled_flag == 1,
                    ).limit(1)
                )
                llm_config = res2.scalar_one_or_none()
        if not llm_config:
            raise RuntimeError("未找到可用的LLM配置，请在系统设置中配置支持视觉的AI模型（如GPT-4o/Claude/Gemini等）")

        # ---- 2. 启动 headless Playwright ----
        browser_name = "chromium"
        launch_kwargs: Dict[str, Any] = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        try:
            async with async_playwright() as pw:
                try:
                    browser = await pw.chromium.launch(**launch_kwargs)
                except Exception as launch_err:
                    err_msg = str(launch_err)
                    if "Executable doesn't exist" in err_msg or "executable doesn't exist" in err_msg.lower():
                        raise RuntimeError(
                            f"Playwright chromium 浏览器未安装。请在服务器执行：cd D:\\GeniusQA\\backend && .venv\\Scripts\\python.exe -m playwright install chromium"
                        )
                    raise RuntimeError(f"启动 Playwright 浏览器失败：{err_msg}")

                context = await browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height},
                )
                page = await context.new_page()
                try:
                    await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass

                    steps: List[Dict[str, Any]] = []
                    history: List[str] = []
                    done = False
                    last_error = ""

                    for step_idx in range(int(max_steps)):
                        # 截图
                        screenshot_bytes = await page.screenshot(type="jpeg", quality=70)
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

                        # 提取元素
                        try:
                            elements_js = await page.evaluate(WebManagementService._DOM_EXTRACT_JS)
                        except Exception:
                            elements_js = []

                        page_title = await page.title()
                        page_url_now = page.url

                        # 构造 LLM 决策 prompt
                        elements_text = _json.dumps(elements_js, ensure_ascii=False, indent=2)
                        history_text = "\n".join(f"{i+1}. {h}" for i, h in enumerate(history)) or "（尚未执行任何步骤）"

                        system_prompt = f"""你是一个 Web 自动化测试 Agent，正在逐步完成一个测试目标。请用多模态能力分析当前页面截图和元素列表，决定【下一步】操作。

【测试目标】{goal}
【已执行步骤历史】
{history_text}

【测试账号】{account or '（未提供）'}
【测试密码】{password or '（未提供）'}

【页面URL】{page_url_now}
【页面标题】{page_title}

【完成判定规则 - 严格】
- 必须完整执行测试目标中描述的所有动作，不能只做一部分就返回 done=true。
- 例如目标包含"完成登录"时：仅仅进入登录页不算完成，必须完成"输入账号→输入密码→点击登录按钮"，并确认页面跳转或出现登录成功标志后，才能返回 done=true。
- 如果当前页面仍有未填写的账号/密码输入框，且目标包含"登录/登入/填写账号"，则 done 必须为 false，下一步必须是填写或点击操作。
- 只有在目标完全达成，或者遇到验证码/短信/人机验证等确实无法自动化的障碍时，才允许 done=true。

【最重要】请严格返回如下 JSON（不要任何解释文字，不要 markdown 代码块，不要换行符分隔多个 JSON）：
{{
  "done": false,
  "thought": "简要说明这一步为什么这么做以及离目标还差什么",
  "name": "这一步的中文描述",
  "action_type": 1,
  "action": {{
    "type": 1,
    "input": "输入文本（仅 type 5/6 需要，密码从测试密码取）",
    "element": "定位值",
    "locator": 2,
    "locator_select": 1,
    "assert": [],
    "before_wait": 1,
    "after_wait": 1,
    "timeout": 15
  }}
}}

如果目标已经达成，返回：
{{
  "done": true,
  "thought": "目标已完成",
  "name": "结束",
  "action_type": 12,
  "action": {{"type":1,"input":"","element":"1","locator":2,"locator_select":2,"assert":[],"before_wait":1,"after_wait":1,"timeout":15}}
}}

【action_type 枚举】
0=打开网页, 1=点击, 2=双击, 3=长按,
5=直接输入, 6=追加输入, 7=清空输入框,
10=if条件, 11=for循环, 12=等待(秒),
13=打开新窗口, 14=切上一个窗口, 15=切下一个窗口,
16=右键点击, 17=自定义JS, 20=刷新, 21=关闭标签页

【locator 枚举】1=元素库(不用), 2=自定义选择器
【locator_select 枚举】1=id, 2=text, 3=label, 4=title, 5=placeholder, 6=alt, 7=role

【定位器选择规则】
- 优先 id/data-testid（locator_select=1）
- 其次 text（locator_select=2）
- 输入框用 placeholder（locator_select=5）
- 按钮/链接用 role（locator_select=7）配合 element 填 role 名称如 "button"
- element 字段只能从下方元素列表的 text/placeholder/id/role/ariaLabel 中选取，不要编造

只返回 JSON，不要解释。"""

                        user_text = (
                            f"当前页面可交互元素列表：\n{elements_text}\n\n"
                            f"【禁止重复】如果上一步已经执行过某个点击/输入操作，绝对不要再次生成完全相同的操作。"
                            f"例如上一步已经点击了 'USDT Withdrawal'，下一步就不应该再点它。"
                            f"如果某个点击没有产生页面变化（URL 没变、菜单没展开），请换用 hover 或直接选择菜单内的子项。\n\n"
                            f"请决定下一步操作。如果目标已经完成，返回 done=true。"
                        )

                        messages = [
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}", "detail": "high"},
                                    },
                                    {"type": "text", "text": user_text},
                                ],
                            },
                        ]

                        # ---- 调用 LLM 并解析（解析失败/截断最多重试 2 次，把错误反馈给模型重答）----
                        decision = None
                        parse_err = ""
                        for attempt in range(3):
                            try:
                                resp = await AIModelService.call_openai_compatible_api(llm_config, messages, max_tokens=2048)
                                content = (resp["choices"][0]["message"].get("content") or "").strip()
                            except Exception as e:
                                parse_err = f"第{step_idx+1}步 LLM 调用失败: {str(e)}"
                                break

                            if not content:
                                parse_err = f"第{step_idx+1}步 LLM 返回空内容"
                                # 空回复大概率是上下文/图片过大导致，重试时去掉图片只给元素列表
                                messages.append({"role": "assistant", "content": "（空回复）"})
                                messages.append({"role": "user", "content": "请根据当前页面元素列表返回单个 JSON 对象，不要解释文字。"})
                                continue

                            block = WebManagementService._extract_json_block(content, prefer_object=True)
                            if block is None:
                                parse_err = f"第{step_idx+1}步 LLM 返回无法解析（非JSON或被截断）：{content[:300]}"
                                # 把错误反馈给模型，要求仅返回完整 JSON 后重试
                                messages.append({"role": "assistant", "content": content})
                                messages.append({"role": "user", "content": "你的回复必须是单个 JSON 对象（以 } 结尾），不要任何解释文字。请重新只返回 JSON。"})
                                continue

                            try:
                                decision = _json.loads(block)
                            except _json.JSONDecodeError as e:
                                parse_err = f"第{step_idx+1}步 JSON 解析失败: {str(e)}，原始回复：{content[:300]}"
                                messages.append({"role": "assistant", "content": content})
                                messages.append({"role": "user", "content": f"JSON 解析失败：{str(e)}。请重新返回合法且完整的单个 JSON 对象（务必含闭合大括号）。"})
                                continue

                            if not isinstance(decision, dict):
                                parse_err = f"第{step_idx+1}步 LLM 返回了 {type(decision).__name__} 而非 JSON 对象：{content[:300]}"
                                messages.append({"role": "assistant", "content": content})
                                messages.append({"role": "user", "content": "你的回复必须是单个 JSON 对象（{...}），不能是数组。请重新只返回 JSON 对象。"})
                                continue
                            break

                        if decision is None:
                            last_error = parse_err or f"第{step_idx+1}步 LLM 多次解析失败"
                            break

                        # 兜底：如果 LLM 说完成，但页面上仍有未填的账号/密码框且我们提供了账号密码，
                        # 则认定尚未完成，继续生成填写步骤
                        if decision.get("done") is True:
                            if account and password and WebManagementService._page_has_unfilled_login_fields(elements_js):
                                # 改写为未完成的等待步骤，让 LLM 下一步继续处理
                                decision["done"] = False
                                decision["action_type"] = 12
                                decision["name"] = "等待页面稳定后填写登录信息"
                                decision["action"] = {
                                    "type": 1, "input": "", "element": "1",
                                    "locator": 2, "locator_select": 2,
                                    "assert": [], "before_wait": 1, "after_wait": 2,
                                    "timeout": 15,
                                }
                            else:
                                done = True
                                break

                        # 校验 action_type
                        action_type = int(decision.get("action_type", -1))
                        if action_type not in (0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,20,21):
                            last_error = f"第{step_idx+1}步 action_type 非法: {action_type}"
                            break

                        # 去重：如果这一步和最近 3 步的（类型+定位值+选择器）完全相同，则强制 LLM 重新决策
                        next_action = decision.get("action") or {}
                        dup_check = {
                            "type": action_type,
                            "element": str(next_action.get("element") or ""),
                            "locator_select": int(next_action.get("locator_select") or 2),
                        }
                        recent = [
                            {
                                "type": s.get("type"),
                                "element": str((s.get("action") or {}).get("element") or ""),
                                "locator_select": int((s.get("action") or {}).get("locator_select") or 2),
                            }
                            for s in steps[-3:]
                        ]
                        if any(r == dup_check for r in recent):
                            last_error = f"第{step_idx+1}步与近期步骤重复（{dup_check['element']}），AI 可能在原地打转。"
                            break

                        action = next_action
                        step_obj = {
                            "name": decision.get("name") or f"步骤{step_idx+1}",
                            "type": action_type,
                            "children": [],
                            "status": True,
                            "action": {
                                "type": int(action.get("type") or 1),
                                "input": str(action.get("input") or ""),
                                "element": str(action.get("element") or ""),
                                "locator": int(action.get("locator") or 2),
                                "locator_select": int(action.get("locator_select") or 2),
                                "assert": action.get("assert") or [],
                                "before_wait": int(action.get("before_wait") or 1),
                                "after_wait": int(action.get("after_wait") or 1),
                                "timeout": int(action.get("timeout") or 15),
                                "target": "",
                                "target_id": "",
                                "target_type": 1,
                                "target_locator": 1,
                                "target_locator_select": 1,
                                "element_id": None,
                                "cookies": [],
                                "localstorage": [],
                                "sway_type": 1,
                                "up_type": 1,
                                "wait_time": 1,
                            },
                            "step_number": step_idx + 1,
                        }
                        steps.append(step_obj)
                        history.append(decision.get("name") or f"步骤{step_idx+1}")

                        # ---- 在真实页面执行该动作 ----
                        exec_ok, exec_msg = await WebManagementService._execute_explore_action(
                            page, step_obj, account, password
                        )
                        if not exec_ok:
                            last_error = f"第{step_idx+1}步执行失败: {exec_msg}"
                            # 仍保留该步骤，但中断循环，让用户看到已生成的部分
                            break

                        # 执行后等待页面稳定
                        try:
                            await page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                        await page.wait_for_timeout(800)

                        # 快捷完成：如果这一步看起来是点击登录/登入按钮，且页面已离开登录页、没有未填登录框，自动结束
                        if (
                            action_type == 1
                            and any(k in (step_obj.get("name") or "").lower() for k in ("登录", "登入", "login", "sign in", "submit"))
                            and "login" not in page.url.lower()
                            and not WebManagementService._page_has_unfilled_login_fields(await page.evaluate(WebManagementService._DOM_EXTRACT_JS))
                        ):
                            done = True
                            break

                    return {
                        "steps": steps,
                        "done": done,
                        "steps_count": len(steps),
                        "last_error": last_error,
                        "final_url": page.url,
                        "final_title": await page.title(),
                    }
                finally:
                    await context.close()
                    await browser.close()
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"AI 探索生成失败: {str(e)}")

    @staticmethod
    async def _execute_explore_action(
        page, step_obj: Dict[str, Any], account: str, password: str
    ) -> tuple[bool, str]:
        """在真实页面执行探索步骤的单个 action（点击/输入/等待等）。"""
        t = int(step_obj.get("type") or -1)
        action = step_obj.get("action") or {}
        locator_select = int(action.get("locator_select") or 2)
        element = str(action.get("element") or "")
        value = str(action.get("input") or "")

        # 账号密码自动替换（基于 placeholder/text/name 推断）
        if t in (5, 6):
            name_lower = (element or "").lower()
            is_pwd = ("password" in name_lower) or ("密码" in (element or ""))
            is_user = ("email" in name_lower) or ("账号" in (element or "")) or ("用户名" in (element or "")) or ("user" in name_lower) or ("邮箱" in (element or ""))
            if is_pwd and password:
                value = password
            elif is_user and account:
                value = account

        try:
            locator = WebManagementService._build_explore_locator(page, action)
            if locator is None:
                return False, f"无法构建定位器（element={element}, locator_select={locator_select}）"

            before_url = page.url

            if t == 1 or t == 2 or t == 16:
                # 对可能是下拉菜单触发器的元素，先 hover/click 使其展开，再截图给 LLM 下一步识别子项
                if t == 1:
                    try:
                        await locator.first.hover(timeout=5000)
                        await page.wait_for_timeout(600)
                        await locator.first.click(timeout=8000)
                    except Exception:
                        await locator.first.click(timeout=8000)
                elif t == 2:
                    await locator.first.dblclick(timeout=8000)
                else:
                    await locator.first.click(button="right", timeout=8000)

                # 点击后等待页面稳定，并检测是否真正产生变化
                await page.wait_for_timeout(1200)
                try:
                    await page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                after_url = page.url
                if before_url == after_url:
                    return True, "点击成功（URL 未变化，可能是展开菜单）"
                return True, f"点击成功，页面已跳转: {after_url}"
            elif t in (5, 6):
                await locator.first.click(timeout=5000)
                await locator.first.fill(value, timeout=8000)
                return True, f"输入成功: {value[:3]}***" if len(value) > 3 else "输入成功"
            elif t == 7:
                await locator.first.fill("", timeout=8000)
                return True, "清空成功"
            elif t == 12:
                sec = int(action.get("element") or 1)
                await page.wait_for_timeout(sec * 1000)
                return True, f"等待{sec}秒"
            elif t == 0:
                target = element or value
                if target:
                    await page.goto(target, timeout=30000)
                    return True, f"打开网页: {target}"
                return False, "打开网页缺少 URL"
            elif t == 20:
                await page.reload(timeout=30000)
                return True, "刷新页面"
            elif t == 13:
                return True, "新窗口(探索模式暂不处理)"
            else:
                # 兜底：尝试点击
                await locator.first.click(timeout=8000)
                return True, "兜底点击"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _page_has_unfilled_login_fields(elements: List[Dict[str, Any]]) -> bool:
        """启发式判断页面上是否还有未填写的登录相关输入框（邮箱/用户名/密码）。"""
        if not elements:
            return False
        has_user_field = False
        has_pwd_field = False
        for el in elements:
            tag = (el.get("tag") or "").lower()
            if tag != "input":
                continue
            itype = (el.get("type") or "").lower()
            text = " ".join([
                str(el.get("placeholder") or ""),
                str(el.get("text") or ""),
                str(el.get("ariaLabel") or ""),
                str(el.get("name") or ""),
            ]).lower()
            value = str(el.get("value") or "").strip()
            if itype == "password" or "密码" in text or "password" in text:
                if not value:
                    has_pwd_field = True
            elif (
                itype in ("email", "text", "tel") or
                "邮箱" in text or "email" in text or
                "账号" in text or "用户名" in text or "user" in text
            ):
                if not value:
                    has_user_field = True
        return has_user_field or has_pwd_field

    @staticmethod
    def _build_explore_locator(page, action: Dict[str, Any]):
        """根据 action 构建 Playwright locator。"""
        locator_select = int(action.get("locator_select") or 2)
        element = str(action.get("element") or "")
        if not element:
            return None
        try:
            if locator_select == 1:
                if action.get("id"):
                    return page.locator(f"#{action['id']}")
                return page.locator(f"[id='{element}']")
            elif locator_select == 2:
                return page.get_by_text(element, exact=False)
            elif locator_select == 3:
                return page.get_by_label(element)
            elif locator_select == 4:
                return page.get_by_title(element)
            elif locator_select == 5:
                return page.get_by_placeholder(element)
            elif locator_select == 6:
                return page.get_by_alt_text(element)
            elif locator_select == 7:
                return page.get_by_role(element)
            else:
                return page.locator(element)
        except Exception:
            try:
                return page.locator(element)
            except Exception:
                return None
