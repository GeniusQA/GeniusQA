# -*- coding: utf-8 -*-
# @author: rebort

import traceback

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, ProgrammingError, OperationalError
from sqlalchemy.orm.exc import UnmappedInstanceError
from starlette.requests import Request

from app.core.codes import CodeEnum
from app.exceptions.exceptions import IpError, ErrorUser, UserNotExist, SetRedis, AccessTokenFail, IdNotExist, \
    ParameterError
from app.common.response import error_response, success_response


def init_exception(app: FastAPI):
    """ 全局异常捕获 """

    @app.exception_handler(IpError)
    async def ip_error_handler(request: Request, exc: IpError):
        """ ip错误(自定义异常) """
        logger.warning(f"{exc.msg}:{exc.code}\nURL:{request.method}-{request.url}\nHeaders:{request.headers}")
        return JSONResponse(
            status_code=400,
            content=error_response(message=exc.msg, code=exc.code)
        )

    @app.exception_handler(ErrorUser)
    async def error_user_handler(request: Request, exc: ErrorUser):
        """ 错误的用户名或密码(自定义异常) """
        logger.warning(f"{exc.msg}:{exc.code}\nURL:{request.method}-{request.url}\nHeaders:{request.headers}")
        return JSONResponse(
            status_code=400,
            content=error_response(message=exc.msg, code=exc.code)
        )

    @app.exception_handler(UserNotExist)
    async def user_not_exist_handler(request: Request, exc: UserNotExist):
        """ 用户不存在(自定义异常) """
        logger.warning(f"{exc.msg}:{exc.code}\nURL:{request.method}-{request.url}\nHeaders:{request.headers}")
        return JSONResponse(
            status_code=400,
            content=error_response(message=exc.msg, code=exc.code)
        )

    @app.exception_handler(IdNotExist)
    async def id_not_exist_handler(request: Request, exc: IdNotExist):
        """ 查询id不存在(自定义异常) """
        logger.warning(f"{exc.msg}:{exc.code}\nURL:{request.method}-{request.url}\nHeaders:{request.headers}")
        return JSONResponse(
            status_code=400,
            content=error_response(message=exc.msg, code=exc.code)
        )

    @app.exception_handler(SetRedis)
    async def set_redis_handler(request: Request, exc: SetRedis):
        """ Redis存储失败(自定义异常) """
        logger.warning(f"{exc.msg}:{exc.code}\nURL:{request.method}-{request.url}\nHeaders:{request.headers}")
        return JSONResponse(
            status_code=400,
            content=error_response(message=exc.msg, code=exc.code)
        )

    @app.exception_handler(AccessTokenFail)
    async def access_token_fail_handler(request: Request, exc: AccessTokenFail):
        """ 访问令牌失效 """
        logger.warning(f"{exc.msg}:{exc.code}\nURL:{request.method}-{request.url}\nHeaders:{request.headers}")
        return JSONResponse(
            status_code=401,
            content=error_response(message=exc.msg, code=exc.code),
            headers={'Access-Control-Allow-Origin': '*'}
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """ FastAPI HTTPException处理 """
        logger.warning(f"HTTP异常: {exc.status_code} - {exc.detail}\nURL:{request.method}-{request.url}")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(message=exc.detail, code=exc.status_code),
            headers={'Access-Control-Allow-Origin': '*'}
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        """ 添加/更新的数据与数据库中数据冲突 """
        text = f"添加/更新的数据与数据库中数据冲突!"
        logger.warning(f"{text}\nURL:{request.method}-{request.url}\nHeaders:{request.headers}\nerror:{exc.orig}")
        return JSONResponse(
            status_code=400,
            content=error_response(message=text, code=400)
        )

    @app.exception_handler(ProgrammingError)
    async def programming_error_handle(request: Request, exc: ProgrammingError):
        """ 请求参数丢失 """
        logger.error(f"请求参数丢失\nURL:{request.method}-{request.url}\nHeaders:{request.headers}\nerror:{exc}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=400,
            content=error_response(message='请求参数丢失!(实际请求参数错误)', code=400)
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
        """ 请求参数验证异常 """
        logger.error(
            f"请求参数格式错误\nURL:{request.method}-{request.url}\nHeaders:{request.headers}\nerror:{exc.errors()}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=422,
            content=error_response(message="参数错误", code=CodeEnum.PARTNER_CODE_FAIL.code)
        )

    @app.exception_handler(ValidationError)
    async def inner_validation_exception_handler(request: Request, exc: ValidationError):
        """ 内部参数验证异常 """
        logger.error(
            f"内部参数验证错误\nURL:{request.method}-{request.url}\nHeaders:{request.headers}\nerror:{exc.errors()}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content=error_response(message=str(exc.errors()), code=500)
        )

    @app.exception_handler(OperationalError)
    async def operational_error_handler(request: Request, exc: OperationalError):
        """ 数据库连接/操作错误（如密码错误、连接失败等）"""
        error_msg = str(exc.orig) if exc.orig else str(exc)
        logger.error(f"数据库操作错误\nURL:{request.method}-{request.url}\nerror:{error_msg}")
        # 判断错误类型，返回用户友好的提示
        if 'Access denied' in error_msg:
            friendly_msg = '数据库连接失败：用户名或密码错误，请检查配置'
        elif 'Can\'t connect' in error_msg or 'Connection refused' in error_msg:
            friendly_msg = '数据库连接失败：无法连接到数据库服务器，请检查数据库是否启动'
        elif 'Unknown database' in error_msg:
            friendly_msg = '数据库连接失败：指定的数据库不存在'
        else:
            friendly_msg = '数据库操作失败，请稍后重试'
        return JSONResponse(
            status_code=500,
            content=error_response(message=friendly_msg, code=500)
        )

    @app.exception_handler(UnmappedInstanceError)
    async def un_mapped_instance_error_handler(request: Request, exc: UnmappedInstanceError):
        """ 删除数据的id在数据库中不存在 """
        id = request.path_params.get("id")
        text = f"不存在编号为 {id} 的数据, 删除失败!"
        logger.warning(f"{text}\nURL:{request.method}-{request.url}\nHeaders:{request.headers}")
        return JSONResponse(
            status_code=400,
            content=error_response(message=text, code=400)
        )

    @app.exception_handler(ParameterError)
    async def parameter_error_handler(request: Request, exc: ParameterError):
        """ 参数错误 """
        logger.error(
            f"参数错误\n{request.method}URL:{request.url}\nHeaders:{request.headers}\n{traceback.format_exc()}")
        return JSONResponse(
            status_code=400,
            content=error_response(message=exc.msg, code=exc.code)
        )

    @app.exception_handler(Exception)
    async def all_exception_handler(request: Request, exc: Exception):
        """ 捕获全局异常 """
        logger.error(
            f"全局异常\n{request.method} URL:{request.url}\nHeaders:{request.headers}\n{traceback.format_exc()}")
        # 不要暴露原始错误详情给用户，返回通用错误信息
        return JSONResponse(
            status_code=500,
            content=error_response(message='服务器内部错误，请稍后重试', code=CodeEnum.PARTNER_CODE_FAIL.code),
            headers={'Access-Control-Allow-Origin': '*'}
        )
