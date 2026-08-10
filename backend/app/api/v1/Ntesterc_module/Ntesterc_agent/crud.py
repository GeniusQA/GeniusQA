#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""AI 测试任务中心 CRUD"""

from typing import List, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from app.core.base_crud import BaseCRUD
from .model import AgentTaskModel, AgentArtifactModel


class AgentTaskCRUD(BaseCRUD[AgentTaskModel]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentTaskModel, db)

    async def get_list(self, keyword: Optional[str] = None, status: Optional[str] = None,
                       skip: int = 0, limit: int = 20) -> Tuple[List[AgentTaskModel], int]:
        conds = [self.model.enabled_flag == 1]
        if keyword:
            conds.append(self.model.name.like(f"%{keyword}%"))
        if status:
            conds.append(self.model.status == status)
        total = (await self.db.execute(select(func.count(self.model.id)).where(and_(*conds)))).scalar() or 0
        stmt = (select(self.model).where(and_(*conds))
                .order_by(self.model.creation_date.desc())
                .offset(skip).limit(limit))
        items = (await self.db.execute(stmt)).scalars().all()
        return list(items), total


class AgentArtifactCRUD(BaseCRUD[AgentArtifactModel]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentArtifactModel, db)

    async def get_by_task(self, task_id: int) -> List[AgentArtifactModel]:
        stmt = (select(self.model)
                .where(self.model.task_id == task_id, self.model.enabled_flag == 1)
                .order_by(self.model.creation_date.asc()))
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_latest_by_kind(self, task_id: int, kind: str) -> Optional[AgentArtifactModel]:
        stmt = (select(self.model)
                .where(self.model.task_id == task_id, self.model.kind == kind, self.model.enabled_flag == 1)
                .order_by(self.model.creation_date.desc()).limit(1))
        return (await self.db.execute(stmt)).scalars().first()
