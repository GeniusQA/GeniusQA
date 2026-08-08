#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: Rebort

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import HTTPException, UploadFile
from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.Ntesterc_module.Ntesterc_project.service import ProjectService
from app.api.v1.Ntesterc_module.Ntesterc_project.model import ProjectMCPConfigModel
from app.api.v1.Ntesterc_module.Ntesterc_skills.model import ProjectSkillModel
from app.api.v1.Ntesterc_module.Ntesterc_skills.execution_model import SkillExecutionArtifactModel, SkillExecutionEventModel, SkillExecutionJobModel
from app.api.v1.Ntesterc_module.Ntesterc_skills.skill_job_runner import cancel_skill_job as runner_cancel_skill_job, schedule_skill_job
from app.api.v1.Ntesterc_module.Ntesterc_skills import external_agent as EA
from app.common.response import page_response, success_response


def _resolve_skill_root() -> Path:
    """
    解析 skill 文件根目录，优先使用显式环境变量，否则跟随 portable 项目根目录，
    保证无论 uvicorn worker 从哪个目录启动，skill 都稳定落在项目根目录的 uploads/skills 下。
    """
    if os.getenv("SKILL_UPLOAD_DIR"):
        return Path(os.environ["SKILL_UPLOAD_DIR"]).resolve()
    portable_root = (os.environ.get("NT_PORTABLE_ROOT") or "").strip()
    if portable_root:
        return Path(portable_root) / "uploads" / "skills"
    backend_dir = Path(__file__).resolve().parents[5]
    project_root = backend_dir.parent
    return project_root / "uploads" / "skills"


SKILL_ROOT = _resolve_skill_root()
DEFAULT_RUNNER_TYPE = (os.getenv("SKILL_RUNNER_TYPE") or "local").strip().lower()  # local/docker


async def _check_member(project_id: int, user_id: int, db: AsyncSession) -> None:
    await ProjectService._check_project_member(project_id, user_id, db)  # noqa: SLF001


async def _check_role(project_id: int, user_id: int, roles: List[str], db: AsyncSession) -> None:
    await ProjectService._check_project_permission(project_id, user_id, roles, db)  # noqa: SLF001


def _iso(dt) -> Optional[str]:
    if not dt:
        return None
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


def _safe_skill_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "").strip())[:120]


async def _assert_skill_names_available(
    project_id: int,
    user_id: int,
    db: AsyncSession,
    names: List[str],
    *,
    exclude_id: Optional[int] = None,
) -> None:
    """严格校验：同项目同用户下技能名不可重复（大小写不敏感）。"""
    cleaned: List[str] = []
    seen: set[str] = set()
    for raw in names:
        name = (raw or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="技能名称不能为空")
        key = name.lower()
        if key in seen:
            raise HTTPException(status_code=400, detail=f"技能名称重复：{name}")
        seen.add(key)
        cleaned.append(name)

    for name in cleaned:
        stmt = select(ProjectSkillModel).where(
            ProjectSkillModel.project_id == project_id,
            ProjectSkillModel.user_id == user_id,
            func.lower(ProjectSkillModel.name) == name.lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(ProjectSkillModel.id != int(exclude_id))
        existing = list((await db.execute(stmt)).scalars().all())
        actives = [r for r in existing if int(getattr(r, "enabled_flag", 1) or 0) == 1]
        if actives:
            raise HTTPException(status_code=400, detail=f"技能名称已存在，不允许重复：{name}")
        # 清理历史软删残留，避免唯一索引阻断重新导入
        soft_ids = [int(r.id) for r in existing if int(getattr(r, "enabled_flag", 1) or 0) != 1]
        if soft_ids:
            await db.execute(delete(ProjectSkillModel).where(ProjectSkillModel.id.in_(soft_ids)))
            await db.flush()


def _is_under_skill_root(path: Path) -> bool:
    try:
        root = SKILL_ROOT.resolve()
        return path.resolve() == root or root in path.resolve().parents
    except Exception:
        return False


def _remove_skill_filesystem(m: ProjectSkillModel, sibling_pack_roots: set[str]) -> None:
    """删除技能对应本地目录；共享 pack_root 时仅在无其他引用时删除包根。"""
    skill_path = Path(str(m.skill_path or "").strip()) if m.skill_path else None
    extra = m.extra_config if isinstance(m.extra_config, dict) else {}
    pack_root_raw = str(extra.get("pack_root") or "").strip()
    pack_root = Path(pack_root_raw) if pack_root_raw else None

    if pack_root and pack_root_raw in sibling_pack_roots:
        # 仍有其他技能引用同一 pack，只删本技能子目录（若独立）
        if skill_path and skill_path.exists() and _is_under_skill_root(skill_path):
            try:
                if skill_path.resolve() != pack_root.resolve() and pack_root.resolve() in skill_path.resolve().parents:
                    shutil.rmtree(skill_path, ignore_errors=True)
            except Exception:
                shutil.rmtree(skill_path, ignore_errors=True)
        return

    # 无共享引用：优先删 pack_root，否则删 skill_path
    target = None
    if pack_root and pack_root.exists() and _is_under_skill_root(pack_root):
        target = pack_root
    elif skill_path and skill_path.exists() and _is_under_skill_root(skill_path):
        target = skill_path
    if target is not None:
        shutil.rmtree(target, ignore_errors=True)


def _build_dir_tree(base: Path, *, max_depth: int = 6, max_entries: int = 800) -> List[dict]:
    """构建目录树，供前端展示。"""
    if not base.exists():
        return []
    count = 0

    def walk(cur: Path, depth: int) -> List[dict]:
        nonlocal count
        if depth > max_depth or count >= max_entries:
            return []
        nodes: List[dict] = []
        try:
            entries = sorted(cur.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except Exception:
            return []
        for p in entries:
            if count >= max_entries:
                break
            # 跳过常见噪声目录
            if p.name in {".git", "__pycache__", "node_modules", ".venv", "venv"}:
                continue
            count += 1
            rel = str(p.relative_to(base)).replace("\\", "/")
            if p.is_dir():
                nodes.append({
                    "name": p.name,
                    "path": rel,
                    "type": "dir",
                    "children": walk(p, depth + 1),
                })
            else:
                try:
                    size = p.stat().st_size
                except Exception:
                    size = 0
                nodes.append({
                    "name": p.name,
                    "path": rel,
                    "type": "file",
                    "size": size,
                })
        return nodes

    return walk(base, 0)


def _read_skill_file(skill_dir: Path, relative: str, *, max_bytes: int = 512_000) -> str:
    rel = (relative or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(status_code=400, detail="非法文件路径")
    target = (skill_dir / rel).resolve()
    if not _is_under_skill_root(target) and skill_dir.resolve() not in target.parents and target != skill_dir.resolve():
        # must stay under skill_dir
        try:
            target.relative_to(skill_dir.resolve())
        except Exception:
            raise HTTPException(status_code=400, detail="文件不在技能目录内")
    try:
        target.relative_to(skill_dir.resolve())
    except Exception:
        raise HTTPException(status_code=400, detail="文件不在技能目录内")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    data = target.read_bytes()[:max_bytes]
    try:
        return data.decode("utf-8")
    except Exception:
        return data.decode("utf-8", errors="replace")


def _parse_skill_description(skill_dir: Path) -> str:
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return ""
    try:
        text = md.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            return s.lstrip("#").strip()[:255]
        return s[:255]
    return ""


def _parse_skill_md(md_path: Path) -> dict:
    """
    Parse SKILL.md with optional YAML-like frontmatter:
    ---
    name: xxx
    description: yyy
    allowed-tools: Bash(cmd1), Bash(cmd2)
    ---
    """
    try:
        text = md_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].strip() == "---":
        meta = {}
        i = 1
        while i < len(lines):
            if lines[i].strip() == "---":
                break
            line = lines[i].strip()
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
            i += 1
        return meta
    return {}


def _scan_skill_pack(repo_dir: Path) -> List[dict]:
    """
    Scan repo_dir/skills/**/SKILL.md and return list of skill dict:
    {name, description, allowed_tools, skill_dir}
    """
    skills_dir = repo_dir / "skills"
    if not skills_dir.exists():
        return []
    items = []
    for md in skills_dir.rglob("SKILL.md"):
        meta = _parse_skill_md(md)
        name = (meta.get("name") or md.parent.name).strip()
        desc = (meta.get("description") or "").strip() or _parse_skill_description(md.parent)
        allowed = (meta.get("allowed-tools") or meta.get("allowed_tools") or "").strip()
        items.append(
            {
                "name": name,
                "description": desc,
                "allowed_tools": allowed,
                "skill_dir": md.parent,
            }
        )
    return items


def _build_skill_runtime_dirs(project_id: int, session_key: str) -> tuple[Path, Path]:
    screenshots_dir = SKILL_ROOT / "runtime" / "screenshots" / str(project_id) / session_key
    artifacts_dir = SKILL_ROOT / "runtime" / "artifacts" / str(project_id) / session_key
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return screenshots_dir, artifacts_dir


def _collect_files(base_dir: Path) -> List[dict]:
    if not base_dir.exists():
        return []
    files: List[dict] = []
    for p in base_dir.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(base_dir)).replace("\\", "/")
            files.append({"name": p.name, "relative_path": rel, "size": p.stat().st_size})
    return files


def _list_templates(skill_dir: Path) -> List[dict]:
    tdir = skill_dir / "templates"
    if not tdir.exists():
        return []
    items: List[dict] = []
    for p in sorted(tdir.glob("*")):
        if p.is_file():
            items.append({"name": p.name, "relative_path": f"templates/{p.name}", "size": p.stat().st_size})
    return items


def _quote_cmd_arg(value: str) -> str:
    # Compatible with cmd/powershell shell parsing for common paths/args
    return '"' + str(value).replace('"', '\\"') + '"'


def _smart_decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


def _inject_agent_browser_session(command: str, session_id: Optional[str]) -> str:
    cmd = (command or "").strip()
    sid = (session_id or "").strip()
    if not cmd or not sid:
        return cmd
    # Already has session options
    if re.search(r"--session-name\s+\S+|--session\s+\S+", cmd, flags=re.IGNORECASE):
        return cmd
    # npx agent-browser ...
    cmd = re.sub(
        r"\bnpx\s+agent-browser\b",
        f"npx agent-browser --session-name {sid}",
        cmd,
        count=1,
        flags=re.IGNORECASE,
    )
    # agent-browser ...
    cmd = re.sub(
        r"(?<!npx\s)\bagent-browser\b",
        f"agent-browser --session-name {sid}",
        cmd,
        count=1,
        flags=re.IGNORECASE,
    )
    return cmd


def _resolve_skill_command(
    *,
    entry_command: str,
    skill_dir: Path,
    arguments: Optional[dict],
) -> str:
    cmd = (entry_command or "").strip()
    if cmd:
        return cmd
    args = arguments or {}
    override_cmd = str(args.get("command") or args.get("__command") or "").strip()
    if override_cmd:
        return override_cmd

    template = str(args.get("template") or "").strip()
    if template:
        template_name = Path(template).name
        template_path = skill_dir / "templates" / template_name
        if not template_path.exists() or not template_path.is_file():
            raise HTTPException(status_code=400, detail=f"模板不存在: {template_name}")
        template_args = args.get("template_args")
        if not isinstance(template_args, list):
            template_args = []
        tail = " ".join(_quote_cmd_arg(str(x)) for x in template_args)
        # agent-browser templates are shell scripts; run with bash explicitly.
        if template_path.suffix.lower() == ".sh":
            return f"bash {_quote_cmd_arg(str(template_path))}" + (f" {tail}" if tail else "")
        return _quote_cmd_arg(str(template_path)) + (f" {tail}" if tail else "")

    return ""


async def get_skill_manifest(project_id: int, user_id: int, skill_id: int, db: AsyncSession) -> dict:
    await _check_member(project_id, user_id, db)
    stmt = select(ProjectSkillModel).where(
        ProjectSkillModel.id == skill_id,
        ProjectSkillModel.project_id == project_id,
        ProjectSkillModel.user_id == user_id,
        ProjectSkillModel.enabled_flag == 1,
    )
    m = (await db.execute(stmt)).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="技能不存在")
    skill_dir = Path(m.skill_path or "")
    extra = m.extra_config or {}
    allowed = (extra.get("allowed_tools") or "").strip()
    templates = _list_templates(skill_dir) if skill_dir.exists() else []
    return success_response(
        data={
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "scenario_category": m.scenario_category,
            "source_type": m.source_type,
            "repo_url": m.repo_url,
            "skill_path": m.skill_path,
            "entry_command": m.entry_command,
            "is_active": m.is_active,
            "allowed_tools": allowed,
            "templates": templates,
            "extra_config": extra,
        },
        message="查询成功",
    )


async def list_skills(
    project_id: int,
    user_id: int,
    db: AsyncSession,
    search: str = "",
    scenario_category: str = "",
    is_active: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    await _check_member(project_id, user_id, db)
    q = select(ProjectSkillModel).where(
        ProjectSkillModel.project_id == project_id,
        ProjectSkillModel.user_id == user_id,
        ProjectSkillModel.enabled_flag == 1,
    )
    if search:
        q = q.where(ProjectSkillModel.name.contains(search))
    if scenario_category:
       
        q = q.where(ProjectSkillModel.scenario_category.contains(scenario_category.strip()))
    if is_active is not None:
        q = q.where(ProjectSkillModel.is_active == is_active)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    q = q.order_by(ProjectSkillModel.id.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()
    items = [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "scenario_category": r.scenario_category,
            "source_type": r.source_type,
            "repo_url": r.repo_url,
            "skill_path": r.skill_path,
            "entry_command": r.entry_command,
            "is_active": r.is_active,
            "extra_config": r.extra_config or {},
            "allowed_tools": ((r.extra_config or {}).get("allowed_tools") or ""),
            "created_at": _iso(r.creation_date),
            "updated_at": _iso(r.updation_date),
        }
        for r in rows
    ]
    return page_response(items, total, page, page_size, "查询成功")


async def _remaining_pack_roots(
    project_id: int,
    user_id: int,
    db: AsyncSession,
    exclude_ids: List[int],
) -> set[str]:
    stmt = select(ProjectSkillModel).where(
        ProjectSkillModel.project_id == project_id,
        ProjectSkillModel.user_id == user_id,
        ProjectSkillModel.enabled_flag == 1,
    )
    if exclude_ids:
        stmt = stmt.where(ProjectSkillModel.id.notin_([int(x) for x in exclude_ids]))
    rows = (await db.execute(stmt)).scalars().all()
    roots: set[str] = set()
    for r in rows:
        extra = r.extra_config if isinstance(r.extra_config, dict) else {}
        pr = str(extra.get("pack_root") or "").strip()
        if pr:
            roots.add(pr)
    return roots


async def create_skill(project_id: int, user_id: int, db: AsyncSession, data: dict) -> dict:
    await _check_role(project_id, user_id, ["owner", "admin", "developer"], db)
    name = (data.get("name") or "").strip()
    await _assert_skill_names_available(project_id, user_id, db, [name])
    m = ProjectSkillModel(
        project_id=project_id,
        user_id=user_id,
        name=name,
        description=data.get("description"),
        scenario_category=data.get("scenario_category"),
        source_type=(data.get("source_type") or "builtin").strip().lower(),
        repo_url=data.get("repo_url"),
        skill_path=data.get("skill_path"),
        entry_command=data.get("entry_command"),
        is_active=bool(data.get("is_active", True)),
        extra_config=data.get("extra_config") if isinstance(data.get("extra_config"), dict) else {},
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return success_response(data={"id": m.id}, message="创建成功")


async def update_skill(project_id: int, user_id: int, skill_id: int, db: AsyncSession, data: dict) -> dict:
    await _check_role(project_id, user_id, ["owner", "admin", "developer"], db)
    stmt = select(ProjectSkillModel).where(
        ProjectSkillModel.id == skill_id,
        ProjectSkillModel.project_id == project_id,
        ProjectSkillModel.user_id == user_id,
        ProjectSkillModel.enabled_flag == 1,
    )
    m = (await db.execute(stmt)).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="技能不存在")
    if data.get("name"):
        new_name = str(data["name"]).strip()
        await _assert_skill_names_available(project_id, user_id, db, [new_name], exclude_id=skill_id)
        m.name = new_name
    for f in ("description", "scenario_category", "repo_url", "skill_path", "entry_command"):
        if f in data:
            setattr(m, f, data.get(f))
    if "source_type" in data and data.get("source_type"):
        m.source_type = str(data.get("source_type")).strip().lower()
    if "is_active" in data:
        m.is_active = bool(data.get("is_active"))
    if "extra_config" in data and isinstance(data.get("extra_config"), dict):
        m.extra_config = data.get("extra_config")
    m.updated_by = user_id
    await db.commit()
    await db.refresh(m)
    return success_response(data={"id": m.id}, message="更新成功")


async def delete_skill(project_id: int, user_id: int, skill_id: int, db: AsyncSession) -> dict:
    return await batch_delete_skills(project_id, user_id, db, skill_ids=[skill_id])


async def batch_delete_skills(
    project_id: int,
    user_id: int,
    db: AsyncSession,
    *,
    skill_ids: Optional[List[int]] = None,
    delete_all: bool = False,
) -> dict:
    """删除本地技能目录。"""
    await _check_role(project_id, user_id, ["owner", "admin"], db)
    stmt = select(ProjectSkillModel).where(
        ProjectSkillModel.project_id == project_id,
        ProjectSkillModel.user_id == user_id,
        ProjectSkillModel.enabled_flag == 1,
    )
    if delete_all:
        pass
    else:
        ids = [int(x) for x in (skill_ids or []) if x is not None]
        if not ids:
            raise HTTPException(status_code=400, detail="请选择要删除的技能")
        stmt = stmt.where(ProjectSkillModel.id.in_(ids))
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        raise HTTPException(status_code=404, detail="未找到可删除的技能")

    delete_ids = [int(r.id) for r in rows]
    remaining_packs = await _remaining_pack_roots(project_id, user_id, db, delete_ids)

    snapshots = list(rows)


    job_ids = list(
        (
            await db.execute(
                select(SkillExecutionJobModel.id).where(SkillExecutionJobModel.skill_id.in_(delete_ids))
            )
        ).scalars().all()
    )
    if job_ids:
        await db.execute(delete(SkillExecutionEventModel).where(SkillExecutionEventModel.job_id.in_(job_ids)))
        await db.execute(delete(SkillExecutionArtifactModel).where(SkillExecutionArtifactModel.job_id.in_(job_ids)))
        await db.execute(delete(SkillExecutionJobModel).where(SkillExecutionJobModel.id.in_(job_ids)))

    await db.execute(
        delete(ProjectSkillModel).where(ProjectSkillModel.id.in_(delete_ids))
    )
    await db.commit()
    for m in snapshots:
        _remove_skill_filesystem(m, remaining_packs)
    return success_response(
        data={"deleted": delete_ids, "count": len(delete_ids)},
        message=f"已删除 {len(delete_ids)} 个技能及相关本地目录",
    )


def _normalize_repo_url(url: str) -> str:
    """
    统一仓库 URL：忽略 .git 后缀、尾部斜杠、大小写。
    用于把 https://github.com/obra/superpowers 与 https://github.com/obra/superpowers.git 视为同一仓库。
    """
    s = (url or "").strip().lower()
    if s.endswith(".git"):
        s = s[:-4]
    return s.rstrip("/")


def _git_hash(repo_url: str) -> str:
    """仓库 URL 的 8 位确定性哈希，同一仓库永远得到同一值。"""
    return hashlib.sha256(_normalize_repo_url(repo_url).encode("utf-8")).hexdigest()[:8]


def _find_existing_repo_dir(base_dir: Path, repo_hash: str) -> Optional[Path]:
    """
    查找已存在的同仓库目录（兼容旧版 hash_label 目录名）。
    优先返回同名精确目录，其次是含有 skill 内容的有效 git 目录。
    """
    candidates: list[Path] = []
    for d in base_dir.iterdir():
        if d.is_dir() and d.name.startswith(repo_hash):
            if _is_valid_git_repo(d) and ((d / "skills").exists() or (d / "SKILL.md").exists()):
                candidates.append(d)
    if not candidates:
        return None
    exact = next((c for c in candidates if c.name == repo_hash), None)
    if exact:
        return exact
    # 优先最短名称，减少 URL 类长标签目录被误用
    return sorted(candidates, key=lambda p: (len(p.name), p.name))[0]


def _git_env() -> dict:
    env = os.environ.copy()
    proxy = os.getenv("SKILL_IMPORT_PROXY")
    if proxy:
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    return env


def _run_git(args: List[str], *, cwd: Optional[Path] = None, timeout: int = 240):
    return subprocess.run(
        ["git"] + list(args),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_git_env(),
    )


def _is_valid_git_repo(dst: Path) -> bool:
    return dst.exists() and (dst / ".git").is_dir() and (dst / ".git" / "HEAD").is_file()


def _cleanup_dst_for_resync(dst: Path) -> None:
    """删除目录以便重新克隆；若删除失败（文件被占用）则重命名为 .broken 备份，避免 already exists。"""
    if not dst.exists():
        return
    try:
        shutil.rmtree(dst, ignore_errors=True)
    except Exception:
        pass
    if dst.exists():
        broken = dst.with_name(f"{dst.name}.broken_{int(time.time())}")
        try:
            dst.rename(broken)
        except Exception:
            shutil.rmtree(dst, ignore_errors=True)


def _sync_git_repo(repo_url: str, dst: Path, branch: Optional[str] = None) -> None:
    """
    确保 dst 含有 repo_url 的最新内容。
    - 已存在且是完整 git 仓库时优先原地 fetch + reset --hard 更新；
    - fetch 失败但本地已有内容时保留本地版本（兼容后端 SYSTEM 进程偶发网络问题）；
    - 否则（首次/损坏的 .git）清理后重新浅克隆，支持重试与 HTTP/1.1 降级。
    """
    http11 = ["--config", "http.version=HTTP/1.1"]

    if _is_valid_git_repo(dst):
        try:
            fetch = _run_git(["fetch", "--depth", "1", "origin"] + http11, cwd=dst, timeout=180)
            if fetch.returncode == 0:
                _run_git(["reset", "--hard", "FETCH_HEAD"] + http11, cwd=dst)
                _run_git(["clean", "-fd"], cwd=dst)
                return
            logger.warning(f"git fetch 失败: {fetch.stderr or fetch.stdout}")
        except Exception as e:
            logger.warning(f"git 原地更新异常: {e}")
        # 本地已有 skill 内容则保留，避免网络抖动导致导入失败
        if (dst / "skills").exists() or (dst / "SKILL.md").exists():
            logger.info(f"保留本地仓库内容: {dst}")
            return
        logger.warning("本地仓库无有效内容，将重新克隆")

    # 非有效仓库或更新失败 -> 清理后克隆（带重试）
    _cleanup_dst_for_resync(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    clone_args = ["clone", "--depth", "1"] + http11
    if branch:
        clone_args += ["--branch", branch]
    clone_args += [repo_url, str(dst)]

    last_err = ""
    for attempt in range(1, 4):
        cp = _run_git(clone_args, timeout=240)
        if cp.returncode == 0:
            return
        last_err = (cp.stderr or cp.stdout or "unknown").strip()
        logger.warning(f"git clone 第 {attempt} 次失败: {last_err}")
        if attempt < 3:
            time.sleep(2 ** attempt)
    _cleanup_dst_for_resync(dst)
    raise HTTPException(status_code=400, detail=f"拉取仓库失败: {last_err}")


async def _get_enabled_skills_by_repo(
    project_id: int, user_id: int, repo_url: str, db: AsyncSession
) -> dict:
    """返回 {name.lower(): model}，用于重复导入时原地更新而非新建。按规范化后的 repo_url 匹配。"""
    norm_target = _normalize_repo_url(repo_url)
    stmt = select(ProjectSkillModel).where(
        ProjectSkillModel.project_id == project_id,
        ProjectSkillModel.user_id == user_id,
        ProjectSkillModel.enabled_flag == 1,
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {(r.name or "").lower(): r for r in rows if _normalize_repo_url(r.repo_url or "") == norm_target}


async def import_skill_from_git(project_id: int, user_id: int, db: AsyncSession, data: dict) -> dict:
    await _check_role(project_id, user_id, ["owner", "admin", "developer"], db)
    repo_url = str(data.get("repo_url") or "").strip()
    if not repo_url:
        raise HTTPException(status_code=400, detail="repo_url 不能为空")
    scenario_category = (data.get("scenario_category") or "").strip() or None
    name = _safe_skill_name(str(data.get("name") or Path(repo_url).stem or "skill"))
    base_dir = SKILL_ROOT / str(project_id) / str(user_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    # 目录只由仓库 hash 决定：无论分类/名称怎么填，同一仓库永远复用同一目录
    repo_hash = _git_hash(repo_url)
    dst = _find_existing_repo_dir(base_dir, repo_hash) or (base_dir / repo_hash)

    try:
        _sync_git_repo(repo_url, dst, branch=data.get("branch"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"拉取仓库失败: {e}")

    source_type = "gitee" if "gitee.com" in repo_url else "github" if "github.com" in repo_url else "git"
    entry_command = str(data.get("entry_command") or "").strip() or None
    existing = await _get_enabled_skills_by_repo(project_id, user_id, repo_url, db)

    created_ids: List[int] = []
    updated_ids: List[int] = []
    new_records: List[ProjectSkillModel] = []

    def _build_extra(*, pack_root: Optional[str] = None, allowed_tools: str = "", fallback: Optional[dict] = None) -> dict:
        extra = dict(fallback) if isinstance(fallback, dict) else {}
        if pack_root:
            extra["pack_root"] = pack_root
        if allowed_tools:
            extra["allowed_tools"] = allowed_tools
        return extra

    def _prepare_record(skill_name: str, skill_path: str, description, extra: dict) -> None:
        rec = existing.pop(skill_name.lower(), None)
        if rec is not None:
            # 该技能已存在且来源相同 -> 原地更新
            rec.skill_path = skill_path
            rec.description = description
            rec.scenario_category = scenario_category or rec.scenario_category or skill_name
            rec.source_type = source_type
            rec.repo_url = repo_url
            rec.entry_command = entry_command
            rec.extra_config = extra
            rec.updated_by = user_id
            updated_ids.append(int(rec.id))
            return
        # 新建记录（稍后批量校验名称并写入）
        new_records.append(
            ProjectSkillModel(
                project_id=project_id,
                user_id=user_id,
                name=skill_name,
                description=description,
                scenario_category=scenario_category or skill_name,
                source_type=source_type,
                repo_url=repo_url,
                skill_path=skill_path,
                entry_command=entry_command,
                is_active=True,
                extra_config=extra,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    try:
        pack = _scan_skill_pack(dst)
        if pack:
            for item in pack:
                skill_name = _safe_skill_name(item["name"])
                extra = _build_extra(
                    pack_root=str(dst),
                    allowed_tools=item.get("allowed_tools") or "",
                )
                _prepare_record(skill_name, str(item["skill_dir"]), item.get("description"), extra)
        else:
            extra = _build_extra(fallback=data.get("extra_config") if isinstance(data.get("extra_config"), dict) else {})
            _prepare_record(
                name,
                str(dst),
                str(data.get("description") or _parse_skill_description(dst)),
                extra,
            )

        if new_records:
            new_names = [m.name for m in new_records]
            await _assert_skill_names_available(project_id, user_id, db, new_names)
            for m in new_records:
                db.add(m)

        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    created_ids = [int(m.id) for m in new_records]
    total = created_ids + updated_ids
    msg = "导入成功"
    if created_ids and updated_ids:
        msg = f"导入成功（新增 {len(created_ids)} 个，更新 {len(updated_ids)} 个）"
    elif updated_ids and not created_ids:
        msg = f"导入成功（已更新 {len(updated_ids)} 个，目录原地刷新）"
    elif created_ids and not updated_ids:
        msg = f"导入成功（新增 {len(created_ids)} 个）"
    return success_response(
        data={"created": created_ids, "updated": updated_ids, "count": len(total)},
        message=msg,
    )


async def preview_skill_from_git(project_id: int, user_id: int, db: AsyncSession, data: dict) -> dict:
    """拉取仓库并扫描其中所有 Skill，但**不写入数据库**，返回预览列表供前端勾选。"""
    await _check_role(project_id, user_id, ["owner", "admin", "developer"], db)
    repo_url = str(data.get("repo_url") or "").strip()
    if not repo_url:
        raise HTTPException(status_code=400, detail="repo_url 不能为空")
    base_dir = SKILL_ROOT / str(project_id) / str(user_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    repo_hash = _git_hash(repo_url)
    dst = _find_existing_repo_dir(base_dir, repo_hash) or (base_dir / repo_hash)

    try:
        _sync_git_repo(repo_url, dst, branch=data.get("branch"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"拉取仓库失败: {e}")

    existing = await _get_enabled_skills_by_repo(project_id, user_id, repo_url, db)
    pack = _scan_skill_pack(dst)
    skills: List[dict] = []
    if pack:
        for item in pack:
            skill_name = _safe_skill_name(item["name"])
            skills.append({
                "name": skill_name,
                "display_name": str(item["name"]),
                "description": item.get("description") or "",
                "allowed_tools": item.get("allowed_tools") or "",
                "already_imported": skill_name.lower() in existing,
            })
    else:
        fallback_name = _safe_skill_name(str(data.get("name") or Path(repo_url).stem or "skill"))
        skills.append({
            "name": fallback_name,
            "display_name": str(data.get("name") or Path(repo_url).stem or "skill"),
            "description": _parse_skill_description(dst),
            "allowed_tools": "",
            "already_imported": fallback_name.lower() in existing,
        })

    return success_response(
        data={
            "repo_url": repo_url,
            "repo_hash": repo_hash,
            "skills": skills,
        },
        message=f"预览完成，共发现 {len(skills)} 个 Skill",
    )


async def import_selected_skills(project_id: int, user_id: int, db: AsyncSession, data: dict) -> dict:
    """仅导入用户在预览中勾选的 Skill（其余忽略），同仓库重复导入原地更新。"""
    await _check_role(project_id, user_id, ["owner", "admin", "developer"], db)
    repo_url = str(data.get("repo_url") or "").strip()
    if not repo_url:
        raise HTTPException(status_code=400, detail="repo_url 不能为空")
    raw_selected = data.get("selected") or []
    if not isinstance(raw_selected, list) or not [s for s in raw_selected if str(s).strip()]:
        raise HTTPException(status_code=400, detail="请至少选择一个要导入的 Skill")
    selected_set = {str(s).strip().lower() for s in raw_selected}

    scenario_category = (data.get("scenario_category") or "").strip() or None
    source_type = "gitee" if "gitee.com" in repo_url else "github" if "github.com" in repo_url else "git"
    entry_command = str(data.get("entry_command") or "").strip() or None
    base_dir = SKILL_ROOT / str(project_id) / str(user_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    repo_hash = _git_hash(repo_url)
    dst = _find_existing_repo_dir(base_dir, repo_hash) or (base_dir / repo_hash)

    try:
        _sync_git_repo(repo_url, dst, branch=data.get("branch"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"拉取仓库失败: {e}")

    existing = await _get_enabled_skills_by_repo(project_id, user_id, repo_url, db)
    created_ids: List[int] = []
    updated_ids: List[int] = []
    new_records: List[ProjectSkillModel] = []
    selected_found: set[str] = set()

    def _build_extra(*, pack_root: Optional[str] = None, allowed_tools: str = "", fallback: Optional[dict] = None) -> dict:
        extra = dict(fallback) if isinstance(fallback, dict) else {}
        if pack_root:
            extra["pack_root"] = pack_root
        if allowed_tools:
            extra["allowed_tools"] = allowed_tools
        return extra

    def _prepare_record(skill_name: str, skill_path: str, description, extra: dict) -> None:
        if skill_name.lower() not in selected_set:
            return
        selected_found.add(skill_name.lower())
        rec = existing.pop(skill_name.lower(), None)
        if rec is not None:
            rec.skill_path = skill_path
            rec.description = description
            rec.scenario_category = scenario_category or rec.scenario_category or skill_name
            rec.source_type = source_type
            rec.repo_url = repo_url
            rec.entry_command = entry_command
            rec.extra_config = extra
            rec.updated_by = user_id
            updated_ids.append(int(rec.id))
            return
        new_records.append(
            ProjectSkillModel(
                project_id=project_id,
                user_id=user_id,
                name=skill_name,
                description=description,
                scenario_category=scenario_category or skill_name,
                source_type=source_type,
                repo_url=repo_url,
                skill_path=skill_path,
                entry_command=entry_command,
                is_active=True,
                extra_config=extra,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    try:
        pack = _scan_skill_pack(dst)
        if pack:
            for item in pack:
                skill_name = _safe_skill_name(item["name"])
                extra = _build_extra(
                    pack_root=str(dst),
                    allowed_tools=item.get("allowed_tools") or "",
                )
                _prepare_record(skill_name, str(item["skill_dir"]), item.get("description"), extra)
        else:
            name = _safe_skill_name(str(data.get("name") or Path(repo_url).stem or "skill"))
            extra = _build_extra(fallback=data.get("extra_config") if isinstance(data.get("extra_config"), dict) else {})
            _prepare_record(
                name,
                str(dst),
                str(data.get("description") or _parse_skill_description(dst)),
                extra,
            )

        if not selected_found:
            raise HTTPException(status_code=400, detail="所选 Skill 在仓库中未找到对应内容")

        if new_records:
            new_names = [m.name for m in new_records]
            await _assert_skill_names_available(project_id, user_id, db, new_names)
            for m in new_records:
                db.add(m)

        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    created_ids = [int(m.id) for m in new_records]
    total = created_ids + updated_ids
    msg = "导入成功"
    if created_ids and updated_ids:
        msg = f"导入成功（新增 {len(created_ids)} 个，更新 {len(updated_ids)} 个）"
    elif updated_ids and not created_ids:
        msg = f"导入成功（已更新 {len(updated_ids)} 个，目录原地刷新）"
    elif created_ids and not updated_ids:
        msg = f"导入成功（新增 {len(created_ids)} 个）"
    return success_response(
        data={"created": created_ids, "updated": updated_ids, "count": len(total)},
        message=msg,
    )


async def _import_skills_from_local_dir(
    project_id: int,
    user_id: int,
    db: AsyncSession,
    dst: Path,
    scenario_category: Optional[str],
    entry_command: Optional[str],
    fallback_name: str,
) -> dict:
    """从已准备好的本地目录导入 Skill：优先识别 <dst>/skills/**/SKILL.md 的 skill pack，否则整体作为单个 skill。"""
    pack = _scan_skill_pack(dst)
    if pack:
        names = [_safe_skill_name(item["name"]) for item in pack]
        await _assert_skill_names_available(project_id, user_id, db, names)
        created_ids: List[int] = []
        for item in pack:
            skill_name = _safe_skill_name(item["name"])
            extra = {
                "allowed_tools": item.get("allowed_tools") or "",
                "pack_root": str(dst),
            }
            res = await create_skill(
                project_id,
                user_id,
                db,
                {
                    "name": skill_name,
                    "description": item.get("description"),
                    "scenario_category": scenario_category or skill_name,
                    "source_type": "upload",
                    "repo_url": None,
                    "skill_path": str(item["skill_dir"]),
                    "entry_command": (entry_command or "").strip() or None,
                    "is_active": True,
                    "extra_config": extra,
                },
            )
            created_ids.append(int(((res or {}).get("data") or {}).get("id") or 0))
        return success_response(data={"created": created_ids, "count": len(created_ids)}, message="导入成功")

    name = _safe_skill_name(fallback_name or "skill")
    await _assert_skill_names_available(project_id, user_id, db, [name])
    payload = {
        "name": name,
        "description": _parse_skill_description(dst),
        "scenario_category": scenario_category,
        "source_type": "upload",
        "repo_url": None,
        "skill_path": str(dst),
        "entry_command": (entry_command or "").strip() or None,
        "is_active": True,
        "extra_config": {},
    }
    res = await create_skill(project_id, user_id, db, payload)
    return success_response(data={"created": [((res or {}).get("data") or {}).get("id")], "count": 1}, message="导入成功")


async def import_skill_from_upload(
    project_id: int,
    user_id: int,
    db: AsyncSession,
    file: UploadFile,
    scenario_category: Optional[str] = None,
    entry_command: Optional[str] = None,
) -> dict:
    await _check_role(project_id, user_id, ["owner", "admin", "developer"], db)
    filename = file.filename or "skill.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 zip 包上传")
    base_dir = SKILL_ROOT / str(project_id) / str(user_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_skill_name(Path(filename).stem or "skill")
    dst = base_dir / f"{secrets.token_hex(6)}_{name}"
    dst.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tf:
        raw = await file.read()
        tf.write(raw)
        zip_path = Path(tf.name)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dst)
    except Exception as e:
        shutil.rmtree(dst, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"解压失败: {e}")
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass

    try:
        return await _import_skills_from_local_dir(project_id, user_id, db, dst, scenario_category, entry_command, name)
    except Exception:
        shutil.rmtree(dst, ignore_errors=True)
        raise


async def import_skill_from_folder(
    project_id: int,
    user_id: int,
    db: AsyncSession,
    files: List[UploadFile],
    paths: Optional[List[str]],
    scenario_category: Optional[str] = None,
    entry_command: Optional[str] = None,
) -> dict:
    """上传本地文件夹导入 Skill：浏览器通过 webkitdirectory 发送多文件，后端按相对路径落盘。"""
    await _check_role(project_id, user_id, ["owner", "admin", "developer"], db)
    if not files:
        raise HTTPException(status_code=400, detail="未收到任何文件")

    # 统一去除浏览器自动加上的顶层文件夹名，使 SKILL.md 或 skills/ 直接落在 dst 下
    rels = [str(p).replace("\\", "/") if p else (f.filename or "") for p, f in zip(paths or [], files)]
    rels = [r or (f.filename or "") for r, f in zip(rels, files)]
    first_parts = [r.split("/") for r in rels if r]
    common_root = ""
    if first_parts and all(len(p) > 1 and p[0] == first_parts[0][0] for p in first_parts):
        common_root = first_parts[0][0]

    base_dir = SKILL_ROOT / str(project_id) / str(user_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    dst = base_dir / f"{secrets.token_hex(6)}_folder"
    dst.mkdir(parents=True, exist_ok=True)

    try:
        for idx, f in enumerate(files):
            rel = rels[idx]
            if common_root and rel.startswith(common_root + "/"):
                rel = rel[len(common_root) + 1:]
            if not rel:
                rel = f.filename or f"file_{idx}"
            target = dst / rel.replace("/", os.sep)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = await f.read()
                target.write_bytes(data)
            except Exception as e:
                shutil.rmtree(dst, ignore_errors=True)
                raise HTTPException(status_code=400, detail=f"写入文件失败 {rel}: {e}")

        fallback_name = _safe_skill_name(common_root or Path(files[0].filename or "skill").name or "skill")
        return await _import_skills_from_local_dir(project_id, user_id, db, dst, scenario_category, entry_command, fallback_name)
    except Exception:
        shutil.rmtree(dst, ignore_errors=True)
        raise


def _scan_local_claude_skills() -> List[Dict[str, Any]]:
    """扫描本机 ~/.claude/skills/，返回可被导入的 Claude Code Skill 列表。

    目录结构示例：~/.claude/skills/<skill-name>/SKILL.md
    SKILL.md 支持 YAML frontmatter：name / description / tools。
    """
    root = Path.home() / ".claude" / "skills"
    if not root.exists() or not root.is_dir():
        return []

    items: List[Dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        md_file = path / "SKILL.md"
        if not md_file.exists():
            md_file = path / "README.md"
        if not md_file.exists():
            continue

        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        meta: Dict[str, Any] = {}
        body = content.strip()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1]) or {}
                    body = parts[2].strip()
                except Exception:
                    pass

        name = str(meta.get("name") or path.name).strip()
        description = str(meta.get("description") or "").strip()
        if not description:
            description = body.replace("#", "").replace("*", "").strip()[:200]

        tools = meta.get("tools") or meta.get("allowed_tools") or []
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",") if t.strip()]
        elif not isinstance(tools, list):
            tools = []

        items.append({
            "name": name,
            "local_name": path.name,
            "description": description,
            "allowed_tools": tools,
            "path": str(path),
            "md_file": str(md_file),
            "content": body[:2000],
        })
    return items


async def list_local_claude_skills(project_id: int, user_id: int, db: AsyncSession) -> dict:
    """列出本机已安装的 Claude Code Skill。"""
    await _check_member(project_id, user_id, db)
    items = _scan_local_claude_skills()
    return success_response(data={"items": items}, message="查询成功")


async def import_local_claude_skill(project_id: int, user_id: int, db: AsyncSession, data: dict) -> dict:
    """把本机 ~/.claude/skills/<skill> 复制到项目 skill 目录并创建记录。"""
    await _check_role(project_id, user_id, ["owner", "admin", "developer"], db)
    local_name = str(data.get("local_name") or "").strip()
    if not local_name:
        raise HTTPException(status_code=400, detail="请选择要导入的本地 skill")

    items = _scan_local_claude_skills()
    skill = next((s for s in items if s["local_name"] == local_name), None)
    if not skill:
        raise HTTPException(status_code=404, detail="本地 skill 不存在")

    name = _safe_skill_name(str(data.get("name") or skill["name"]))
    await _assert_skill_names_available(project_id, user_id, db, [name])

    base_dir = SKILL_ROOT / str(project_id) / str(user_id)
    base_dir.mkdir(parents=True, exist_ok=True)
    dst = base_dir / f"{secrets.token_hex(6)}_{name}"
    try:
        shutil.copytree(Path(skill["path"]), dst)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"复制本地 skill 失败: {e}")

    payload = {
        "name": name,
        "description": skill["description"],
        "scenario_category": (data.get("scenario_category") or "").strip() or name,
        "source_type": "claude-local",
        "repo_url": None,
        "skill_path": str(dst),
        "entry_command": str(data.get("entry_command") or "").strip() or None,
        "is_active": True,
        "extra_config": {
            "allowed_tools": ",".join(skill["allowed_tools"]),
            "local_path": skill["path"],
        },
    }
    res = await create_skill(project_id, user_id, db, payload)
    return success_response(
        data={"created": [((res or {}).get("data") or {}).get("id")], "count": 1},
        message="导入成功",
    )


async def get_skill_content(
    project_id: int,
    user_id: int,
    skill_id: int,
    db: AsyncSession,
    *,
    file_path: Optional[str] = None,
) -> dict:
    await _check_member(project_id, user_id, db)
    stmt = select(ProjectSkillModel).where(
        ProjectSkillModel.id == skill_id,
        ProjectSkillModel.project_id == project_id,
        ProjectSkillModel.user_id == user_id,
        ProjectSkillModel.enabled_flag == 1,
    )
    m = (await db.execute(stmt)).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="技能不存在")
    skill_dir = Path(str(m.skill_path or "").strip()) if m.skill_path else None
    if not skill_dir or not skill_dir.exists():
        return success_response(
            data={
                "skill_id": skill_id,
                "skill_path": m.skill_path,
                "tree": [],
                "content": "",
                "file_path": None,
            },
            message="技能目录不存在",
        )

    tree = _build_dir_tree(skill_dir)
    rel = (file_path or "").strip() or "SKILL.md"
    content = ""
    try:
        content = _read_skill_file(skill_dir, rel)
    except HTTPException:
        if rel == "SKILL.md":
            content = ""
        else:
            raise
    return success_response(
        data={
            "skill_id": skill_id,
            "skill_path": str(skill_dir),
            "tree": tree,
            "content": content,
            "file_path": rel,
        },
        message="查询成功",
    )

async def run_skill_tool(
    project_id: int,
    user_id: int,
    db: AsyncSession,
    *,
    skill_ref: str,
    arguments: Optional[dict] = None,
    session_id: Optional[str] = None,
) -> dict:
    await _check_member(project_id, user_id, db)
    ref = (skill_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="skill_ref 不能为空")
    stmt = select(ProjectSkillModel).where(
        ProjectSkillModel.project_id == project_id,
        ProjectSkillModel.user_id == user_id,
        ProjectSkillModel.enabled_flag == 1,
        ProjectSkillModel.is_active == 1,
    )
    stmt = stmt.where(ProjectSkillModel.id == int(ref)) if ref.isdigit() else stmt.where(ProjectSkillModel.name == ref)
    m = (await db.execute(stmt)).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="技能不存在或未启用")
    skill_dir = Path(m.skill_path or "")
    if not skill_dir.exists():
        raise HTTPException(status_code=400, detail="技能目录不存在，请重新导入技能")

    extra = m.extra_config or {}
    sess = (session_id or f"s{secrets.token_hex(4)}").strip()
    screenshots_dir, artifacts_dir = _build_skill_runtime_dirs(project_id, sess)
    env = os.environ.copy()
    env["SCREENSHOT_DIR"] = str(screenshots_dir)
    env["SKILL_OUTPUT_DIR"] = str(artifacts_dir)
    env["ARTIFACT_DIR"] = str(artifacts_dir)
    env["SKILL_ARGS_JSON"] = json.dumps(arguments or {}, ensure_ascii=False)
    env["SKILL_SESSION_ID"] = sess
    env["PROJECT_ID"] = str(project_id)
    env["USER_ID"] = str(user_id)
    cmd = _resolve_skill_command(entry_command=m.entry_command or "", skill_dir=skill_dir, arguments=arguments)
    cmd = _inject_agent_browser_session(cmd, sess)

    # Guard: allowed-tools like "agent-browser:*" are NOT runnable commands.
    # Users sometimes paste them into command and npm treats it as an invalid tag name.
    if re.search(r"\bagent-browser:\*?\b", cmd, flags=re.IGNORECASE):
        raise HTTPException(
            status_code=400,
            detail=(
                "检测到非法命令片段 'agent-browser:*' 或 'agent-browser:'。"
                " 这是 SKILL.md 中 allowed-tools 的权限声明，不是可执行命令。"
                " 请改用例如: 'npx agent-browser --help' 或 'agent-browser open https://example.com'。"
            ),
        )

    # Allow workdir override for monorepo skills
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

    if not cmd:
        allowed = (extra.get("allowed_tools") or "").strip()
        templates = _list_templates(skill_dir)
        raise HTTPException(
            status_code=400,
            detail=(
                "未配置 entry_command，无法执行该 Skill。"
                + " 可通过 arguments.command 或 arguments.template 执行。"
                + (f" allowed-tools: {allowed}。" if allowed else "")
                + (f" templates: {[t['name'] for t in templates]}。" if templates else "")
            ),
        )

    try:
        cp = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            shell=True,
            capture_output=True,
            text=False,
            timeout=240,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="技能执行超时")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"技能执行异常: {e}")

    out_text = _smart_decode(cp.stdout)
    err_text = _smart_decode(cp.stderr)
    return {
        "ok": cp.returncode == 0,
        "skill_id": m.id,
        "skill_name": m.name,
        "session_id": sess,
        "return_code": cp.returncode,
        "stdout": (out_text or "").strip()[:12000],
        "stderr": (err_text or "").strip()[:8000],
        "artifacts": _collect_files(artifacts_dir),
        "screenshots": _collect_files(screenshots_dir),
    }


async def execute_skill(project_id: int, user_id: int, skill_id: int, db: AsyncSession, data: dict) -> dict:
    result = await run_skill_tool(
        project_id=project_id,
        user_id=user_id,
        db=db,
        skill_ref=str(skill_id),
        arguments=data.get("arguments") if isinstance(data.get("arguments"), dict) else {},
        session_id=data.get("session_id"),
    )
    return success_response(data=result, message="执行成功" if result.get("ok") else "执行失败")


async def create_skill_job(
    project_id: int,
    user_id: int,
    db: AsyncSession,
    *,
    skill_id: int,
    action_name: Optional[str],
    arguments: Optional[dict],
    session_id: Optional[str],
    runner_type: Optional[str] = None,
) -> dict:
    """
    Create async execution job for production runner.
    The runner will execute `command` inside skill_dir with env dirs mounted.
    """
    await _check_member(project_id, user_id, db)
    stmt = select(ProjectSkillModel).where(
        ProjectSkillModel.id == skill_id,
        ProjectSkillModel.project_id == project_id,
        ProjectSkillModel.user_id == user_id,
        ProjectSkillModel.enabled_flag == 1,
        ProjectSkillModel.is_active == 1,
    )
    m = (await db.execute(stmt)).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="技能不存在或未启用")
    skill_dir = Path(m.skill_path or "")
    if not skill_dir.exists():
        raise HTTPException(status_code=400, detail="技能目录不存在，请重新导入技能")

    args = arguments if isinstance(arguments, dict) else {}
    cmd = _resolve_skill_command(entry_command=m.entry_command or "", skill_dir=skill_dir, arguments=args)
    cmd = _inject_agent_browser_session(cmd, session_id)
    if not cmd:
        extra = m.extra_config or {}
        allowed = (extra.get("allowed_tools") or "").strip()
        templates = _list_templates(skill_dir)
        raise HTTPException(
            status_code=400,
            detail=(
                "未配置 entry_command，无法创建执行任务。"
                + " 请通过 arguments.command 或 arguments.template 指定执行内容。"
                + (f" allowed-tools: {allowed}。" if allowed else "")
                + (f" templates: {[t['name'] for t in templates]}。" if templates else "")
            ),
        )

    if re.search(r"\bagent-browser:\*?\b", cmd, flags=re.IGNORECASE):
        raise HTTPException(status_code=400, detail="命令包含 allowed-tools 片段（agent-browser:*），请改用 npx/agent-browser 实际命令。")

    runtime_key = (session_id or f"j{secrets.token_hex(6)}").strip()
    rt = (runner_type or DEFAULT_RUNNER_TYPE or "local").strip().lower()
    job = SkillExecutionJobModel(
        project_id=project_id,
        user_id=user_id,
        skill_id=skill_id,
        action_name=action_name,
        command=cmd,
        input_args=args,
        session_id=session_id,
        status="pending",
        runtime_key=runtime_key,
        runner_type=rt,
        runner_meta={"skill_dir": str(skill_dir)},
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Seed first event
    db.add(SkillExecutionEventModel(job_id=job.id, seq=1, level="info", message=f"queued runner={rt}"))
    await db.commit()

    return success_response(
        data={
            "job_id": int(job.id),
            "status": job.status,
            "runner_type": rt,
            "runtime_key": runtime_key,
        },
        message="已入队",
    )


async def get_skill_job(project_id: int, user_id: int, db: AsyncSession, job_id: int) -> dict:
    await _check_member(project_id, user_id, db)
    stmt = select(SkillExecutionJobModel).where(
        SkillExecutionJobModel.id == job_id,
        SkillExecutionJobModel.project_id == project_id,
        SkillExecutionJobModel.user_id == user_id,
        SkillExecutionJobModel.enabled_flag == 1,
    )
    j = (await db.execute(stmt)).scalar_one_or_none()
    if not j:
        raise HTTPException(status_code=404, detail="任务不存在")
    return success_response(
        data={
            "job_id": int(j.id),
            "skill_id": int(j.skill_id),
            "status": j.status,
            "action_name": j.action_name,
            "session_id": j.session_id,
            "runner_type": j.runner_type,
            "return_code": j.return_code,
            "stdout": (j.stdout or ""),
            "stderr": (j.stderr or ""),
            "error_message": j.error_message,
            "queued_at": _iso(j.queued_at),
            "started_at": _iso(j.started_at),
            "finished_at": _iso(j.finished_at),
        },
        message="查询成功",
    )


async def cancel_skill_job(project_id: int, user_id: int, db: AsyncSession, job_id: int) -> dict:
    await _check_member(project_id, user_id, db)
    j = (await db.execute(select(SkillExecutionJobModel).where(
        SkillExecutionJobModel.id == job_id,
        SkillExecutionJobModel.project_id == project_id,
        SkillExecutionJobModel.user_id == user_id,
        SkillExecutionJobModel.enabled_flag == 1,
    ))).scalar_one_or_none()
    if not j:
        raise HTTPException(status_code=404, detail="任务不存在")
    if j.status in ("succeeded", "failed", "cancelled"):
        return success_response(data={"job_id": job_id, "status": j.status, "cancelled": False}, message="任务已结束，无需取消")
    ok = await runner_cancel_skill_job(job_id, cancelled_by=user_id)
    return success_response(data={"job_id": job_id, "status": "cancelled" if ok else j.status, "cancelled": ok}, message="取消成功" if ok else "取消失败或任务已结束")


async def list_job_artifacts(project_id: int, user_id: int, db: AsyncSession, job_id: int) -> dict:
    await _check_member(project_id, user_id, db)
    j = (await db.execute(select(SkillExecutionJobModel).where(
        SkillExecutionJobModel.id == job_id,
        SkillExecutionJobModel.project_id == project_id,
        SkillExecutionJobModel.user_id == user_id,
        SkillExecutionJobModel.enabled_flag == 1,
    ))).scalar_one_or_none()
    if not j:
        raise HTTPException(status_code=404, detail="任务不存在")
    rows = (await db.execute(
        select(SkillExecutionArtifactModel).where(
            SkillExecutionArtifactModel.job_id == job_id,
            SkillExecutionArtifactModel.enabled_flag == 1,
        ).order_by(SkillExecutionArtifactModel.id.asc())
    )).scalars().all()
    items = [{"id": int(r.id), "kind": r.kind, "name": r.name, "relative_path": r.relative_path, "size": r.size} for r in rows]
    return success_response(data={"job_id": job_id, "items": items}, message="查询成功")


# ============================================================================
# 外部编程 Agent 集成（Claude Code / Codex / OpenCode 驱动 Playwright Test Agents / agent-device）
# 复用既有 Skill Job / Event / Artifact 体系，零新建表。
# ============================================================================

EXTERNAL_AGENT_SKILL_PREFIX = "__external_agent__"


async def detect_external_agents(project_id: int, user_id: int, db: AsyncSession, custom_agents: Optional[List[str]] = None) -> dict:
    """探测本机可用的外部 Agent 二进制。"""
    await _check_member(project_id, user_id, db)
    return success_response(data=EA.detect_external_agents(custom_agents), message="探测完成")


async def _ensure_external_agent_skill(project_id: int, user_id: int, db: AsyncSession, agent: str, cwd: str) -> int:
    """为外部 Agent 复用 Skill 表：返回一个稳定的虚拟 Skill id（external-agent 分类）。"""
    name = f"{EXTERNAL_AGENT_SKILL_PREFIX}{agent}"
    stmt = select(ProjectSkillModel).where(
        ProjectSkillModel.project_id == project_id,
        ProjectSkillModel.user_id == user_id,
        ProjectSkillModel.name == name,
        ProjectSkillModel.enabled_flag == 1,
    )
    m = (await db.execute(stmt)).scalar_one_or_none()
    if m:
        if m.skill_path != str(cwd):
            m.skill_path = str(cwd)
            await db.commit()
        return int(m.id)
    m = ProjectSkillModel(
        project_id=project_id,
        user_id=user_id,
        name=name,
        description=f"外部编程 Agent（{agent}）执行器，复用 Skill Job 实时日志与产物体系",
        scenario_category="external-agent",
        source_type="builtin",
        skill_path=str(cwd),
        entry_command="",
        is_active=True,
        extra_config={"agent": agent, "external": True},
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return int(m.id)


async def _resolve_cwd(project_id: int, user_id: int, db: AsyncSession, *, skill_id: Optional[int], workdir: str) -> Path:
    if skill_id:
        m = (await db.execute(select(ProjectSkillModel).where(
            ProjectSkillModel.id == int(skill_id),
            ProjectSkillModel.project_id == project_id,
            ProjectSkillModel.user_id == user_id,
            ProjectSkillModel.enabled_flag == 1,
        ))).scalar_one_or_none()
        if m and m.skill_path and Path(m.skill_path).exists():
            return Path(m.skill_path)
    if workdir and Path(workdir).exists():
        return Path(workdir)
    cwd = SKILL_ROOT / str(project_id) / str(user_id) / "external-agent"
    cwd.mkdir(parents=True, exist_ok=True)
    return cwd


async def _upsert_agent_device_mcp(project_id: int, user_id: int, db: AsyncSession, mcp: dict, scope: str = "project") -> int:
    """把 agent-device 登记进项目 MCP 配置表（便于复用与导出到 Claude/Cursor）。"""
    name = (mcp.get("name") or "agent-device").strip()
    stmt = select(ProjectMCPConfigModel).where(
        ProjectMCPConfigModel.user_id == user_id,
        ProjectMCPConfigModel.project_id == project_id,
        ProjectMCPConfigModel.name == name,
    )
    m = (await db.execute(stmt)).scalar_one_or_none()
    command = mcp.get("command") or EA.AGENT_DEVICE_DEFAULT_CMD
    args = mcp.get("args") or []
    env = mcp.get("env") or {}
    if m:
        m.transport = "stdio"
        m.command = command
        m.args = args
        m.env = env
        m.scope = scope
        m.is_enabled = True
        m.updated_by = user_id
    else:
        m = ProjectMCPConfigModel(
            user_id=user_id,
            project_id=project_id,
            scope=scope,
            name=name,
            transport="stdio",
            command=command,
            args=args,
            env=env,
            is_enabled=True,
            description="agent-device MCP（外部 Agent 驱动设备测试）",
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(m)
    await db.commit()
    await db.refresh(m)
    return int(m.id)


AGENT_DEVICE_SESSION_KEY_VAR = "GENIUS_AGENT_SESSION_KEY"


async def _get_or_create_agent_device_session_key(
    project_id: int,
    user_id: int,
    db: AsyncSession,
    name: str = "agent-device",
    command: Optional[str] = None,
    args: Optional[list] = None,
) -> str:
    """获取/生成 agent-device 的人机共享 session_key，并持久化到 ProjectMCPConfig env。

    复用规则：先查现有 ProjectMCPConfig.env，没有则生成并写入。key 在同一 project/user/name
    下保持稳定，使得人和外部 Agent 能复用同一个设备 session。
    """
    name = name.strip() or "agent-device"
    m = (await db.execute(select(ProjectMCPConfigModel).where(
        ProjectMCPConfigModel.user_id == user_id,
        ProjectMCPConfigModel.project_id == project_id,
        ProjectMCPConfigModel.name == name,
        ProjectMCPConfigModel.is_enabled == 1,
        ProjectMCPConfigModel.enabled_flag == 1,
    ))).scalar_one_or_none()
    if m and m.env:
        stored_env = m.env if isinstance(m.env, dict) else json.loads(m.env)
        key = str(stored_env.get(AGENT_DEVICE_SESSION_KEY_VAR) or "").strip()
        if key:
            return key

    key = f"genius-{project_id}-{user_id}-{name[:20]}-{secrets.token_hex(3)}"
    env = {AGENT_DEVICE_SESSION_KEY_VAR: key}
    if m:
        existing_env = m.env if isinstance(m.env, dict) else json.loads(m.env or "{}")
        existing_env[AGENT_DEVICE_SESSION_KEY_VAR] = key
        m.env = existing_env
        m.updated_by = user_id
        await db.commit()
        await db.refresh(m)
    else:
        await _upsert_agent_device_mcp(
            project_id,
            user_id,
            db,
            {
                "name": name,
                "command": command or EA.AGENT_DEVICE_DEFAULT_CMD,
                "args": list(args or []),
                "env": env,
            },
            scope="project",
        )
    return key


async def _find_registered_agent_device(project_id: int, user_id: int, db: AsyncSession) -> Optional[str]:
    """若项目已登记 agent-device MCP，则生成临时 mcp.json 路径供 Claude Code 加载。"""
    m = (await db.execute(select(ProjectMCPConfigModel).where(
        ProjectMCPConfigModel.user_id == user_id,
        ProjectMCPConfigModel.project_id == project_id,
        ProjectMCPConfigModel.name == "agent-device",
        ProjectMCPConfigModel.is_enabled == 1,
        ProjectMCPConfigModel.enabled_flag == 1,
    ))).scalar_one_or_none()
    if not m:
        return None
    entry = EA.agent_device_server_entry(m.command or EA.AGENT_DEVICE_DEFAULT_CMD, m.args, m.env)
    return str(EA.write_mcp_config_file([{"name": m.name, "entry": entry}]))


def _sync_agent_device_mcp(name: str, command: str, args: list, env: dict, scope: str, workspace_path: Optional[str]) -> dict:
    """把 agent-device 同步到本机 N-Tester/Claude/Cursor 的 mcp.json。"""
    if scope == "project" and not workspace_path:
        return {"skipped": True, "reason": "project 作用域需要 workspace_path"}
    try:
        from app.api.v1.Ntesterc_module.Ntesterc_project.mcp_file_sync import sync_config_to_files

        class _Cfg:
            scope = scope
            name = name
            transport = "stdio"
            command = command
            args = args
            env = env
            url = ""
            headers = {}
            auth_type = "none"
            auth_config = {}

        return sync_config_to_files(_Cfg(), workspace_path=workspace_path)
    except Exception as e:  # 同步失败不影响 Agent 调用
        return {"error": str(e)[:500]}


async def register_agent_device_mcp(project_id: int, user_id: int, db: AsyncSession, data: dict) -> dict:
    """注册 agent-device 为 MCP server（写入项目 MCP 配置 + 同步到本机 mcp 文件）。"""
    await _check_role(project_id, user_id, ["owner", "admin", "developer"], db)
    name = (data.get("name") or "agent-device").strip()
    command = (data.get("command") or EA.AGENT_DEVICE_DEFAULT_CMD).strip()
    args = data.get("args") if isinstance(data.get("args"), list) else []
    env = data.get("env") if isinstance(data.get("env"), dict) else {}
    scope = (data.get("scope") or "project").strip().lower()
    workspace_path = (data.get("workspace_path") or "").strip() or None

    # 生成/复用人机共享的 agent-device session_key，并持久化到 env
    session_key = await _get_or_create_agent_device_session_key(
        project_id, user_id, db, name=name, command=command, args=args
    )
    env[AGENT_DEVICE_SESSION_KEY_VAR] = session_key
    data["env"] = env

    await _upsert_agent_device_mcp(project_id, user_id, db, {"name": name, "command": command, "args": args, "env": env}, scope=scope)
    written = _sync_agent_device_mcp(name, command, args, env, scope, workspace_path)
    return success_response(
        data={"name": name, "scope": scope, "session_key": session_key, "written": written},
        message="agent-device MCP 已注册",
    )


async def scaffold_pw_test_agents(project_id: int, user_id: int, db: AsyncSession, data: dict) -> dict:
    """脚手架：运行 init-agents --loop=... 生成 specs/seed.spec.ts 等（由 Claude Code 驱动）。"""
    await _check_member(project_id, user_id, db)
    loop = (data.get("loop") or "claude").strip().lower()
    cwd = await _resolve_cwd(project_id, user_id, db, skill_id=data.get("skill_id"), workdir=(data.get("workdir") or "").strip())
    cmd = EA.build_pw_test_agents_scaffold_command(loop=loop, command=data.get("command"))
    skill_id_final = await _ensure_external_agent_skill(project_id, user_id, db, "claude", str(cwd))
    sess = f"pw-init-{secrets.token_hex(4)}"
    job = SkillExecutionJobModel(
        project_id=project_id,
        user_id=user_id,
        skill_id=skill_id_final,
        action_name="pw-test-agents:scaffold",
        command=cmd,
        input_args=data,
        session_id=sess,
        status="pending",
        runtime_key=sess,
        runner_type="local",
        runner_meta={"agent": "claude", "kind": "pw-test-agents", "loop": loop, "scaffold": True},
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    db.add(SkillExecutionEventModel(job_id=job.id, seq=1, level="info", message=f"queued pw-test-agents scaffold loop={loop}"))
    await db.commit()
    schedule_skill_job(int(job.id))
    return success_response(
        data={"job_id": int(job.id), "status": "pending", "command": cmd, "runtime_key": sess},
        message="Playwright Test Agents 脚手架任务已入队",
    )


async def run_external_agent_job(project_id: int, user_id: int, db: AsyncSession, data: dict) -> dict:
    """创建外部 Agent 执行任务（驱动 Playwright Test Agents / agent-device）。

    后端只负责拉起外部编程 Agent 子进程并实时收集日志/产物；真正的测试规划与执行
    由 Claude Code / Codex / OpenCode 完成。agent-device 通过 --mcp-config 加载 MCP server。
    """
    await _check_member(project_id, user_id, db)
    agent = (data.get("agent") or "claude").strip().lower()
    kind = (data.get("kind") or "pw-test-agents").strip().lower()
    prompt = (data.get("prompt") or "").strip()
    loop = (data.get("loop") or "claude").strip().lower()
    session_id = data.get("session_id")
    device_ref = (data.get("device_ref") or "").strip()
    os_type = (data.get("os_type") or "android").strip().lower()
    model = (data.get("model") or None)
    extra_args = data.get("extra_args") if isinstance(data.get("extra_args"), list) else None

    if agent != "npx" and EA.resolve_agent_binary(agent) is None:
        raise HTTPException(
            status_code=400,
            detail=f"本机未探测到外部 Agent 二进制：{agent}（请先安装 Claude Code / Codex / OpenCode，或改用 agent=npx）",
        )

    cwd = await _resolve_cwd(project_id, user_id, db, skill_id=data.get("skill_id"), workdir=(data.get("workdir") or "").strip())
    cwd.mkdir(parents=True, exist_ok=True)

    mcp_config_path = None
    agent_device_session_key: Optional[str] = None
    if kind == "agent-device":
        mcp = data.get("mcp") if isinstance(data.get("mcp"), dict) else None
        if mcp:
            mcp_name = (mcp.get("name") or "agent-device").strip()
            mcp_env = mcp.get("env") if isinstance(mcp.get("env"), dict) else {}
            agent_device_session_key = await _get_or_create_agent_device_session_key(
                project_id,
                user_id,
                db,
                name=mcp_name,
                command=mcp.get("command") or EA.AGENT_DEVICE_DEFAULT_CMD,
                args=mcp.get("args") if isinstance(mcp.get("args"), list) else [],
            )
            mcp_env[AGENT_DEVICE_SESSION_KEY_VAR] = agent_device_session_key
            mcp["env"] = mcp_env
            entry = EA.agent_device_server_entry(
                mcp.get("command") or EA.AGENT_DEVICE_DEFAULT_CMD, mcp.get("args"), mcp_env
            )
            mcp_config_path = str(EA.write_mcp_config_file([{"name": mcp_name, "entry": entry}]))
            await _upsert_agent_device_mcp(project_id, user_id, db, mcp)
        else:
            agent_device_session_key = await _get_or_create_agent_device_session_key(project_id, user_id, db)
            mcp_config_path = await _find_registered_agent_device(project_id, user_id, db)
        if not prompt:
            prompt = EA.build_agent_device_prompt(
                device_ref=device_ref,
                task=(data.get("task") or "执行已规划的测试用例"),
                session_name=session_id or agent_device_session_key or "agent-device-session",
                os_type=os_type,
            )

    if not prompt:
        raise HTTPException(status_code=400, detail="缺少 prompt（外部 Agent 执行指令）")

    skill_id_final = await _ensure_external_agent_skill(project_id, user_id, db, agent, str(cwd))
    sess = session_id or agent_device_session_key or f"ext-{secrets.token_hex(4)}"
    cmd = EA.build_external_agent_command(
        agent=agent, prompt=prompt, mcp_config_path=mcp_config_path, model=model, extra_args=extra_args
    )

    job = SkillExecutionJobModel(
        project_id=project_id,
        user_id=user_id,
        skill_id=skill_id_final,
        action_name=f"external-agent:{kind}",
        command=cmd,
        input_args=data,
        session_id=sess,
        status="pending",
        runtime_key=sess,
        runner_type="local",
        runner_meta={
            "agent": agent,
            "kind": kind,
            "loop": loop,
            "device_ref": device_ref,
            "os_type": os_type,
            "mcp_config_path": mcp_config_path,
            "session_key": agent_device_session_key,
            "prompt": prompt[:2000],
        },
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    db.add(SkillExecutionEventModel(job_id=job.id, seq=1, level="info", message=f"queued agent={agent} kind={kind}"))
    await db.commit()
    schedule_skill_job(int(job.id))
    return success_response(
        data={"job_id": int(job.id), "status": "pending", "command": cmd, "runtime_key": sess},
        message="外部 Agent 任务已入队",
    )

