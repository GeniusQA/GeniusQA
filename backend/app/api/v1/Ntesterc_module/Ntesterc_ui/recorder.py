#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""
UI 自动化「录制」

设计要点：
- 直接驱动官方 Playwright codegen 子进程（有头）进行录制：
  用户在 codegen 弹出的真实浏览器里操作，codegen 实时把脚本打印到 stdout，
  Python 端累积后解析为步骤落库。codegen 必须使用系统 Edge/Chrome 等真实浏览器，
  自带更智能的定位器推断（getByRole / getByText / getByTestId 等）。
- 解析复用 _parse_codegen / _extract_locator（与 codegen 脚本导入共用一套逻辑），
  落库复用 _build_case_from_parsed，并填充到 start() 时已经建好的用例与元素分组。
- 同时保留 codegen（--output 生成的 spec）与 Selenium IDE .side 文件导入能力，
  作为外部脚本的落地路径。
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

# 把浏览器固定到后端目录，避免不同用户/服务身份运行时找不到浏览器
_recorder_file = os.path.abspath(__file__)
_backend_dir = os.path.dirname(_recorder_file)
for _ in range(6):
    _backend_dir = os.path.dirname(_backend_dir)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join(_backend_dir, ".playwright"))

from fastapi import HTTPException
from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.sqlalchemy import async_session_factory
from ..Ntesterc_web.model import WebMenuModel, WebScriptModel
from ..Ntesterc_web.service import WebManagementService
from .crud import (
    UIElementCRUD,
    UIElementGroupCRUD,
    UITestCaseCRUD,
    UITestStepCRUD,
    UIPageObjectCRUD,
    UIPageObjectElementCRUD,
)
from .model import (
    UIElementGroupModel,
    UIElementModel,
    UITestCaseModel,
    UITestStepModel,
    UIPageObjectModel,
    UIPageObjectElementModel,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 注入到被测页面的采集脚本（在每次文档加载时执行）
# ---------------------------------------------------------------------------
RECORDER_JS = r"""
(function () {
  window.__assertMode = 'none';   // none | visible | text | value
  window.__pickMode = false;

  function cssPath(el) {
    if (!(el instanceof Element)) return null;
    var path = [];
    while (el && el.nodeType === 1 && el.tagName.toLowerCase() !== 'html') {
      var tag = el.tagName.toLowerCase();
      var parent = el.parentNode;
      if (parent) {
        var same = [].slice.call(parent.children).filter(function (c) { return c.tagName === el.tagName; });
        var idx = same.indexOf(el) + 1;
        path.unshift(idx > 1 ? tag + ':nth-of-type(' + idx + ')' : tag);
      } else {
        path.unshift(tag);
      }
      el = parent;
    }
    path.unshift('html');
    return path.join(' > ');
  }

  function computeLocators(el) {
    var cands = [];
    var testid = el.getAttribute && (el.getAttribute('data-testid') || el.getAttribute('data-test-id'));
    if (testid) cands.push({ strategy: 'test-id', value: testid });
    var id = el.id;
    if (id) cands.push({ strategy: 'id', value: id });
    var name = el.getAttribute && el.getAttribute('name');
    if (name) cands.push({ strategy: 'name', value: name });
    var ph = el.getAttribute && el.getAttribute('placeholder');
    if (ph) cands.push({ strategy: 'placeholder', value: ph });
    var text = (el.textContent || '').trim().replace(/\s+/g, ' ');
    var hasFormChild = el.querySelector && el.querySelector('input,textarea,select,img');
    if (text && text.length <= 40 && !hasFormChild) cands.push({ strategy: 'text', value: text });
    var css = cssPath(el);
    if (css) cands.push({ strategy: 'css', value: css });
    return cands;
  }

  function trim(s, n) { s = s || ''; return s.length > n ? s.slice(0, n) : s; }

  function emit(obj) {
    if (window.__geniusRecord) {
      try { window.__geniusRecord(JSON.stringify(obj)); } catch (e) {}
    }
  }

  function onAction(evt) {
    var el = evt.target;
    if (!el || !el.getAttribute) return;
    if (el.tagName === 'BODY' || el === document.documentElement) return;

    // 断言模式：先把当前元素作为断言目标回传，再复位
    var mode = window.__assertMode || 'none';
    if (mode !== 'none') {
      emit({
        kind: 'assert', assertMode: mode,
        locators: computeLocators(el),
        text: trim(el.textContent, 80),
        value: (el.value !== undefined ? el.value : '')
      });
      window.__assertMode = 'none';
      return;
    }

    // 定位器拾取模式
    if (window.__pickMode) {
      emit({ kind: 'pick', locators: computeLocators(el), text: trim(el.textContent, 80) });
      window.__pickMode = false;
      return;
    }

    var kind = evt.type;
    if (kind === 'click' || kind === 'dblclick') {
      emit({ kind: 'click', locators: computeLocators(el), tag: el.tagName, text: trim(el.textContent, 40) });
    } else if (kind === 'change') {
      emit({ kind: 'fill', locators: computeLocators(el), tag: el.tagName, value: el.value });
    }
    // submit 由 URL 变化检测统一处理，这里不单独录制
  }

  document.addEventListener('click', onAction, true);
  document.addEventListener('dblclick', onAction, true);
  document.addEventListener('change', onAction, true);

  // URL 变化检测（兼容 SPA history 路由与整页跳转）
  var _lastUrl = location.href;
  function _checkUrl() {
    if (location.href !== _lastUrl) {
      _lastUrl = location.href;
      emit({ kind: 'navigate', url: location.href });
    }
  }
  setInterval(_checkUrl, 700);
  var _push = history.pushState, _rep = history.replaceState;
  history.pushState = function () { _push.apply(this, arguments); _checkUrl(); };
  history.replaceState = function () { _rep.apply(this, arguments); _checkUrl(); };
  window.addEventListener('popstate', _checkUrl);
})();
"""


ASSERT_MODE_MAP = {
    'visible': 'isVisible',
    'text': 'textContains',
    'value': 'textEquals',
}


class RecorderSession:
    """一次录制会话：持有一个有头浏览器实例与落库状态。"""

    def __init__(self, session_id: int, project_id: int, user_id: int,
                 test_case_id: int, group_id: int, options: Dict[str, Any]):
        self.session_id = session_id
        self.project_id = project_id
        self.user_id = user_id
        self.test_case_id = test_case_id
        self.group_id = group_id
        self.options = options
        self.running = False
        self.browser = None
        self.context = None
        self.page = None
        self.pw = None
        self.interactive_pid: Optional[int] = None
        self.actual_headless = False
        self.step_counter = 0
        self.element_cache: Dict[tuple, int] = {}
        self.pick_result: Optional[Dict[str, Any]] = None
        self.paused: bool = False
        self._lock = asyncio.Lock()
        self.started_event = asyncio.Event()
        self.start_error: Optional[str] = None
        # codegen 子进程驱动相关
        self.codegen_proc = None
        self.codegen_lines: List[str] = []
        self._finalized: bool = False
        self._stdout_task = None

    # ---- 事件处理（来自页面注入脚本） ----------------------------------
    async def _handle(self, data: str):
        try:
            payload = json.loads(data)
        except Exception:
            return
        # 暂停期间不再记录新的操作步骤（断言/拾取也一并暂停，保持语义简单）
        if self.paused:
            return
        kind = payload.get('kind')
        try:
            if kind == 'navigate':
                await self._add_navigate(payload.get('url', ''))
            elif kind == 'click':
                primary = self._primary(payload.get('locators', []))
                if not primary:
                    return
                el_id = await self._ensure_element(primary, payload.get('tag'), payload.get('text'), 'button')
                await self._add_step('click', el_id, description=f"点击 {payload.get('text') or primary['value']}")
            elif kind == 'fill':
                primary = self._primary(payload.get('locators', []))
                if not primary:
                    return
                el_id = await self._ensure_element(primary, payload.get('tag'), None, 'input')
                await self._add_step('fill', el_id, action_value=payload.get('value', ''),
                                     description=f"输入 {payload.get('value', '')}")
            elif kind == 'assert':
                primary = self._primary(payload.get('locators', []))
                if not primary:
                    return
                mode = payload.get('assertMode', 'visible')
                assertion_type = ASSERT_MODE_MAP.get(mode, 'isVisible')
                assertion_value = None
                if mode == 'text':
                    assertion_value = payload.get('text', '')
                elif mode == 'value':
                    assertion_value = payload.get('value', '')
                el_id = await self._ensure_element(primary, payload.get('tag'), payload.get('text'), 'button')
                await self._add_step('assert', el_id, assertion_type=assertion_type,
                                     assertion_value=assertion_value,
                                     description=f"断言{mode}: {assertion_value or primary['value']}")
            elif kind == 'pick':
                self.pick_result = {
                    'locators': payload.get('locators', []),
                    'text': payload.get('text', ''),
                }
        except Exception as e:
            logger.error(f"录制事件处理失败: {e}", exc_info=True)

    @staticmethod
    def _primary(locators: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        if not locators:
            return None
        return locators[0]

    async def _ensure_element(self, locator: Dict[str, str], tag: Optional[str],
                              text: Optional[str], default_type: str) -> int:
        """元素去重：同一 (strategy, value) 复用同一行 ui_elements。"""
        key = (locator['strategy'], locator['value'])
        if key in self.element_cache:
            return self.element_cache[key]

        backups = [l for l in [] if False]  # 占位
        async with async_session_factory() as db:
            crud = UIElementCRUD(db)
            # 库内是否已存在（避免重复）
            existing = await crud.get_by_project_locator(db, self.project_id, locator['strategy'], locator['value'])
            if existing:
                self.element_cache[key] = existing.id
                return existing.id

            element_type = self._guess_type(tag, default_type)
            name = (text or locator['value'] or tag or 'element')
            name = name[:60]
            model = UIElementModel(
                group_id=self.group_id,
                name=name,
                description=f"录制生成 ({locator['strategy']}={locator['value']})",
                element_type=element_type,
                locator_strategy=locator['strategy'],
                locator_value=locator['value'],
                backup_locators=backups,
                wait_time=5000,
                created_by=self.user_id,
            )
            db.add(model)
            await db.commit()
            await db.refresh(model)
            self.element_cache[key] = model.id
            return model.id

    @staticmethod
    def _guess_type(tag: Optional[str], default_type: str) -> str:
        tag = (tag or '').lower()
        if tag in ('input', 'textarea'):
            return 'input'
        if tag in ('select',):
            return 'select'
        if tag in ('a', 'button'):
            return 'button'
        if tag in ('img',):
            return 'image'
        return default_type

    async def _add_step(self, action_type: str, element_id: Optional[int] = None,
                        action_value: Optional[str] = None, assertion_type: Optional[str] = None,
                        assertion_value: Optional[str] = None, description: Optional[str] = None):
        async with self._lock:
            self.step_counter += 1
            step_no = self.step_counter
        async with async_session_factory() as db:
            crud = UITestStepCRUD(db)
            model = UITestStepModel(
                test_case_id=self.test_case_id,
                step_number=step_no,
                action_type=action_type,
                element_id=element_id,
                action_value=action_value,
                assertion_type=assertion_type,
                assertion_value=assertion_value,
                description=description,
                screenshot_on_failure=True,
                continue_on_failure=False,
                created_by=self.user_id,
            )
            db.add(model)
            await db.commit()

    async def _add_navigate(self, url: str):
        if not url:
            return
        await self._add_step('navigate', action_value=url, description=f"导航到 {url}")

    # ---- 浏览器生命周期 ------------------------------------------------
    @staticmethod
    def _install_browser(browser_type: str) -> None:
        """自动安装 Playwright 浏览器（用于 SYSTEM/服务用户找不到浏览器时）。"""
        try:
            logger.info(f"正在自动安装 Playwright 浏览器: {browser_type}")
            subprocess.run(
                [sys.executable, '-m', 'playwright', 'install', browser_type],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"Playwright 浏览器 {browser_type} 安装完成")
        except Exception as e:
            logger.error(f"自动安装 Playwright 浏览器失败: {e}", exc_info=True)
            raise

    # 与浏览器检查页一致的浏览器 -> Playwright launcher/channel 映射
    _BROWSER_MAP = {
        'edge': ('chromium', 'msedge'),
        'chrome': ('chromium', 'chrome'),
        'firefox': ('firefox', None),
        'safari': ('webkit', None),
        # 兼容旧数据
        'msedge': ('chromium', 'msedge'),
        'chromium': ('chromium', None),
        'webkit': ('webkit', None),
    }

    async def _launch_browser(self, opts: Dict[str, Any]):
        browser_type = opts.get('browser_type', 'msedge')
        headless = bool(opts.get('headless', False))
        self.actual_headless = headless

        # 后端运行于无桌面环境（session 0 / 非活动会话 / 非交互窗口站）时，
        # 普通有头浏览器无法创建窗口会立即退出（exitCode=1002）。
        # 两端处理：
        #   1) 若后端确实没有可交互桌面 -> 直接强制无头，用系统 Edge 以 --headless=new
        #      启动（仍是系统安装的 Edge，只是无头运行），避免窗口创建失败崩溃；
        #   2) 若后端当前在本机交互桌面（有可见桌面）-> 尝试把浏览器派生到当前登录
        #      用户的交互桌面，从而保留可见弹窗录制体验。
        try:
            from .browser_path_config import is_headless_required
            headless_required = is_headless_required()
        except Exception:
            headless_required = False

        if headless_required and not headless:
            logger.warning(
                "后端运行于无桌面环境(session 0 / 非交互会话)，强制以无头方式启动系统 "
                "浏览器（仍为系统安装的 Edge，仅无头运行，避免窗口创建失败）"
            )
            headless = True
            self.actual_headless = True

        if not headless_required and not headless:
            # 仅在「有可见桌面」时尝试交互桌面弹出，避免无效尝试浪费时间
            try:
                from .browser_path_config import launch_interactive_browser
                logger.warning(
                    "后端运行于有桌面环境，尝试在交互桌面启动有头浏览器"
                )
                try:
                    info = launch_interactive_browser(browser_type)
                    self.interactive_pid = info["pid"]
                    cdp_port = info["cdp_port"]
                    # 等待 CDP 端口就绪（最多 30 秒）
                    import socket
                    for _ in range(60):
                        try:
                            with socket.create_connection(
                                ("127.0.0.1", cdp_port), timeout=1
                            ):
                                break
                        except Exception:
                            await asyncio.sleep(0.5)
                    else:
                        raise RuntimeError(
                            f"浏览器 CDP 端口 {cdp_port} 未在 30 秒内就绪"
                        )
                    browser = await self.pw.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{cdp_port}"
                    )
                    try:
                        from .browser_path_config import register_active_browser
                        register_active_browser(browser, pid=self.interactive_pid)
                    except Exception:
                        pass
                    logger.info(
                        f"已通过 CDP 连接交互桌面浏览器 (pid={self.interactive_pid}, "
                        f"port={cdp_port})"
                    )
                    return browser
                except Exception as e:
                    logger.warning(
                        f"交互桌面启动失败，回退到普通启动: {e}", exc_info=True
                    )
                    self.interactive_pid = None
            except Exception:
                pass

        launch_args = [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-gpu',
            '--disable-dev-shm-usage',
        ]
        if headless:
            launch_args.append('--hide-scrollbars')
            # 系统 Edge 在无头模式下使用 new headless，支持 CDP 注入且更稳定
            launch_args.append('--headless=new')

        launcher_name, channel = self._BROWSER_MAP.get(browser_type, ('chromium', None))
        launcher = getattr(self.pw, launcher_name, self.pw.chromium)
        launch_kwargs: Dict[str, Any] = {'headless': headless, 'args': launch_args}

        # 清理交互桌面启动失败时遗留的 profile 目录（避免锁冲突导致本次启动即崩）
        try:
            from .browser_path_config import cleanup_interactive_profiles
            cleanup_interactive_profiles()
        except Exception:
            pass

        # 重定向浏览器临时目录，规避 SYSTEM 身份下 C:\WINDOWS\TEMP 锁冲突
        from .browser_path_config import get_browser_launch_env
        launch_kwargs['env'] = get_browser_launch_env()

        # 优先使用用户配置的自定义浏览器路径
        custom_path = None
        try:
            from .browser_path_config import get_browser_path
            custom_path = get_browser_path(browser_type)
        except Exception:
            pass
        if custom_path and os.path.exists(custom_path):
            launch_kwargs['executable_path'] = custom_path
            launch_kwargs.pop('channel', None)
        elif channel:
            launch_kwargs['channel'] = channel

        try:
            browser = await launcher.launch(**launch_kwargs)
            try:
                from .browser_path_config import register_active_browser
                register_active_browser(browser)
            except Exception:
                pass
            return browser
        except Exception as e:
            err = str(e)
            logger.error(
                f"_launch_browser 启动失败 (browser_type={browser_type}, "
                f"headless={headless}, channel={channel}, custom_path={custom_path}): "
                f"{err}",
                exc_info=True,
            )
            # 即便 is_headless_required() 误判为非强制无头，这里也做通用兜底：
            # 有头启动失败（典型为 exitCode=1002 / Target page, context or browser has been closed）
            # 往往就是「无桌面会话无法创建窗口」导致。直接以无头模式重试一次，
            # 仍使用系统安装的 Edge（channel 不变），只是无头运行。
            if not self.actual_headless and not headless:
                logger.warning(
                    "有头启动失败，自动以无头模式重试系统浏览器（--headless=new）"
                )
                headless = True
                self.actual_headless = True
                launch_args = [
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-gpu',
                    '--disable-dev-shm-usage',
                    '--hide-scrollbars',
                    '--headless=new',
                ]
                launch_kwargs = {
                    'headless': True,
                    'args': launch_args,
                    'env': launch_kwargs.get('env') or get_browser_launch_env(),
                }
                if channel:
                    launch_kwargs['channel'] = channel
                try:
                    browser = await launcher.launch(**launch_kwargs)
                    try:
                        from .browser_path_config import register_active_browser
                        register_active_browser(browser)
                    except Exception:
                        pass
                    logger.info("无头模式重试启动成功")
                    return browser
                except Exception as e2:
                    logger.error(f"无头模式重试仍然失败: {e2}", exc_info=True)
                    # 继续走后续兜底逻辑

            # 启动失败后在重试兜底前，回收本进程树内残留的浏览器子进程，
            # 避免句柄/管道累积导致后续启动也失败（注意：必须在 launch 失败后才回收，
            # 否则会误伤本次即将启动的浏览器，造成 Target page, context or browser has been closed）
            try:
                from .browser_path_config import reap_stale_browser_processes
                reap_stale_browser_processes()
            except Exception:
                pass
            if custom_path and "Executable doesn't exist" in err:
                raise RuntimeError(
                    f"自定义浏览器路径无法启动: {custom_path}，请检查是否选择了正确的可执行文件"
                ) from e
            if channel and "Chromium distribution" in err:
                raise RuntimeError(
                    f"未找到系统安装的 {channel} 浏览器，请确认已安装后再试"
                ) from e
            # channel（系统 Edge/Chrome，可能版本不兼容）失败时，
            # 优先回退到 Playwright 自带的、版本严格匹配的 Chromium
            try:
                from .browser_path_config import find_bundled_chromium
                bundled = find_bundled_chromium()
                if bundled and os.path.exists(bundled):
                    # 同步最新的 headless 状态（前面判定无头时强制无头）
                    launch_kwargs['headless'] = headless
                    if headless and '--headless=new' not in launch_kwargs.get('args', []):
                        launch_kwargs.setdefault('args', []).append('--headless=new')
                    launch_kwargs['executable_path'] = bundled
                    launch_kwargs.pop('channel', None)
                    logger.warning(
                        f"尝试用 Playwright 自带 Chromium 重新启动浏览器: {bundled}"
                    )
                    browser = await launcher.launch(**launch_kwargs)
                    try:
                        from .browser_path_config import register_active_browser
                        register_active_browser(browser)
                    except Exception:
                        pass
                    return browser
            except Exception as e2:
                logger.error(
                    f"Playwright 自带 Chromium 也启动失败: {e2}", exc_info=True
                )
            # 再尝试直接使用系统浏览器可执行文件路径
            if channel in ('msedge', 'chrome') and not (custom_path and os.path.exists(custom_path)):
                try:
                    from .browser_path_config import _get_interactive_browser_executable
                    fallback_exe = _get_interactive_browser_executable(browser_type)
                    launch_kwargs['headless'] = headless
                    if headless and '--headless=new' not in launch_kwargs.get('args', []):
                        launch_kwargs.setdefault('args', []).append('--headless=new')
                    launch_kwargs['executable_path'] = fallback_exe
                    launch_kwargs.pop('channel', None)
                    logger.warning(
                        f"尝试用系统可执行文件路径重新启动浏览器: {fallback_exe}"
                    )
                    browser = await launcher.launch(**launch_kwargs)
                    try:
                        from .browser_path_config import register_active_browser
                        register_active_browser(browser)
                    except Exception:
                        pass
                    return browser
                except Exception as e3:
                    logger.error(
                        f"系统可执行文件路径也启动失败: {e3}", exc_info=True
                    )
            if "Executable doesn't exist" in err or "browserType.launch" in err:
                # 尝试自动安装 Playwright 自带浏览器后重试一次
                await asyncio.get_event_loop().run_in_executor(
                    None, self._install_browser, launcher_name
                )
                launch_kwargs['headless'] = headless
                if headless and '--headless=new' not in launch_kwargs.get('args', []):
                    launch_kwargs.setdefault('args', []).append('--headless=new')
                return await launcher.launch(**launch_kwargs)
            raise

    # ---- codegen 子进程驱动（官方 Playwright codegen 录制） ----------------
    async def run(self):
        opts = self.options
        try:
            # codegen 必须 headed（CLI 无 --headless），无桌面环境无法弹出窗口
            try:
                from .browser_path_config import is_headless_required
                if is_headless_required():
                    raise RuntimeError(
                        "后端处于无桌面环境（session 0 / 非交互会话），codegen 录制必须 headed，"
                        "无法在此环境运行。请在有桌面的服务器上启动后端后再录制。"
                    )
            except ImportError:
                pass

            await self._start_codegen(opts)
            self.running = True
            self.started_event.set()

            # 短等待，检测 codegen 是否立即失败（如缺少浏览器/无法启动）
            try:
                await asyncio.wait_for(self.codegen_proc.wait(), timeout=5)
                stderr = b''
                try:
                    if self.codegen_proc.stderr:
                        stderr = await self.codegen_proc.stderr.read()
                except Exception:
                    pass
                raise RuntimeError(
                    "codegen 启动失败：" + (stderr or b'').decode('utf-8', 'replace')[:800]
                )
            except asyncio.TimeoutError:
                pass  # 正常：codegen 持续运行，等待用户关闭浏览器或被停止

            # 正常结束（用户关闭浏览器窗口 / 被 stop 终止）
            await self.codegen_proc.wait()
            await self._finalize_from_codegen()
        except Exception as e:
            self.start_error = str(e)
            self.started_event.set()
            logger.error(f"录制会话 {self.session_id} 运行异常: {e}", exc_info=True)
        finally:
            await self._cleanup()

    async def _read_stdout(self):
        if not self.codegen_proc or not self.codegen_proc.stdout:
            return
        try:
            async for line in self.codegen_proc.stdout:
                self.codegen_lines.append(line.decode('utf-8', 'replace'))
        except Exception as e:
            logger.warning(f"读取 codegen stdout 失败: {e}")

    async def _start_codegen(self, opts: Dict[str, Any]):
        """启动官方 playwright codegen 子进程，实时把脚本打印到 stdout。"""
        browser_type = opts.get('browser_type', 'msedge')
        launcher_name, channel = self._BROWSER_MAP.get(browser_type, ('chromium', None))
        cmd: List[str] = [
            sys.executable, '-m', 'playwright', 'codegen',
            '--target', 'playwright-test',
            '--browser', launcher_name,
        ]
        if channel:
            cmd += ['--channel', channel]
        vw = int(opts.get('viewport_width', 1280))
        vh = int(opts.get('viewport_height', 720))
        cmd += ['--viewport-size', f'{vw}, {vh}']
        if opts.get('locale'):
            cmd += ['--lang', str(opts['locale'])]
        if opts.get('timezone'):
            cmd += ['--timezone', str(opts['timezone'])]
        if opts.get('color_scheme'):
            cmd += ['--color-scheme', str(opts['color_scheme'])]
        url = opts.get('url')
        if url:
            cmd.append(str(url))

        from .browser_path_config import get_browser_launch_env
        env = dict(os.environ)
        env.update(get_browser_launch_env())

        logger.info(f"启动 codegen 录制子进程: {' '.join(cmd)}")
        self.codegen_proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._stdout_task = asyncio.ensure_future(self._read_stdout())

    async def _finalize_from_codegen(self):
        """解析 codegen 累积的脚本并落入已建立的用例/元素分组。"""
        async with self._lock:
            if self._finalized:
                return
            self._finalized = True
        try:
            code = ''.join(self.codegen_lines)
            if not code.strip():
                logger.info(f"录制会话 {self.session_id} codegen 未生成任何脚本")
                return
            steps = _parse_codegen(code)
            if not steps:
                logger.info(f"录制会话 {self.session_id} codegen 脚本解析后无步骤")
                return
            async with async_session_factory() as db:
                await _build_case_from_parsed(
                    self.project_id, self.user_id,
                    self.options.get('name') or f"录制用例_{self.session_id}",
                    steps, 'codegen',
                    test_case_id=self.test_case_id, group_id=self.group_id,
                )
        except Exception as e:
            logger.error(f"codegen 录制结果落库失败: {e}", exc_info=True)

    def get_codegen_script(self) -> str:
        return ''.join(self.codegen_lines)

    async def _on_page_close(self):
        self.running = False

    async def _cleanup(self):
        try:
            if self.browser and self.browser.is_connected():
                try:
                    from .browser_path_config import unregister_active_browser
                    unregister_active_browser(
                        self.browser, pid=self.interactive_pid
                    )
                except Exception:
                    pass
                await self.browser.close()
        except Exception:
            pass
        # 交互桌面启动的浏览器进程需要显式结束（connect_over_cdp 不会 kill 系统进程）
        if self.interactive_pid:
            try:
                _subprocess.run(
                    f"taskkill /F /PID {self.interactive_pid} /T",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception:
                pass
            self.interactive_pid = None
        try:
            if self.pw:
                await self.pw.stop()
        except Exception:
            pass
        # 兜底确保 codegen 子进程被回收
        if self.codegen_proc and self.codegen_proc.returncode is None:
            try:
                self.codegen_proc.kill()
            except Exception:
                pass
        self.running = False

    async def stop(self):
        self.running = False
        # 终止 codegen 子进程（用户点击停止录制），结束后 stdout 收尾并落库
        if self.codegen_proc and self.codegen_proc.returncode is None:
            try:
                self.codegen_proc.terminate()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.codegen_proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                try:
                    self.codegen_proc.kill()
                except Exception:
                    pass
        if self._stdout_task:
            try:
                await self._stdout_task
            except Exception:
                pass
        await self._finalize_from_codegen()

    async def set_assert_mode(self, mode: str):
        if self.page:
            await self.page.evaluate("window.__assertMode = arguments[0]", mode)

    async def set_pick_mode(self):
        self.pick_result = None
        if self.page:
            await self.page.evaluate("window.__pickMode = true")

    async def pause(self):
        """暂停录制：后续页面操作不再生成步骤。"""
        self.paused = True
        logger.info(f"录制会话 {self.session_id} 已暂停")

    async def resume(self):
        """继续录制：恢复生成步骤。"""
        self.paused = False
        logger.info(f"录制会话 {self.session_id} 已继续")

    async def get_pick(self) -> Optional[Dict[str, Any]]:
        return self.pick_result

    async def count_steps(self) -> int:
        async with async_session_factory() as db:
            steps = await UITestStepCRUD(db).get_by_test_case_id(db, self.test_case_id)
            return len(steps)


class RecorderManager:
    """会话管理器（单例）。"""

    def __init__(self):
        self.sessions: Dict[int, RecorderSession] = {}

    async def start(self, project_id: int, user_id: int, options: Dict[str, Any]) -> Dict[str, Any]:
        session_id = int(time.time() * 1000)
        async with async_session_factory() as db:
            group = UIElementGroupModel(
                ui_project_id=project_id,
                name=f"录制元素_{session_id}",
                description="录制自动生成的元素分组",
                order_num=0,
                created_by=user_id,
            )
            db.add(group)
            await db.flush()
            tc_name = options.get('name') or f"录制用例_{time.strftime('%Y%m%d_%H%M%S')}"
            tc = UITestCaseModel(
                ui_project_id=project_id,
                name=tc_name,
                description=options.get('description') or "通过录制生成的测试用例",
                priority=options.get('priority', 'medium'),
                created_by=user_id,
            )
            db.add(tc)
            await db.flush()
            group_id = group.id
            tc_id = tc.id
            await db.commit()

        session = RecorderSession(session_id, project_id, user_id, tc_id, group_id, options)
        self.sessions[session_id] = session
        asyncio.ensure_future(session.run())

        # 等待浏览器实际启动成功（最多 15 秒），失败则清理并返回错误
        try:
            await asyncio.wait_for(session.started_event.wait(), timeout=15)
        except asyncio.TimeoutError:
            await session.stop()
            self.sessions.pop(session_id, None)
            raise HTTPException(status_code=500, detail='浏览器启动超时，请尝试开启“无头模式”后再试')

        if session.start_error:
            await session.stop()
            self.sessions.pop(session_id, None)
            raise HTTPException(status_code=500, detail=f'浏览器启动失败: {session.start_error}')

        return {
            'session_id': session_id,
            'test_case_id': tc_id,
            'group_id': group_id,
        }

    def get(self, session_id: int) -> Optional[RecorderSession]:
        return self.sessions.get(session_id)

    async def pause(self, session_id: int) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError('录制会话不存在或已结束')
        await session.pause()
        return {'session_id': session_id, 'paused': True}

    async def resume(self, session_id: int) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError('录制会话不存在或已结束')
        await session.resume()
        return {'session_id': session_id, 'paused': False}

    async def stop(self, session_id: int) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError('录制会话不存在或已结束')
        await session.stop()
        count = await session.count_steps()
        # 录制结束时自动把本会话采集到的元素聚合为一个页面对象，
        # 这样「页面对象」Tab 也能直接看到本次录制的对象数据。
        page_object_id = None
        try:
            page_object_id = await self._create_page_object(session)
        except Exception as e:
            logger.error(f"录制生成页面对象失败: {e}", exc_info=True)
        # 若指定了 Web 脚本目标，把录制步骤同步到脚本库
        web_script_menu_id = None
        if session.options.get('script_id') or session.options.get('script_menu_id'):
            try:
                web_script_menu_id = await self._save_steps_to_web_script(session)
            except Exception as e:
                logger.error(f"同步录制步骤到 Web 脚本失败: {e}", exc_info=True)
        # 稍等浏览器回收
        await asyncio.sleep(1)
        return {
            'session_id': session_id,
            'test_case_id': session.test_case_id,
            'steps_count': count,
            'page_object_id': page_object_id,
            'web_script_menu_id': web_script_menu_id,
        }

    async def _save_steps_to_web_script(self, session: 'RecorderSession') -> Optional[int]:
        """把录制步骤转换后写入 Web 脚本库（追加到所选脚本，或在所选脚本库下新建脚本）。"""
        script_id = session.options.get('script_id')
        script_menu_id = session.options.get('script_menu_id')
        if not script_id and not script_menu_id:
            return None

        async with async_session_factory() as db:
            result = await db.execute(
                select(UITestStepModel).where(
                    UITestStepModel.test_case_id == session.test_case_id,
                ).order_by(UITestStepModel.step_number)
            )
            steps = result.scalars().all()
            if not steps:
                return None

            data: List[Dict[str, Any]] = []
            for s in steps:
                element: Optional[Dict[str, Any]] = None
                if s.element_id:
                    el = await db.get(UIElementModel, s.element_id)
                    if el:
                        custom_locators: List[Dict[str, str]] = [
                            {"value": f"{el.locator_strategy}={el.locator_value}"}
                        ]
                        if el.backup_locators:
                            for bl in el.backup_locators:
                                if not isinstance(bl, dict):
                                    continue
                                strategy = bl.get('strategy')
                                val = bl.get('value')
                                if val and strategy and '=' not in str(val):
                                    custom_locators.append({"value": f"{strategy}={val}"})
                                elif val:
                                    custom_locators.append({"value": str(val)})
                        element = {"custom_locators": custom_locators}
                if s.action_type == 'navigate':
                    data.append({
                        "action": "open_page",
                        "fill_name": s.description or "打开",
                        "action_detail": {"open_page": {"url": s.action_value or ""}},
                    })
                elif s.action_type == 'click':
                    data.append({
                        "action": "mouse_clicking",
                        "fill_name": s.description or "点击",
                        "action_detail": {"mouse_clicking": {"type": "single_click_left", "element": element or {}}},
                    })
                elif s.action_type == 'fill':
                    data.append({
                        "action": "input_operations",
                        "fill_name": s.description or "输入",
                        "action_detail": {"input_operations": {"input_content": s.action_value or "", "element": element or {}}},
                    })
                else:
                    continue

            if not data:
                return None

            ok, msg, new_script = await WebManagementService._analysis_element("recorded", session.user_id, 0, data)
            if not ok:
                raise Exception(msg)

            target_menu_id: Optional[int] = None
            if script_id:
                target_menu_id = int(script_id)
            else:
                name = session.options.get('name') or f"录制脚本_{session.session_id}"
                created = await WebManagementService.create_web_menu(
                    db,
                    name=name,
                    pid=int(script_menu_id),
                    type=2,
                    user_id=session.user_id,
                )
                target_menu_id = created["id"]

            res = await db.execute(
                select(WebScriptModel).where(
                    WebScriptModel.menu_id == target_menu_id,
                    WebScriptModel.enabled_flag == 1,
                )
            )
            row = res.scalar_one_or_none()
            if row:
                existing = row.script or []
                row.script = existing + new_script
                row.last_updated_by = session.user_id
            else:
                row = WebScriptModel(
                    script=new_script,
                    menu_id=target_menu_id,
                    created_by=session.user_id,
                )
                db.add(row)
            await db.commit()
            return target_menu_id

    async def _create_page_object(self, session: 'RecorderSession') -> Optional[int]:
        """把录制分组下的元素关联生成一个页面对象（ui_page_objects）。"""
        group_id = session.group_id
        project_id = session.project_id
        user_id = session.user_id
        async with async_session_factory() as db:
            elements, _ = await UIElementCRUD(db).get_by_group_id(db, group_id, limit=1000)
            if not elements:
                return None
            po = await UIPageObjectCRUD(db).create_crud({
                'ui_project_id': project_id,
                'name': f"录制页面对象_{session.session_id}",
                'class_name': f"RecordedPage{session.session_id}"[-31:],
                'description': f"由录制自动生成（用例 #{session.test_case_id}）",
                'url_pattern': '',
                'created_by': user_id,
            })
            po_id = po.id
            for idx, el in enumerate(elements):
                raw = (el.name or f"element_{el.id}").replace(' ', '_').lower()
                method_name = re.sub(r'\W+', '_', raw) or f"element_{el.id}"
                await UIPageObjectElementCRUD(db).create_crud({
                    'page_object_id': po_id,
                    'element_id': el.id,
                    'method_name': method_name,
                    'is_property': False,
                    'order_num': idx,
                    'created_by': user_id,
                })
            return po_id


    async def get_steps(self, session_id: int) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            return {'steps': [], 'count': 0, 'paused': False}
        async with async_session_factory() as db:
            steps = await UITestStepCRUD(db).get_by_test_case_id(db, session.test_case_id)
            return {
                'steps': [{
                    'id': s.id,
                    'step_number': s.step_number,
                    'action_type': s.action_type,
                    'element_id': s.element_id,
                    'action_value': s.action_value,
                    'assertion_type': s.assertion_type,
                    'assertion_value': s.assertion_value,
                    'description': s.description,
                } for s in steps],
                'count': len(steps),
                'paused': session.paused,
            }

    def get_codegen_script(self, session_id: int) -> str:
        """返回 codegen 实时累积的脚本文本（供前端实时展示）。"""
        session = self.sessions.get(session_id)
        if not session:
            return ''
        return session.get_codegen_script()


RECORDER_MANAGER = RecorderManager()


# ---------------------------------------------------------------------------
# codegen 生成的 .spec 文件导入（加速路径）
# ---------------------------------------------------------------------------
async def import_codegen(project_id: int, user_id: int, name: str, code: str) -> Dict[str, Any]:
    """解析 Playwright codegen 生成的 JS/Python 测试，转为步骤/元素。"""
    steps = _parse_codegen(code)
    return await _build_case_from_parsed(project_id, user_id, name, steps, 'codegen')


async def import_side(project_id: int, user_id: int, name: str, side_json: str) -> Dict[str, Any]:
    """解析 Selenium IDE 导出的 .side 文件，转为步骤/元素（Selenium 原生录制路径）。"""
    steps = _parse_side(side_json)
    return await _build_case_from_parsed(project_id, user_id, name, steps, 'side')


def _parse_codegen(code: str) -> List[Dict[str, Any]]:
    """简易解析 Playwright 生成代码，提取动作。"""
    out: List[Dict[str, Any]] = []
    lines = code.splitlines()
    for line in lines:
        s = line.strip()
        # page.goto
        m = re.search(r"page\.goto\(\s*['\"]([^'\"]+)['\"]", s)
        if m and s.startswith('await'):
            out.append({'action_type': 'navigate', 'action_value': m.group(1)})
            continue
        # *.fill('...')
        m = re.search(r"\.(?:fill|type)\(\s*['\"]([^'\"]*)['\"]\s*\)", s)
        if m and s.startswith('await'):
            loc = _extract_locator(s)
            out.append({'action_type': 'fill', 'locator': loc, 'action_value': m.group(1)})
            continue
        # *.click()
        if '.click()' in s and s.startswith('await'):
            loc = _extract_locator(s)
            out.append({'action_type': 'click', 'locator': loc})
            continue
        # expect(...).toBeVisible()
        if 'toBeVisible()' in s:
            loc = _extract_locator(s)
            out.append({'action_type': 'assert', 'locator': loc, 'assertion_type': 'isVisible'})
            continue
        # expect(...).toHaveText('...')
        m = re.search(r"toHaveText\(\s*['\"]([^'\"]*)['\"]", s)
        if m:
            loc = _extract_locator(s)
            out.append({'action_type': 'assert', 'locator': loc, 'assertion_type': 'textContains',
                        'assertion_value': m.group(1)})
            continue
    return out


def _extract_locator(line: str) -> Dict[str, str]:
    """从代码行提取定位器，返回 {strategy, value}。"""
    # getByRole('x', { name: 'y' })
    m = re.search(r"getByRole\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*\{[^}]*name\s*:\s*['\"]([^'\"]+)['\"])?", line)
    if m:
        role = m.group(1)
        name = m.group(2)
        return {'strategy': 'role', 'value': role + (f" {name}" if name else "")}
    # getByText('x')
    m = re.search(r"getByText\(\s*['\"]([^'\"]+)['\"]", line)
    if m:
        return {'strategy': 'text', 'value': m.group(1)}
    # locator('css or xpath=...')
    m = re.search(r"locator\(\s*['\"]([^'\"]+)['\"]", line)
    if m:
        val = m.group(1)
        if val.startswith('xpath='):
            return {'strategy': 'xpath', 'value': val[len('xpath='):]}
        if val.startswith('#'):
            return {'strategy': 'id', 'value': val[1:]}
        return {'strategy': 'css', 'value': val}
    # getByPlaceholder / getByLabel
    m = re.search(r"getBy(Placeholder|Label|Role|TestId|Title)\(\s*['\"]([^'\"]+)['\"]", line)
    if m:
        smap = {'Placeholder': 'placeholder', 'Label': 'label', 'Role': 'role',
                'TestId': 'test-id', 'Title': 'title'}
        return {'strategy': smap.get(m.group(1), 'text'), 'value': m.group(2)}
    return {'strategy': 'css', 'value': 'body'}


def _parse_side(side_json: str) -> List[Dict[str, Any]]:
    """解析 Selenium IDE .side JSON。"""
    out: List[Dict[str, Any]] = []
    try:
        data = json.loads(side_json)
    except Exception:
        return out
    tests = data.get('tests') or []
    if not tests:
        return out
    commands = tests[0].get('commands', [])
    for cmd in commands:
        command = (cmd.get('command') or '').strip()
        target = cmd.get('target', '') or ''
        value = cmd.get('value', '') or ''
        # target 形如 id=foo / css=.x / name=bar / xpath=//..
        strategy, locator_value = _split_side_target(target)
        if command in ('open',):
            out.append({'action_type': 'navigate', 'action_value': target})
        elif command in ('click', 'clickAndWait', 'clickAt'):
            out.append({'action_type': 'click', 'locator': {'strategy': strategy, 'value': locator_value}})
        elif command in ('type', 'sendKeys', 'setText'):
            out.append({'action_type': 'fill', 'locator': {'strategy': strategy, 'value': locator_value},
                        'action_value': value})
        elif command in ('assertText', 'verifyText', 'assertValue', 'verifyValue'):
            atype = 'textEquals' if 'Value' in command else 'textContains'
            out.append({'action_type': 'assert', 'locator': {'strategy': strategy, 'value': locator_value},
                        'assertion_type': atype, 'assertion_value': value})
        elif command in ('assertElementPresent', 'verifyElementPresent', 'assertVisible', 'verifyVisible'):
            out.append({'action_type': 'assert', 'locator': {'strategy': strategy, 'value': locator_value},
                        'assertion_type': 'isVisible'})
        elif command in ('waitForElementPresent', 'waitForElementVisible'):
            out.append({'action_type': 'waitFor', 'locator': {'strategy': strategy, 'value': locator_value}})
    return out


def _split_side_target(target: str):
    if '=' in target and target.split('=', 1)[0].lower() in (
        'id', 'name', 'css', 'xpath', 'link', 'linktext', 'class', 'tag', 'partiallinktext'
    ):
        strat, val = target.split('=', 1)
        smap = {'id': 'id', 'name': 'name', 'css': 'css', 'xpath': 'xpath',
                'link': 'text', 'linktext': 'text', 'partiallinktext': 'text',
                'class': 'css', 'tag': 'css'}
        return smap.get(strat.lower(), 'css'), val
    return 'css', target


async def _build_case_from_parsed(project_id: int, user_id: int, name: str,
                                  steps: List[Dict[str, Any]], source: str,
                                  test_case_id: Optional[int] = None,
                                  group_id: Optional[int] = None) -> Dict[str, Any]:
    async with async_session_factory() as db:
        if group_id is None:
            group = UIElementGroupModel(
                ui_project_id=project_id,
                name=f"导入元素_{source}_{int(time.time() * 1000)}",
                description=f"从 {source} 导入",
                order_num=0,
                created_by=user_id,
            )
            db.add(group)
            await db.flush()
            group_id = group.id

        if test_case_id is None:
            tc = UITestCaseModel(
                ui_project_id=project_id,
                name=name or f"导入用例_{source}_{time.strftime('%Y%m%d_%H%M%S')}",
                description=f"从 {source} 导入生成的测试用例",
                priority='medium',
                created_by=user_id,
            )
            db.add(tc)
            await db.flush()
            test_case_id = tc.id

        el_crud = UIElementCRUD(db)
        element_cache: Dict[tuple, int] = {}
        step_no = 0
        for st in steps:
            step_no += 1
            element_id = None
            loc = st.get('locator')
            if loc and st['action_type'] in ('click', 'fill', 'assert', 'waitFor'):
                key = (loc['strategy'], loc['value'])
                if key in element_cache:
                    element_id = element_cache[key]
                else:
                    existing = await el_crud.get_by_project_locator(db, project_id, loc['strategy'], loc['value'])
                    if existing:
                        element_id = existing.id
                    else:
                        etype = 'input' if st['action_type'] == 'fill' else 'button'
                        el = UIElementModel(
                            group_id=group_id,
                            name=(loc['value'] or 'element')[:60],
                            description=f"{source} 导入 ({loc['strategy']}={loc['value']})",
                            element_type=etype,
                            locator_strategy=loc['strategy'],
                            locator_value=loc['value'],
                            wait_time=5000,
                            created_by=user_id,
                        )
                        db.add(el)
                        await db.flush()
                        element_id = el.id
                    element_cache[key] = element_id

            step = UITestStepModel(
                test_case_id=test_case_id,
                step_number=step_no,
                action_type=st['action_type'],
                element_id=element_id,
                action_value=st.get('action_value'),
                assertion_type=st.get('assertion_type'),
                assertion_value=st.get('assertion_value'),
                description=st.get('description'),
                screenshot_on_failure=True,
                continue_on_failure=False,
                created_by=user_id,
            )
            await db.add(step)

        await db.commit()
        return {'test_case_id': test_case_id, 'steps_count': step_no}
