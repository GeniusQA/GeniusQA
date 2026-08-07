#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: Rebort
import os
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.infra.db.sqlalchemy import get_db
from app.common.response import success_response
from app.core.dependencies import get_current_user_id
from .recorder import RECORDER_MANAGER, import_codegen, import_side
from .schema import (
    UIProjectCreateSchema,
    UIProjectUpdateSchema,
    UIElementGroupCreateSchema,
    UIElementGroupUpdateSchema,
    UIElementCreateSchema,
    UIElementUpdateSchema,
    UIPageObjectCreateSchema,
    UIPageObjectUpdateSchema,
    UITestCaseCreateSchema,
    UITestCaseUpdateSchema,
    UITestSuiteCreateSchema,
    UITestSuiteUpdateSchema,
    UITestStepCreateSchema,
    UITestStepUpdateSchema,
    TestStepReorderSchema,
    ExecutionRequestSchema,
    CodeGenerationSchema,
    BrowserCustomPathSchema,
    BrowserCustomPathOutSchema,
    BrowserVerifyPathSchema
)
from .service import (
    UIProjectService,
    UIElementGroupService,
    UIElementService,
    UIPageObjectService,
    UITestCaseService,
    UITestSuiteService,
    UITestStepService,
    UIExecutionService,
    UICodeGenerationService,
    UIReportService,
    UIElementValidationService
)
from .browser_path_config import (
    get_browser_path,
    get_all_browser_paths,
    set_browser_path,
    remove_browser_path,
    path_exists
)
router = APIRouter()


# ==================== UI项目管理 ====================
@router.post("/projects", summary="创建UI项目")
async def create_ui_project(
    data: UIProjectCreateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """创建UI项目"""
    result = await UIProjectService.create_ui_project(db, data, user_id)
    return success_response(data=result, message="创建成功")


@router.get("/projects", summary="获取UI项目列表")
async def get_ui_project_list(
    project_id: Optional[int] = Query(None, description="项目ID"),
    name: Optional[str] = Query(None, description="项目名称"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=1000, description="每页数量"),
    db: AsyncSession = Depends(get_db)
):
    """获取UI项目列表"""
    result = await UIProjectService.get_ui_project_list(db, project_id, name, page, page_size)
    return success_response(data=result)


@router.get("/projects/{ui_project_id}", summary="获取UI项目详情")
async def get_ui_project(
    ui_project_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取UI项目详情"""
    result = await UIProjectService.get_ui_project(db, ui_project_id)
    return success_response(data=result)


@router.put("/projects/{ui_project_id}", summary="更新UI项目")
async def update_ui_project(
    ui_project_id: int,
    data: UIProjectUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """更新UI项目"""
    result = await UIProjectService.update_ui_project(db, ui_project_id, data, user_id)
    return success_response(data=result, message="更新成功")


@router.delete("/projects/{ui_project_id}", summary="删除UI项目")
async def delete_ui_project(
    ui_project_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """删除UI项目"""
    await UIProjectService.delete_ui_project(db, ui_project_id, user_id)
    return success_response(message="删除成功")


# ==================== UI元素分组管理 ====================
@router.post("/element-groups", summary="创建元素分组")
async def create_element_group(
    data: UIElementGroupCreateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """创建元素分组"""
    result = await UIElementGroupService.create_element_group(db, data, user_id)
    return success_response(data=result, message="创建成功")


@router.get("/element-groups/tree", summary="获取元素分组树")
async def get_element_group_tree(
    ui_project_id: int = Query(..., description="UI项目ID"),
    db: AsyncSession = Depends(get_db)
):
    """获取元素分组树"""
    result = await UIElementGroupService.get_element_group_tree(db, ui_project_id)
    return success_response(data=result)


@router.put("/element-groups/{group_id}", summary="更新元素分组")
async def update_element_group(
    group_id: int,
    data: UIElementGroupUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """更新元素分组"""
    result = await UIElementGroupService.update_element_group(db, group_id, data, user_id)
    return success_response(data=result, message="更新成功")


@router.delete("/element-groups/{group_id}", summary="删除元素分组")
async def delete_element_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """删除元素分组"""
    await UIElementGroupService.delete_element_group(db, group_id, user_id)
    return success_response(message="删除成功")


# ==================== UI元素管理 ====================
@router.post("/elements", summary="创建UI元素")
async def create_element(
    data: UIElementCreateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """创建UI元素"""
    result = await UIElementService.create_element(db, data, user_id)
    return success_response(data=result, message="创建成功")


@router.get("/elements", summary="获取UI元素列表")
async def get_element_list(
    group_id: int = Query(..., description="分组ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=1000, description="每页数量"),
    db: AsyncSession = Depends(get_db)
):
    """获取UI元素列表"""
    result = await UIElementService.get_element_list(db, group_id, page, page_size)
    return success_response(data=result)


@router.get("/elements/{element_id}", summary="获取UI元素详情")
async def get_element(
    element_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取UI元素详情"""
    result = await UIElementService.get_element(db, element_id)
    return success_response(data=result)


@router.put("/elements/{element_id}", summary="更新UI元素")
async def update_element(
    element_id: int,
    data: UIElementUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """更新UI元素"""
    result = await UIElementService.update_element(db, element_id, data, user_id)
    return success_response(data=result, message="更新成功")


@router.delete("/elements/{element_id}", summary="删除UI元素")
async def delete_element(
    element_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """删除UI元素"""
    await UIElementService.delete_element(db, element_id, user_id)
    return success_response(message="删除成功")


# ==================== UI页面对象管理 ====================
@router.post("/page-objects", summary="创建页面对象")
async def create_page_object(
    data: UIPageObjectCreateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """创建页面对象"""
    result = await UIPageObjectService.create_page_object(db, data, user_id)
    return success_response(data=result, message="创建成功")


@router.get("/page-objects", summary="获取页面对象列表")
async def get_page_object_list(
    ui_project_id: int = Query(..., description="UI项目ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=1000, description="每页数量"),
    db: AsyncSession = Depends(get_db)
):
    """获取页面对象列表"""
    result = await UIPageObjectService.get_page_object_list(db, ui_project_id, page, page_size)
    return success_response(data=result)


@router.get("/page-objects/{page_object_id}", summary="获取页面对象详情")
async def get_page_object(
    page_object_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取页面对象详情"""
    result = await UIPageObjectService.get_page_object(db, page_object_id)
    return success_response(data=result)


@router.put("/page-objects/{page_object_id}", summary="更新页面对象")
async def update_page_object(
    page_object_id: int,
    data: UIPageObjectUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """更新页面对象"""
    result = await UIPageObjectService.update_page_object(db, page_object_id, data, user_id)
    return success_response(data=result, message="更新成功")


@router.delete("/page-objects/{page_object_id}", summary="删除页面对象")
async def delete_page_object(
    page_object_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """删除页面对象"""
    await UIPageObjectService.delete_page_object(db, page_object_id, user_id)
    return success_response(message="删除成功")


# ==================== UI测试用例管理 ====================
@router.post("/test-cases", summary="创建测试用例")
async def create_test_case(
    data: UITestCaseCreateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """创建测试用例"""
    result = await UITestCaseService.create_test_case(db, data, user_id)
    return success_response(data=result, message="创建成功")


@router.get("/test-cases", summary="获取测试用例列表")
async def get_test_case_list(
    ui_project_id: int = Query(..., description="UI项目ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=1000, description="每页数量"),
    name: Optional[str] = Query(None, description="用例名称搜索"),
    priority: Optional[str] = Query(None, description="优先级筛选"),
    db: AsyncSession = Depends(get_db)
):
    """获取测试用例列表"""
    result = await UITestCaseService.get_test_case_list(
        db, ui_project_id, page, page_size, name, priority
    )
    return success_response(data=result)


@router.get("/test-cases/{test_case_id}", summary="获取测试用例详情")
async def get_test_case(
    test_case_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取测试用例详情"""
    result = await UITestCaseService.get_test_case(db, test_case_id)
    return success_response(data=result)


@router.put("/test-cases/{test_case_id}", summary="更新测试用例")
async def update_test_case(
    test_case_id: int,
    data: UITestCaseUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """更新测试用例"""
    result = await UITestCaseService.update_test_case(db, test_case_id, data, user_id)
    return success_response(data=result, message="更新成功")


@router.delete("/test-cases/{test_case_id}", summary="删除测试用例")
async def delete_test_case(
    test_case_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """删除测试用例"""
    await UITestCaseService.delete_test_case(db, test_case_id, user_id)
    return success_response(message="删除成功")


# ==================== UI测试套件管理 ====================
@router.post("/test-suites", summary="创建测试套件")
async def create_test_suite(
    data: UITestSuiteCreateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """创建测试套件"""
    result = await UITestSuiteService.create_test_suite(db, data, user_id)
    return success_response(data=result, message="创建成功")


@router.get("/test-suites", summary="获取测试套件列表")
async def get_test_suite_list(
    ui_project_id: int = Query(..., description="UI项目ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=1000, description="每页数量"),
    db: AsyncSession = Depends(get_db)
):
    """获取测试套件列表"""
    result = await UITestSuiteService.get_test_suite_list(db, ui_project_id, page, page_size)
    return success_response(data=result)


@router.get("/test-suites/{test_suite_id}", summary="获取测试套件详情")
async def get_test_suite(
    test_suite_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取测试套件详情"""
    result = await UITestSuiteService.get_test_suite(db, test_suite_id)
    return success_response(data=result)


@router.put("/test-suites/{test_suite_id}", summary="更新测试套件")
async def update_test_suite(
    test_suite_id: int,
    data: UITestSuiteUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """更新测试套件"""
    result = await UITestSuiteService.update_test_suite(db, test_suite_id, data, user_id)
    return success_response(data=result, message="更新成功")


@router.delete("/test-suites/{test_suite_id}", summary="删除测试套件")
async def delete_test_suite(
    test_suite_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """删除测试套件"""
    await UITestSuiteService.delete_test_suite(db, test_suite_id, user_id)
    return success_response(message="删除成功")



# ==================== UI测试步骤管理 ====================
@router.get("/test-cases/{test_case_id}/steps", summary="获取测试用例的步骤列表")
async def get_test_case_steps(
    test_case_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取测试用例的所有步骤"""
    result = await UITestStepService.get_test_steps_by_case(db, test_case_id)
    return success_response(data=result)


@router.post("/test-steps", summary="创建测试步骤")
async def create_test_step(
    data: UITestStepCreateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """创建测试步骤"""
    result = await UITestStepService.create_test_step(db, data, user_id)
    return success_response(data=result, message="创建成功")


@router.post("/test-steps/batch", summary="批量创建测试步骤")
async def batch_create_test_steps(
    steps_data: List[UITestStepCreateSchema],
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """批量创建测试步骤"""
    result = await UITestStepService.batch_create_test_steps(db, steps_data, user_id)
    return success_response(data=result, message=f"成功创建{len(result)}个步骤")


@router.put("/test-steps/reorder", summary="调整步骤顺序")
async def reorder_test_steps(
    data: TestStepReorderSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """调整测试步骤顺序"""
    await UITestStepService.reorder_test_steps(
        db, 
        data.test_case_id, 
        data.step_orders, 
        user_id
    )
    return success_response(message="步骤顺序调整成功")


@router.put("/test-steps/{step_id}", summary="更新测试步骤")
async def update_test_step(
    step_id: int,
    data: UITestStepUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """更新测试步骤"""
    result = await UITestStepService.update_test_step(db, step_id, data, user_id)
    return success_response(data=result, message="更新成功")


@router.delete("/test-steps/{step_id}", summary="删除测试步骤")
async def delete_test_step(
    step_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """删除测试步骤"""
    await UITestStepService.delete_test_step(db, step_id, user_id)
    return success_response(message="删除成功")



# ==================== UI测试执行 ====================
@router.get("/browsers/check", summary="检查浏览器可用性")
async def check_browser_availability(
    browser_type: str = Query('chrome', description="浏览器类型: chrome, firefox, edge, safari")
):
    """检查指定浏览器是否可用（优先使用已配置的自定义路径）"""
    from .selenium_engine import SeleniumTestEngine

    custom_path = get_browser_path(browser_type)
    is_available, error_msg = SeleniumTestEngine.check_browser_available(browser_type, custom_path)

    return success_response(data={
        'browser_type': browser_type,
        'is_available': is_available,
        'message': error_msg if not is_available else '浏览器可用',
        'custom_path': custom_path,
        'custom_path_exists': path_exists(browser_type),
        'install_tips': {
            'chrome': {
                'macos': 'brew install --cask google-chrome',
                'windows': '访问 https://www.google.com/chrome/ 下载安装',
                'linux': 'sudo apt-get install google-chrome-stable'
            },
            'firefox': {
                'macos': 'brew install --cask firefox',
                'windows': '访问 https://www.mozilla.org/firefox/ 下载安装',
                'linux': 'sudo apt-get install firefox'
            },
            'edge': {
                'macos': 'brew install --cask microsoft-edge',
                'windows': 'Windows 10+ 自带 Edge 浏览器',
                'linux': '访问 https://www.microsoft.com/edge 下载安装'
            },
            'safari': {
                'macos': 'macOS 自带 Safari，需执行: sudo safaridriver --enable',
                'windows': 'Safari 不支持 Windows',
                'linux': 'Safari 不支持 Linux'
            }
        }.get(browser_type, {})
    })


@router.get("/browsers/check-all", summary="检查所有浏览器可用性")
async def check_all_browsers():
    """检查所有支持的浏览器可用性（优先使用已配置的自定义路径）"""
    from .selenium_engine import SeleniumTestEngine

    browsers = ['chrome', 'firefox', 'edge', 'safari']
    results = []

    for browser in browsers:
        custom_path = get_browser_path(browser)
        is_available, error_msg = SeleniumTestEngine.check_browser_available(browser, custom_path)
        results.append({
            'browser_type': browser,
            'is_available': is_available,
            'message': error_msg if not is_available else '浏览器可用',
            'custom_path': custom_path,
            'custom_path_exists': bool(custom_path and os.path.exists(custom_path))
        })

    return success_response(data={
        'browsers': results,
        'total': len(results),
        'available_count': sum(1 for r in results if r['is_available'])
    })


@router.get("/browsers/check-playwright", summary="检查 Playwright 录制浏览器可用性")
async def check_playwright_browser(
    browser_type: str = Query('edge', description="录制所选浏览器: edge, chrome, firefox, safari（兼容 chromium/msedge/webkit）"),
    headless: bool = Query(True, description="检测时是否使用无头模式，避免弹窗"),
):
    """检测后端运行身份能否实际启动所选浏览器（用于录制前环境校验）。"""
    from playwright.async_api import async_playwright

    # 与浏览器检查页/执行引擎一致的映射：edge/chrome 走系统浏览器，safari 用 webkit
    browser_map = {
        'edge': ('chromium', 'msedge'),
        'chrome': ('chromium', 'chrome'),
        'firefox': ('firefox', None),
        'safari': ('webkit', None),
        'msedge': ('chromium', 'msedge'),
        'chromium': ('chromium', None),
        'webkit': ('webkit', None),
    }
    launcher_name, channel = browser_map.get(browser_type, ('chromium', None))
    custom_path = get_browser_path(browser_type)

    try:
        pw = await async_playwright().start()
        launcher = getattr(pw, launcher_name)
        launch_kwargs = {'headless': headless}
        if channel:
            launch_kwargs['channel'] = channel
        # 若用户配置了自定义安装路径，优先使用 executable_path 启动
        if custom_path and os.path.exists(custom_path):
            launch_kwargs['executable_path'] = custom_path
            # 使用 executable_path 时 channel 与之冲突，需要移除
            launch_kwargs.pop('channel', None)
        browser = await launcher.launch(**launch_kwargs)
        await browser.close()
        await pw.stop()
        return success_response(data={
            'browser_type': browser_type,
            'is_available': True,
            'channel': channel,
            'custom_path': custom_path,
            'message': '浏览器可用'
        })
    except Exception as e:
        error_msg = str(e)
        if channel and 'Chromium distribution' in error_msg:
            error_msg = f'未找到系统安装的 {channel} 浏览器，请先安装或切换到 Playwright 自带 Chromium'
        elif "Executable doesn't exist" in error_msg:
            error_msg = f'Playwright 未找到 {browser_type} 浏览器可执行文件，请执行: playwright install {browser_type}'
        return success_response(data={
            'browser_type': browser_type,
            'is_available': False,
            'channel': channel,
            'custom_path': custom_path,
            'message': error_msg
        })


@router.get("/browsers/custom-paths", summary="获取浏览器自定义路径列表", response_model=success_response)
async def list_browser_custom_paths():
    """获取所有已保存的浏览器自定义安装路径。"""
    paths = get_all_browser_paths()
    data = [
        {
            'browser_type': bt,
            'executable_path': path,
            'exists': os.path.exists(path)
        }
        for bt, path in paths.items()
    ]
    return success_response(data=data)


@router.post("/browsers/custom-paths", summary="保存浏览器自定义路径")
async def save_browser_custom_path(data: BrowserCustomPathSchema):
    """保存浏览器自定义安装路径。"""
    normalized = set_browser_path(data.browser_type, data.executable_path)
    saved_path = get_browser_path(normalized)
    return success_response(data={
        'browser_type': normalized,
        'executable_path': saved_path,
        'exists': os.path.exists(saved_path) if saved_path else False
    }, message="自定义路径已保存")


@router.delete("/browsers/custom-paths/{browser_type}", summary="删除浏览器自定义路径")
async def delete_browser_custom_path(browser_type: str):
    """删除指定浏览器的自定义安装路径，恢复使用默认路径查找。"""
    remove_browser_path(browser_type)
    return success_response(data={'browser_type': browser_type}, message="自定义路径已删除")


@router.post("/browsers/verify-custom-path", summary="验证浏览器自定义路径")
async def verify_browser_custom_path(data: BrowserVerifyPathSchema):
    """
    验证自定义路径是否真的能启动浏览器。
    对 edge/chrome/chromium 使用 headless 模式打开 about:blank 验证；
    对 firefox 使用 --version 验证；
    对 safari 仅做路径存在性校验（Windows/Linux 不支持 Safari）。
    """
    import asyncio
    import platform

    executable_path = data.executable_path.strip() if data.executable_path else ''
    if not executable_path:
        return success_response(data={'is_available': False, 'message': '可执行文件路径不能为空'})
    if not os.path.exists(executable_path):
        return success_response(data={'is_available': False, 'message': f'路径不存在: {executable_path}'})

    browser_type = data.browser_type.lower().strip()

    # edge/chrome/chromium: 先用 --version 做轻量验证；
    # 若不支持 --version（如 Edge 返回 1002），再尝试 headless + dump-dom + 独立 user-data-dir。
    # 两种验证都失败时，只要文件存在且是有效可执行文件，仍允许保存，
    # 因为 Playwright/Selenium 实际启动方式与独立子进程可能不同。
    if browser_type in ('edge', 'chrome', 'msedge', 'chromium'):
        import tempfile
        import shutil

        # 第一重：--version
        try:
            process = await asyncio.create_subprocess_exec(
                executable_path,
                '--version',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x08000000 if os.name == 'nt' else 0
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
            output = (stdout + stderr).decode('utf-8', errors='ignore').strip()
            if process.returncode == 0 and output:
                return success_response(data={
                    'browser_type': browser_type,
                    'executable_path': executable_path,
                    'is_available': True,
                    'message': f'路径验证通过，{output}'
                })
        except Exception:
            pass

        # 第二重：headless + dump-dom + 独立 user-data-dir
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix=f'{browser_type}-verify-')
            process = await asyncio.create_subprocess_exec(
                executable_path,
                '--headless',
                '--disable-gpu',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                f'--user-data-dir={tmp_dir}',
                '--dump-dom',
                'about:blank',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x08000000 if os.name == 'nt' else 0
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15.0)
                output = (stdout + stderr).decode('utf-8', errors='ignore').strip()
                if process.returncode == 0:
                    return success_response(data={
                        'browser_type': browser_type,
                        'executable_path': executable_path,
                        'is_available': True,
                        'message': '路径验证通过，浏览器可以正常启动'
                    })
            except asyncio.TimeoutError:
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
        finally:
            if tmp_dir:
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass

        # 两重回验证均失败：若文件存在且扩展名符合可执行文件，允许保存并给出提示
        if os.path.isfile(executable_path):
            ext = os.path.splitext(executable_path)[1].lower()
            if ext in ('.exe', ''):
                return success_response(data={
                    'browser_type': browser_type,
                    'executable_path': executable_path,
                    'is_available': True,
                    'message': '路径格式正确，已保存。独立验证未通过，但 Playwright/Selenium 执行时仍会尝试从该路径启动浏览器。'
                })
        return success_response(data={
            'browser_type': browser_type,
            'executable_path': executable_path,
            'is_available': False,
            'message': '路径验证失败: 无法识别为可用的浏览器可执行文件，请检查是否选择了正确的 .exe 文件'
        })

    # firefox 使用 --version
    if browser_type == 'firefox':
        try:
            process = await asyncio.create_subprocess_exec(
                executable_path,
                '--version',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x08000000 if os.name == 'nt' else 0
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15.0)
            output = (stdout + stderr).decode('utf-8', errors='ignore').strip()
            if process.returncode == 0 and output:
                return success_response(data={
                    'browser_type': browser_type,
                    'executable_path': executable_path,
                    'is_available': True,
                    'message': f'路径验证通过，{output}'
                })
            return success_response(data={
                'browser_type': browser_type,
                'executable_path': executable_path,
                'is_available': False,
                'message': f'路径验证失败: 进程退出码 {process.returncode}，输出: {output or "(无输出)"}'
            })
        except Exception as e:
            return success_response(data={
                'browser_type': browser_type,
                'executable_path': executable_path,
                'is_available': False,
                'message': f'路径验证失败: {e}'
            })

    # Safari 仅在 macOS 有效
    if browser_type in ('safari', 'webkit'):
        if platform.system() != 'Darwin':
            return success_response(data={
                'browser_type': browser_type,
                'executable_path': executable_path,
                'is_available': False,
                'message': 'Safari 仅在 macOS 系统上可用，Windows/Linux 请使用 Edge/Chrome/Firefox'
            })
        return success_response(data={
            'browser_type': browser_type,
            'executable_path': executable_path,
            'is_available': True,
            'message': '路径已确认'
        })

    return success_response(data={
        'browser_type': browser_type,
        'executable_path': executable_path,
        'is_available': False,
        'message': f'不支持的浏览器类型: {browser_type}'
    })


@router.post("/test-suites/{test_suite_id}/execute", summary="执行测试套件")
async def execute_test_suite(
    test_suite_id: int,
    config: ExecutionRequestSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """执行测试套件"""
    result = await UIExecutionService.execute_test_suite(
        db, test_suite_id, config.model_dump(), user_id
    )
    return success_response(data=result, message="测试套件开始执行")


@router.post("/test-cases/{test_case_id}/execute", summary="执行测试用例")
async def execute_test_case(
    test_case_id: int,
    config: ExecutionRequestSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """执行测试用例"""
    result = await UIExecutionService.execute_test_case(
        db, test_case_id, config.model_dump(), user_id
    )
    return success_response(data=result, message="测试用例开始执行")


@router.post("/test-cases/batch-execute", summary="批量执行测试用例")
async def batch_execute_test_cases(
    request: dict,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """批量执行测试用例"""
    test_case_ids = request.get('test_case_ids', [])
    ui_project_id = request.get('ui_project_id')
    config = {
        'engine_type': request.get('engine_type', 'playwright'),
        'browser_type': request.get('browser_type', 'edge'),
        'channel': request.get('channel') or None,
        'headless': request.get('headless', True),
        'parallel': request.get('parallel', False),
        'max_workers': request.get('max_workers', 1),
        'timeout': request.get('timeout', 30000)
    }
    
    result = await UIExecutionService.batch_execute_test_cases(
        db, ui_project_id, test_case_ids, config, user_id
    )
    return success_response(data=result, message=f"开始批量执行 {len(test_case_ids)} 个测试用例")


@router.post("/test-suites/batch-execute", summary="批量执行测试套件")
async def batch_execute_test_suites(
    request: dict,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """批量执行测试套件"""
    suite_ids = request.get('suite_ids', [])
    config = {
        'engine_type': request.get('engine_type', 'playwright'),
        'browser_type': request.get('browser_type', 'edge'),
        'channel': request.get('channel') or None,
        'headless': request.get('headless', True),
        'parallel': request.get('parallel', False),
        'max_workers': request.get('max_workers', 1),
        'timeout': request.get('timeout', 30000)
    }
    
    result = await UIExecutionService.batch_execute_test_suites(
        db, suite_ids, config, user_id
    )
    return success_response(data=result, message=f"开始批量执行 {len(suite_ids)} 个测试套件")


@router.post("/executions/{execution_id}/stop", summary="停止执行")
async def stop_execution(
    execution_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """停止执行"""
    await UIExecutionService.stop_execution(db, execution_id, user_id)
    return success_response(message="执行已停止")


@router.get("/executions/{execution_id}/status", summary="获取执行状态")
async def get_execution_status(
    execution_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取执行状态"""
    result = await UIExecutionService.get_execution_status(db, execution_id)
    return success_response(data=result)


@router.get("/executions/{execution_id}/logs", summary="获取执行日志")
async def get_execution_logs(
    execution_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取执行日志"""
    logs = await UIExecutionService.get_execution_logs(db, execution_id)
    return success_response(data={'logs': logs})


# ==================== UI执行记录管理 ====================
@router.get("/executions", summary="获取执行历史列表")
async def get_execution_list(
    ui_project_id: Optional[int] = Query(None, description="UI项目ID"),
    suite_id: Optional[int] = Query(None, description="测试套件ID"),
    test_case_id: Optional[int] = Query(None, description="测试用例ID"),
    status: Optional[str] = Query(None, description="执行状态"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db)
):
    """获取执行历史列表"""
    query = {
        'ui_project_id': ui_project_id,
        'suite_id': suite_id,
        'test_case_id': test_case_id,
        'status': status,
        'start_date': start_date,
        'end_date': end_date
    }
    result = await UIExecutionService.get_execution_list(db, query, page, page_size)
    return success_response(data=result)


@router.get("/executions/statistics", summary="获取执行统计")
async def get_execution_statistics(
    ui_project_id: Optional[int] = Query(None, description="UI项目ID"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    db: AsyncSession = Depends(get_db)
):
    """获取执行统计数据"""
    from datetime import datetime
    
    # 解析日期
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    
    result = await UIReportService.get_execution_statistics(
        db, ui_project_id, start, end
    )
    return success_response(data=result)


@router.get("/executions/{execution_id}/export", summary="导出执行报告")
async def export_execution_report(
    execution_id: int,
    format: str = Query('html', description="导出格式: html/pdf"),
    db: AsyncSession = Depends(get_db)
):
    """导出执行报告"""
    report = await UIReportService.export_execution_report(db, execution_id, format)
    
    from fastapi.responses import HTMLResponse
    if format == 'html':
        return HTMLResponse(content=report)
    else:
        return success_response(data={'report': report})


@router.get("/executions/{execution_id}", summary="获取执行详情")
async def get_execution_detail(
    execution_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取执行详情"""
    result = await UIExecutionService.get_execution_detail(db, execution_id)
    return success_response(data=result)


@router.get("/executions/{execution_id}/logs", summary="获取执行日志")
async def get_execution_logs(
    execution_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取执行日志"""
    result = await UIExecutionService.get_execution_detail(db, execution_id)
    return success_response(data={'logs': result.get('logs', '')})


@router.delete("/executions/{execution_id}", summary="删除执行记录")
async def delete_execution(
    execution_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """删除执行记录"""
    await UIExecutionService.delete_execution(db, execution_id, user_id)
    return success_response(message="删除成功")



# ==================== 代码生成 ====================
@router.post("/page-objects/{page_object_id}/generate-code", summary="生成页面对象代码")
async def generate_page_object_code(
    page_object_id: int,
    config: CodeGenerationSchema,
    db: AsyncSession = Depends(get_db)
):
    """生成页面对象代码"""
    code = await UICodeGenerationService.generate_page_object_code(
        db,
        page_object_id,
        config.language,
        config.framework,
        config.include_comments
    )
    return success_response(data={'code': code}, message="代码生成成功")


@router.get("/page-objects/{page_object_id}/preview-code", summary="预览页面对象代码")
async def preview_page_object_code(
    page_object_id: int,
    language: str = Query('javascript', description="编程语言"),
    framework: str = Query('playwright', description="框架"),
    include_comments: bool = Query(True, description="是否包含注释"),
    db: AsyncSession = Depends(get_db)
):
    """预览页面对象代码"""
    code = await UICodeGenerationService.generate_page_object_code(
        db,
        page_object_id,
        language,
        framework,
        include_comments
    )
    return success_response(data={'code': code})


@router.post("/projects/{ui_project_id}/generate-code", summary="生成项目代码")
async def generate_project_code(
    ui_project_id: int,
    config: CodeGenerationSchema,
    db: AsyncSession = Depends(get_db)
):
    """生成项目所有页面对象代码"""
    code_files = await UICodeGenerationService.generate_project_code(
        db,
        ui_project_id,
        config.language,
        config.framework,
        config.include_comments
    )
    return success_response(data={'files': code_files}, message=f"成功生成{len(code_files)}个文件")



# ==================== 元素智能定位 ====================
@router.post("/elements/validate-locator", summary="验证元素定位器")
async def validate_locator(
    data: Dict[str, str],
    db: AsyncSession = Depends(get_db)
):
    """验证元素定位器是否有效"""
    url = data.get('url')
    locator_strategy = data.get('locator_strategy')
    locator_value = data.get('locator_value')
    
    if not all([url, locator_strategy, locator_value]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少必要参数"
        )
    
    result = await UIElementValidationService.validate_locator(
        db, url, locator_strategy, locator_value
    )
    return success_response(data=result)


@router.post("/elements/suggest-locator", summary="推荐定位策略")
async def suggest_locator(
    data: Dict[str, str],
    db: AsyncSession = Depends(get_db)
):
    """根据元素HTML推荐最佳定位策略"""
    url = data.get('url')
    element_html = data.get('element_html')
    
    if not all([url, element_html]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少必要参数"
        )
    
    suggestions = await UIElementValidationService.suggest_locator(
        db, url, element_html
    )
    return success_response(data={'suggestions': suggestions})



@router.post("/test-cases/{test_case_id}/generate-code", summary="生成测试用例代码")
async def generate_test_case_code(
    test_case_id: int,
    config: CodeGenerationSchema,
    db: AsyncSession = Depends(get_db)
):
    """生成测试用例代码"""
    code = await UICodeGenerationService.generate_test_case_code(
        db,
        test_case_id,
        config.language,
        config.framework
    )
    return success_response(data={'code': code}, message="测试用例代码生成成功")


# ==================== UI 录制（Pattern A 自建录制器） ====================
class RecordStartSchema(BaseModel):
    """开始录制请求"""
    url: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    browser_type: str = 'chromium'
    viewport_width: int = 1280
    viewport_height: int = 720
    color_scheme: Optional[str] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    user_agent: Optional[str] = None


class RecordAssertModeSchema(BaseModel):
    """设置断言模式"""
    mode: str  # none | visible | text | value


class RecordImportSchema(BaseModel):
    """导入 codegen / .side 文件"""
    ui_project_id: int
    name: Optional[str] = None
    code: Optional[str] = None      # codegen 生成的测试代码
    side_json: Optional[str] = None  # Selenium IDE .side 内容


@router.post("/projects/{ui_project_id}/record/start", summary="开始录制")
async def start_record(
    ui_project_id: int,
    data: RecordStartSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """启动有头浏览器录制：用户在弹出的浏览器中操作，实时生成步骤。"""
    options = data.model_dump()
    options['ui_project_id'] = ui_project_id
    result = await RECORDER_MANAGER.start(ui_project_id, user_id, options)
    return success_response(data=result, message="录制已启动，请在弹出的浏览器中操作")


@router.post("/record/{session_id}/stop", summary="停止录制")
async def stop_record(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """停止录制并关闭浏览器，返回生成的用例与步骤数。"""
    try:
        result = await RECORDER_MANAGER.stop(session_id)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return success_response(data=result, message="录制已停止")


@router.get("/record/{session_id}/steps", summary="获取录制中的实时步骤")
async def get_record_steps(
    session_id: int,
    db: AsyncSession = Depends(get_db)
):
    """轮询获取当前已录制步骤（前端可每秒刷新实现近实时展示）。"""
    steps = await RECORDER_MANAGER.get_steps(session_id)
    return success_response(data={'steps': steps, 'count': len(steps)})


@router.post("/record/{session_id}/assert-mode", summary="设置断言模式")
async def set_assert_mode(
    session_id: int,
    data: RecordAssertModeSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """设置下一次点击为断言捕获（可见性/文本/值），对标 codegen 断言。"""
    session = RECORDER_MANAGER.get(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="录制会话不存在")
    await session.set_assert_mode(data.mode)
    return success_response(message=f"断言模式已设为 {data.mode}，下一次点击将捕获断言")


@router.post("/record/{session_id}/pick", summary="开始定位器拾取")
async def start_pick(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """下一次点击拾取元素定位器（对标 codegen Pick locator）。"""
    session = RECORDER_MANAGER.get(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="录制会话不存在")
    await session.set_pick_mode()
    return success_response(message="拾取模式已开启，请点击目标元素")


@router.get("/record/{session_id}/pick", summary="获取拾取结果")
async def get_pick(
    session_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取最近一次拾取到的定位器。"""
    session = RECORDER_MANAGER.get(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="录制会话不存在")
    return success_response(data=session.pick_result or {})


@router.post("/record/import-codegen", summary="导入 codegen 生成的测试")
async def import_codegen_endpoint(
    data: RecordImportSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """解析 Playwright codegen 生成的测试文件，转为平台用例与步骤。"""
    if not data.code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 code 内容")
    result = await import_codegen(data.ui_project_id, user_id, data.name or "codegen导入用例", data.code)
    return success_response(data=result, message="codegen 导入成功")


@router.post("/record/import-side", summary="导入 Selenium IDE .side 文件")
async def import_side_endpoint(
    data: RecordImportSchema,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """解析 Selenium IDE 导出的 .side 文件（Selenium 原生录制路径），转为平台用例与步骤。"""
    if not data.side_json:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 side_json 内容")
    result = await import_side(data.ui_project_id, user_id, data.name or "side导入用例", data.side_json)
    return success_response(data=result, message=".side 导入成功")
