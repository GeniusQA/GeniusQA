#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: Rebort

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime


class ApiServiceRequest(BaseModel):
    """获取服务列表（支持分页和筛选）"""
    page: Optional[int] = Field(1, description="页码")
    pageSize: Optional[int] = Field(20, description="每页条数")
    project_id: Optional[int] = Field(None, description="项目ID，不传则返回全部")
    name: Optional[str] = Field(None, description="服务名称关键字（模糊匹配）")
    manager: Optional[int] = Field(None, description="负责人用户ID")
    business_id: Optional[int] = Field(None, description="业务线ID")


class ApiServiceSortRequest(BaseModel):
    """服务排序"""
    ids: List[int] = Field(..., description="按顺序传入服务 ID 列表")

class AddApiServiceRequest(BaseModel):
    """新增服务"""
    name: str = Field(..., description="服务名称")
    api_project_id: int = Field(..., description="所属项目ID")
    img: Optional[str] = Field(None, description="服务图标")
    description: Optional[str] = Field(None, description="服务描述")
    source_type: Optional[str] = Field(None, description="接口文档类型：swagger/apifox")
    source_addr: Optional[str] = Field(None, description="接口文档地址")
    manager: Optional[int] = Field(None, description="负责人用户ID")
    business_id: Optional[int] = Field(None, description="业务线ID")


class EditApiServiceRequest(BaseModel):
    """编辑服务"""
    id: int = Field(..., description="服务ID")
    name: Optional[str] = Field(None, description="服务名称")
    api_project_id: Optional[int] = Field(None, description="所属项目ID")
    img: Optional[str] = Field(None, description="服务图标")
    description: Optional[str] = Field(None, description="服务描述")
    source_type: Optional[str] = Field(None, description="接口文档类型：swagger/apifox")
    source_addr: Optional[str] = Field(None, description="接口文档地址")
    manager: Optional[int] = Field(None, description="负责人用户ID")
    business_id: Optional[int] = Field(None, description="业务线ID")


class DelApiServiceRequest(BaseModel):
    """删除服务"""
    id: int = Field(..., description="服务ID")


class ApiTreeRequest(BaseModel):
    """获取接口菜单树 - search 与 service get_api_tree(search) 一致"""
    search: Optional[Dict[str, Any]] = Field(None, description="查询条件：api_service_id, name 等")


class AddMenuRequest(BaseModel):
    """新增菜单/目录"""
    name: str = Field(..., description="菜单名称")
    pid: int = Field(..., description="父节点ID，根为 0")
    type: int = Field(..., description="类型：1=目录 2=用例等")
    api_service_id: int = Field(..., description="所属服务ID")


class EditMenuRequest(BaseModel):
    """编辑菜单"""
    id: int = Field(..., description="菜单ID")
    name: str = Field(..., description="新名称")


class DelMenuRequest(BaseModel):
    """删除菜单"""
    id: int = Field(..., description="菜单ID")
    type: Optional[int] = Field(None, description="菜单类型，用于级联删 API")


class CopyMenuRequest(BaseModel):
    """复制菜单及关联接口"""
    id: int = Field(..., description="源菜单ID")
    api_id: int = Field(..., description="源接口ID")


class ApiInfoRequest(BaseModel):
    """获取接口详情"""
    api_id: int = Field(..., description="接口ID")


class SaveApiRequest(BaseModel):
    """保存接口（编辑） - 与 service save_api 入参一致"""
    id: int = Field(..., description="接口ID")
    url: Optional[str] = Field(None, description="请求 URL")
    req: Optional[Dict[str, Any]] = Field(None, description="完整请求配置(header/params/body/before/after/assert 等)")


class ApiSendRequest(BaseModel):
    """发送单接口请求 - 与 service execute_api_send 入参一致"""
    id: Optional[int] = Field(None, description="接口ID，可选")
    env_id: Optional[int] = Field(None, description="环境ID")
    url: Optional[str] = Field(None, description="请求 URL（可含变量）")
    req: Optional[Dict[str, Any]] = Field(None, description="请求配置(header/params/body/before/after/assert 等)")


class ReqHistoryRequest(BaseModel):
    """请求历史 - 无必填参数"""
    pass


class EditHistoryRequest(BaseModel):
    """接口编辑历史"""
    api_id: int = Field(..., description="接口ID")


class ApiDocHistoryRequest(BaseModel):
    """接口文档历史版本列表"""
    api_id: int = Field(..., description="接口ID")
    page: Optional[int] = Field(1, description="页码")
    pageSize: Optional[int] = Field(20, description="每页条数")


class ApiDocHistoryDiffRequest(BaseModel):
    """接口文档历史版本差异对比"""
    history_id_a: int = Field(..., description="前一个版本ID")
    history_id_b: int = Field(..., description="后一个版本ID")


class ApiDocHistoryRestoreRequest(BaseModel):
    """还原接口文档到指定历史版本"""
    id: int = Field(..., description="历史版本ID")


class DataSourceHistoryRequest(BaseModel):
    """数据源导入历史列表"""
    api_service_id: int = Field(..., description="服务ID")
    module_id: Optional[int] = Field(None, description="模块ID")
    page: Optional[int] = Field(1, description="页码")
    pageSize: Optional[int] = Field(20, description="每页条数")


class DataSourceHistoryDiffRequest(BaseModel):
    """数据源导入历史差异对比"""
    history_id_a: int = Field(..., description="前一次历史记录ID")
    history_id_b: int = Field(..., description="后一次历史记录ID")


class DataSourceHistoryDeleteRequest(BaseModel):
    """删除数据源导入历史"""
    id: int = Field(..., description="历史记录ID")


# ---------- 环境 ----------
class EnvInfoRequest(BaseModel):
    """获取环境详情"""
    id: int = Field(..., description="环境ID")


class SaveEnvRequest(BaseModel):
    """批量保存环境"""
    env_list: List[Dict[str, Any]] = Field(default_factory=list, description="环境列表，每项含 id/name/config/variable")


class AddEnvRequest(BaseModel):
    """新增环境"""
    name: str = Field(..., description="环境名称")
    config: Optional[List[Dict[str, Any]]] = Field(None, description="环境配置项")
    variable: Optional[List[Dict[str, Any]]] = Field(None, description="环境变量")


class DelEnvRequest(BaseModel):
    """删除环境"""
    id: int = Field(..., description="环境ID")


# ---------- 全局变量 ----------
class AddVarRequest(BaseModel):
    """新增全局变量"""
    name: str = Field(..., description="变量名")
    value: str = Field(..., description="变量值")


class EditVarRequest(BaseModel):
    """编辑全局变量"""
    id: int = Field(..., description="变量ID")
    name: str = Field(..., description="变量名")
    value: str = Field(..., description="变量值")


class DelVarRequest(BaseModel):
    """删除全局变量"""
    id: int = Field(..., description="变量ID")


# ---------- 数据库配置 ----------
class AddApiDbRequest(BaseModel):
    """新增数据库配置"""
    name: str = Field(..., description="配置名称")
    config: Optional[Dict[str, Any]] = Field(None, description="连接配置 host/user/password/database/port 等")


class EditApiDbRequest(BaseModel):
    """编辑数据库配置"""
    id: int = Field(..., description="配置ID")
    name: Optional[str] = Field(None, description="配置名称")
    config: Optional[Dict[str, Any]] = Field(None, description="连接配置")


class DelApiDbRequest(BaseModel):
    """删除数据库配置"""
    id: int = Field(..., description="配置ID")


# ---------- 接口用例（历史接口路径仍为 api_script_*） ----------
class ApiScriptListRequest(BaseModel):
    """用例列表分页"""
    page: Optional[int] = Field(1, description="页码")
    pageSize: Optional[int] = Field(1000, description="每页条数")


class ApiScriptRequest(BaseModel):
    """用例列表请求 - 与 get_api_script_list 一致"""
    page: Optional[int] = Field(1, description="页码")
    pageSize: Optional[int] = Field(1000, description="每页条数")


class AddApiScriptRequest(BaseModel):
    """新增用例"""
    name: str = Field(..., description="用例名称")
    type: Optional[int] = Field(1, description="类型")
    script: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="步骤列表")
    config: Optional[Dict[str, Any]] = Field(None, description="用例配置")
    description: Optional[str] = Field("", description="描述")


class EditApiScriptRequest(BaseModel):
    """编辑用例"""
    id: int = Field(..., description="用例ID")
    name: Optional[str] = Field(None, description="用例名称")
    type: Optional[int] = Field(None, description="类型")
    script: Optional[List[Dict[str, Any]]] = Field(None, description="步骤列表")
    config: Optional[Dict[str, Any]] = Field(None, description="用例配置")
    description: Optional[str] = Field(None, description="描述")


class DelApiScriptRequest(BaseModel):
    """删除用例"""
    id: int = Field(..., description="用例ID")


class RunApiScriptRequest(BaseModel):
    """执行用例 - 与 service run_api_script 入参一致"""
    result_id: str = Field(..., description="本次执行批次ID（如 UUID）")
    name: str = Field(..., description="任务名称")
    config: Dict[str, Any] = Field(default_factory=dict, description="执行配置，含 env_id 等")
    run_list: List[Dict[str, Any]] = Field(default_factory=list, description="用例列表，每项含 script/config 等")


class ApiScriptResultRequest(BaseModel):
    """获取用例执行结果"""
    result_id: int = Field(..., description="执行批次ID")


class ApiScriptResultListRequest(BaseModel):
    """执行结果汇总列表分页"""
    page: Optional[int] = Field(1, description="页码")
    pageSize: Optional[int] = Field(1000, description="每页条数")
    api_service_id: Optional[int] = Field(None, description="按服务ID过滤，不传则返回全部")


class ApiScriptResultDetailRequest(BaseModel):
    """执行结果详情（按批次）"""
    result_id: int = Field(..., description="执行批次ID")


class ApiScriptResultDetailListRequest(BaseModel):
    """执行结果详情列表（按菜单/用例）"""
    result_id: int = Field(..., description="执行批次ID")
    menu_id: str = Field(..., description="用例/菜单 UUID")


class ApiScriptLogRequest(BaseModel):
    """脚本执行日志（整体）"""
    result_id: str = Field(..., description="执行ID")


class ApiScriptReportLogRequest(BaseModel):
    """脚本执行日志（按菜单）"""
    result_id: str = Field(..., description="执行ID")
    menu_id: str = Field(..., description="菜单/用例 UUID")




class ApiServiceResponse(BaseModel):
    """API 服务"""
    id: int
    name: str
    api_project_id: int
    img: Optional[str] = None
    description: Optional[str] = None
    creation_date: datetime

    class Config:
        from_attributes = True


class ApiResponse(BaseModel):
    """API 接口"""
    id: int
    name: Optional[str] = None
    url: str
    req: Optional[Dict[str, Any]] = None
    document: Optional[Dict[str, Any]] = None
    api_service_id: int
    creation_date: datetime

    class Config:
        from_attributes = True


class ApiEnvironmentResponse(BaseModel):
    """API 环境"""
    id: int
    name: str
    config: Optional[List[Dict[str, Any]]] = None
    variable: Optional[List[Dict[str, Any]]] = None
    description: Optional[str] = None
    creation_date: datetime

    class Config:
        from_attributes = True


class ApiScriptResponse(BaseModel):
    """API 用例"""
    id: int
    name: str
    type: int
    script: List[Dict[str, Any]]
    config: Optional[Dict[str, Any]] = None
    description: str = ""
    creation_date: datetime

    class Config:
        from_attributes = True


class ApiExecutionResponse(BaseModel):
    """单接口执行结果"""
    status_code: int
    response_time: float
    response_data: Dict[str, Any]
    request_data: Dict[str, Any]
    assertions_passed: bool
    error_message: Optional[str] = None


# ---------- 用例集（Suite）----------

class ApiSuiteListRequest(BaseModel):
    """获取用例集树"""
    api_service_id: int = Field(..., description="服务ID")


class AddApiSuiteRequest(BaseModel):
    """新增用例集"""
    name: str = Field(..., description="用例集名称")
    parent: Optional[int] = Field(None, description="父用例集ID，顶级为null")
    api_service_id: int = Field(..., description="所属服务ID")


class EditApiSuiteRequest(BaseModel):
    """编辑用例集"""
    id: int = Field(..., description="用例集ID")
    name: str = Field(..., description="新名称")


class DelApiSuiteRequest(BaseModel):
    """删除用例集（级联删除子集和用例）"""
    id: int = Field(..., description="用例集ID")


class ApiSuiteSortRequest(BaseModel):
    """用例集排序"""
    ids: List[int] = Field(..., description="同级用例集ID列表，按顺序持久化")


# ---------- 用例（Case）----------

class ApiCaseListRequest(BaseModel):
    """获取用例列表"""
    suite_id: int = Field(..., description="用例集ID")


class AddApiCaseRequest(BaseModel):
    """新增用例"""
    name: str = Field(..., description="用例名称")
    description: Optional[str] = Field(None, description="用例描述")
    suite_id: int = Field(..., description="所属用例集ID")
    script: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="步骤列表")


class EditApiCaseRequest(BaseModel):
    """编辑用例"""
    id: int = Field(..., description="用例ID")
    name: Optional[str] = Field(None, description="用例名称")
    description: Optional[str] = Field(None, description="用例描述")
    script: Optional[List[Dict[str, Any]]] = Field(None, description="步骤列表")


class DelApiCaseRequest(BaseModel):
    """删除用例"""
    id: int = Field(..., description="用例ID")


class RunApiCaseRequest(BaseModel):
    """执行用例"""
    case_ids: List[int] = Field(..., description="用例ID列表")
    env_id: int = Field(..., description="环境ID")
    name: Optional[str] = Field(None, description="任务名称，不传则自动生成")
    result_id: Optional[int] = Field(None, description="前端指定的执行ID，用于轮询")
