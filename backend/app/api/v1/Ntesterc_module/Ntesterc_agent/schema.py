#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""AI 测试任务中心 Schema"""

from typing import Optional, List, Any
from pydantic import BaseModel, Field
from app.core.base_schema import BaseSchema


class AgentTaskCreateSchema(BaseModel):
    """创建 AI 测试任务"""
    name: str = Field(..., max_length=100, description='任务名称')
    pipeline_type: str = Field('api', description='流水线类型: api/ui')
    project_id: Optional[int] = Field(None, description='关联项目ID')
    env_name: Optional[str] = Field('测试环境', description='执行环境')
    input_file: Optional[str] = Field(None, max_length=255, description='需求文档/OpenAPI 文件名')
    exec_mode: str = Field('manual', description='执行模式: manual/auto')
    model_tier: str = Field('standard', description='模型档位')
    case_config: Optional[dict] = Field(None, description='用例生成配置 {types, extra_requirements, step_generation, case_count}')


class AgentTaskUpdateSchema(BaseModel):
    """更新 AI 测试任务（全部可选）"""
    name: Optional[str] = Field(None, max_length=100)
    project_id: Optional[int] = None
    env_name: Optional[str] = None
    input_file: Optional[str] = None
    model_tier: Optional[str] = None


class AgentArtifactOutSchema(BaseSchema):
    id: int
    task_id: int
    kind: str
    content: Optional[Any] = None
    version: int
    status: str
    summary: Optional[str] = None
    creation_date: Optional[Any] = None


class AgentTaskOutSchema(BaseSchema):
    id: int
    name: str
    pipeline_type: str
    status: str
    project_id: Optional[int] = None
    env_name: Optional[str] = None
    input_file: Optional[str] = None
    exec_mode: str
    model_tier: Optional[str] = None
    progress: int
    current_node: Optional[str] = None
    error_msg: Optional[str] = None
    token_used: int
    cost: Optional[Any] = None
    trace: Optional[Any] = None
    created_by: Optional[int] = None
    creation_date: Optional[Any] = None
    updation_date: Optional[Any] = None
    artifacts: Optional[List[AgentArtifactOutSchema]] = Field(None, description='产物列表')
    case_config: Optional[Any] = Field(None, description='用例生成配置')


class AgentTaskPageSchema(BaseSchema):
    total: int
    page: int
    page_size: int
    items: List[AgentTaskOutSchema]
