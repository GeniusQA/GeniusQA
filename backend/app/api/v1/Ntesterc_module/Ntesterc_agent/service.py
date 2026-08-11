#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""AI 测试任务中心 Service：任务状态机 + 流水线模拟执行 + 产物管理"""

import asyncio
from datetime import datetime
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.common.response import success_response
from .crud import AgentTaskCRUD, AgentArtifactCRUD
from .model import AgentTaskModel, AgentArtifactModel
from .schema import AgentTaskCreateSchema, AgentTaskUpdateSchema

# 流水线节点定义（api 类型）
PIPELINE_NODES = [
    {"key": "analyzing", "agent": "需求分析 Agent", "progress": 20},
    {"key": "case_generating", "agent": "用例生成 Agent", "progress": 45},
    {"key": "awaiting_review", "agent": "人工审核点(HITL)", "progress": 55},
    {"key": "executing", "agent": "执行 Agent", "progress": 85},
    {"key": "reviewing", "agent": "评审 Agent", "progress": 95},
]
NODE_ORDER = {n["key"]: i for i, n in enumerate(PIPELINE_NODES)}


def _demo_points() -> list:
    return [
        {"id": 1, "api": "POST /api/auth/login", "point": "正确账号密码登录成功，返回 token", "type": "正常", "priority": "P0"},
        {"id": 2, "api": "POST /api/auth/login", "point": "密码错误返回 401 与错误码", "type": "异常", "priority": "P0"},
        {"id": 3, "api": "POST /api/auth/login", "point": "用户名 2-20 位边界（1/20/21 位）", "type": "边界", "priority": "P1"},
        {"id": 4, "api": "GET /api/user/info", "point": "无 token 访问返回 401", "type": "鉴权", "priority": "P0"},
        {"id": 5, "api": "POST /api/auth/login", "point": "连续 5 次失败触发锁定策略", "type": "边界", "priority": "P1"},
    ]


def _demo_cases() -> list:
    return [
        {"id": 1, "name": "登录-正常路径", "method": "POST", "path": "/api/auth/login", "asserts": "code == 200 且 token 非空", "enabled": True},
        {"id": 2, "name": "登录-密码错误", "method": "POST", "path": "/api/auth/login", "asserts": "status == 401", "enabled": True},
        {"id": 3, "name": "登录-用户名边界 1 位", "method": "POST", "path": "/api/auth/login", "asserts": "status == 400", "enabled": True},
        {"id": 4, "name": "登录-锁定策略", "method": "POST", "path": "/api/auth/login", "asserts": "第 5 次返回 429", "enabled": True},
    ]


def _demo_results() -> dict:
    return {
        "total": 25, "passed": 22, "failed": 3,
        "failures": [
            {"case": "退款金额边界 0.01 元", "path": "POST /api/refund", "type": "断言失败", "reason": "响应码 200 但退款状态 FAILED"},
            {"case": "订单列表时间范围", "path": "POST /api/order/query", "type": "断言失败", "reason": "total 与 DB 统计不一致"},
            {"case": "订单详情非法单号", "path": "GET /api/order/{id}", "type": "环境问题", "reason": "预发库缺种子数据"},
        ]
    }


def _demo_report() -> dict:
    return {
        "pass_rate": 88.0, "suggestions": [
            "退款金额边界疑似服务端未处理最小金额，建议转研发确认",
            "时间范围参数断言口径需与开发对齐（排序分页影响 total）",
            "环境数据问题已给出补数脚本建议",
        ]
    }


class AgentTaskService:

    # ---------- 查询 ----------
    @staticmethod
    async def get_list(db, keyword: Optional[str], status_filter: Optional[str], page: int, page_size: int) -> dict:
        crud = AgentTaskCRUD(db)
        items, total = await crud.get_list(keyword=keyword, status=status_filter,
                                           skip=(page - 1) * page_size, limit=page_size)
        return {
            "items": [await AgentTaskService._to_out(db, t, with_artifacts=False) for t in items],
            "total": total, "page": page, "page_size": page_size,
        }

    @staticmethod
    async def get_detail(db, task_id: int) -> dict:
        task = await AgentTaskCRUD(db).get_by_id_crud(task_id)
        if not task or not task.enabled_flag:
            raise HTTPException(status_code=404, detail="任务不存在")
        return await AgentTaskService._to_out(db, task, with_artifacts=True)

    @staticmethod
    async def _to_out(db, task: AgentTaskModel, with_artifacts: bool) -> dict:
        data = {
            "id": task.id, "name": task.name, "pipeline_type": task.pipeline_type,
            "status": task.status, "project_id": task.project_id, "env_name": task.env_name,
            "input_file": task.input_file, "exec_mode": task.exec_mode, "model_tier": task.model_tier,
            "progress": task.progress, "current_node": task.current_node, "error_msg": task.error_msg,
            "token_used": task.token_used, "cost": float(task.cost or 0),
            "trace": task.trace or [], "created_by": task.created_by,
            "creation_date": task.creation_date, "updation_date": task.updation_date,
            "artifacts": [],
        }
        if with_artifacts:
            arts = await AgentArtifactCRUD(db).get_by_task(task.id)
            data["artifacts"] = [
                {"id": a.id, "task_id": a.task_id, "kind": a.kind, "content": a.content,
                 "version": a.version, "status": a.status, "summary": a.summary,
                 "creation_date": a.creation_date}
                for a in arts
            ]
        return data

    # ---------- 创建与状态机 ----------
    @staticmethod
    async def create(db, data: AgentTaskCreateSchema, user_id: int) -> dict:
        crud = AgentTaskCRUD(db)
        task = await crud.create_crud({
            **data.model_dump(), "created_by": user_id, "status": "pending",
            "progress": 0, "trace": [], "artifacts": [],
        })
        # 启动后台模拟流水线（MVP：不接真实 LLM，按延时推进状态机）
        asyncio.create_task(AgentTaskService._run_pipeline(task.id, data.exec_mode))
        return await AgentTaskService.get_detail(db, task.id)

    @staticmethod
    async def _run_pipeline(task_id: int, exec_mode: str):
        """模拟流水线：pending → analyzing → case_generating → awaiting_review → executing → reviewing → done"""
        from app.infra.db.sqlalchemy import content_transaction
        try:
            async with content_transaction() as db:
                crud = AgentTaskCRUD(db)
                art_crud = AgentArtifactCRUD(db)
                task = await crud.get_by_id_crud(task_id)
                if not task:
                    return
                trace = task.trace or []
                node_idx = 0

                # 节点 1：需求分析
                await AgentTaskService._advance(db, task_id, "analyzing", 15, trace,
                                                "解析需求文档，提取接口清单", "doc_parse", "2026-08-10 17:42:11")
                await asyncio.sleep(1.2)
                await AgentTaskService._advance(db, task_id, "analyzing", 25, trace,
                                                f"生成测试点 {len(_demo_points())} 条，结构校验通过", "llm", "2026-08-10 17:42:52")
                await asyncio.sleep(0.8)
                points_art = await art_crud.create_crud({
                    "task_id": task_id, "kind": "test_points", "content": _demo_points(),
                    "version": 1, "status": "confirmed", "summary": f"测试点 {len(_demo_points())} 条（正常 2/边界 1/异常 1/鉴权 1）",
                })
                await AgentTaskService._advance(db, task_id, "case_generating", 45, trace,
                                                f"产出测试点 v1（#{points_art.id}），流转至用例生成 Agent", "artifact", "2026-08-10 17:43:04")

                # 节点 2：用例生成
                await asyncio.sleep(1.4)
                cases_art = await art_crud.create_crud({
                    "task_id": task_id, "kind": "cases", "content": _demo_cases(),
                    "version": 1, "status": "draft", "summary": f"用例 {len(_demo_cases())} 条",
                })
                await AgentTaskService._advance(db, task_id, "awaiting_review", 55, trace,
                                                f"产出用例集 v1（#{cases_art.id}），等待人工确认", "artifact", "2026-08-10 17:45:29")

                if exec_mode == "auto":
                    await AgentTaskService._run_execution(db, task_id, trace)
            # 手动模式：任务停在 awaiting_review，等 confirm 接口
        except Exception as e:
            try:
                from app.infra.db.sqlalchemy import content_transaction
                async with content_transaction() as db:
                    task = await AgentTaskCRUD(db).get_by_id_crud(task_id)
                    if task:
                        task.status = "failed"
                        task.error_msg = f"流水线异常: {e}"
            except Exception:
                pass

    @staticmethod
    async def _run_execution(db, task_id: int, trace: list):
        art_crud = AgentArtifactCRUD(db)
        await AgentTaskService._advance(db, task_id, "executing", 75, trace,
                                        f"调用接口执行引擎运行 {len(_demo_cases())} 条用例", "api_execute", "2026-08-10 17:46:10")
        await asyncio.sleep(1.6)
        await art_crud.create_crud({
            "task_id": task_id, "kind": "results", "content": _demo_results(),
            "version": 1, "status": "confirmed", "summary": f"执行完成：通过 {_demo_results()['passed']}/{_demo_results()['total']}，失败 {_demo_results()['failed']}",
        })
        await AgentTaskService._advance(db, task_id, "reviewing", 95, trace,
                                        "失败归类与根因分析，输出质量报告 v1", "llm", "2026-08-10 17:52:45")
        await asyncio.sleep(1.0)
        await art_crud.create_crud({
            "task_id": task_id, "kind": "report", "content": _demo_report(),
            "version": 1, "status": "confirmed", "summary": f"通过率 {_demo_report()['pass_rate']}%，失败归类完成",
        })
        await AgentTaskService._advance(db, task_id, "done", 100, trace,
                                        "流水线执行完成，评审报告已生成", "done", "2026-08-10 17:53:10")

    @staticmethod
    async def _advance(db, task_id: int, node: str, progress: int, trace: list,
                       content: str, tool: str, ts: str):
        task = await AgentTaskCRUD(db).get_by_id_crud(task_id)
        if not task:
            return
        trace.append({"tool": tool, "content": content, "timestamp": ts, "node": node})
        task.status = node
        task.current_node = node
        task.progress = progress
        task.trace = trace
        task.token_used = (task.token_used or 0) + 2100
        task.cost = round(float(task.cost or 0) + 0.15, 2)

    # ---------- HITL 操作 ----------
    @staticmethod
    async def confirm_execution(db, task_id: int) -> dict:
        task = await AgentTaskCRUD(db).get_by_id_crud(task_id)
        if not task or not task.enabled_flag:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status != "awaiting_review":
            raise HTTPException(status_code=400, detail=f"当前状态 {task.status} 不允许确认执行")
        # 用例产物置 confirmed
        art_crud = AgentArtifactCRUD(db)
        cases = await art_crud.get_latest_by_kind(task_id, "cases")
        if cases:
            cases.status = "confirmed"
        # 同步推进到 executing，后台继续执行+评审+done
        trace = task.trace or []
        trace.append({"tool": "hitl", "content": "测试人员确认用例集，进入执行阶段", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "node": "executing"})
        task.status = "executing"
        task.current_node = "executing"
        task.progress = 75
        task.trace = trace
        await db.flush()
        asyncio.create_task(AgentTaskService._run_execution_async(task_id))
        return await AgentTaskService._to_out(db, task, with_artifacts=True)

    @staticmethod
    async def _run_execution_async(task_id: int):
        from app.infra.db.sqlalchemy import content_transaction
        try:
            async with content_transaction() as db:
                task = await AgentTaskCRUD(db).get_by_id_crud(task_id)
                if not task:
                    return
                trace = task.trace or []
                await AgentTaskService._run_execution(db, task_id, trace)
        except Exception:
            pass

    @staticmethod
    async def reject_cases(db, task_id: int) -> dict:
        task = await AgentTaskCRUD(db).get_by_id_crud(task_id)
        if not task or not task.enabled_flag:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status != "awaiting_review":
            raise HTTPException(status_code=400, detail=f"当前状态 {task.status} 不允许驳回")
        art_crud = AgentArtifactCRUD(db)
        cases = await art_crud.get_latest_by_kind(task_id, "cases")
        if cases:
            cases.status = "rejected"
        trace = task.trace or []
        trace.append({"tool": "hitl", "content": "测试人员驳回用例集，用例生成 Agent 重新生成", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "node": "case_generating"})
        task.trace = trace
        task.status = "case_generating"
        task.current_node = "case_generating"
        task.progress = 45
        asyncio.create_task(AgentTaskService._regen_cases_async(task_id))
        return await AgentTaskService._to_out(db, task, with_artifacts=True)

    @staticmethod
    async def _regen_cases_async(task_id: int):
        from app.infra.db.sqlalchemy import content_transaction
        try:
            async with content_transaction() as db:
                art_crud = AgentArtifactCRUD(db)
                await asyncio.sleep(1.5)
                new_art = await art_crud.create_crud({
                    "task_id": task_id, "kind": "cases", "content": _demo_cases(),
                    "version": 2, "status": "draft", "summary": f"用例集 v2（{len(_demo_cases())} 条，重新生成）",
                })
                await AgentTaskService._advance(db, task_id, "awaiting_review", 55,
                                                (await AgentTaskCRUD(db).get_by_id_crud(task_id)).trace or [],
                                                f"重新生成用例集 v2（#{new_art.id}），等待人工确认", "artifact",
                                                datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass

    @staticmethod
    async def rerun(db, task_id: int) -> dict:
        task = await AgentTaskCRUD(db).get_by_id_crud(task_id)
        if not task or not task.enabled_flag:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status in ("pending", "analyzing", "case_generating", "executing", "reviewing"):
            raise HTTPException(status_code=400, detail=f"当前状态 {task.status} 不允许重跑")
        task.status = "pending"
        task.progress = 0
        task.error_msg = None
        task.trace = task.trace or []
        task.trace.append({"tool": "rerun", "content": "用户触发重跑", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "node": "pending"})
        asyncio.create_task(AgentTaskService._run_pipeline(task.id, task.exec_mode or "manual"))
        return await AgentTaskService._to_out(db, task, with_artifacts=True)

    @staticmethod
    async def update(db, task_id: int, data: AgentTaskUpdateSchema, user_id: int) -> dict:
        task = await AgentTaskCRUD(db).get_by_id_crud(task_id)
        if not task or not task.enabled_flag:
            raise HTTPException(status_code=404, detail="任务不存在")
        task = await AgentTaskCRUD(db).update_crud(task_id, {**data.model_dump(exclude_unset=True), "updated_by": user_id})
        return await AgentTaskService._to_out(db, task, with_artifacts=False)

    @staticmethod
    async def delete(db, task_id: int) -> None:
        task = await AgentTaskCRUD(db).get_by_id_crud(task_id)
        if not task or not task.enabled_flag:
            raise HTTPException(status_code=404, detail="任务不存在")
        await AgentTaskCRUD(db).soft_delete_crud([task_id])
