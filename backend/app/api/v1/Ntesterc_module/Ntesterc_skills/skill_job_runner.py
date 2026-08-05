# -*- coding: utf-8 -*-
"""Skill 异步任务执行器：将 pending 任务在本机拉起子进程并写入事件流与产物索引。"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.Ntesterc_module.Ntesterc_skills.execution_model import SkillExecutionArtifactModel, SkillExecutionEventModel, SkillExecutionJobModel
from app.api.v1.Ntesterc_module.Ntesterc_skills.model import ProjectSkillModel
from app.infra.db import sqlalchemy as db_sa


async def _next_event_seq(db: AsyncSession, job_id: int) -> int:
    r = (await db.execute(select(func.max(SkillExecutionEventModel.seq)).where(SkillExecutionEventModel.job_id == job_id))).scalar()
    return int(r or 0) + 1


async def _append_event(db: AsyncSession, job_id: int, level: str, message: str, user_id: int) -> None:
    seq = await _next_event_seq(db, job_id)
    db.add(
        SkillExecutionEventModel(
            job_id=job_id,
            seq=seq,
            level=level,
            message=message[:65000],
            created_by=user_id,
            updated_by=user_id,
        )
    )
    await db.commit()


async def run_skill_job_worker(job_id: int) -> None:
    """
    独立 DB 会话中执行单个 job（勿在请求会话内 await，避免阻塞）。
    """
    from app.api.v1.Ntesterc_module.Ntesterc_skills.service import (
        _build_skill_runtime_dirs,
        _collect_files,
        _ingest_saved_outputs,
        _inject_agent_browser_session,
        _smart_decode,
    )

    timeout_s = int(os.getenv("SKILL_JOB_TIMEOUT_SEC", "600"))

    async with db_sa.async_session_factory() as db:
        try:
            job = (
                await db.execute(
                    select(SkillExecutionJobModel).where(
                        SkillExecutionJobModel.id == job_id,
                        SkillExecutionJobModel.enabled_flag == 1,
                    )
                )
            ).scalar_one_or_none()
            if not job or job.status != "pending":
                return

            skill = (
                await db.execute(
                    select(ProjectSkillModel).where(
                        ProjectSkillModel.id == job.skill_id,
                        ProjectSkillModel.enabled_flag == 1,
                    )
                )
            ).scalar_one_or_none()
            if not skill:
                await db.execute(
                    update(SkillExecutionJobModel)
                    .where(SkillExecutionJobModel.id == job_id)
                    .values(status="failed", finished_at=datetime.now(), error_message="技能不存在或已删除", updated_by=job.user_id)
                )
                await db.commit()
                return

            skill_dir = Path(skill.skill_path or "")
            if not skill_dir.exists():
                await db.execute(
                    update(SkillExecutionJobModel)
                    .where(SkillExecutionJobModel.id == job_id)
                    .values(status="failed", finished_at=datetime.now(), error_message="技能目录不存在，请重新上传/导入", updated_by=job.user_id)
                )
                await db.commit()
                return

            cmd = (job.command or "").strip()
            cmd = _inject_agent_browser_session(cmd, job.session_id)
            if not cmd:
                await db.execute(
                    update(SkillExecutionJobModel)
                    .where(SkillExecutionJobModel.id == job_id)
                    .values(status="failed", finished_at=datetime.now(), error_message="任务命令为空", updated_by=job.user_id)
                )
                await db.commit()
                return

            rt = (job.runner_type or "local").strip().lower()
            if rt == "docker":
                await _append_event(db, job_id, "warn", "docker runner 未接入，已回退为 local 执行", job.user_id)

            await db.execute(
                update(SkillExecutionJobModel)
                .where(SkillExecutionJobModel.id == job_id, SkillExecutionJobModel.status == "pending")
                .values(status="running", started_at=datetime.now(), updated_by=job.user_id)
            )
            await db.commit()
            await _append_event(db, job_id, "info", f"开始执行: {cmd[:2000]}", job.user_id)

            screenshots_dir, artifacts_dir = _build_skill_runtime_dirs(int(job.project_id), str(job.runtime_key))
            env = os.environ.copy()
            env["SCREENSHOT_DIR"] = str(screenshots_dir)
            env["SKILL_OUTPUT_DIR"] = str(artifacts_dir)
            env["ARTIFACT_DIR"] = str(artifacts_dir)
            env["SKILL_ARGS_JSON"] = json.dumps(job.input_args or {}, ensure_ascii=False)
            env["SKILL_SESSION_ID"] = str(job.runtime_key)
            env["PROJECT_ID"] = str(job.project_id)
            env["USER_ID"] = str(job.user_id)

            extra = skill.extra_config or {}
            workdir = (extra.get("workdir") or "").strip()
            cwd = skill_dir
            if workdir:
                wd = Path(workdir)
                if not wd.is_absolute():
                    pack_root = Path(str(extra.get("pack_root") or "")).resolve() if extra.get("pack_root") else None
                    base = pack_root if pack_root and pack_root.exists() else skill_dir
                    wd = (base / workdir).resolve()
                if wd.exists():
                    cwd = wd

            # 实时流式执行：用 asyncio 子进程逐行读取 stdout/stderr 并写入事件流，
            # 使外部 Agent（Claude Code / Codex / OpenCode 等）的思考/工具流可在前端 SSE 实时呈现。
            out_text, err_text, rc = await _run_streaming(
                job_id=job_id,
                cmd=cmd,
                cwd=str(cwd),
                env=env,
                user_id=job.user_id,
                db=db,
                timeout_s=timeout_s,
            )

            ok = rc == 0
            final_status = "succeeded" if ok else "failed"

            await db.execute(
                update(SkillExecutionJobModel)
                .where(SkillExecutionJobModel.id == job_id)
                .values(
                    status=final_status,
                    finished_at=datetime.now(),
                    return_code=rc,
                    stdout=(out_text or "").strip()[:24000],
                    stderr=(err_text or "").strip()[:12000],
                    updated_by=job.user_id,
                )
            )
            await db.commit()

            _ingest_saved_outputs(out_text, err_text, cwd, screenshots_dir)

            # 产物索引（与下载接口路径一致）；外部 Agent 还会在 cwd 产出 specs/tests/.ad 等，也一并复制进产物目录
            _collect_external_outputs(Path(str(cwd)), artifacts_dir)
            for kind, base in (("screenshots", screenshots_dir), ("artifacts", artifacts_dir)):
                for it in _collect_files(base):
                    db.add(_artifact_row(job_id, kind, it, job.user_id))
            await db.commit()
            await _append_event(db, job_id, "info", f"任务结束: {final_status} rc={rc}", job.user_id)
        except Exception as e:
            logger.exception("run_skill_job_worker fatal job_id={}", job_id)
            try:
                await db.execute(
                    update(SkillExecutionJobModel)
                    .where(SkillExecutionJobModel.id == job_id)
                    .values(status="failed", finished_at=datetime.now(), error_message=str(e)[:2000], updated_by=1)
                )
                await db.commit()
            except Exception:
                await db.rollback()


def _artifact_row(job_id: int, kind: str, it: dict, user_id: int) -> SkillExecutionArtifactModel:
    return SkillExecutionArtifactModel(
        job_id=job_id,
        kind=kind,
        name=it["name"],
        relative_path=it["relative_path"],
        size=it.get("size"),
        created_by=user_id,
        updated_by=user_id,
    )


MAX_EXT_ARTIFACT_BYTES = 2_000_000
EXT_ARTIFACT_DIRS = {"specs", "tests", "e2e", "playwright-report", "test-results"}


def _collect_external_outputs(cwd: Path, artifacts_dir: Path) -> None:
    """
    将外部 Agent 在 cwd 产出的关键文件（specs/*.md、tests/*.spec.ts、*.ad 录制脚本、
    Playwright 报告等）复制到 artifacts_dir，使它们可被现有产物下载接口检索。
    """
    if not cwd.exists():
        return
    count = 0
    for root, dirs, files in os.walk(cwd):
        rel_root = Path(root).relative_to(cwd)
        if len(rel_root.parts) > 4:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "coverage", ".next"}]
        for f in files:
            if count >= 400:
                return
            fp = Path(root) / f
            low = f.lower()
            in_allowed = bool(rel_root.parts) and rel_root.parts[0] in EXT_ARTIFACT_DIRS
            keep = in_allowed and (
                low.endswith(".md") or low.endswith(".spec.ts") or low.endswith(".ad") or low.endswith(".ts")
            )
            if not keep:
                continue
            try:
                if fp.stat().st_size > MAX_EXT_ARTIFACT_BYTES:
                    continue
            except Exception:
                continue
            dest = artifacts_dir / rel_root / f
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(fp, dest)
            except Exception:
                continue
            count += 1


async def _flush_pending(db, job_id: int, user_id: int, pending: list) -> None:
    for level, text in pending:
        await _append_event(db, job_id, level, text[:8000], user_id)


async def _run_streaming(
    *, job_id: int, cmd: str, cwd: str, env: dict, user_id: int, db, timeout_s: int
) -> tuple:
    """
    asyncio 子进程逐行流式执行。返回 (stdout, stderr, return_code)。
    每个 Agent 输出行实时写入事件表，供前端 SSE 轮询实时呈现（替代原 capture_output 全缓冲）。
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:  # 命令无法启动（如二进制不存在）
        logger.exception("external agent subprocess spawn failed job_id={}", job_id)
        await db.execute(
            update(SkillExecutionJobModel)
            .where(SkillExecutionJobModel.id == job_id)
            .values(status="failed", finished_at=datetime.now(), error_message=f"进程启动失败: {e}", updated_by=user_id)
        )
        await db.commit()
        await _append_event(db, job_id, "error", f"进程启动失败: {e}", user_id)
        return "", str(e), -1

    out_chunks: list = []
    err_chunks: list = []
    pending: list = []

    async def _pump(stream, sink, level):
        try:
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                text = _smart_decode(raw).rstrip("\n").rstrip("\r")
                sink.append(text)
                pending.append((level, text))
                if len(pending) >= 25:
                    await _flush_pending(db, job_id, user_id, pending)
                    pending.clear()
        except Exception:
            pass

    t_out = asyncio.create_task(_pump(proc.stdout, out_chunks, "info"))
    t_err = asyncio.create_task(_pump(proc.stderr, err_chunks, "error"))
    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        timed_out = True
        try:
            proc.kill()
        except Exception:
            pass
        try:
            await proc.wait()
        except Exception:
            pass
    await t_out
    await t_err
    if pending:
        await _flush_pending(db, job_id, user_id, pending)
        pending.clear()

    rc = int(proc.returncode)
    out_text = "\n".join(out_chunks)
    err_text = "\n".join(err_chunks)

    if timed_out:
        await db.execute(
            update(SkillExecutionJobModel)
            .where(SkillExecutionJobModel.id == job_id)
            .values(
                status="failed",
                finished_at=datetime.now(),
                return_code=-1,
                error_message=f"执行超时（>{timeout_s}s）",
                updated_by=user_id,
            )
        )
        await db.commit()
        await _append_event(db, job_id, "error", f"超时 >{timeout_s}s", user_id)
        return out_text, err_text, -1

    return out_text, err_text, rc


def schedule_skill_job(job_id: int) -> None:
    """在事件循环中调度异步 worker（非阻塞）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(run_skill_job_worker(job_id))
        return

    def _done(t: asyncio.Task) -> None:
        try:
            t.result()
        except Exception as e:
            logger.warning("skill job task exception: {}", e)

    task = loop.create_task(run_skill_job_worker(job_id))
    task.add_done_callback(_done)
