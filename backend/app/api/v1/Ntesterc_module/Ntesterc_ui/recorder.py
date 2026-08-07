#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""
UI 自动化「录制」

设计要点：
- 复用 Playwright 启动一个「有头（可见）」浏览器，用户在弹出的浏览器里操作。
- 通过 page.expose_function + page.add_init_script 注入采集脚本，
  捕获 DOM 事件（click / change / submit / URL 变化）并实时回传 Python。
- Python 端实时推断健壮定位器，去重后写入 ui_elements / ui_test_steps，
  现有 PlaywrightTestEngine / SeleniumExecutionWrapper 可直接回放。
- 同时提供 codegen（--output 生成的 spec）与 Selenium IDE .side 文件导入，
  作为 Selenium 原生录制的落地路径。
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.sqlalchemy import async_session_factory
from .crud import (
    UIElementCRUD,
    UIElementGroupCRUD,
    UITestCaseCRUD,
    UITestStepCRUD,
)
from .model import (
    UIElementGroupModel,
    UIElementModel,
    UITestCaseModel,
    UITestStepModel,
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
        self.step_counter = 0
        self.element_cache: Dict[tuple, int] = {}
        self.pick_result: Optional[Dict[str, Any]] = None
        self._lock = asyncio.Lock()
        self.started_event = asyncio.Event()
        self.start_error: Optional[str] = None

    # ---- 事件处理（来自页面注入脚本） ----------------------------------
    async def _handle(self, data: str):
        try:
            payload = json.loads(data)
        except Exception:
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
        launch_args = [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-gpu',
            '--disable-dev-shm-usage',
        ]
        if headless:
            launch_args.append('--hide-scrollbars')

        launcher_name, channel = self._BROWSER_MAP.get(browser_type, ('chromium', None))
        launcher = getattr(self.pw, launcher_name, self.pw.chromium)
        launch_kwargs: Dict[str, Any] = {'headless': headless, 'args': launch_args}

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
            return await launcher.launch(**launch_kwargs)
        except Exception as e:
            err = str(e)
            if custom_path and "Executable doesn't exist" in err:
                raise RuntimeError(
                    f"自定义浏览器路径无法启动: {custom_path}，请检查是否选择了正确的可执行文件"
                ) from e
            if channel and "Chromium distribution" in err:
                raise RuntimeError(
                    f"未找到系统安装的 {channel} 浏览器，请确认已安装后再试"
                ) from e
            if "Executable doesn't exist" in err or "browserType.launch" in err:
                # 尝试自动安装 Playwright 自带浏览器后重试一次
                await asyncio.get_event_loop().run_in_executor(
                    None, self._install_browser, launcher_name
                )
                return await launcher.launch(**launch_kwargs)
            raise

    async def run(self):
        opts = self.options
        try:
            self.pw = await async_playwright().start()
            self.browser = await self._launch_browser(opts)
            viewport = {
                'width': int(opts.get('viewport_width', 1280)),
                'height': int(opts.get('viewport_height', 720)),
            }
            ctx_kwargs: Dict[str, Any] = {'viewport': viewport}
            if opts.get('color_scheme'):
                ctx_kwargs['color_scheme'] = opts['color_scheme']
            if opts.get('locale'):
                ctx_kwargs['locale'] = opts['locale']
            if opts.get('timezone'):
                ctx_kwargs['timezone_id'] = opts['timezone']
            if opts.get('user_agent'):
                ctx_kwargs['user_agent'] = opts['user_agent']
            self.context = await self.browser.new_context(**ctx_kwargs)
            self.page = await self.context.new_page()
            await self.page.expose_function('__geniusRecord', self._handle)
            await self.page.add_init_script(RECORDER_JS)
            self.page.on('close', lambda: asyncio.ensure_future(self._on_page_close()))

            url = opts.get('url') or 'about:blank'
            await self.page.goto(url)
            self.running = True
            self.started_event.set()
            logger.info(f"录制会话 {self.session_id} 浏览器已启动(headless={opts.get('headless', False)})，目标: {url}")

            # 保持会话，直到被停止或浏览器关闭
            while self.running and self.browser and self.browser.is_connected():
                await asyncio.sleep(1)
        except Exception as e:
            self.start_error = str(e)
            self.started_event.set()
            logger.error(f"录制会话 {self.session_id} 运行异常: {e}", exc_info=True)
        finally:
            await self._cleanup()

    async def _on_page_close(self):
        self.running = False

    async def _cleanup(self):
        try:
            if self.browser and self.browser.is_connected():
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.pw:
                await self.pw.stop()
        except Exception:
            pass
        self.running = False

    async def stop(self):
        self.running = False
        try:
            if self.browser and self.browser.is_connected():
                await self.browser.close()
        except Exception:
            pass

    async def set_assert_mode(self, mode: str):
        if self.page:
            await self.page.evaluate("window.__assertMode = arguments[0]", mode)

    async def set_pick_mode(self):
        self.pick_result = None
        if self.page:
            await self.page.evaluate("window.__pickMode = true")

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

    async def stop(self, session_id: int) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError('录制会话不存在或已结束')
        await session.stop()
        count = await session.count_steps()
        # 稍等浏览器回收
        await asyncio.sleep(1)
        return {
            'session_id': session_id,
            'test_case_id': session.test_case_id,
            'steps_count': count,
        }

    async def get_steps(self, session_id: int) -> List[Dict[str, Any]]:
        session = self.sessions.get(session_id)
        if not session:
            return []
        async with async_session_factory() as db:
            steps = await UITestStepCRUD(db).get_by_test_case_id(db, session.test_case_id)
            return [{
                'id': s.id,
                'step_number': s.step_number,
                'action_type': s.action_type,
                'element_id': s.element_id,
                'action_value': s.action_value,
                'assertion_type': s.assertion_type,
                'assertion_value': s.assertion_value,
                'description': s.description,
            } for s in steps]


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
                                  steps: List[Dict[str, Any]], source: str) -> Dict[str, Any]:
    async with async_session_factory() as db:
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

        tc = UITestCaseModel(
            ui_project_id=project_id,
            name=name or f"导入用例_{source}_{time.strftime('%Y%m%d_%H%M%S')}",
            description=f"从 {source} 导入生成的测试用例",
            priority='medium',
            created_by=user_id,
        )
        db.add(tc)
        await db.flush()
        tc_id = tc.id

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
                test_case_id=tc_id,
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
        return {'test_case_id': tc_id, 'steps_count': step_no}
