#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""浏览器自定义安装路径配置管理。

支持为 edge/chrome/firefox/safari 指定自定义可执行文件路径，
解决浏览器未安装在默认目录导致 Playwright/Selenium 找不到浏览器的问题。
"""
import json
import os
from pathlib import Path
from typing import Dict, Optional

from app.core.logger import logger


# 配置文件路径，放在 backend 根目录，避免和源码混在一起
_CONFIG_FILE = Path(__file__).resolve().parents[5] / "browser_paths.json"

# 支持的浏览器类型（统一命名）
_SUPPORTED_BROWSERS = {"edge", "chrome", "firefox", "safari", "chromium", "msedge", "webkit"}


def _normalize_browser_type(browser_type: Optional[str]) -> str:
    """统一浏览器命名，兼容旧值。"""
    if not browser_type:
        return "edge"
    bt = str(browser_type).strip().lower()
    mapping = {
        "msedge": "edge",
        "chromium": "chrome",
        "webkit": "safari",
    }
    return mapping.get(bt, bt)


def _load_config() -> Dict[str, str]:
    """读取配置文件，返回 browser_type -> path 映射。"""
    if not _CONFIG_FILE.exists():
        return {}
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning(f"browser_paths.json 格式异常，预期 dict，实际 {type(data)}")
            return {}
        return {k: str(v).strip() for k, v in data.items() if isinstance(v, (str,))}
    except Exception as e:
        logger.error(f"读取浏览器路径配置失败: {e}")
        return {}


def _save_config(config: Dict[str, str]) -> None:
    """保存配置文件。"""
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存浏览器路径配置失败: {e}")
        raise


def get_browser_path(browser_type: str) -> Optional[str]:
    """获取指定浏览器的自定义可执行文件路径，未配置返回 None。"""
    bt = _normalize_browser_type(browser_type)
    path = _load_config().get(bt)
    if path and os.path.exists(path):
        return path
    return path  # 即使文件不存在也返回，方便上层给出更精确提示


def get_all_browser_paths() -> Dict[str, str]:
    """获取所有已配置的自定义路径。"""
    return _load_config()


def set_browser_path(browser_type: str, executable_path: str) -> str:
    """保存浏览器自定义路径，返回统一后的浏览器类型。"""
    bt = _normalize_browser_type(browser_type)
    if bt not in _SUPPORTED_BROWSERS:
        raise ValueError(f"不支持的浏览器类型: {browser_type}")
    path = str(executable_path).strip()
    if not path:
        raise ValueError("可执行文件路径不能为空")
    # 统一路径分隔符
    path = os.path.normpath(path)
    config = _load_config()
    config[bt] = path
    _save_config(config)
    return bt


def remove_browser_path(browser_type: str) -> None:
    """删除指定浏览器的自定义路径。"""
    bt = _normalize_browser_type(browser_type)
    config = _load_config()
    if bt in config:
        del config[bt]
        _save_config(config)


def path_exists(browser_type: str) -> bool:
    """判断配置的自定义路径文件是否存在。"""
    path = get_browser_path(browser_type)
    return bool(path and os.path.exists(path))
