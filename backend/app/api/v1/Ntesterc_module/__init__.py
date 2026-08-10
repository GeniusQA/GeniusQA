#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: Rebort
"""
业务模块统一入口（目录名 Ntesterc_module 不出现在 URL）。
命名原则：短词用全称；过长模块名保留简写，避免路径难读又过长。
"""

from fastapi import APIRouter

# AI 须先于 project 加载，避免循环导入
from app.api.v1.Ntesterc_module.Ntesterc_ai import router as ai_router
from app.api.v1.Ntesterc_module.Ntesterc_oauth.controller import router as oauth_router
from app.api.v1.Ntesterc_module.Ntesterc_project import router as projects_router
from app.api.v1.Ntesterc_module.Ntesterc_intel.controller import router as intel_router
from app.api.v1.Ntesterc_module.Ntesterc_skills import router as skill_router
from app.api.v1.Ntesterc_module.Ntesterc_testcases.controller import router as case_router
from app.api.v1.Ntesterc_module.Ntesterc_ui.controller import router as ui_router
from app.api.v1.Ntesterc_module.Ntesterc_data_factory.controller import router as data_router
from app.api.v1.Ntesterc_module.Ntesterc_reviews.controller import router as review_router
from app.api.v1.Ntesterc_module.Ntesterc_assistant.controller import router as asst_router
from app.api.v1.Ntesterc_module.Ntesterc_notifications.controller import router as notify_router
from app.api.v1.Ntesterc_module.Ntesterc_dashboard.controller import router as dash_router
from app.api.v1.Ntesterc_module.Ntesterc_api.controller import router as api_router
from app.api.v1.Ntesterc_module.Ntesterc_web.controller import router as web_router
from app.api.v1.Ntesterc_module.Ntesterc_app.controller import router as app_router
from app.api.v1.Ntesterc_module.Ntesterc_task_scheduler.controller import router as task_router
from app.api.v1.Ntesterc_module.Ntesterc_precision_test.controller import router as cov_router
from app.api.v1.Ntesterc_module.Ntesterc_desk.controller import router as desk_router
from app.api.v1.Ntesterc_module.Ntesterc_mini.controller import router as mini_router
from app.api.v1.Ntesterc_module.Ntesterc_performance import router as perf_router
from app.api.v1.Ntesterc_module.Ntesterc_cloud_device.controller import router as cloud_router
from app.api.v1.Ntesterc_module.Ntesterc_mitmproxy.controller import router as mitm_router
from app.api.v1.Ntesterc_module.Ntesterc_demo.controller import router as demo_router
from app.api.v1.Ntesterc_module.Ntesterc_agent import router as agent_router

router = APIRouter()

router.include_router(oauth_router, prefix="/Ntesterc_oauth", tags=["OAuth 第三方登录"])
router.include_router(projects_router, prefix="/Ntesterc_project", tags=["项目管理"])

router.include_router(ai_router, prefix="/Ntesterc_ai", tags=["AI管理"])
router.include_router(intel_router, prefix="/Ntesterc_intel", tags=["AI智能化"])
router.include_router(skill_router, prefix="/Ntesterc_skills", tags=["Skill管理"])
router.include_router(asst_router, prefix="/Ntesterc_assistant", tags=["AI助手"])

router.include_router(case_router, prefix="/Ntesterc_testcases", tags=["测试用例管理"])
router.include_router(api_router, prefix="/Ntesterc_api", tags=["接口自动化"])
router.include_router(ui_router, prefix="/Ntesterc_ui", tags=["UI自动化"])
router.include_router(web_router, prefix="/Ntesterc_web", tags=["Web管理模块"])
router.include_router(app_router, prefix="/Ntesterc_app", tags=["APP管理"])
router.include_router(desk_router, prefix="/Ntesterc_desk", tags=["客户端UI自动化"])
router.include_router(mini_router, prefix="/Ntesterc_mini", tags=["小程序自动化"])
router.include_router(cloud_router, prefix="/Ntesterc_cloud_device", tags=["云真机"])
router.include_router(mitm_router, prefix="/Ntesterc_mitmproxy", tags=["APP抓包"])
router.include_router(cov_router, prefix="/Ntesterc_precision_test", tags=["精准测试"])
router.include_router(perf_router, prefix="/Ntesterc_performance", tags=["性能测试"])
router.include_router(data_router, prefix="/Ntesterc_data_factory", tags=["数据工厂"])
router.include_router(task_router, prefix="/Ntesterc_task_scheduler", tags=["定时任务调度"])

router.include_router(review_router, prefix="/Ntesterc_reviews", tags=["用例评审"])
router.include_router(notify_router, prefix="/Ntesterc_notifications", tags=["统一通知系统"])
router.include_router(dash_router, prefix="/Ntesterc_dashboard", tags=["首页看板"])
router.include_router(demo_router, prefix="/Ntesterc_demo", tags=["示例业务"])
router.include_router(agent_router, prefix="/Ntesterc_agent", tags=["AI测试任务中心"])

__all__ = ["router"]