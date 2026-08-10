# -*- coding: utf-8 -*-
"""针对精准测试「查询报告采集进度」接口(get_report_progress)的代码覆盖率测试。

覆盖路径：
  1) 报告存在  -> _row_to_dict(report) + 返回 {"code":200, "data": {...}}
  2) 报告不存在 -> 返回 {"code":400, "message":"报告不存在", "data":None}
  3) 缺少 id -> 抛出 KeyError，由 controller 捕获返回 500

运行方式（生成 coverage.xml，供 GeniusQA 精准测试采集）：
  coverage run -m pytest tests/test_report_progress_coverage.py -v
  coverage xml -o coverage.xml
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.Ntesterc_module.Ntesterc_precision_test import service


def _make_row(values: dict) -> MagicMock:
    """构造一个 MagicMock，使其 _mapping 行为等价于 SQLAlchemy Result 行。"""
    row = MagicMock()
    mapping = dict(values)
    row._mapping = mapping
    return row


def _fake_session_with_rows(rows):
    """返回 mock 的 AsyncSession：execute 直接返回含 rows 的结果对象。"""
    session = AsyncMock()
    result = MagicMock()
    result.__iter__.return_value = iter(rows)
    session.execute.return_value = result
    return session


# ---------------------------------------------------------------------------
# 用例 1：报告存在（主分支）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_report_progress_found():
    progress_json = [
        {"step": 1, "name": "克隆仓库", "status": "completed", "detail": "ok"},
        {"step": 2, "name": "安装依赖", "status": "completed", "detail": "ok"},
        {"step": 3, "name": "执行 pytest", "status": "running", "detail": "50%"},
        {"step": 4, "name": "解析入库", "status": "pending", "detail": ""},
    ]
    row = _make_row({
        "id": 42,
        "name": "全量覆盖报告",
        "service_id": 1,
        "repo_id": 7,
        "coverage_type": 10,
        "coverage_rate": "62.5%",
        "status": "collecting",
        "progress": progress_json,
        "new_branches": "main",
        "new_last_commit_id": "abc123",
        "old_branches": None,
        "old_last_commit_id": None,
        "package_count": 10,
        "class_count": 50,
        "method_count": 200,
        "duration": 120,
    })
    session = _fake_session_with_rows([row])

    result = await service.get_report_progress(session, {"id": 42})

    assert result["code"] == 200
    assert result["data"]["id"] == 42
    assert result["data"]["name"] == "全量覆盖报告"
    assert result["data"]["status"] == "collecting"
    # 验证 progress JSON 列被正确解析为 Python 对象
    assert isinstance(result["data"]["progress"], list)
    assert result["data"]["progress"][2]["name"] == "执行 pytest"


# ---------------------------------------------------------------------------
# 用例 2：报告不存在（enabled_flag=1 但查无对应 id）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_report_progress_not_found():
    session = _fake_session_with_rows([])  # 空迭代 => 走 report is None 分支

    result = await service.get_report_progress(session, {"id": 999})

    assert result["code"] == 400
    assert result["message"] == "报告不存在"
    assert result["data"] is None


# ---------------------------------------------------------------------------
# 用例 3：缺少 id 字段（触发 KeyError）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_report_progress_missing_id():
    session = AsyncMock()

    with pytest.raises(KeyError):
        await service.get_report_progress(session, {})
