#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""AI 测试任务中心 Controller"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.infra.db.sqlalchemy import get_db
from app.common.response import success_response
from app.core.dependencies import get_current_user_id
from .schema import AgentTaskCreateSchema, AgentTaskUpdateSchema
from .service import AgentTaskService

router = APIRouter()


@router.get("/tasks", summary="任务列表（分页）")
async def list_tasks(
        keyword: Optional[str] = Query(None, description='任务名称模糊搜索'),
        status_filter: Optional[str] = Query(None, alias='status', description='状态筛选'),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=200),
        db: AsyncSession = Depends(get_db),
        user_id: int = Depends(get_current_user_id)):
    data = await AgentTaskService.get_list(db, keyword, status_filter, page, page_size)
    return success_response(data=data, message="查询成功")


@router.post("/tasks", summary="创建 AI 测试任务")
async def create_task(data: AgentTaskCreateSchema,
                      db: AsyncSession = Depends(get_db),
                      user_id: int = Depends(get_current_user_id)):
    result = await AgentTaskService.create(db, data, user_id)
    return success_response(data=result, message="任务创建成功")


@router.get("/tasks/{task_id}", summary="任务详情（含产物）")
async def get_task(task_id: int, db: AsyncSession = Depends(get_db),
                   user_id: int = Depends(get_current_user_id)):
    return success_response(data=await AgentTaskService.get_detail(db, task_id), message="查询成功")


@router.put("/tasks/{task_id}", summary="更新任务")
async def update_task(task_id: int, data: AgentTaskUpdateSchema,
                      db: AsyncSession = Depends(get_db),
                      user_id: int = Depends(get_current_user_id)):
    return success_response(data=await AgentTaskService.update(db, task_id, data, user_id), message="更新成功")


@router.post("/tasks/{task_id}/confirm", summary="确认执行（HITL 通过）")
async def confirm_task(task_id: int, db: AsyncSession = Depends(get_db),
                       user_id: int = Depends(get_current_user_id)):
    return success_response(data=await AgentTaskService.confirm_execution(db, task_id), message="已确认，开始执行")


@router.post("/tasks/{task_id}/reject", summary="驳回用例（HITL 拒绝）")
async def reject_task(task_id: int, db: AsyncSession = Depends(get_db),
                      user_id: int = Depends(get_current_user_id)):
    return success_response(data=await AgentTaskService.reject_cases(db, task_id), message="已驳回，重新生成用例")


@router.post("/tasks/{task_id}/rerun", summary="重跑任务")
async def rerun_task(task_id: int, db: AsyncSession = Depends(get_db),
                     user_id: int = Depends(get_current_user_id)):
    return success_response(data=await AgentTaskService.rerun(db, task_id), message="任务已重新启动")


@router.delete("/tasks/{task_id}", summary="删除任务")
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db),
                      user_id: int = Depends(get_current_user_id)):
    await AgentTaskService.delete(db, task_id)
    return success_response(message="删除成功")
