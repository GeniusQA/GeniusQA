#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: Rebort

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from .model import (
    NtestRepositoryModel,
    NtestCoverageReportModel,
    NtestCoverageDetailModel,
)
from .jacoco_parser import JaCoCoParser
from .cobertura_parser import CoberturaParser
from .istanbul_parser import IstanbulLcovParser, IstanbulParseError
from .go_parser import GoCoverageParser, GoCoverageParseError

# LLM + Skill 驱动预分析（延迟导入，避免循环依赖）
_LLM_SERVICE = None
_SkillsModel = None


def _get_llm_service():
    """延迟导入 LLM 服务"""
    global _LLM_SERVICE
    if _LLM_SERVICE is None:
        from app.api.v1.Ntesterc_module.Ntesterc_ai.conversation.llm_service import get_llm_service
        _LLM_SERVICE = get_llm_service
    return _LLM_SERVICE


def _get_skills_model():
    """延迟导入 Skills 模型"""
    global _SkillsModel
    if _SkillsModel is None:
        from app.api.v1.Ntesterc_module.Ntesterc_skills.model import ProjectSkillModel
        _SkillsModel = ProjectSkillModel
    return _SkillsModel


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a SQLAlchemy model instance to a plain dict.
    JSON columns from MySQL are sometimes returned as str; parse them."""
    import json
    d = row.__dict__.copy()
    d.pop("_sa_instance_state", None)
    # Ensure JSON columns are native Python types (not str)
    for key in ("progress",):
        val = d.get(key)
        if isinstance(val, str) and val:
            try:
                d[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ---------------------------------------------------------------------------
# JaCoCo CLI jar path — resolved relative to the backend root
# ---------------------------------------------------------------------------
def _get_jacoco_jar_path() -> str:
    """Return the absolute path to org.jacoco.cli.jar."""
    # service.py -> precision_test -> module -> v1 -> api -> app -> backend
    backend_root = Path(__file__).resolve().parents[5]
    jar = backend_root / "static" / "tools" / "org.jacoco.cli.jar"
    if not jar.exists():
        raise FileNotFoundError(
            f"org.jacoco.cli.jar not found at {jar}. "
            "Please place the jar under backend/static/tools/."
        )
    return str(jar)


class PrecisionTestService:
    """精准测试服务层"""

    # ------------------------------------------------------------------ #
    # Task 3.1 — Repository management methods                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def list_repositories(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """分页查询仓库列表"""
        service_id = body.get("service_id")
        name_filter = body.get("name", "")
        page = int(body.get("page", 1))
        page_size = int(body.get("pageSize", 20))

        stmt = (
            select(NtestRepositoryModel)
            .where(
                NtestRepositoryModel.service_id == service_id,
                NtestRepositoryModel.enabled_flag == 1,
            )
        )
        if name_filter:
            stmt = stmt.where(
                NtestRepositoryModel.name.like(f"%{name_filter}%")
            )

        # 按 id 倒序（最新创建的仓库在前）
        stmt = stmt.order_by(NtestRepositoryModel.id.desc())

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        # Paginate
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        content = [_row_to_dict(r) for r in rows]

        return {
            "content": content,
            "total": total,
            "page": page,
            "pageSize": page_size,
        }

    @staticmethod
    async def save_repository(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """新增或更新仓库（支持 Git URL 或本地目录二选一）"""
        repo_id = body.get("id")

        # 校验 html_url / local_path 至少填一个
        html_url = (body.get("html_url") or "").strip()
        local_path = (body.get("local_path") or "").strip()
        if not html_url and not local_path:
            return {"code": 400, "message": "仓库地址与本地目录至少填写一项", "data": None}

        if repo_id:
            # UPDATE
            result = await db.execute(
                select(NtestRepositoryModel).where(
                    NtestRepositoryModel.id == repo_id,
                    NtestRepositoryModel.enabled_flag == 1,
                )
            )
            repo = result.scalar_one_or_none()
            if not repo:
                return {"code": 400, "message": "仓库不存在", "data": None}

            repo.name = body.get("name", repo.name)
            # 切换来源类型时，显式清空另一方字段（前端传空字符串表示清除）
            repo.html_url = html_url if html_url else None
            repo.local_path = local_path if local_path else None
            repo.description = body.get("description", repo.description)
            repo.service_id = body.get("service_id", repo.service_id)
            repo.service_host = body.get("service_host", repo.service_host)
            repo.jacoco_port = int(body.get("jacoco_port") or repo.jacoco_port or 6300)
            repo.lang_type = body.get("lang_type", repo.lang_type) or "java"
            repo.updated_by = user_id
            repo.updation_date = datetime.now()
            await db.flush()
            return _row_to_dict(repo)
        else:
            # INSERT
            repo = NtestRepositoryModel(
                name=body.get("name"),
                html_url=html_url or None,
                local_path=local_path or None,
                description=body.get("description"),
                service_id=body.get("service_id"),
                service_host=body.get("service_host"),
                jacoco_port=int(body.get("jacoco_port") or 6300),
                lang_type=body.get("lang_type") or "java",
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(repo)
            await db.flush()
            await db.refresh(repo)
            return _row_to_dict(repo)

    @staticmethod
    async def delete_repository(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """逻辑删除仓库"""
        repo_id = body.get("id")

        result = await db.execute(
            select(NtestRepositoryModel).where(
                NtestRepositoryModel.id == repo_id,
                NtestRepositoryModel.enabled_flag == 1,
            )
        )
        repo = result.scalar_one_or_none()
        if not repo:
            return {"code": 400, "message": "仓库不存在", "data": None}

        repo.enabled_flag = 0
        repo.updated_by = user_id
        repo.updation_date = datetime.now()
        await db.flush()
        return {"code": 0, "message": "删除成功", "data": None}

    # ------------------------------------------------------------------ #
    # Task 3.2 — Coverage report management methods                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def list_reports(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """分页查询覆盖率报告列表"""
        service_id = body.get("service_id")
        name_filter = body.get("name", "")
        page = int(body.get("page", 1))
        page_size = int(body.get("pageSize", 20))

        stmt = (
            select(NtestCoverageReportModel)
            .where(
                NtestCoverageReportModel.service_id == service_id,
                NtestCoverageReportModel.enabled_flag == 1,
            )
            .order_by(NtestCoverageReportModel.id.desc())
        )
        if name_filter:
            stmt = stmt.where(
                NtestCoverageReportModel.name.like(f"%{name_filter}%")
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        content = [_row_to_dict(r) for r in rows]

        return {
            "content": content,
            "total": total,
            "page": page,
            "pageSize": page_size,
        }

    @staticmethod
    async def get_report(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Optional[Dict[str, Any]]:
        """按 id 查询单条报告"""
        report_id = body.get("id")
        result = await db.execute(
            select(NtestCoverageReportModel).where(
                NtestCoverageReportModel.id == report_id,
                NtestCoverageReportModel.enabled_flag == 1,
            )
        )
        report = result.scalar_one_or_none()
        if not report:
            return {"code": 400, "message": "报告不存在", "data": None}
        d = _row_to_dict(report)
        # 关联查询仓库的 lang_type，供前端判断是否显示上传按钮
        repo_result = await db.execute(
            select(NtestRepositoryModel.lang_type).where(
                NtestRepositoryModel.id == report.repo_id,
                NtestRepositoryModel.enabled_flag == 1,
            )
        )
        repo_row = repo_result.scalar_one_or_none()
        d["lang_type"] = repo_row if repo_row else "java"
        return d

    @staticmethod
    async def delete_report(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """逻辑删除覆盖率报告"""
        report_id = body.get("id")
        result = await db.execute(
            select(NtestCoverageReportModel).where(
                NtestCoverageReportModel.id == report_id,
                NtestCoverageReportModel.enabled_flag == 1,
            )
        )
        report = result.scalar_one_or_none()
        if not report:
            return {"code": 400, "message": "报告不存在", "data": None}

        report.enabled_flag = 0
        report.updated_by = user_id
        report.updation_date = datetime.now()
        await db.flush()
        return {"code": 0, "message": "删除成功", "data": None}

    @staticmethod
    async def trigger_coverage(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """触发覆盖率分析，创建报告记录"""
        coverage_type = body.get("coverage_type")
        old_branch = body.get("old_branch", "") or ""
        repo_id = body.get("repo_id")
        new_branch = body.get("new_branch", "")

        # Validate: incremental mode requires old_branch
        if coverage_type == 20 and not old_branch.strip():
            raise HTTPException(
                status_code=422,
                detail="增量模式下旧分支不能为空",
            )

        # Validate repo exists
        repo_result = await db.execute(
            select(NtestRepositoryModel).where(
                NtestRepositoryModel.id == repo_id,
                NtestRepositoryModel.enabled_flag == 1,
            )
        )
        repo = repo_result.scalar_one_or_none()
        if not repo:
            return {"code": 400, "message": "仓库不存在", "data": None}

        # Derive report name（先用 repo_id 占位，拿到 report id 后修正为 report_{id}_{branch}）
        _report_name_max_len = 64
        name = (body.get("name") or f"report_0_{new_branch}")[:_report_name_max_len]

        # Create coverage report record
        report = NtestCoverageReportModel(
            name=name,
            service_id=repo.service_id,
            repo_id=repo_id,
            coverage_type=coverage_type,
            new_branches=new_branch,
            old_branches=old_branch if old_branch.strip() else None,
            package_count=0,
            class_count=0,
            method_count=0,
            coverage_rate="0.0%",
            status="collecting" if (repo.lang_type or "java") == "python" else "pending",
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(report)
        await db.flush()
        await db.refresh(report)

        # 用实际 report id 修正名称
        if not body.get("name"):
            report.name = f"report_{report.id}_{new_branch}"[:_report_name_max_len]

        # Python 仓库：创建报告后自动后台采集覆盖率（clone 分支 -> 跑 pytest -> 解析回填）
        if (repo.lang_type or "java") == "python":
            _coverage_repo_url = repo.local_path or repo.html_url
            asyncio.create_task(
                PrecisionTestService.run_python_coverage(
                    report.id, _coverage_repo_url, new_branch or "main", user_id,
                    coverage_type=coverage_type, old_branch=old_branch or "",
                )
            )

        status_val = report.status
        return {
            "id": report.id,
            "status": status_val,
            "coverage_rate": report.coverage_rate,
            "message": (
                "报告已创建，Python 仓库正在后台自动采集覆盖率，请稍后刷新查看结果"
                if status_val == "collecting"
                else "报告已创建，等待手动上传覆盖率 XML 或 JaCoCo dump"
            ),
        }

    # ------------------------------------------------------------------ #
    # Task 3.3 — Coverage detail query methods                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def get_coverage_detail(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Any:
        """根据 el_type 返回不同层级的覆盖率详情"""
        el_type = body.get("el_type")
        report_id = body.get("report_id")

        if el_type == "report":
            # GROUP BY package_name, SUM all counter fields
            stmt = (
                select(
                    NtestCoverageDetailModel.package_name,
                    func.sum(NtestCoverageDetailModel.branch_missed).label("branch_missed"),
                    func.sum(NtestCoverageDetailModel.branch_covered).label("branch_covered"),
                    func.sum(NtestCoverageDetailModel.instruction_missed).label("instruction_missed"),
                    func.sum(NtestCoverageDetailModel.instruction_covered).label("instruction_covered"),
                    func.sum(NtestCoverageDetailModel.line_missed).label("line_missed"),
                    func.sum(NtestCoverageDetailModel.line_covered).label("line_covered"),
                    func.sum(NtestCoverageDetailModel.method_missed).label("method_missed"),
                    func.sum(NtestCoverageDetailModel.method_covered).label("method_covered"),
                    func.sum(NtestCoverageDetailModel.class_missed).label("class_missed"),
                    func.sum(NtestCoverageDetailModel.class_covered).label("class_covered"),
                )
                .where(
                    NtestCoverageDetailModel.report_id == report_id,
                    NtestCoverageDetailModel.enabled_flag == 1,
                )
                .group_by(NtestCoverageDetailModel.package_name)
            )
            result = await db.execute(stmt)
            rows = result.all()
            return [
                {
                    "package_name": r.package_name,
                    "branch_missed": r.branch_missed or 0,
                    "branch_covered": r.branch_covered or 0,
                    "instruction_missed": r.instruction_missed or 0,
                    "instruction_covered": r.instruction_covered or 0,
                    "line_missed": r.line_missed or 0,
                    "line_covered": r.line_covered or 0,
                    "method_missed": r.method_missed or 0,
                    "method_covered": r.method_covered or 0,
                    "class_missed": r.class_missed or 0,
                    "class_covered": r.class_covered or 0,
                }
                for r in rows
            ]

        elif el_type == "package":
            package_name = body.get("package_name")
            stmt = (
                select(NtestCoverageDetailModel)
                .where(
                    NtestCoverageDetailModel.report_id == report_id,
                    NtestCoverageDetailModel.package_name == package_name,
                    NtestCoverageDetailModel.enabled_flag == 1,
                )
            )
            result = await db.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "class_name": r.class_name,
                    "package_name": r.package_name,
                    "branch_missed": r.branch_missed or 0,
                    "branch_covered": r.branch_covered or 0,
                    "instruction_missed": r.instruction_missed or 0,
                    "instruction_covered": r.instruction_covered or 0,
                    "line_missed": r.line_missed or 0,
                    "line_covered": r.line_covered or 0,
                    "method_missed": r.method_missed or 0,
                    "method_covered": r.method_covered or 0,
                    "class_missed": r.class_missed or 0,
                    "class_covered": r.class_covered or 0,
                }
                for r in rows
            ]

        elif el_type == "class":
            class_id = body.get("class_id")
            result = await db.execute(
                select(NtestCoverageDetailModel).where(
                    NtestCoverageDetailModel.id == class_id,
                    NtestCoverageDetailModel.enabled_flag == 1,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                return {"code": 400, "message": "类数据不存在", "data": None}
            return {
                "id": row.id,
                "class_name": row.class_name,
                "package_name": row.package_name,
                "class_file_content": row.class_file_content,
                "class_source_path": row.class_source_path,
                "class_md5": row.class_md5,
                "methods": row.methods or [],
            }

        else:
            return {"code": 400, "message": f"不支持的 el_type: {el_type}", "data": None}

    # ------------------------------------------------------------------ #
    # Task 3.4 — JaCoCo XML upload/parse method                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _detect_coverage_format(file_bytes: bytes) -> str:
        """嗅探覆盖率文件格式，返回: jacoco / cobertura / lcov / go / unknown。
        - jacoco:    JaCoCo XML (<report> 根)
        - cobertura: Cobertura XML (<coverage> 根，Python coverage.py / nyc --reporter=cobertura)
        - lcov:      Istanbul (nyc/c8/jest) 文本
        - go:        go test -coverprofile 文本
        """
        # 1) 优先尝试 XML 解析
        try:
            root = ET.fromstring(file_bytes)
            if root.tag == "report":
                return "jacoco"
            if root.tag == "coverage":
                # Python cobertura 与 Istanbul cobertura 均为 <coverage>，统一走 cobertura 解析
                return "cobertura"
        except ET.ParseError:
            pass

        # 2) 文本格式（lcov / go）
        text = file_bytes.decode("utf-8", errors="replace")
        stripped = text.lstrip()
        if stripped.startswith("mode:") or re.match(r"^mode:\s*(set|count|atomic)", stripped):
            return "go"
        if "SF:" in text and ("end_of_record" in text or "DA:" in text):
            return "lcov"
        return "unknown"

    @staticmethod
    async def upload_jacoco_xml(
        db: AsyncSession,
        file_bytes: bytes,
        report_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """解析覆盖率文件（自动识别 JaCoCo / Cobertura / Istanbul(lcov) / Go）并写入数据库。"""
        fmt = PrecisionTestService._detect_coverage_format(file_bytes)

        # ---- Istanbul (nyc / c8 / jest): lcov 文本 ----
        if fmt == "lcov":
            try:
                result = IstanbulLcovParser().parse(
                    file_bytes.decode("utf-8", errors="replace")
                )
            except IstanbulParseError as e:
                raise HTTPException(status_code=400, detail=f"无效的 Istanbul lcov 文件: {e}")
            return await PrecisionTestService._ingest_line_based(db, result, report_id, user_id)

        # ---- Go: go test -coverprofile 文本 ----
        if fmt == "go":
            try:
                result = GoCoverageParser().parse(
                    file_bytes.decode("utf-8", errors="replace")
                )
            except GoCoverageParseError as e:
                raise HTTPException(status_code=400, detail=f"无效的 Go coverage 文件: {e}")
            return await PrecisionTestService._ingest_line_based(db, result, report_id, user_id)

        # ---- Python coverage.py / Istanbul cobertura XML ----
        if fmt == "cobertura":
            return await PrecisionTestService.ingest_cobertura(db, file_bytes, report_id, user_id)

        # ---- JaCoCo XML ----
        if fmt == "jacoco":
            parser = JaCoCoParser()

        # Validate
        if not parser.validate(file_bytes):
            raise HTTPException(status_code=400, detail="无效的 JaCoCo XML 文件")

        # Parse
        parse_result = parser.parse(file_bytes)

        # Bulk insert NtestCoverageDetailModel records (one per class)
        for pkg in parse_result.packages:
            for cls in pkg.classes:
                # Build method list
                methods_list: List[Dict[str, Any]] = []
                for method in cls.methods:
                    _mc = method.counters
                    method_entry: Dict[str, Any] = {
                        "name": method.name,
                        "params_string": method.desc,
                        "offset": method.offset,
                        "lines_covered_status": method.lines_covered_status,
                        "branch_missed": _mc["BRANCH"].missed if "BRANCH" in _mc else 0,
                        "branch_covered": _mc["BRANCH"].covered if "BRANCH" in _mc else 0,
                        "instruction_missed": _mc["INSTRUCTION"].missed if "INSTRUCTION" in _mc else 0,
                        "instruction_covered": _mc["INSTRUCTION"].covered if "INSTRUCTION" in _mc else 0,
                        "line_missed": _mc["LINE"].missed if "LINE" in _mc else 0,
                        "line_covered": _mc["LINE"].covered if "LINE" in _mc else 0,
                        "complexity_missed": _mc["COMPLEXITY"].missed if "COMPLEXITY" in _mc else 0,
                        "complexity_covered": _mc["COMPLEXITY"].covered if "COMPLEXITY" in _mc else 0,
                        "method_missed": _mc["METHOD"].missed if "METHOD" in _mc else 0,
                        "method_covered": _mc["METHOD"].covered if "METHOD" in _mc else 0,
                    }
                    methods_list.append(method_entry)

                # Class-level counters from cls.counters
                branch_c = cls.counters.get("BRANCH")
                instruction_c = cls.counters.get("INSTRUCTION")
                line_c = cls.counters.get("LINE")
                method_c = cls.counters.get("METHOD")
                class_c = cls.counters.get("CLASS")

                detail = NtestCoverageDetailModel(
                    report_id=report_id,
                    package_name=pkg.name,
                    class_name=cls.name,
                    class_file_content=cls.file_content,
                    class_source_path=cls.source_path,
                    class_md5=cls.md5,
                    methods=methods_list,
                    branch_missed=branch_c.missed if branch_c else 0,
                    branch_covered=branch_c.covered if branch_c else 0,
                    instruction_missed=instruction_c.missed if instruction_c else 0,
                    instruction_covered=instruction_c.covered if instruction_c else 0,
                    line_missed=line_c.missed if line_c else 0,
                    line_covered=line_c.covered if line_c else 0,
                    method_missed=method_c.missed if method_c else 0,
                    method_covered=method_c.covered if method_c else 0,
                    class_missed=class_c.missed if class_c else 0,
                    class_covered=class_c.covered if class_c else 0,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(detail)

        await db.flush()

        # Update NtestCoverageReportModel stats
        report_result = await db.execute(
            select(NtestCoverageReportModel).where(
                NtestCoverageReportModel.id == report_id,
            )
        )
        report = report_result.scalar_one_or_none()
        if report:
            report.package_count = parse_result.package_count
            report.class_count = parse_result.class_count
            report.method_count = parse_result.method_count
            report.coverage_rate = parse_result.coverage_rate
            report.status = "completed"
            report.updated_by = user_id
            report.updation_date = datetime.now()

        await db.flush()
        return {
            "package_count": parse_result.package_count,
            "class_count": parse_result.class_count,
            "method_count": parse_result.method_count,
            "coverage_rate": parse_result.coverage_rate,
        }

        raise HTTPException(
            status_code=400,
            detail="不支持的覆盖率文件格式（仅支持 JaCoCo XML / Cobertura XML / Istanbul lcov / Go coverage.out）",
        )

    # ------------------------------------------------------------------ #
    # JaCoCo Dump — call org.jacoco.cli.jar to pull .exec from agent      #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def jacoco_dump(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """
        通过 org.jacoco.cli.jar dump 命令从运行中的 JaCoCo agent 拉取覆盖率数据，
        然后生成 XML 报告并解析入库。

        body 参数:
          - report_id: int  (必填) 关联的覆盖率报告 ID
          - address: str    (可选) agent 地址，默认 localhost
          - port: int       (可选) agent 端口，默认 6300
          - reset: bool     (可选) dump 后是否重置 agent 数据，默认 False
        """
        report_id = body.get("report_id")
        address = body.get("address") or "localhost"
        port = int(body.get("port") or 6300)
        reset = bool(body.get("reset", False))

        if not report_id:
            raise HTTPException(status_code=422, detail="report_id 不能为空")

        # Verify report exists
        report_result = await db.execute(
            select(NtestCoverageReportModel).where(
                NtestCoverageReportModel.id == report_id,
                NtestCoverageReportModel.enabled_flag == 1,
            )
        )
        report = report_result.scalar_one_or_none()
        if not report:
            raise HTTPException(status_code=404, detail="报告不存在")

        try:
            jar_path = _get_jacoco_jar_path()
        except FileNotFoundError as e:
            raise HTTPException(status_code=500, detail=str(e))

        with tempfile.TemporaryDirectory() as tmpdir:
            exec_file = os.path.join(tmpdir, f"jacoco_{report_id}.exec")
            xml_file = os.path.join(tmpdir, f"jacoco_{report_id}.xml")

            # Step 1: dump .exec from running agent
            dump_cmd = [
                "java", "-jar", jar_path,
                "dump",
                "--address", address,
                "--port", str(port),
                "--destfile", exec_file,
                "--quiet",
            ]
            if reset:
                dump_cmd.append("--reset")

            proc = await asyncio.create_subprocess_exec(
                *dump_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                raise HTTPException(
                    status_code=502,
                    detail=f"JaCoCo dump 失败（address={address}:{port}）: {err_msg or 'unknown error'}",
                )

            if not os.path.exists(exec_file):
                raise HTTPException(
                    status_code=502,
                    detail=f"dump 命令执行成功但未生成 .exec 文件，请检查 agent 是否正在运行",
                )

            # Step 2: generate XML report from .exec
            # Note: --classfiles is not required for basic XML generation from .exec
            # The XML will contain raw counter data without source mapping
            report_cmd = [
                "java", "-jar", jar_path,
                "report", exec_file,
                "--xml", xml_file,
                "--quiet",
            ]

            proc2 = await asyncio.create_subprocess_exec(
                *report_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout2, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=60)

            if proc2.returncode != 0:
                err_msg2 = stderr2.decode("utf-8", errors="replace").strip()
                raise HTTPException(
                    status_code=502,
                    detail=f"JaCoCo report 生成失败: {err_msg2 or 'unknown error'}",
                )

            if not os.path.exists(xml_file):
                raise HTTPException(
                    status_code=502,
                    detail="report 命令执行成功但未生成 XML 文件",
                )

            # Step 3: parse XML and write to DB
            with open(xml_file, "rb") as f:
                xml_bytes = f.read()

            result = await PrecisionTestService.upload_jacoco_xml(
                db, xml_bytes, report_id, user_id
            )
            return {
                **result,
                "address": address,
                "port": port,
                "message": f"成功从 {address}:{port} 拉取覆盖率数据并解析入库",
            }

    # ------------------------------------------------------------------ #
    # Cobertura (Python) — parse & store                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _ingest_line_based(
        db: AsyncSession,
        parse_result: Any,
        report_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """将 line/branch 粒度的解析结果（Cobertura / Istanbul / Go）写入数据库。

        三类格式共用同一套 CoberturaResult 结构（packages/classes/methods），
        因此统一走同一个入库逻辑，避免重复代码。
        """
        for pkg in parse_result.packages:
            for cls in pkg.classes:
                # 方法级汇总（兼容前端 JaCoCo 方法结构）
                methods_list: List[Dict[str, Any]] = []
                for m in cls.methods:
                    methods_list.append({
                        "name": m.name,
                        "params_string": "",
                        "offset": 0,
                        "lines_covered_status": {},
                        "branch_missed": m.branch_missed,
                        "branch_covered": m.branch_covered,
                        "instruction_missed": 0,
                        "instruction_covered": 0,
                        "line_missed": m.line_missed,
                        "line_covered": m.line_covered,
                        "complexity_missed": 0,
                        "complexity_covered": 0,
                        "method_missed": 0,
                        "method_covered": 1 if m.line_covered > 0 else 0,
                    })

                detail = NtestCoverageDetailModel(
                    report_id=report_id,
                    package_name=pkg.name,
                    class_name=cls.name,
                    class_file_content="",  # 行级格式不在此嵌入源码
                    class_source_path=cls.filename,
                    class_md5=None,
                    methods=methods_list,
                    branch_missed=cls.branch_missed,
                    branch_covered=cls.branch_covered,
                    instruction_missed=0,
                    instruction_covered=0,
                    line_missed=cls.line_missed,
                    line_covered=cls.line_covered,
                    method_missed=sum(1 for m in cls.methods if m.line_covered == 0),
                    method_covered=sum(1 for m in cls.methods if m.line_covered > 0),
                    class_missed=0 if cls.line_covered > 0 else 1,
                    class_covered=1 if cls.line_covered > 0 else 0,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(detail)

        await db.flush()

        report_result = await db.execute(
            select(NtestCoverageReportModel).where(
                NtestCoverageReportModel.id == report_id,
            )
        )
        report = report_result.scalar_one_or_none()
        if report:
            report.package_count = parse_result.package_count
            report.class_count = parse_result.class_count
            report.method_count = parse_result.method_count
            report.coverage_rate = parse_result.coverage_rate
            report.status = "completed"
            report.updated_by = user_id
            report.updation_date = datetime.now()

        await db.flush()
        return {
            "package_count": parse_result.package_count,
            "class_count": parse_result.class_count,
            "method_count": parse_result.method_count,
            "coverage_rate": parse_result.coverage_rate,
        }

    @staticmethod
    async def ingest_cobertura(
        db: AsyncSession,
        file_bytes: bytes,
        report_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """解析 Python coverage.py 产出的 Cobertura XML 并写入数据库"""
        parser = CoberturaParser()
        if not parser.validate(file_bytes):
            raise HTTPException(status_code=400, detail="无效的 Cobertura XML 文件")
        parse_result = parser.parse(file_bytes)
        return await PrecisionTestService._ingest_line_based(db, parse_result, report_id, user_id)

    # ------------------------------------------------------------------ #
    # 启动恢复：将残留的 collecting 报告标记为 failed                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def recover_stale_collecting_reports() -> int:
        """后端启动时，将状态仍为 collecting 的报告标记为 failed（后台任务已被重启杀死）。
        返回修复的报告数量。"""
        from app.infra.db.sqlalchemy import async_session_factory
        try:
            async with async_session_factory() as db_sess:
                result = await db_sess.execute(
                    update(NtestCoverageReportModel)
                    .where(
                        NtestCoverageReportModel.status == 'collecting',
                        NtestCoverageReportModel.enabled_flag == 1,
                    )
                    .values(status='failed', updation_date=datetime.now())
                )
                await db_sess.commit()
                count = result.rowcount
                if count > 0:
                    logger.warning(f"[coverage-recovery] 已将 {count} 条残留的 collecting 报告标记为 failed")
                return count
        except Exception as e:
            logger.error(f"[coverage-recovery] 恢复失败: {e}")
            return 0

    # ------------------------------------------------------------------ #
    # Python 自动化采集：clone 分支 -> 安装依赖 -> 跑 pytest 覆盖率 -> 回填   #
    # ------------------------------------------------------------------ #

    _COV_STEPS = [
        {"step": 1, "name": "克隆代码仓库", "status": "pending", "detail": ""},
        {"step": 2, "name": "安装测试依赖", "status": "pending", "detail": ""},
        {"step": 3, "name": "运行覆盖率采集", "status": "pending", "detail": ""},
        {"step": 4, "name": "解析覆盖率报告文件并入库", "status": "pending", "detail": ""},
    ]

    @staticmethod
    async def _update_progress(
        report_id: int,
        step_index: int,
        status: str,
        detail: str = "",
    ) -> None:
        """更新报告的采集进度到数据库。"""
        from app.infra.db.sqlalchemy import async_session_factory

        steps = [dict(s) for s in PrecisionTestService._COV_STEPS]
        for i in range(step_index):
            steps[i]["status"] = "completed"
        steps[step_index]["status"] = status
        if detail:
            steps[step_index]["detail"] = detail
        try:
            async with async_session_factory() as db_sess:
                r = (await db_sess.execute(
                    select(NtestCoverageReportModel).where(
                        NtestCoverageReportModel.id == report_id
                    )
                )).scalar_one_or_none()
                if r:
                    r.progress = steps
                    await db_sess.commit()
        except Exception as e:
            logger.warning(f"[progress] report={report_id} 更新进度失败: {e}")

    @staticmethod
    async def run_python_coverage(
        report_id: int,
        repo_url: str,
        branch: str,
        user_id: int,
        coverage_type: int = 10,
        old_branch: str = "",
    ) -> None:
        """
        后台任务：自动为 Python 仓库采集代码覆盖率。
        每步更新进度到数据库，前端可轮询查看。

        :param coverage_type: 覆盖类型 10=全量 20=增量
        :param old_branch: 增量模式下的旧分支名
        """
        from app.infra.db.sqlalchemy import async_session_factory
        import time as _time

        _start_ts = _time.time()
        workdir = tempfile.mkdtemp(prefix="cov_py_")
        try:
            logger.info(f"[local coverage] 开始为 report={report_id} 采集分支 {branch} ({repo_url})")

            # Step 1: 获取源码（Git URL → clone；本地目录 → 复制/直接使用）
            is_local = os.path.isdir(repo_url)
            if is_local:
                await PrecisionTestService._update_progress(
                    report_id, 0, "running", f"正在使用本地目录: {repo_url}"
                )
                # 本地目录：复制到 workdir 避免污染原目录
                import shutil
                try:
                    shutil.copytree(repo_url, workdir, symlinks=True, dirs_exist_ok=True)
                except Exception as copy_err:
                    await PrecisionTestService._update_progress(
                        report_id, 0, "failed", f"复制本地目录失败: {str(copy_err)[:200]}"
                    )
                    raise RuntimeError(f"shutil.copytree 失败: {copy_err}")
            else:
                await PrecisionTestService._update_progress(report_id, 0, "running", f"正在克隆 {branch} 分支...")
                rc, _, err = await PrecisionTestService._run_cmd(
                    ["git", "clone", "--depth", "1", "-b", branch, repo_url, workdir],
                    cwd=None, timeout=180,
                )
                if rc != 0:
                    await PrecisionTestService._update_progress(
                        report_id, 0, "failed", f"克隆失败: {err.strip()[:200]}"
                    )
                    raise RuntimeError(f"git clone 失败: {err.strip()}")

            _, latest_commit, _ = await PrecisionTestService._run_cmd(
                ["git", "log", "-1", "--format=%H"],
                cwd=workdir, timeout=30,
            )
            latest_commit = latest_commit.strip()
            if latest_commit:
                async with async_session_factory() as db_sess:
                    r = (await db_sess.execute(
                        select(NtestCoverageReportModel).where(
                            NtestCoverageReportModel.id == report_id
                        )
                    )).scalar_one_or_none()
                    if r:
                        r.new_last_commit_id = latest_commit
                        await db_sess.commit()
            await PrecisionTestService._update_progress(
                report_id, 0, "completed",
                f"已克隆 {branch} 分支，commit: {latest_commit[:12] if latest_commit else '?'}"
            )

            py = sys.executable

            # Step 2: 安装依赖
            await PrecisionTestService._update_progress(
                report_id, 1, "running", "正在安装 coverage / pytest..."
            )
            await PrecisionTestService._run_cmd(
                [py, "-m", "pip", "install", "-q", "coverage", "pytest"],
                cwd=workdir, timeout=600,
            )
            req_file = os.path.join(workdir, "requirements.txt")
            req_detail = ""
            if os.path.exists(req_file):
                req_detail = "检测到 requirements.txt，正在安装项目依赖..."
                await PrecisionTestService._update_progress(
                    report_id, 1, "running", req_detail
                )
                await PrecisionTestService._run_cmd(
                    [py, "-m", "pip", "install", "-q", "-r", req_file],
                    cwd=workdir, timeout=600,
                )
                req_detail += " 已完成"
            await PrecisionTestService._update_progress(
                report_id, 1, "completed", req_detail or "基础工具已安装"
            )

            # Step 3: 运行覆盖率
            await PrecisionTestService._update_progress(
                report_id, 2, "running", "正在执行 coverage run -m pytest..."
            )
            # --source 限定采集范围；--omit 必须用逗号分隔的单个字符串，
            # 否则 coverage 会把后续 pattern 当作 pytest 的位置参数（测试路径），
            # 导致 "No file to run: '*\\test_*.py'" 错误。
            omit_patterns = ",".join([
                "*/tests/*",
                "*/test_*.py",
                "*/__pycache__/*",
                "*/.venv/*",
                "*/venv/*",
                "setup.py",
                "*/conftest.py",
            ])
            # 跳过集成/健康检查类测试（依赖外部 DB/Redis/后端，无外部依赖环境下必失败），
            # 避免它们导致 pytest 整体 exit_code=1、coverage.xml 无法生成。
            # 同时用 --override-ini=addopts= 清除目标项目自身 pytest.ini/setup.cfg 中的
            # 可能破坏采集的配置（如强制的 --cov 插件、严格 addopts 等）。
            pytest_args = [
                py, "-m", "coverage", "run",
                "--source", "./",
                "--omit", omit_patterns,
                "-m", "pytest", "--tb=short", "-rA",
                "--continue-on-collection-errors",
                "--override-ini=addopts=",
                "--ignore-glob=**/test_health*.py",
                "--ignore-glob=**/tests/integration/**",
                "--ignore-glob=**/integration/**",
                "--ignore-glob=**/test_integration*.py",
                ".",
            ]
            rc, out, err = await PrecisionTestService._run_cmd(
                pytest_args,
                cwd=workdir, timeout=900,
            )
            # 记录完整输出到日志和进度
            out_summary = (out or "")[-800:]
            err_summary = (err or "")[-800:]
            logger.info(f"[local coverage] report={report_id} pytest exit_code={rc}, stdout={out_summary}, stderr={err_summary}")
            # 将 pytest 输出写入进度详情，前端可见
            progress_detail = f"pytest exit_code={rc}"
            if out:
                progress_detail += f"\nstdout: {out_summary[:300]}"
            if err:
                progress_detail += f"\nstderr: {err_summary[:300]}"
            await PrecisionTestService._update_progress(report_id, 2, "running", progress_detail)

            xml_path = os.path.join(workdir, "coverage.xml")
            cov_data_path = os.path.join(workdir, ".coverage")

            # 关键修复：coverage.py 在 pytest 返回非零退出码时默认不会自动生成
            # coverage.xml，但 .coverage 数据文件通常已经写好。只要 .coverage 存在，
            # 就强制执行 `coverage xml` 导出，使部分测试失败不再阻断覆盖率采集。
            if not os.path.exists(xml_path):
                if os.path.exists(cov_data_path):
                    await PrecisionTestService._update_progress(
                        report_id, 2, "running", "检测到 .coverage 数据，尝试导出 XML..."
                    )
                    rc2, out2, err2 = await PrecisionTestService._run_cmd(
                        [py, "-m", "coverage", "xml", "-o", "coverage.xml"],
                        cwd=workdir, timeout=300,
                    )
                    logger.info(f"[local coverage] report={report_id} coverage xml exit_code={rc2}, err={(err2 or '')[:300]}")
                    if not os.path.exists(xml_path):
                        # xml 导出仍失败，记录详细错误便于排查
                        await PrecisionTestService._update_progress(
                            report_id, 2, "running",
                            f"coverage xml 导出失败(exit={rc2}): {(err2 or out2 or '')[:300]}"
                        )
                else:
                    # 兜底：.coverage 也不存在，尝试用 combine + xml 强制生成
                    await PrecisionTestService._update_progress(
                        report_id, 2, "running", "尝试 coverage combine + xml 强制导出..."
                    )
                    await PrecisionTestService._run_cmd(
                        [py, "-m", "coverage", "combine"],
                        cwd=workdir, timeout=120,
                    )
                    rc3, out3, err3 = await PrecisionTestService._run_cmd(
                        [py, "-m", "coverage", "xml", "-o", "coverage.xml"],
                        cwd=workdir, timeout=300,
                    )
                    logger.info(f"[local coverage] report={report_id} coverage xml(combine) exit_code={rc3}, err={(err3 or '')[:300]}")

            if not os.path.exists(xml_path):
                # 同时用 stdout 和 stderr 构建错误信息，不再出现"(无错误输出)"
                combined_err = (err or "").strip() or (out or "").strip() or "(无输出)"
                err_info = combined_err[:500]
                # 判断是否为集成测试/依赖缺失导致的失败
                is_integration_fail = any(kw in (out or "").lower() + (err or "").lower()
                                           for kw in ["importerror", "connectionrefused",
                                                      "modulenotfound", "attributeerror",
                                                      "asyncclient", "asgitransport"])
                hint = ""
                if is_integration_fail:
                    hint = "\n提示：测试失败可能是因为集成测试依赖外部服务（数据库/Redis/后端服务）。建议：1) 将集成测试移至 tests/integration/ 并在 .coveragerc 中排除；2) 或确保测试可在无外部依赖环境下运行。"
                await PrecisionTestService._update_progress(
                    report_id, 2, "failed",
                    f"未生成 coverage.xml。pytest exit_code={rc}，错误: {err_info}{hint}"
                )
                raise RuntimeError(f"未生成 coverage.xml。pytest exit_code={rc}, 错误: {err_info}{hint}")

            # 注意：pytest 失败（exit_code != 0）但已成功生成 coverage.xml 时，
            # 依然视为采集成功（覆盖率反映的是已执行代码的覆盖情况）。
            if rc != 0:
                await PrecisionTestService._update_progress(
                    report_id, 2, "completed",
                    f"pytest 部分测试失败(exit_code={rc})，但覆盖率数据已成功采集并导出"
                )
            else:
                await PrecisionTestService._update_progress(
                    report_id, 2, "completed", f"pytest 执行完毕，exit code={rc}"
                )

            # Step 4: 解析并回填
            await PrecisionTestService._update_progress(
                report_id, 3, "running", "正在解析 coverage.xml 并写入数据库..."
            )
            with open(xml_path, "rb") as f:
                xml_bytes = f.read()

            async with async_session_factory() as db:
                await PrecisionTestService.ingest_cobertura(db, xml_bytes, report_id, user_id)
                await db.commit()
            await PrecisionTestService._update_progress(
                report_id, 3, "completed", "解析入库完成"
            )
            _elapsed = int(_time.time() - _start_ts)
            logger.info(f"[local coverage] report={report_id} 采集完成, 耗时 {_elapsed}s")
            # 回填耗时
            async with async_session_factory() as db_sess:
                r = (await db_sess.execute(
                    select(NtestCoverageReportModel).where(
                        NtestCoverageReportModel.id == report_id
                    )
                )).scalar_one_or_none()
                if r:
                    r.duration = _elapsed
                    await db_sess.commit()

        except Exception as e:
            _elapsed = int(_time.time() - _start_ts)
            logger.error(f"[local coverage] report={report_id} 采集失败(耗时{_elapsed}s): {e}")
            try:
                async with async_session_factory() as db:
                    r = (await db.execute(
                        select(NtestCoverageReportModel).where(
                            NtestCoverageReportModel.id == report_id
                        )
                    )).scalar_one_or_none()
                    if r:
                        r.coverage_rate = "ERROR"
                        r.status = "failed"
                        if r.progress:
                            prog = list(r.progress)
                            hit_failed = False
                            for p in prog:
                                if p["status"] in ("running", "failed"):
                                    # running → 标记为 failed（补充 detail）
                                    if p["status"] == "running":
                                        p["status"] = "failed"
                                        p["detail"] = str(e)[:300]
                                    hit_failed = True
                                elif p["status"] == "pending" and hit_failed:
                                    # 失败之后的步骤不会执行，标记为 skipped
                                    p["status"] = "skipped"
                                    p["detail"] = "前序步骤失败，已跳过"
                            r.progress = prog
                        r.duration = _elapsed
                        r.updation_date = datetime.now()
                        await db.commit()
            except Exception:
                pass
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # 仓库健康检测 & 报告进度查询                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def check_repo_health(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """
        检测 Python 仓库是否具备自动采集覆盖率的前置条件。
        浅 clone 后检查：是否可访问、是否有 pytest 测试用例、是否有 requirements.txt。
        """
        repo_url = body.get("repo_url") or body.get("html_url", "")
        local_path = body.get("local_path", "")
        branch = body.get("branch", "main")
        repo_id = body.get("repo_id")
        # 用户标记为「已在本机部署」的服务，跳过硬性拦截
        skip_service_deps: List[str] = body.get("skip_service_deps", [])

        # 优先用 local_path，其次 repo_url（兼容旧字段名 html_url）
        effective_path = local_path or repo_url
        if not effective_path:
            raise HTTPException(status_code=400, detail="缺少仓库地址或本地目录")

        is_local = os.path.isdir(effective_path)

        workdir = tempfile.mkdtemp(prefix="cov_check_")
        try:
            if is_local:
                # 本地目录模式：直接使用（复制一份避免污染）
                import shutil
                try:
                    shutil.copytree(effective_path, workdir, symlinks=True, dirs_exist_ok=True)
                except Exception as copy_err:
                    return {
                        "accessible": False,
                        "error": f"本地目录无法读取: {str(copy_err)[:300]}",
                        "checks": [],
                        "recommendations": [
                            "请确认服务器上该目录存在且可读",
                            "检查路径拼写和权限",
                        ],
                    }
            else:
                # Git URL 模式：clone
                rc, _, err = await PrecisionTestService._run_cmd(
                    ["git", "clone", "--depth", "1", "--no-tags", "--single-branch",
                     "-b", branch, effective_path, workdir],
                    cwd=None, timeout=120,
                )
                if rc != 0:
                    return {
                    "accessible": False,
                    "error": f"仓库无法访问（git clone 失败）: {err.strip()[:300]}",
                    "checks": [],
                    "recommendations": [
                        "请确认仓库地址正确且为公开可访问",
                        "私有仓库需确保服务器有 SSH key 或 Token 访问权限",
                    ],
                }

            import glob as glob_mod
            checks: List[Dict[str, Any]] = []
            recommendations: List[str] = []

            # ---- 1. 测试文件 ----
            test_patterns = [
                "**/test_*.py",
                "**/*_test.py",
                "tests/**/*.py",
                "conftest.py",
            ]
            test_files: List[str] = []
            for pat in test_patterns:
                found = glob_mod.glob(os.path.join(workdir, pat), recursive=True)
                for f in found:
                    rel = os.path.relpath(f, workdir).replace("\\", "/")
                    if rel not in test_files:
                        test_files.append(rel)

            has_tests = len(test_files) > 0
            checks.append({
                "name": "测试文件",
                "status": "pass" if has_tests else "fail",
                "detail": f"已检测到 {len(test_files)} 个测试文件" if has_tests else "未检测到 pytest 测试文件（test_*.py / *_test.py / tests/ / conftest.py）",
                "files": test_files[:20],
            })
            if not has_tests:
                recommendations.append("未检测到测试文件，覆盖率采集结果可能为 0%。建议在仓库根目录或 tests/ 目录下添加 pytest 测试用例。")

            # ---- 2. requirements.txt ----
            has_req = os.path.exists(os.path.join(workdir, "requirements.txt"))
            checks.append({
                "name": "依赖清单",
                "status": "pass" if has_req else "warn",
                "detail": "已检测到 requirements.txt" if has_req else "未检测到，将仅安装 coverage/pytest 基础工具",
            })
            if not has_req:
                recommendations.append("未检测到 requirements.txt，项目额外依赖将无法安装。建议添加。")

            # ---- 3. 覆盖率配置 (.coveragerc / pyproject.toml) ----
            cov_config_files = [
                ".coveragerc",
                ".coveragerc.ini",
                "setup.cfg",
                "pyproject.toml",
            ]
            found_cov_config = None
            for cf in cov_config_files:
                p = os.path.join(workdir, cf)
                if os.path.exists(p):
                    found_cov_config = cf
                    break
            checks.append({
                "name": "覆盖率配置",
                "status": "pass" if found_cov_config else "info",
                "detail": f"已检测到 {found_cov_config}" if found_cov_config else "未检测到 .coveragerc / pyproject.toml 等配置（将使用默认采集范围）",
            })

            # ---- 4. pytest 配置 (pytest.ini / setup.cfg / pyproject.toml) ----
            pytest_config_files = ["pytest.ini", "setup.cfg", "pyproject.toml"]
            found_pytest_config = None
            for pf in pytest_config_files:
                pp = os.path.join(workdir, pf)
                if os.path.exists(pp):
                    found_pytest_config = pf
                    break
            has_conftest = os.path.exists(os.path.join(workdir, "conftest.py"))
            checks.append({
                "name": "pytest 配置",
                "status": "pass" if (found_pytest_config or has_conftest) else "info",
                "detail": (
                    f"已检测到 {found_pytest_config}" + (" + conftest.py" if has_conftest else "")
                    if found_pytest_config
                    else ("已检测到 conftest.py" if has_conftest else "未检测到 pytest.ini / conftest.py（将使用默认发现规则）")
                ),
            })

            # ---- 5. 外部服务依赖扫描（优化：用 rg/findstr 批量搜索替代逐文件读取）----
            external_deps: List[Dict[str, str]] = []
            # 需要实际运行的外部服务（命中即硬性拦截）
            SERVICE_DEP_KEYS = {"mysql", "redis", "mongodb", "elasticsearch", "rabbitmq"}
            service_deps: List[Dict[str, str]] = []
            dep_patterns = {
                "mysql": ["import pymysql", "import mysql", "import MySQLdb"],
                "redis": ["import redis"],
                "mongodb": ["import pymongo", "import mongoengine"],
                "elasticsearch": ["import elasticsearch"],
                "rabbitmq": ["import pika", "import aio_pika"],
                "http_client": ["import requests", "import httpx", "import aiohttp"],
                "django": ["import django"],
                "flask": ["from flask", "import flask"],
                "fastapi": ["from fastapi", "import fastapi"],
                "sqlalchemy": ["import sqlalchemy", "from sqlalchemy"],
            }
            dep_labels = {
                "mysql": "MySQL 数据库",
                "redis": "Redis 缓存",
                "mongodb": "MongoDB 数据库",
                "elasticsearch": "Elasticsearch 搜索引擎",
                "rabbitmq": "RabbitMQ 消息队列",
                "http_client": "HTTP 客户端（requests/httpx）",
                "django": "Django Web 框架",
                "flask": "Flask Web 框架",
                "fastapi": "FastAPI Web 框架",
                "sqlalchemy": "SQLAlchemy ORM",
            }

            # 构建所有需要搜索的 snippet，用 rg 一次性搜索
            all_snippets = list({s for snippets in dep_patterns.values() for s in snippets})
            # 排除目录
            exclude_dirs = ['venv', '.venv', 'node_modules', '__pycache__', '.git', 'dist', 'build', '.tox']

            # 尝试用 rg (ripgrep) 批量搜索，速度比 Python 遍历快 10-50 倍
            _rg_matches: Dict[str, Set[str]] = {}  # snippet -> set of file paths
            try:
                rg_cmd = [
                    "rg", "-l", "--no-messages", "--type", "py",
                    *["--glob=!" + d + "/**" for d in exclude_dirs],
                    *(f'"{s}"' if ' ' in s or '.' in s else s for s in all_snippets),
                    workdir,
                ]
                rc2, out2, _ = await PrecisionTestService._run_cmd(rg_cmd, cwd=None, timeout=30)
                if rc2 == 0 and out2.strip():
                    # rg 输出的是匹配的文件列表，每个文件可能匹配多个 pattern
                    matched_files = [f.strip() for f in out2.strip().splitlines() if f.strip()]
                    # 对每个匹配文件，快速扫描它包含哪些 snippet
                    for mf in matched_files:
                        rel = os.path.relpath(mf, workdir).replace("\\", "/")
                        # 跳过排除目录
                        if any(rel.startswith(d + "/" or d + "\\") for d in exclude_dirs):
                            continue
                        try:
                            with open(mf, 'r', encoding='utf-8', errors='ignore') as fh:
                                content = fh.read()
                            for dep_name, snippets in dep_patterns.items():
                                label = dep_labels.get(dep_name, dep_name)
                                for snippet in snippets:
                                    if snippet in content:
                                        if label not in [d['name'] for d in external_deps]:
                                            external_deps.append({"name": label, "file": rel})
                                        if dep_name in SERVICE_DEP_KEYS and label not in [d['name'] for d in service_deps]:
                                            if label in skip_service_deps:
                                                continue
                                            service_deps.append({"name": label, "file": rel})
                                        break
                        except Exception:
                            pass
                elif rc2 != 0:
                    # rg 不可用或出错，回退到 Python 遍历（但限制文件数）
                    raise RuntimeError("rg fallback")
            except Exception:
                # 回退方案：Python 遍历 + 文件数限制（最多扫 200 个 .py 文件）
                _py_file_count = 0
                _MAX_PY_FILES = 200
                for dep_name, import_snippets in dep_patterns.items():
                    for root_dir, _dirs, files in os.walk(workdir):
                        _dirs[:] = [d for d in _dirs if d not in exclude_dirs]
                        for fn in files:
                            if not fn.endswith('.py'):
                                continue
                            _py_file_count += 1
                            if _py_file_count > _MAX_PY_FILES:
                                break
                            fpath = os.path.join(root_dir, fn)
                            try:
                                with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                                    content = fh.read()
                                for snippet in import_snippets:
                                    if snippet in content:
                                        label = dep_labels.get(dep_name, dep_name)
                                        rel = os.path.relpath(fpath, workdir).replace("\\", "/")
                                        if label not in [d['name'] for d in external_deps]:
                                            external_deps.append({"name": label, "file": rel})
                                        if dep_name in SERVICE_DEP_KEYS and label not in [d['name'] for d in service_deps]:
                                            if label in skip_service_deps:
                                                continue
                                            service_deps.append({"name": label, "file": rel})
                                        break
                            except Exception:
                                pass
                        if _py_file_count > _MAX_PY_FILES:
                            break
                    if _py_file_count > _MAX_PY_FILES:
                        break

            has_external_services = len(service_deps) > 0
            # 计算被跳过（已部署）的服务
            skipped_services = [s for s in skip_service_deps if s in [d['name'] for d in external_deps]]
            ext_status = "info"
            if skipped_services and not service_deps:
                # 有服务依赖但全部已标记为已部署 → pass
                ext_status = "pass"
            elif service_deps:
                ext_status = "fail"
                recommendations.append(
                    f"检测到项目依赖需要运行的外部服务：{', '.join(d['name'] for d in service_deps)}。"
                    " 这些服务在自动化采集的服务器上通常不可用，测试会连接失败导致覆盖率为 0%。"
                    " 请确认测试已用 Mock/测试容器隔离，或在本服务器启动对应服务后再创建报告。"
                )
            elif external_deps:
                ext_status = "warn"
                recommendations.append(
                    f"检测到项目依赖外部框架/库：{', '.join(d['name'] for d in external_deps)}。"
                    " 如测试用例直接连接这些服务，需确保服务器上对应服务可用，否则测试会失败导致覆盖率为 0%。"
                )
            checks.append({
                "name": "外部依赖",
                "status": ext_status,
                "detail": (
                    f"检测到 {len(external_deps)} 个潜在依赖"
                    + (f"，其中 {len(service_deps)} 个需要运行的服务" if service_deps else "")
                    if external_deps
                    else "未检测到明显的外部服务依赖"
                ),
                "deps": external_deps[:10],
                "service_deps": service_deps[:10],
            })

            # ---- 6. Python 版本兼容性 ----
            py_version = sys.version_info[:2]
            py_version_str = f"{py_version[0]}.{py_version[1]}"
            checks.append({
                "name": "Python 环境",
                "status": "pass",
                "detail": f"后端运行环境 Python {py_version_str}（自动化采集将使用此版本执行）",
            })

            # 综合判定：ready = 有测试文件 + 可访问
            ready = has_tests

            return {
                "accessible": True,
                "error": None,
                "has_tests": has_tests,
                "has_requirements_txt": has_req,
                "has_external_services": has_external_services,
                "skip_service_deps": skip_service_deps,
                "skipped_services": skipped_services,
                "test_files": test_files[:50],
                "test_count": len(test_files),
                "checks": checks,
                "recommendations": recommendations,
                "ready": ready,
            }
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # 本地目录树浏览（前端选目录用，后端返回真实绝对路径）                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def list_server_dirs(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """列出服务器上的目录，用于前端本地目录选择器逐级浏览。

        返回结构：
        {
            "valid": bool,          # path 是否为有效目录
            "path": str,            # 当前路径
            "dirs": [               # 子目录列表（仅目录，不含文件）
                {"name": "xxx", "path": "D:/xxx"},
                ...
            ],
            "parent": str | None,   # 父目录（根级为 None）
        }
        """
        import platform

        path = (body.get("path") or "").strip()

        # 1) 空路径：返回磁盘根（Windows 盘符 / *nix 根）
        if not path:
            if platform.system() == "Windows":
                import string
                roots = []
                for d in string.ascii_uppercase:
                    root = f"{d}:/"
                    if os.path.isdir(root):
                        roots.append({"name": root, "path": root})
                return {
                    "valid": True,
                    "path": "",
                    "dirs": roots,
                    "parent": None,
                }
            else:
                root = "/"
                dirs = sorted(
                    d for d in os.listdir(root)
                    if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")
                )
                return {
                    "valid": True,
                    "path": root,
                    "dirs": [{"name": d, "path": os.path.join(root, d)} for d in dirs],
                    "parent": None,
                }

        # 2) 指定路径：校验 + 列出子目录
        norm_path = os.path.normpath(path)
        if not os.path.isdir(norm_path):
            return {"valid": False, "path": norm_path, "dirs": [], "parent": None}

        try:
            entries = sorted(
                d for d in os.listdir(norm_path)
                if os.path.isdir(os.path.join(norm_path, d)) and not d.startswith(".")
            )
        except PermissionError:
            return {"valid": True, "path": norm_path, "dirs": [], "parent": os.path.dirname(norm_path) or None}

        parent = os.path.dirname(norm_path)
        # Windows 盘符根目录的 dirname 仍为自身，需特殊处理
        if platform.system() == "Windows" and len(norm_path) <= 3 and norm_path.endswith(":"):
            parent = None
        elif parent == norm_path:
            parent = None

        return {
            "valid": True,
            "path": norm_path,
            "dirs": [{"name": d, "path": os.path.join(norm_path, d)} for d in entries],
            "parent": parent,
        }

    @staticmethod
    async def get_report_progress(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """查询单条报告的采集进度。"""
        report_id = body.get("id")
        result = await db.execute(
            select(NtestCoverageReportModel).where(
                NtestCoverageReportModel.id == report_id,
                NtestCoverageReportModel.enabled_flag == 1,
            )
        )
        report = result.scalar_one_or_none()
        if not report:
            return {"code": 400, "message": "报告不存在", "data": None}
        return _row_to_dict(report)

    # ------------------------------------------------------------------ #
    # 覆盖缺口分析：低覆盖区域 / 未覆盖分支 / 未执行异常 / 未测试边界        #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def gap_analysis(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """分析报告覆盖缺口，结果持久化到 ntest_coverage_gap 并返回统计 + 列表。"""
        report_id = body.get("report_id")
        force_refresh = bool(body.get("force_refresh", False))
        if not report_id:
            raise ValueError("report_id 必填")

        # 1. 确保缺口表存在（兼容尚未迁移的 SQLite 库）
        from app.core.db_base import Base
        from app.infra.db.sqlalchemy import engine as _engine
        async with _engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: NtestCoverageGapModel.__table__.create(sync_conn, checkfirst=True)
            )

        # 2. 查报告 + 语言类型
        report = (await db.execute(
            select(NtestCoverageReportModel).where(
                NtestCoverageReportModel.id == report_id,
                NtestCoverageReportModel.enabled_flag == 1,
            )
        )).scalar_one_or_none()
        if not report:
            return {"code": 400, "message": "报告不存在", "data": None}

        lang_type = "java"
        if report.repo_id:
            repo = (await db.execute(
                select(NtestRepositoryModel).where(
                    NtestRepositoryModel.id == report.repo_id,
                    NtestRepositoryModel.enabled_flag == 1,
                )
            )).scalar_one_or_none()
            if repo and repo.lang_type:
                lang_type = repo.lang_type

        # 3. 已有缺口则复用（除非 force_refresh）
        existing = (await db.execute(
            select(func.count()).select_from(NtestCoverageGapModel).where(
                NtestCoverageGapModel.report_id == report_id,
                NtestCoverageGapModel.enabled_flag == 1,
            )
        )).scalar() or 0

        if force_refresh or existing == 0:
            old_rows = (await db.execute(
                select(NtestCoverageGapModel).where(
                    NtestCoverageGapModel.report_id == report_id,
                    NtestCoverageGapModel.enabled_flag == 1,
                )
            )).scalars().all()
            for g in old_rows:
                g.enabled_flag = 0
            await db.flush()

            gaps = await PrecisionTestService._build_gaps(db, report_id, lang_type)
            for g in gaps:
                db.add(NtestCoverageGapModel(created_by=user_id, updated_by=user_id, **g))
            await db.flush()

        # 4. 读取并返回（severity 权重排序 + 统计）
        rows = (await db.execute(
            select(NtestCoverageGapModel).where(
                NtestCoverageGapModel.report_id == report_id,
                NtestCoverageGapModel.enabled_flag == 1,
            )
        )).scalars().all()
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        gap_list = sorted(
            [_row_to_dict(r) for r in rows],
            key=lambda x: sev_order.get(x.get("severity"), 9),
        )

        summary = {"total": len(gap_list), "by_severity": {}, "by_type": {}}
        for g in gap_list:
            summary["by_severity"][g["severity"]] = summary["by_severity"].get(g["severity"], 0) + 1
            summary["by_type"][g["gap_type"]] = summary["by_type"].get(g["gap_type"], 0) + 1

        return {"lang_type": lang_type, "summary": summary, "gaps": gap_list}

    @staticmethod
    async def _build_gaps(
        db: AsyncSession, report_id: int, lang_type: str
    ) -> List[Dict[str, Any]]:
        """基于已入库的覆盖率数据，构建缺口列表。"""
        details = (await db.execute(
            select(NtestCoverageDetailModel).where(
                NtestCoverageDetailModel.report_id == report_id,
                NtestCoverageDetailModel.enabled_flag == 1,
            )
        )).scalars().all()

        gaps: List[Dict[str, Any]] = []
        for d in details:
            pkg = d.package_name
            cls = d.class_name
            total_lines = (d.line_missed or 0) + (d.line_covered or 0)
            total_branches = (d.branch_missed or 0) + (d.branch_covered or 0)
            line_rate = (d.line_covered / total_lines * 100) if total_lines else 0.0
            branch_rate = (d.branch_covered / total_branches * 100) if total_branches else 0.0

            if d.branch_missed and d.branch_missed > 0:
                sev = "critical" if d.branch_missed >= 5 else "high"
                gaps.append({
                    "report_id": report_id, "gap_type": "uncovered_branch", "severity": sev,
                    "package_name": pkg, "class_name": cls,
                    "description": f"类 {cls} 有 {d.branch_missed} 个分支未覆盖（分支覆盖率 {branch_rate:.1f}%）",
                    "suggestion": "补充参数组合用例覆盖未执行的分支（如边界值、空值、异常输入）",
                })

            if total_lines > 0 and line_rate < 80:
                sev = "critical" if line_rate < 50 else ("high" if line_rate < 70 else "medium")
                gaps.append({
                    "report_id": report_id, "gap_type": "low_coverage", "severity": sev,
                    "package_name": pkg, "class_name": cls,
                    "description": f"类 {cls} 行覆盖率 {line_rate:.1f}%，未覆盖 {d.line_missed} 行 / 共 {total_lines} 行",
                    "suggestion": "针对核心业务逻辑补充单元测试，优先覆盖条件分支与异常路径",
                })

            methods = d.methods or []
            for m in methods:
                m_missed = m.get("line_missed", 0) or 0
                m_cov = m.get("line_covered", 0) or 0
                m_total = m_missed + m_cov
                if m_total > 0 and m_missed > 0 and (m_missed / m_total * 100) < 60:
                    gaps.append({
                        "report_id": report_id, "gap_type": "low_coverage", "severity": "low",
                        "package_name": pkg, "class_name": cls, "method_name": m.get("name"),
                        "description": f"方法 {m.get('name')} 行覆盖率 {(m_missed / m_total * 100):.1f}%，未覆盖 {m_missed} 行",
                        "suggestion": f"为方法 {m.get('name')} 补充测试用例，覆盖其输入组合与边界情况",
                    })

            if lang_type == "java" and d.class_file_content:
                has_class_gap = (d.branch_missed and d.branch_missed > 0) or (total_lines > 0 and line_rate < 80)
                if has_class_gap:
                    exc_count = 0; bound_count = 0
                    for i, text in enumerate(d.class_file_content.split("\n"), start=1):
                        if exc_count >= 6 and bound_count >= 6: break
                        stripped = text.strip()
                        if re.search(r"\b(try|except|catch|finally)\b", text):
                            if exc_count < 6:
                                exc_count += 1
                                gaps.append({"report_id": report_id, "gap_type": "unhandled_exception", "severity": "high",
                                    "package_name": pkg, "class_name": cls, "line_number": i, "source_snippet": stripped[:200],
                                    "description": f"类 {cls} 第 {i} 行存在异常处理结构，建议核实是否被测试覆盖",
                                    "suggestion": "补充触发该异常分支的测试用例（如模拟依赖抛出异常），验证异常处理路径"})
                            continue
                        if re.search(r"(is None|is not None|not\s+\w+|len\([^)]*\)\s*(==|!=|<=|>=|<|>)\s*0|<\s*=|>\s*=|==\s*0|!=\s*0|\b(range|assert|validate)\b)", text):
                            if bound_count < 6:
                                bound_count += 1
                                gaps.append({"report_id": report_id, "gap_type": "boundary_condition", "severity": "medium",
                                    "package_name": pkg, "class_name": cls, "line_number": i, "source_snippet": stripped[:200],
                                    "description": f"类 {cls} 第 {i} 行存在边界判断，建议补充边界值用例",
                                    "suggestion": "补充参数最小值/最大值/空值用例，覆盖该边界判断逻辑"})

        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        gaps.sort(key=lambda g: sev_order.get(g["severity"], 9))
        return gaps

    # ------------------------------------------------------------------ #
    # 远程分支列表（增量模式选择旧分支）                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def list_remote_branches(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """获取仓库分支列表（Git URL 用 ls-remote，本地目录用 git branch）。"""
        repo_id = body.get("repo_id")
        repo_url = body.get("repo_url") or body.get("html_url")
        local_path = body.get("local_path", "")

        if repo_id:
            repo = (await db.execute(
                select(NtestRepositoryModel).where(
                    NtestRepositoryModel.id == repo_id,
                    NtestRepositoryModel.enabled_flag == 1,
                )
            )).scalar_one_or_none()
            if repo:
                # 优先 local_path，其次 html_url
                repo_url = repo.local_path or repo.html_url

        effective_path = local_path or repo_url
        if not effective_path:
            raise ValueError("请提供 repo_id 或 repo_url/local_path")

        is_local = os.path.isdir(effective_path)

        if is_local:
            # 本地目录模式：获取分支 + tag + 最近 commits（作为版本标识）
            rc, out, err = await PrecisionTestService._run_cmd(
                ["git", "branch", "--list", "--no-color"],
                cwd=effective_path, timeout=30,
            )
            if rc != 0:
                # 非 git 仓库：不抛错，返回空分支并标记 is_git_repo=false
                return {
                    "branches": [],
                    "total": 0,
                    "is_git_repo": False,
                    "collected_branches": [],
                    "recommended_old_branch": "",
                }
            branches = []
            for line in out.strip().splitlines():
                name = line.strip().lstrip("* ").strip()
                if name:
                    branches.append({"name": name, "ref": f"refs/heads/{name}", "type": "branch"})

            # 获取 git tags（版本标签，如 v1.0.0、release-2.1 等）
            rc2, out2, _ = await PrecisionTestService._run_cmd(
                ["git", "tag", "--sort=-creatordate"],
                cwd=effective_path, timeout=15,
            )
            if rc2 == 0 and out2.strip():
                for tag_name in out2.strip().splitlines():
                    tag_name = tag_name.strip()
                    if tag_name:
                        branches.append({"name": tag_name, "ref": f"refs/tags/{tag_name}", "type": "tag"})

            # 获取最近 5 条 commit（短 hash + 摘要），作为无 tag 时的版本参考
            rc3, out3, _ = await PrecisionTestService._run_cmd(
                ["git", "log", "--oneline", "-5", "--no-decorate"],
                cwd=effective_path, timeout=15,
            )
            if rc3 == 0 and out3.strip():
                for line in out3.strip().splitlines()[:5]:
                    line = line.strip()
                    if line:
                        # 格式: "abc1234 commit message"，取前 8 位 hash 作为 value
                        short_hash = line.split()[0] if line.split() else line
                        branches.append({
                            "name": line,
                            "ref": short_hash,
                            "type": "commit",
                        })
        else:
            # Git URL 模式：ls-remote
            rc, out, err = await PrecisionTestService._run_cmd(
                ["git", "ls-remote", "--heads", effective_path],
                timeout=30,
            )
            if rc != 0:
                raise RuntimeError(f"获取远程分支失败：{err.strip()[:300]}")

            branches = []
            for line in out.strip().splitlines():
                parts = line.split("\t", 1)
                if len(parts) == 2 and parts[1].startswith("refs/heads/"):
                    name = parts[1].replace("refs/heads/", "", 1)
                    branches.append({"name": name, "ref": parts[1]})

        # 常见分支排序：main/master 优先，然后按字母
        priority = {"main": 0, "master": 1, "develop": 2}
        branches.sort(key=lambda b: priority.get(b["name"], 99))

        # 聚合该仓库已采集成功的分支（用于增量模式自动推荐旧分支 baseline）
        collected_branches: list[str] = []
        recommended_old_branch = ""
        if repo_id:
            recs = (
                await db.execute(
                    select(
                        NtestCoverageReportModel.new_branches,
                        NtestCoverageReportModel.old_branches,
                    )
                    .where(
                        NtestCoverageReportModel.repo_id == repo_id,
                        NtestCoverageReportModel.status == "completed",
                    )
                    .order_by(NtestCoverageReportModel.id.desc())
                )
            ).all()
            seen: set[str] = set()
            for nb, ob in recs:
                if nb and nb.strip():
                    seen.add(nb.strip())
                if ob and ob.strip():
                    seen.add(ob.strip())
            collected_branches = list(seen)
            # 推荐旧分支 = 最近一次采集的目标分支（优先 new_branches）
            for nb, ob in recs:
                cand = (nb or "").strip() or (ob or "").strip()
                if cand:
                    recommended_old_branch = cand
                    break

        return {
            "branches": branches,
            "total": len(branches),
            "is_git_repo": True,
            "collected_branches": collected_branches,
            "recommended_old_branch": recommended_old_branch,
        }

    @staticmethod
    async def _run_cmd(
        cmd: List[str],
        cwd: Optional[str] = None,
        timeout: int = 300,
    ) -> tuple[int, str, str]:
        """运行子进程，返回 (returncode, stdout, stderr)。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return 124, "", "命令执行超时"
        except FileNotFoundError as e:
            return 127, "", str(e)
        return (
            proc.returncode or 0,
            (out or b"").decode("utf-8", errors="replace"),
            (err or b"").decode("utf-8", errors="replace"),
        )

    # ------------------------------------------------------------------ #
    # 智能预分析：执行覆盖率采集前的 Skill 驱动分析                     #
    # 参考: test-coverage Skill (elevanaltd/HestAI-MCP)                  #
    # 协议: 缺口分类 A→B→C→D / 常见模式识别 / 反模式检测 / TDD 建议     #
    # ------------------------------------------------------------------ #

    # 缺口分类定义（与 test-coverage Skill §2 一致）
    _GAP_CATEGORIES = {
        "A": {
            "name": "验证路径 (Validation Paths)",
            "severity": "HIGH",
            "description": "安全关键代码、参数校验、异常抛出",
            "patterns": [
                r"raise\s+(ValueError|TypeError|KeyError|PermissionError|AuthenticationError|ValidationError)",
                r"if\s+not\s+.+:\s*raise\s+",
                r"assert\s+.+",
                r"\.authenticate\(",
                r"\.authorize\(",
                r"@.*permission|@.*auth_required|@.*login_required",
            ],
            "template": "def test_{fn}_rejects_{case}():\n    with pytest.raises({Error}):\n        {fn}({invalid})",
        },
        "B": {
            "name": "边界条件 (Edge Cases)",
            "severity": "MEDIUM",
            "description": "空值/None/零值/边界输入处理",
            "patterns": [
                r"if\s+not\s+\w+:\s*return\s+None",
                r"if\s+not\s+\w+:\s*return\s+\[\]",
                r"if\s+not\s+\w+:\s*return\s+['\"]{0}",
                r"if\s+len\(.+\)\s*==\s*0",
                r"if\s+\w+\s*(==|!=|<=|>=|<|>)\s*(0|None|''|\"\")",
                r"\.get\([^)]*\)",
            ],
            "template": "def test_{fn}_handles_{edge}():\n    assert {fn}({input}) == {expected}",
        },
        "C": {
            "name": "异常处理 (Error Handlers)",
            "severity": "MEDIUM",
            "description": "except 防御性代码、降级逻辑、日志记录",
            "patterns": [
                r"except\s+\w+Error\s*:",
                r"except\s+\w+Exception\s*as\s+\w+\s*:",
                r"except\s*:",
                r"logger\.warning\(",
                r"logger\.error\(",
                r"\.fallback\(",
                r"try\s*:",
            ],
            "template": "with patch.object({Target}, '{method}', side_effect={Error}):\n    assert {fn}(...) == {fallback}",
        },
        "D": {
            "name": "基础设施 (Infrastructure)",
            "severity": "LOW",
            "description": "调试日志、平台特定代码、第三方包装",
            "patterns": [
                r"logger\.debug\(",
                r"logger\.info\(",
                r"#\s*(TODO|FIXME|HACK|XXX)",
                r"if\s+sys\.platform",
                r"if\s+os\.name",
                r"__repr__|__str__|__hash__",
            ],
            "template": "# 可接受缺口 - 文档化即可\n# {reason}",
        },
    }

    # 反模式检测规则（参考 §8）
    _ANTI_PATTERNS = {
        "coverage_theater": {
            "name": "覆盖率剧场 (Coverage Theater)",
            "symptom": "测试调用了函数但未断言行为，仅为了覆盖行号",
            "example": "def test_fn(): fn()  # 无任何 assert",
            "remedy": "每个测试必须包含有意义的断言（assert / raises / mock verify）",
            "detect_regex": r"^\s*def\s+test_\w+\(.*\):\s*\n(\s*.+\n)*\s*(?!assert|raises|mock|patch|return)(\w+\(\))\s*$",
        },
        "over_mocking": {
            "name": "过度 Mock (Over-Mocking)",
            "symptom": "Mock 了所有依赖导致测试证明不了什么",
            "example": "Mock 所有依赖后仅 assert mock 被调用",
            "remedy": "仅 Mock 外部边界（数据库/网络/文件系统），保留内部逻辑真实执行",
            "detect_keywords": ["@patch", "@mock_patch", "MagicMock", "AsyncMock"],
        },
        "chasing_100": {
            "name": "盲目追求 100% (Chasing 100%)",
            "symptom": "为覆盖 debug 日志等低价值行编写复杂 mock",
            "example": "复杂 mock 仅为了命中 logger.debug 行",
            "remedy": "接受 95% 并文档化剩余可接受缺口",
            "detect_patterns": [r"logger\.debug\(.*\)", r"# pragma: no cover"],
        },
    }

    @staticmethod
    async def pre_coverage_analysis(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """智能预分析入口：执行覆盖率采集前的深度分析。

        支持两种模式：
          - LLM 驱动模式：当 body 同时提供 llm_config_id 与 skill_id 时，读取选中 Skill 的
            SKILL.md 内容，结合仓库结构概览，调用指定 LLM 生成「如何配合 Pytest/Coverage.py
            进行代码覆盖率测试」的方案（用户核心诉求）。
          - 静态分析模式（默认/未选模型时）：基于 test-coverage Skill 协议做正则缺口分类、
            模式识别与反模式检测。
        """
        llm_config_id = body.get("llm_config_id")
        skill_id = body.get("skill_id")
        if llm_config_id and skill_id:
            return await PrecisionTestService.pre_coverage_analysis_llm(db, body, user_id)
        return await PrecisionTestService.pre_coverage_analysis_static(db, body, user_id)

    @staticmethod
    async def pre_coverage_analysis_static(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """静态预分析（默认）：基于 test-coverage Skill 协议做正则缺口分类/模式识别/反模式检测。"""
        repo_id = body.get("repo_id")
        repo_url = body.get("repo_url") or body.get("html_url", "")
        local_path = body.get("local_path", "")
        branch = body.get("branch", "main")

        # 获取仓库信息
        if repo_id:
            repo_result = await db.execute(
                select(NtestRepositoryModel).where(
                    NtestRepositoryModel.id == repo_id,
                    NtestRepositoryModel.enabled_flag == 1,
                )
            )
            repo = repo_result.scalar_one_or_none()
            if not repo:
                return {"code": 400, "message": "仓库不存在", "data": None}
            effective_path = local_path or repo.local_path or repo.html_url or ""
            lang_type = repo.lang_type or "python"
        else:
            effective_path = local_path or repo_url
            lang_type = body.get("lang_type", "python")

        if lang_type != "python":
            return {
                "code": 200,
                "message": "智能预分析当前仅支持 Python 仓库",
                "data": {"supported": False, "lang_type": lang_type},
            }

        if not effective_path:
            raise HTTPException(status_code=400, detail="缺少仓库地址或本地目录")

        is_local = os.path.isdir(effective_path)
        workdir = tempfile.mkdtemp(prefix="pre_cov_")
        analysis_start = __import__("time").time()

        try:
            # ---- Step 1: 准备源码 ----
            logger.info(f"[local coverage] pre-analysis 开始: repo={repo_id}, path={effective_path[:80]}")

            if is_local:
                import shutil as _shutil
                try:
                    _shutil.copytree(effective_path, workdir, symlinks=True, dirs_exist_ok=True)
                except Exception as e:
                    raise RuntimeError(f"复制目录失败: {e}")
            else:
                rc, _, err = await PrecisionTestService._run_cmd(
                    ["git", "clone", "--depth", "1", "-b", branch, effective_path, workdir],
                    cwd=None, timeout=180,
                )
                if rc != 0:
                    raise RuntimeError(f"克隆失败: {err.strip()}")

            py = sys.executable

            # ---- Step 2: 收集测试用例 (pytest --collect-only) ----
            collect_rc, collect_out, collect_err = await PrecisionTestService._run_cmd(
                [py, "-m", "pytest", "--collect-only", "-q", "--co", "."],
                cwd=workdir, timeout=120,
            )

            # 解析收集结果
            test_files: List[str] = []
            test_cases: List[str] = []
            if collect_out:
                for line in collect_out.splitlines():
                    line = line.strip()
                    # pytest --collect-only 输出格式: "tests/test_xxx.py::TestClass::test_method"
                    if "::" in line and ("test_" in line or "Test" in line):
                        test_cases.append(line)
                        fpart = line.split("::")[0]
                        if fpart not in test_files:
                            test_files.append(fpart)

            # ---- Step 3: 扫描源码文件（排除 tests/ / venv / __pycache__）----
            source_files: List[str] = []
            source_lines_total = 0
            exclude_dirs = {'venv', '.venv', 'node_modules', '__pycache__', '.git',
                           'dist', 'build', '.tox', 'tests', '.mypy_cache', '.pytest_cache'}

            for root_dir, _dirs, files in os.walk(workdir):
                _dirs[:] = [d for d in _dirs if d not in exclude_dirs]
                for fn in files:
                    if not fn.endswith('.py'):
                        continue
                    # 排除 conftest.py 和测试文件本身
                    if fn.startswith('test_') or fn.endswith('_test.py') or fn == 'conftest.py':
                        continue
                    fpath = os.path.join(root_dir, fn)
                    rel = os.path.relpath(fpath, workdir).replace("\\", "/")
                    source_files.append(rel)
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                        source_lines_total += sum(1 for _ in fh)

            # ---- Step 4: 缺口分析（A/B/C/D 分类）----
            gap_findings: List[Dict[str, Any]] = []
            category_stats: Dict[str, Dict] = {}

            for cat_id, cat_info in PrecisionTestService._GAP_CATEGORIES.items():
                findings_in_cat: List[Dict[str, Any]] = []
                pattern_matches: Dict[str, int] = {}  # pattern regex → match count

                for src_rel in source_files:
                    src_abs = os.path.join(workdir, src_rel)
                    try:
                        with open(src_abs, 'r', encoding='utf-8', errors='ignore') as fh:
                            content = fh.read()
                            lines = content.split('\n')
                    except Exception:
                        continue

                    for pat_idx, pattern in enumerate(cat_info["patterns"]):
                        matches = []
                        try:
                            for match in re.finditer(pattern, content):
                                lineno = content[:match.start()].count('\n') + 1
                                snippet = lines[lineno - 1].strip()[:120]
                                matches.append({"line": lineno, "snippet": snippet})
                        except re.error:
                            continue

                        if matches:
                            pat_key = f"P{pat_idx + 1}"
                            pattern_matches[pat_key] = len(matches)
                            findings_in_cat.append({
                                "file": src_rel,
                                "pattern_index": pat_idx,
                                "match_count": len(matches),
                                "matches": matches[:5],  # 最多展示 5 个匹配位置
                            })

                category_stats[cat_id] = {
                    **cat_info,
                    "finding_count": len(findings_in_cat),
                    "total_matches": sum(m["match_count"] for m in findings_in_cat),
                    "pattern_breakdown": pattern_stats,
                    "findings": findings_in_cat[:10],  # 最多返回 10 个文件级发现
                }
                gap_stats = pattern_matches  # alias for clarity below

            # ---- Step 5: 常见模式识别（§7）----
            common_patterns_found: List[Dict[str, Any]] = []
            pattern_recognition = {
                "early_return": {"label": "提前返回 (Early Return)", "regex": r"if\s+not\s+\w+:\s*return\s+(None|\[\]|''|\"\"|False|0)"},
                "exception_raise": {"label": "异常抛出 (Exception Raise)", "regex": r"raise\s+\w+Error\("},
                "except_block": {"label": "Except 防护块 (Except Block)", "regex": r"except\s+\w+\w*Error\s*(?:as\s+\w+)?:\s*"},
                "fallback_else": {"label": "Else 默认分支 (Fallback Else)", "regex": r"else:\s*return\s+"},
                "loop_continue": {"label": "循环跳过 (Loop Continue)", "regex": r"if\s+not\s+.*:\s*continue"},
                "os_error_handler": {"label": "OS 错误处理 (OS Error Handler)", "regex": r"except\s+OSError"},
            }

            for src_rel in source_files[:50]:  # 限制扫描文件数避免超时
                src_abs = os.path.join(workdir, src_rel)
                try:
                    with open(src_abs, 'r', encoding='utf-8', errors='ignore') as fh:
                        content = fh.read()
                except Exception:
                    continue

                for pid, pinfo in pattern_recognition.items():
                    found = re.findall(pinfo["regex"], content)
                    if found:
                        common_patterns_found.append({
                            "pattern_id": pid,
                            "pattern_name": pinfo["label"],
                            "file": src_rel,
                            "count": len(found),
                        })

            # 按 pattern_id 去重聚合
            pattern_summary: Dict[str, Dict] = {}
            for pf in common_patterns_found:
                key = pf["pattern_id"]
                if key not in pattern_summary:
                    pattern_summary[key] = {
                        "pattern_id": key,
                        "pattern_name": pf["pattern_name"],
                        "file_count": 0,
                        "total_count": 0,
                        "sample_files": [],
                    }
                pattern_summary[key]["file_count"] += 1
                pattern_summary[key]["total_count"] += pf["count"]
                if len(pattern_summary[key]["sample_files"]) < 3:
                    pattern_summary[key]["sample_files"].append(pf["file"])

            # ---- Step 6: 反模式检测（§8）----
            anti_pattern_warnings: List[Dict[str, Any]] = []

            # 6a: Over-mocking 检测 — 扫描测试文件中的 mock 使用密度
            mock_heavy_tests: List[str] = []
            for tf in test_files:
                tf_abs = os.path.join(workdir, tf)
                try:
                    with open(tf_abs, 'r', encoding='utf-8', errors='ignore') as fh:
                        tcontent = fh.read()
                except Exception:
                    continue
                mock_count = sum(len(re.findall(kw, tcontent))
                                 for kw in PrecisionTestService._ANTI_PATTERNS["over_mocking"]["detect_keywords"])
                line_count = tcontent.count('\n') + 1
                if line_count > 5 and mock_count > max(3, line_count // 3):  # mock 密度 > 33%
                    mock_heavy_tests.append(tf)

            if mock_heavy_tests:
                anti_pattern_warnings.append({
                    **PrecisionTestService._ANTI_PATTERNS["over_mocking"],
                    "affected_files": mock_heavy_tests[:5],
                    "severity": "medium",
                })

            # 6b: Chasing 100% 检测 — 大量 debug 日志 + pragma: no cover
            pragma_count = 0
            debug_log_count = 0
            for src_rel in source_files[:30]:
                src_abs = os.path.join(workdir, src_rel)
                try:
                    with open(src_abs, 'r', encoding='utf-8', errors='ignore') as fh:
                        sc = fh.read()
                except Exception:
                    continue
                pragma_count += len(re.findall(r"#\s*pragma:\s*no\s*cover", sc))
                debug_log_count += len(re.findall(r"logger\.debug\(", sc))

            if debug_log_count > 20 or pragma_count > 5:
                anti_pattern_warnings.append({
                    **PrecisionTestService._ANTI_PATTERNS["chasing_100"],
                    "debug_log_count": debug_log_count,
                    "pragma_no_cover_count": pragma_count,
                    "severity": "low",
                })

            # ---- Step 7: 综合评分与建议 ----
            total_gaps = sum(cs["total_matches"] for cs in category_stats.values())
            high_priority_gaps = category_stats.get("A", {}).get("total_matches", 0) + \
                                  category_stats.get("B", {}).get("total_matches", 0)

            # 覆盖率预估（基于测试数量 vs 源码规模）
            estimated_coverage = None
            if source_lines_total > 0 and len(test_cases) > 0:
                # 粗估：每测试约覆盖 15-25 行源码（经验值）
                estimated_low = min(100, round(len(test_cases) * 15 / source_lines_total * 100, 1))
                estimated_high = min(100, round(len(test_cases) * 25 / source_lines_total * 100, 1))
                estimated_coverage = f"{estimated_low}% ~ {estimated_high}%"

            # 生成建议列表
            recommendations: List[str] = []
            if high_priority_gaps > 20:
                recommendations.append(
                    f"检测到 {high_priority_gaps} 处高优先级缺口(A+B)，建议优先补充验证路径和边界条件测试"
                )
            if len(test_cases) < 10:
                recommendations.append(
                    f"仅发现 {len(test_cases)} 个测试用例，建议增加单元测试以达到 90%+ 覆盖率目标"
                )
            if anti_pattern_warnings:
                rec = "; ".join([ap["name"] for ap in anti_pattern_warnings])
                recommendations.append(f"检测到反模式风险: {rec}，建议 review 测试质量")
            if not test_files:
                recommendations.append("未发现测试文件，请确认 pytest 配置正确或创建 tests/ 目录")

            elapsed = round(__import__("time").time() - analysis_start, 1)

            logger.info(f"[local coverage] pre-analysis 完成: repo={repo_id}, "
                       f"源文件={len(source_files)}, 测试={len(test_cases)}, "
                       f"缺口={total_gaps}, 耗时={elapsed}s")

            return {
                "supported": True,
                "lang_type": "python",
                "analysis_elapsed_seconds": elapsed,

                # 概览
                "overview": {
                    "source_file_count": len(source_files),
                    "source_line_count": source_lines_total,
                    "test_file_count": len(test_files),
                    "test_case_count": len(test_cases),
                    "total_gap_count": total_gaps,
                    "estimated_coverage_range": estimated_coverage,
                    "collect_exit_code": collect_rc,
                    "collect_stdout": (collect_out or "")[-500:] if collect_out else "",
                    "collect_stderr": (collect_err or "")[-300:] if collect_err else "",
                },

                # 缺口分类 A/B/C/D
                "gap_categories": category_stats,

                # 常见模式识别
                "common_patterns": sorted(
                    pattern_summary.values(),
                    key=lambda x: x["total_count"], reverse=True,
                ),

                # 反模式警告
                "anti_patterns": anti_pattern_warnings,

                # TDD 建议
                "recommendations": recommendations,

                # 快速行动项（按优先级排序）
                "quick_actions": [
                    {
                        "priority": 1,
                        "action": "补充验证路径测试",
                        "category": "A",
                        "target_count": category_stats.get("A", {}).get("total_matches", 0),
                        "template": PrecisionTestService._GAP_CATEGORIES["A"]["template"],
                    },
                    {
                        "priority": 2,
                        "action": "补充边界条件测试",
                        "category": "B",
                        "target_count": category_stats.get("B", {}).get("total_matches", 0),
                        "template": PrecisionTestService._GAP_CATEGORIES["B"]["template"],
                    },
                    {
                        "priority": 3,
                        "action": "补充异常路径测试",
                        "category": "C",
                        "target_count": category_stats.get("C", {}).get("total_matches", 0),
                        "template": PrecisionTestService._GAP_CATEGORIES["C"]["template"],
                    },
                ],
            }

        except HTTPException:
            raise
        except Exception as e:
            elapsed = round(__import__("time").time() - analysis_start, 1)
            logger.error(f"[local coverage] pre-analysis 失败(耗时{elapsed}s): {e}")
            return {
                "code": 500,
                "message": f"预分析失败: {str(e)[:300]}",
                "data": None,
            }
        finally:
            import shutil as _shutil
            _shutil.rmtree(workdir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # LLM + Skill 驱动预分析                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _collect_repo_overview(workdir: str, py: str) -> Dict[str, Any]:
        """收集仓库概览：源文件清单、测试文件、测试用例数、源码行数（供 LLM 上下文使用）。"""
        exclude_dirs = {
            'venv', '.venv', 'node_modules', '__pycache__', '.git',
            'dist', 'build', '.tox', 'tests', '.mypy_cache', '.pytest_cache',
        }

        # 1) pytest --collect-only 收集测试用例
        collect_rc, collect_out, collect_err = await PrecisionTestService._run_cmd(
            [py, "-m", "pytest", "--collect-only", "-q", "--co", "."],
            cwd=workdir, timeout=120,
        )
        test_files: List[str] = []
        test_cases: List[str] = []
        if collect_out:
            for line in collect_out.splitlines():
                line = line.strip()
                if "::" in line and ("test_" in line or "Test" in line):
                    test_cases.append(line)
                    fpart = line.split("::")[0]
                    if fpart not in test_files:
                        test_files.append(fpart)

        # 2) 扫描源码文件（排除 tests/ / venv / __pycache__ 与测试文件本身）
        source_files: List[str] = []
        source_lines_total = 0
        for root_dir, _dirs, files in os.walk(workdir):
            _dirs[:] = [d for d in _dirs if d not in exclude_dirs]
            for fn in files:
                if not fn.endswith('.py'):
                    continue
                if fn.startswith('test_') or fn.endswith('_test.py') or fn == 'conftest.py':
                    continue
                fpath = os.path.join(root_dir, fn)
                rel = os.path.relpath(fpath, workdir).replace("\\", "/")
                source_files.append(rel)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                        source_lines_total += sum(1 for _ in fh)
                except Exception:
                    pass

        return {
            "source_files": source_files,
            "source_file_count": len(source_files),
            "source_line_count": source_lines_total,
            "test_files": test_files,
            "test_file_count": len(test_files),
            "test_case_count": len(test_cases),
            "collect_rc": collect_rc,
            "collect_err": (collect_err or "")[-300:],
        }

    @staticmethod
    async def pre_coverage_analysis_llm(
        db: AsyncSession, body: Dict[str, Any], user_id: int
    ) -> Dict[str, Any]:
        """LLM 驱动预分析：读取选中 Skill 的 SKILL.md，结合仓库概览，调用 LLM 生成覆盖率测试方案。

        这是用户的核心诉求：选择某个 LLM 模型 + 某个 Skill 后，让模型自动读取 Skill 内容，
        分析如何配合 Pytest / Coverage.py 进行代码覆盖率测试。
        """
        import time as _time

        repo_id = body.get("repo_id")
        repo_url = body.get("repo_url") or body.get("html_url", "")
        local_path = body.get("local_path", "")
        branch = body.get("branch", "main")
        llm_config_id = body.get("llm_config_id")
        skill_id = body.get("skill_id")

        try:
            llm_config_id = int(llm_config_id)  # type: ignore[arg-type]
            skill_id = int(skill_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return {"code": 400, "message": "llm_config_id 与 skill_id 必须为整数", "data": None}

        # ---- 获取仓库信息 ----
        if repo_id:
            repo_result = await db.execute(
                select(NtestRepositoryModel).where(
                    NtestRepositoryModel.id == repo_id,
                    NtestRepositoryModel.enabled_flag == 1,
                )
            )
            repo = repo_result.scalar_one_or_none()
            if not repo:
                return {"code": 400, "message": "仓库不存在", "data": None}
            effective_path = local_path or repo.local_path or repo.html_url or ""
            lang_type = repo.lang_type or "python"
        else:
            effective_path = local_path or repo_url
            lang_type = body.get("lang_type", "python")

        if lang_type != "python":
            return {
                "code": 200,
                "message": "LLM 预分析当前仅支持 Python 仓库",
                "data": {"supported": False, "lang_type": lang_type},
            }

        if not effective_path:
            raise HTTPException(status_code=400, detail="缺少仓库地址或本地目录")

        is_local = os.path.isdir(effective_path)
        workdir = tempfile.mkdtemp(prefix="pre_cov_llm_")
        analysis_start = _time.time()

        try:
            logger.info(
                f"[local coverage] pre-analysis(LLM) 开始: repo={repo_id}, "
                f"skill={skill_id}, llm={llm_config_id}"
            )

            # Step 1: 准备源码
            if is_local:
                import shutil as _shutil
                try:
                    _shutil.copytree(effective_path, workdir, symlinks=True, dirs_exist_ok=True)
                except Exception as e:
                    raise RuntimeError(f"复制目录失败: {e}")
            else:
                rc, _, err = await PrecisionTestService._run_cmd(
                    ["git", "clone", "--depth", "1", "-b", branch, effective_path, workdir],
                    cwd=None, timeout=180,
                )
                if rc != 0:
                    raise RuntimeError(f"克隆失败: {err.strip()}")

            py = sys.executable

            # Step 2: 收集仓库概览（源文件清单 + 测试情况）
            overview = await PrecisionTestService._collect_repo_overview(workdir, py)

            # Step 3: 读取选中 Skill 的 SKILL.md 内容
            SkillsModel = _get_skills_model()
            skill_row = (
                await db.execute(
                    select(SkillsModel).where(
                        SkillsModel.id == skill_id,
                        SkillsModel.enabled_flag == 1,
                    )
                )
            ).scalar_one_or_none()
            if not skill_row:
                return {"code": 400, "message": "指定的 Skill 不存在或未启用", "data": None}

            skill_name = getattr(skill_row, "name", "")
            skill_path = getattr(skill_row, "skill_path", None)
            skill_md = ""
            if skill_path:
                md_path = Path(str(skill_path)) / "SKILL.md"
                if md_path.exists() and md_path.is_file():
                    try:
                        skill_md = md_path.read_text(encoding="utf-8", errors="ignore")[:16000]
                    except Exception as e:
                        logger.warning(f"[local coverage] 读取 SKILL.md 失败: {e}")

            # Step 4: 构造给 LLM 的仓库概览文本
            src_list = overview["source_files"][:80]
            test_list = overview["test_files"][:60]
            repo_overview_text = (
                f"源码文件数：{overview['source_file_count']}（共 {overview['source_line_count']} 行）\n"
                f"测试文件数：{overview['test_file_count']}，解析出的测试用例数：{overview['test_case_count']}\n"
                f"pytest collect 退出码：{overview['collect_rc']}\n"
                f"部分源码文件（前 {len(src_list)} 个）：\n"
                + "\n".join(f"- {f}" for f in src_list)
                + "\n\n测试文件列表（前 {0} 个）：\n".format(len(test_list))
                + "\n".join(f"- {f}" for f in test_list)
            )

            system_prompt = (
                "你是一名资深的 Python 测试与代码覆盖率专家，擅长结合 Pytest、Coverage.py "
                "以及项目自带的测试方法论（Skill）来设计科学的代码覆盖率采集方案。\n"
                "请用中文作答，并以 Markdown 格式输出结构化报告。"
            )
            user_prompt = (
                "我准备对一个 Python 仓库执行代码覆盖率采集（工具链：Pytest + Coverage.py）。\n\n"
                "## 项目测试方法论（Skill 内容 / SKILL.md）\n"
                f"{skill_md if skill_md else '(该 Skill 未提供 SKILL.md 内容，请基于通用最佳实践给出方案)'}\n\n"
                "## 仓库结构概览\n"
                f"{repo_overview_text}\n\n"
                "## 你的任务\n"
                "请基于上述 Skill 的方法论，给出如何配合 Pytest / Coverage.py 对该仓库进行代码覆盖率测试的"
                "**具体可执行方案**，至少包含：\n"
                "1. 覆盖率采集的整体流程与建议命令（如 pytest 配合 --cov / `coverage run` 的用法、生成报告的方式）；\n"
                "2. 按该 Skill 方法论，应优先覆盖 / 重点测试的模块或代码路径（结合上面的仓库结构）；\n"
                "3. 缺失测试时应如何补充测试文件（可给出示例测试骨架）；\n"
                "4. 如何解读覆盖率报告（语句/分支覆盖率），以及建议的覆盖率目标与阈值；\n"
                "5. 结合该 Skill 提到的反模式（如覆盖率剧场、过度 Mock），给出注意事项。\n"
                "请输出可直接指导执行的方案，避免空泛。"
            )

            # Step 5: 调用 LLM
            try:
                get_llm_service = _get_llm_service()
                llm_service = await get_llm_service(llm_config_id)
            except Exception as e:
                return {"code": 400, "message": f"LLM 配置不可用：{str(e)[:300]}", "data": None}

            try:
                resp = await llm_service.chat_completion(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    model=llm_service.config.get("model"),
                    temperature=0.3,
                    max_tokens=3000,
                )
                llm_analysis = resp.content
                usage = resp.usage
                model_name = resp.model
            except Exception as e:
                return {"code": 500, "message": f"LLM 调用失败：{str(e)[:300]}", "data": None}

            elapsed = round(_time.time() - analysis_start, 1)
            logger.info(
                f"[local coverage] pre-analysis(LLM) 完成: repo={repo_id}, "
                f"model={model_name}, 耗时={elapsed}s"
            )

            return {
                "mode": "llm",
                "supported": True,
                "lang_type": "python",
                "analysis_elapsed_seconds": elapsed,
                "skill": {
                    "id": skill_id,
                    "name": skill_name,
                    "path": skill_path,
                    "has_skill_md": bool(skill_md),
                    "skill_md_length": len(skill_md),
                },
                "model": model_name,
                "usage": usage or {},
                "llm_analysis": llm_analysis,
                "repo_overview": overview,
            }

        except HTTPException:
            raise
        except Exception as e:
            elapsed = round(_time.time() - analysis_start, 1)
            logger.error(f"[local coverage] pre-analysis(LLM) 失败(耗时{elapsed}s): {e}")
            return {"code": 500, "message": f"LLM 预分析失败: {str(e)[:300]}", "data": None}
        finally:
            import shutil as _shutil
            _shutil.rmtree(workdir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Task 3.x — AI 规范重构（按 Pytest + Coverage.py 模板重构仓库）       #
    # ------------------------------------------------------------------ #

    # 符合 PDF《AI 自动化代码覆盖率检测》规范的参考模板（src/ + tests/ + 配置文件）
    _AUTO_FIX_TEMPLATES = (
        "=== 项目结构模板 ===\n"
        "project/\n"
        "├── src/                  # 业务源代码（被统计覆盖率）\n"
        "│   └── user_service.py\n"
        "├── tests/                # 测试代码（pytest 收集）\n"
        "│   └── test_user_service.py\n"
        "├── coverage/             # 覆盖率报告输出目录\n"
        "│   ├── coverage.json\n"
        "│   └── html/\n"
        "├── pytest.ini\n"
        "├── .coveragerc\n"
        "└── requirements.txt\n\n"
        "=== 参考模板 1：requirements.txt ===\n"
        "pytest\npytest-cov\ncoverage\n\n"
        "=== 参考模板 2：pytest.ini ===\n"
        "[pytest]\n"
        "testpaths =\n"
        "    tests\n"
        "python_files =\n"
        "    test_*.py\n"
        "python_classes =\n"
        "    Test*\n"
        "python_functions =\n"
        "    test_*\n"
        "addopts =\n"
        "    -v\n"
        "    --cov=src\n"
        "    --cov-branch\n"
        "    --cov-report=json:coverage/coverage.json\n"
        "    --cov-report=html:coverage/html\n"
        "    --cov-report=term-missing\n\n"
        "=== 参考模板 3：.coveragerc ===\n"
        "[run]\n"
        "branch = True\n"
        "source = src\n"
        "omit =\n"
        "    */tests/*\n"
        "[report]\n"
        "exclude_lines =\n"
        "    pragma: no cover\n"
        "    if __name__ == \"__main__\":\n"
        "precision = 2\n"
        "[html]\n"
        "directory = coverage/html\n\n"
        "=== 参考模板 4：src/user_service.py（依赖注入，便于 Mock）===\n"
        "\"\"\"用户服务模块，用于 AI 覆盖率检测示例\"\"\"\n"
        "from typing import Dict\n"
        "class UserService:\n"
        "    def __init__(self, repository):\n"
        "        # 依赖注入：外部依赖通过构造参数传入，方便 AI 生成 Mock 测试\n"
        "        self.repository = repository\n"
        "    def create_user(self, username: str, age: int) -> Dict:\n"
        "        if not username:\n"
        "            raise ValueError(\"username不能为空\")\n"
        "        if age < 18:\n"
        "            return {\"success\": False, \"message\": \"年龄不足\"}\n"
        "        user = {\"username\": username, \"age\": age}\n"
        "        result = self.repository.save(user)\n"
        "        if result:\n"
        "            return {\"success\": True, \"data\": user}\n"
        "        return {\"success\": False, \"message\": \"保存失败\"}\n"
        "    def get_user(self, user_id: int):\n"
        "        user = self.repository.find(user_id)\n"
        "        if user is None:\n"
        "            return None\n"
        "        return user\n\n"
        "=== 参考模板 5：tests/test_user_service.py（pytest 可收集，覆盖正常/异常/边界）===\n"
        "\"\"\"用户服务测试\"\"\"\n"
        "import pytest\n"
        "from unittest.mock import Mock\n"
        "from src.user_service import UserService\n\n"
        "@pytest.fixture\n"
        "def repository_mock():\n"
        "    return Mock()\n\n"
        "@pytest.fixture\n"
        "def service(repository_mock):\n"
        "    return UserService(repository_mock)\n\n"
        "def test_create_user_success(service, repository_mock):\n"
        "    repository_mock.save.return_value = True\n"
        "    assert service.create_user(\"Tom\", 20)[\"success\"] is True\n\n"
        "def test_create_user_empty_name(service):\n"
        "    with pytest.raises(ValueError):\n"
        "        service.create_user(\"\", 20)\n\n"
        "def test_create_user_age_less_than_limit(service):\n"
        "    assert service.create_user(\"Tom\", 15)[\"success\"] is False\n\n"
        "def test_create_user_save_failed(service, repository_mock):\n"
        "    repository_mock.save.return_value = False\n"
        "    assert service.create_user(\"Tom\", 20)[\"success\"] is False\n\n"
        "def test_get_user_success(service, repository_mock):\n"
        "    repository_mock.find.return_value = {\"id\": 1, \"name\": \"Tom\"}\n"
        "    assert service.get_user(1) is not None\n\n"
        "def test_get_user_not_found(service, repository_mock):\n"
        "    repository_mock.find.return_value = None\n"
        "    assert service.get_user(100) is None\n\n"
        "=== AI 检测规则（覆盖率门槛与检查项）===\n"
        "- Line Coverage ≥ 80%；Branch Coverage ≥ 70%\n"
        "- 异常覆盖：所有 raise 必须被测试\n"
        "- 边界覆盖：None、空值、最大值/最小值\n"
        "- Mock 覆盖：第三方接口必须 Mock，禁止真实连接数据库 / 真实 HTTP 调用\n"
        "- 时间必须 mock datetime；随机数必须固定 seed\n\n"
        "=== 适合 LLM 自动修改的代码规范 ===\n"
        "1. 依赖注入：外部资源（DB/Redis/MQ/HTTP/File/Time）通过构造参数或参数传入，不要在函数内直接连接\n"
        "2. 单函数不超过 50 行，便于覆盖分析\n"
        "3. 明确异常类型，不要用 except: pass，应捕获具体异常\n"
        "4. 所有外部资源抽象为接口，便于 Mock\n"
    )

    @staticmethod
    async def auto_fix_tests_preview(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """AI 规范重构（预览）：读取仓库当前源码/测试，调用 LLM 生成
        src/ + tests/ + 配置文件 的重构方案，返回文件清单（不写盘）。
        """
        import time as _time
        repo_id = body.get("repo_id")
        llm_config_id = body.get("llm_config_id")
        try:
            llm_config_id = int(llm_config_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return {"code": 400, "message": "llm_config_id 必须为整数", "data": None}

        if repo_id:
            repo_result = await db.execute(
                select(NtestRepositoryModel).where(
                    NtestRepositoryModel.id == repo_id,
                    NtestRepositoryModel.enabled_flag == 1,
                )
            )
            repo = repo_result.scalar_one_or_none()
            if not repo:
                return {"code": 400, "message": "仓库不存在", "data": None}
            effective_path = repo.local_path or repo.html_url or ""
        else:
            effective_path = body.get("local_path") or body.get("repo_url") or body.get("html_url", "")

        if not effective_path:
            return {"code": 400, "message": "缺少仓库地址或本地目录", "data": None}

        if not os.path.isdir(effective_path):
            return {"code": 400, "message": "AI 规范重构仅支持本地目录仓库", "data": None}

        workdir = tempfile.mkdtemp(prefix="auto_fix_")
        analysis_start = _time.time()
        try:
            import shutil as _shutil
            try:
                _shutil.copytree(effective_path, workdir, symlinks=True, dirs_exist_ok=True)
            except Exception as e:
                return {"code": 400, "message": f"复制仓库失败: {str(e)[:200]}", "data": None}

            # 收集当前源码与测试文件（截断单文件，控制 token）
            exclude_dirs = {'venv', '.venv', 'node_modules', '__pycache__', '.git',
                            'dist', 'build', '.tox', 'tests', '.mypy_cache', '.pytest_cache', 'coverage'}
            max_file_chars = 12000
            source_blocks: List[str] = []
            test_blocks: List[str] = []
            for root_dir, _dirs, files in os.walk(workdir):
                _dirs[:] = [d for d in _dirs if d not in exclude_dirs]
                for fn in files:
                    if not fn.endswith('.py'):
                        continue
                    fpath = os.path.join(root_dir, fn)
                    rel = os.path.relpath(fpath, workdir).replace("\\", "/")
                    try:
                        content = Path(fpath).read_text(encoding='utf-8', errors='ignore')
                    except Exception:
                        continue
                    block = f"### 文件：{rel}\n```python\n{content[:max_file_chars]}\n```\n"
                    if fn == 'conftest.py' or fn.startswith('test_') or fn.endswith('_test.py'):
                        test_blocks.append(block)
                    else:
                        source_blocks.append(block)
                    if (sum(len(b) for b in source_blocks) + sum(len(b) for b in test_blocks)) > 48000:
                        break

            if not source_blocks and not test_blocks:
                return {"code": 400, "message": "未在仓库中找到任何 Python 源码或测试文件", "data": None}

            current_code = (
                "# ===== 当前仓库源码文件 =====\n"
                + "\n".join(source_blocks[:40])
                + "\n\n# ===== 当前仓库测试文件 =====\n"
                + "\n".join(test_blocks[:40])
            )

            system_prompt = (
                "你是一名高级 Python 测试工程师，负责把一个代码仓库重构成符合 Pytest + Coverage.py 规范的"
                "可测结构。请严格遵守以下硬规则：\n"
                "1. 仅输出一个 JSON 对象，禁止任何解释文字、Markdown 标记或代码块围栏。\n"
                "2. 优先修改/补充测试文件；只有当代码设计导致无法测试时，才修改 src 源码（如增加依赖注入、拆分函数）。\n"
                "3. 保持业务逻辑不变，新增测试必须使用 pytest，外部依赖必须 Mock，禁止真实连接数据库 / HTTP。\n"
                "4. 新增测试必须覆盖：正常路径、异常流程（pytest.raises）、边界条件（None / 空值 / 极值）。\n"
                "5. 所有生成的测试文件必须能被 pytest 正确收集（文件名为 test_*.py，函数以 test_ 开头或类以 Test 开头）。"
            )
            user_prompt = (
                "下面是《AI 自动化代码覆盖率检测》的参考模板与规则，你生成的文件必须严格遵循这些约定：\n\n"
                f"{PrecisionTestService._AUTO_FIX_TEMPLATES}\n\n"
                "## 当前仓库代码\n"
                f"{current_code}\n\n"
                "## 你的任务（按步骤执行）\n"
                "请分析『当前仓库代码』，按参考模板结构重构，使 pytest 能收集到用例、Coverage.py 能统计 src 覆盖率：\n"
                "步骤1【整理源码】：将业务源码放入 `src/`（保持原类名/函数签名，必要时调整 import；外部依赖改为构造参数注入）。\n"
                "步骤2【补充测试】：在 `tests/` 生成 `test_*.py`，import `src` 中的代码并真正调用+断言，覆盖正常/异常/边界；"
                "用 Mock 替代外部依赖。\n"
                "步骤3【生成配置】：生成 `pytest.ini`、`.coveragerc`、`requirements.txt`（已存在则按模板修正）。\n"
                "步骤4【不丢逻辑】：保留仓库原有逻辑，仅做结构整理与测试补充，不引入无关模块。\n\n"
                "## 输出格式（仅输出如下 JSON，不要其他内容）\n"
                "{\n"
                '  "files": [\n'
                '    {"path": "src/xxx.py", "action": "update", "content": "<完整文件内容>"},\n'
                '    {"path": "tests/test_xxx.py", "action": "create", "content": "<完整文件内容>"},\n'
                '    {"path": "pytest.ini", "action": "create", "content": "<完整文件内容>"},\n'
                '    {"path": ".coveragerc", "action": "create", "content": "<完整文件内容>"},\n'
                '    {"path": "requirements.txt", "action": "update", "content": "<完整文件内容>"}\n'
                "  ]\n"
                "}\n"
                "说明：path 为相对仓库根目录路径；action 取值 create（新建）或 update（覆盖已有）；"
                "content 为该文件完整内容（不要省略）。"
            )

            try:
                get_llm_service = _get_llm_service()
                llm_service = await get_llm_service(llm_config_id)
            except Exception as e:
                return {"code": 400, "message": f"LLM 配置不可用：{str(e)[:300]}", "data": None}

            try:
                resp = await llm_service.chat_completion(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    model=llm_service.config.get("model"),
                    temperature=0.1,
                    max_tokens=12000,
                )
                llm_text = resp.content or ""
                model_name = resp.model
            except Exception as e:
                return {"code": 500, "message": f"LLM 调用失败：{str(e)[:300]}", "data": None}

            # 解析 JSON（容错：截取首个 { 到末个 }）
            parsed = PrecisionTestService._extract_json_object(llm_text)
            if parsed is None or not isinstance(parsed.get("files"), list):
                return {
                    "code": 500,
                    "message": "LLM 返回内容无法解析为文件清单，请重试或调整模型",
                    "data": {"raw": llm_text[:500]},
                }

            files = []
            for item in parsed["files"]:
                path = (item.get("path") or "").strip().replace("\\", "/")
                content = item.get("content") or ""
                action = item.get("action") or "create"
                if not path or not content:
                    continue
                # 安全限制：禁止跳出仓库根目录（仅拦截路径片段为 "." 或 ".."，不误伤含 .. 的文件名）
                parts = path.split("/")
                if path.startswith("/") or any(p in (".", "..") for p in parts):
                    continue
                files.append({"path": path, "action": action, "content": content})

            if not files:
                return {"code": 500, "message": "LLM 未生成任何有效文件", "data": None}

            elapsed = round(_time.time() - analysis_start, 1)
            return {
                "code": 200,
                "data": {
                    "files": files,
                    "model": model_name,
                    "elapsed_seconds": elapsed,
                },
            }
        except HTTPException:
            raise
        except Exception as e:
            elapsed = round(_time.time() - analysis_start, 1)
            logger.error(f"[local coverage] auto_fix_preview 失败(耗时{elapsed}s): {e}")
            return {"code": 500, "message": f"AI 规范重构预览失败: {str(e)[:300]}", "data": None}
        finally:
            import shutil as _shutil
            _shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    async def auto_fix_tests_apply(db: AsyncSession, body: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """AI 规范重构（写回）：将预览返回的文件清单写入仓库本地目录。"""
        repo_id = body.get("repo_id")
        files = body.get("files") or []
        if not isinstance(files, list) or not files:
            return {"code": 400, "message": "缺少 files 文件清单", "data": None}

        if repo_id:
            repo_result = await db.execute(
                select(NtestRepositoryModel).where(
                    NtestRepositoryModel.id == repo_id,
                    NtestRepositoryModel.enabled_flag == 1,
                )
            )
            repo = repo_result.scalar_one_or_none()
            if not repo:
                return {"code": 400, "message": "仓库不存在", "data": None}
            effective_path = repo.local_path or repo.html_url or ""
        else:
            effective_path = body.get("local_path") or body.get("repo_url") or body.get("html_url", "")

        if not effective_path or not os.path.isdir(effective_path):
            return {"code": 400, "message": "仅支持写回本地目录仓库", "data": None}

        written: List[str] = []
        skipped: List[str] = []
        for item in files:
            path = (item.get("path") or "").strip().replace("\\", "/")
            content = item.get("content") or ""
            if not path or not content:
                continue
            parts = path.split("/")
            if path.startswith("/") or any(p in (".", "..") for p in parts):
                skipped.append(path)
                continue
            abs_path = os.path.join(effective_path, path)
            try:
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                Path(abs_path).write_text(content, encoding="utf-8")
                written.append(path)
            except Exception as e:
                skipped.append(f"{path}: {str(e)[:100]}")

        return {
            "code": 200,
            "data": {
                "written": written,
                "skipped": skipped,
                "written_count": len(written),
                "repo_path": effective_path,
            },
        }

    @staticmethod
    def _extract_json_object(text: str) -> Optional[dict]:
        """从 LLM 文本中容错提取首个 JSON 对象。"""
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
