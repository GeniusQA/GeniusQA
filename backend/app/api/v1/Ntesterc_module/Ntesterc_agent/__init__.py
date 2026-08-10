#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""
AI 测试任务中心：多 Agent 流水线任务模块（需求分析 → 用例生成 → 执行 → 评审）
"""

from fastapi import APIRouter
from app.api.v1.Ntesterc_module.Ntesterc_agent.controller import router as agent_router

router = APIRouter()
router.include_router(agent_router)

__all__ = ["router"]
