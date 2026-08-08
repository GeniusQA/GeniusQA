#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: Rebort

from typing import Any, Dict, List, Optional

import asyncio
import json
from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_user_id
from app.infra.db.sqlalchemy import get_db
from app.api.v1.Ntesterc_module.Ntesterc_skills import service as S
from app.api.v1.Ntesterc_module.Ntesterc_skills.execution_model import SkillExecutionEventModel, SkillExecutionJobModel, SkillExecutionArtifactModel
from sqlalchemy import select

router = APIRouter(tags=["Skill管理"])


@router.get("/projects/{project_id}", summary="Skill 列表")
async def list_skills(
    project_id: int,
    search: str = Query("", description="名称搜索"),
    scenario_category: str = Query("", description="场景分类"),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.list_skills(project_id, current_user_id, db, search, scenario_category, is_active, page, page_size)


@router.post("/projects/{project_id}", summary="创建 Skill")
async def create_skill(
    project_id: int,
    data: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.create_skill(project_id, current_user_id, db, data)


@router.put("/projects/{project_id}/{skill_id}", summary="更新 Skill")
async def update_skill(
    project_id: int,
    skill_id: int,
    data: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.update_skill(project_id, current_user_id, skill_id, db, data)


@router.delete("/projects/{project_id}/{skill_id}", summary="删除 Skill")
async def delete_skill(
    project_id: int,
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.delete_skill(project_id, current_user_id, skill_id, db)


@router.post("/projects/{project_id}/batch-delete", summary="批量删除 Skill（硬删+清理本地目录）")
async def batch_delete_skills(
    project_id: int,
    data: Dict[str, Any] = Body({}),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    skill_ids = data.get("skill_ids") if isinstance(data.get("skill_ids"), list) else None
    delete_all = bool(data.get("delete_all"))
    return await S.batch_delete_skills(
        project_id,
        current_user_id,
        db,
        skill_ids=skill_ids,
        delete_all=delete_all,
    )


@router.post("/projects/{project_id}/import/git", summary="从Git仓库导入 Skill")
async def import_skill_git(
    project_id: int,
    data: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.import_skill_from_git(project_id, current_user_id, db, data)


@router.post("/projects/{project_id}/import/git/preview", summary="预览 Git 仓库中的 Skill（不写入数据库）")
async def preview_skill_git(
    project_id: int,
    data: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.preview_skill_from_git(project_id, current_user_id, db, data)


@router.post("/projects/{project_id}/import/git/selected", summary="按勾选结果导入 Git 仓库中的 Skill")
async def import_skill_git_selected(
    project_id: int,
    data: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.import_selected_skills(project_id, current_user_id, db, data)


@router.post("/projects/{project_id}/import/upload", summary="上传zip导入 Skill")
async def import_skill_upload(
    project_id: int,
    file: UploadFile = File(...),
    scenario_category: Optional[str] = Query(None, description="场景分类"),
    entry_command: Optional[str] = Query(None, description="执行命令"),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.import_skill_from_upload(project_id, current_user_id, db, file, scenario_category, entry_command)


@router.post("/projects/{project_id}/import/upload-folder", summary="上传本地文件夹导入 Skill")
async def import_skill_folder(
    project_id: int,
    files: List[UploadFile] = File(...),
    paths: Optional[List[str]] = Form(None),
    scenario_category: Optional[str] = Query(None, description="场景分类"),
    entry_command: Optional[str] = Query(None, description="执行命令"),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.import_skill_from_folder(project_id, current_user_id, db, files, paths, scenario_category, entry_command)


@router.get("/projects/{project_id}/skills/local-claude", summary="列出本机 Claude Code Skill")
async def list_local_claude_skills(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.list_local_claude_skills(project_id, current_user_id, db)


@router.post("/projects/{project_id}/skills/import-local-claude", summary="导入本机 Claude Code Skill")
async def import_local_claude_skill(
    project_id: int,
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.import_local_claude_skill(project_id, current_user_id, db, data)


@router.get("/projects/{project_id}/{skill_id}/content", summary="读取 Skill 目录结构与文件内容")
async def get_skill_content(
    project_id: int,
    skill_id: int,
    file_path: Optional[str] = Query(None, description="相对技能目录的文件路径，默认 SKILL.md"),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.get_skill_content(project_id, current_user_id, skill_id, db, file_path=file_path)


@router.get("/projects/{project_id}/{skill_id}/manifest", summary="读取 Skill 清单（工具/模板）")
async def get_skill_manifest(
    project_id: int,
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.get_skill_manifest(project_id, current_user_id, skill_id, db)


@router.post("/projects/{project_id}/{skill_id}/execute", summary="执行 Skill")
async def execute_skill(
    project_id: int,
    skill_id: int,
    data: Dict[str, Any] = Body({}),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.execute_skill(project_id, current_user_id, skill_id, db, data)


@router.post("/projects/{project_id}/{skill_id}/actions/execute", summary="创建 Skill 执行任务（异步）")
async def execute_skill_action_async(
    project_id: int,
    skill_id: int,
    data: Dict[str, Any] = Body({}),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.create_skill_job(
        project_id,
        current_user_id,
        db,
        skill_id=skill_id,
        action_name=data.get("action_name"),
        arguments=data.get("arguments") if isinstance(data.get("arguments"), dict) else {},
        session_id=data.get("session_id"),
        runner_type=data.get("runner_type"),
    )


@router.get("/projects/{project_id}/jobs/{job_id}", summary="查询 Skill 执行任务")
async def get_skill_job(
    project_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.get_skill_job(project_id, current_user_id, db, job_id)


@router.post("/projects/{project_id}/jobs/{job_id}/cancel", summary="取消 Skill 执行任务")
async def cancel_skill_job(
    project_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.cancel_skill_job(project_id, current_user_id, db, job_id)


@router.get("/projects/{project_id}/jobs/{job_id}/artifacts", summary="查询 Skill 执行产物")
async def get_skill_job_artifacts(
    project_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.list_job_artifacts(project_id, current_user_id, db, job_id)


# ===== 外部编程 Agent 集成（Claude Code / Codex / OpenCode 驱动 Playwright Test Agents / agent-device）=====


@router.get("/projects/{project_id}/external-agent/harness", summary="探测本机可用的外部 Agent 二进制")
async def external_agent_harness(
    project_id: int,
    custom_agents: Optional[str] = Query(None, description="逗号分隔的自定义 Agent 名称，与默认 Agent 一起探测"),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    names = [x.strip() for x in custom_agents.split(",") if x.strip()] if custom_agents else None
    return await S.detect_external_agents(project_id, current_user_id, db, custom_agents=names)


@router.post("/projects/{project_id}/pw-test-agents/scaffold", summary="Playwright Test Agents 脚手架（init-agents --loop）")
async def pw_test_agents_scaffold(
    project_id: int,
    data: Dict[str, Any] = Body({}),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.scaffold_pw_test_agents(project_id, current_user_id, db, data)


@router.post("/projects/{project_id}/agent-device/register", summary="注册 agent-device 为 MCP server")
async def agent_device_register(
    project_id: int,
    data: Dict[str, Any] = Body({}),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.register_agent_device_mcp(project_id, current_user_id, db, data)


@router.post("/projects/{project_id}/external-agent/run", summary="创建外部 Agent 执行任务（驱动 Playwright Test Agents / agent-device）")
async def external_agent_run(
    project_id: int,
    data: Dict[str, Any] = Body({}),
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return await S.run_external_agent_job(project_id, current_user_id, db, data)


@router.get("/projects/{project_id}/jobs/{job_id}/stream", summary="Skill 执行流（SSE）")
async def stream_skill_job(
    project_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # Validate ownership
    stmt = select(SkillExecutionJobModel).where(
        SkillExecutionJobModel.id == job_id,
        SkillExecutionJobModel.project_id == project_id,
        SkillExecutionJobModel.user_id == current_user_id,
        SkillExecutionJobModel.enabled_flag == 1,
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        return StreamingResponse(iter([b"event: error\ndata: {}\n\n"]), media_type="text/event-stream")

    async def gen():
        last_seq = 0
        # initial hello
        yield f"event: hello\ndata: {json.dumps({'job_id': job_id})}\n\n"
        while True:
            rows = (
                await db.execute(
                    select(SkillExecutionEventModel)
                    .where(
                        SkillExecutionEventModel.job_id == job_id,
                        SkillExecutionEventModel.seq > last_seq,
                        SkillExecutionEventModel.enabled_flag == 1,
                    )
                    .order_by(SkillExecutionEventModel.seq.asc())
                    .limit(200)
                )
            ).scalars().all()
            for r in rows:
                last_seq = int(r.seq)
                payload = {"seq": int(r.seq), "level": r.level, "message": r.message, "ts": r.ts.isoformat() if r.ts else None}
                yield f"event: log\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

            # refresh job status
            j = (await db.execute(select(SkillExecutionJobModel).where(SkillExecutionJobModel.id == job_id))).scalar_one()
            if j.status in ("succeeded", "failed", "cancelled"):
                done_payload = {"status": j.status, "return_code": j.return_code}
                yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"
                break

            # keepalive
            yield "event: ping\ndata: {}\n\n"
            await asyncio.sleep(1.2)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/projects/{project_id}/artifacts/{artifact_id}/download", summary="下载 Skill 产物")
async def download_artifact(
    project_id: int,
    artifact_id: int,
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # Find artifact and job
    a = (await db.execute(
        select(SkillExecutionArtifactModel).where(
            SkillExecutionArtifactModel.id == artifact_id,
            SkillExecutionArtifactModel.enabled_flag == 1,
        )
    )).scalar_one_or_none()
    if not a:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="artifact not found")
    job = (await db.execute(
        select(SkillExecutionJobModel).where(
            SkillExecutionJobModel.id == a.job_id,
            SkillExecutionJobModel.project_id == project_id,
            SkillExecutionJobModel.user_id == current_user_id,
            SkillExecutionJobModel.enabled_flag == 1,
        )
    )).scalar_one_or_none()
    if not job:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="job not found")

    from app.api.v1.Ntesterc_module.Ntesterc_skills.service import SKILL_ROOT as _ROOT
    base = _ROOT / "runtime" / ("screenshots" if a.kind == "screenshots" else "artifacts") / str(project_id) / str(job.runtime_key)
    target = (base / str(a.relative_path)).resolve()
    if not str(target).startswith(str(base.resolve())):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path=str(target), filename=a.name)

