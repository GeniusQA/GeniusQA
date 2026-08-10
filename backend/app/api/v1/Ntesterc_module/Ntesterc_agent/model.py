#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""
AI 测试任务中心模型：agent_task（任务主状态机）+ agent_artifact（产物库）
"""

from sqlalchemy import Column, String, Text, Integer, JSON, BigInteger, Numeric, Index
from app.core.db_base import Base


class AgentTaskModel(Base):
    """AI 测试任务（多 Agent 流水线主状态机）"""

    __tablename__ = 'agent_task'
    __table_args__ = (
        Index("idx_agent_task_status", "status"),
        Index("idx_agent_task_created", "creation_date"),
        {'comment': 'AI 测试任务表', 'mysql_charset': 'utf8mb4'}
    )

    name = Column(String(100), nullable=False, comment='任务名称')
    pipeline_type = Column(String(20), nullable=False, default='api', comment='流水线类型: api/ui')
    status = Column(String(20), nullable=False, default='pending', comment='状态: pending/analyzing/case_generating/awaiting_review/executing/reviewing/done/failed')
    project_id = Column(BigInteger, nullable=True, comment='关联项目ID')
    env_name = Column(String(50), nullable=True, comment='执行环境')
    input_file = Column(String(255), nullable=True, comment='需求文档/OpenAPI 文件名')
    exec_mode = Column(String(10), nullable=False, default='manual', comment='执行模式: manual/auto')
    model_tier = Column(String(20), nullable=True, default='standard', comment='模型档位')
    progress = Column(Integer, nullable=False, default=0, comment='整体进度 0-100')
    current_node = Column(String(30), nullable=True, comment='当前节点')
    error_msg = Column(Text, nullable=True, comment='失败原因')
    token_used = Column(Integer, nullable=False, default=0, comment='Token 消耗')
    cost = Column(Numeric(10, 2), nullable=False, default=0, comment='成本(元)')
    trace = Column(JSON, nullable=True, comment='执行轨迹 steps 数组')
    artifacts = Column(JSON, nullable=True, comment='产物索引 [{kind,id,version,status}]')

    def __repr__(self):
        return f"<AgentTask(id={self.__dict__.get('id')}, name='{self.__dict__.get('name')}', status='{self.__dict__.get('status')}')>"


class AgentArtifactModel(Base):
    """AI 测试任务产物（阶段间唯一传递介质）"""

    __tablename__ = 'agent_artifact'
    __table_args__ = (
        Index("idx_agent_artifact_task", "task_id"),
        {'comment': 'AI 测试任务产物表', 'mysql_charset': 'utf8mb4'}
    )

    task_id = Column(BigInteger, nullable=False, comment='任务ID')
    kind = Column(String(20), nullable=False, comment='产物类型: test_points/cases/results/report')
    content = Column(JSON, nullable=True, comment='产物内容(结构化 JSON)')
    version = Column(Integer, nullable=False, default=1, comment='产物版本')
    status = Column(String(10), nullable=False, default='draft', comment='状态: draft/confirmed/rejected')
    summary = Column(String(500), nullable=True, comment='产物摘要')

    def __repr__(self):
        return f"<AgentArtifact(id={self.__dict__.get('id')}, task_id={self.__dict__.get('task_id')}, kind='{self.__dict__.get('kind')}')>"
