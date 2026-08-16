# -*- coding: utf-8 -*-
# @author: Rebort
from contextlib import asynccontextmanager
import asyncio
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import base64
import secrets
from fastapi.staticfiles import StaticFiles
from app.core.logger import init_logger, logger
from app.bootstrap.cors import init_cors
from app.bootstrap.exception import init_exception
from app.bootstrap.middleware import init_middleware
from app.bootstrap.minio import init_minio
from app.bootstrap.scheduler import init_scheduler, shutdown_scheduler, load_perf_pending_jobs
from app.bootstrap.routers import init_router
from app.bootstrap.mount import init_mount
from app.bootstrap.limiter import init_limiter
from config import config


@asynccontextmanager
async def start_app(app: FastAPI):
    """ 注册中心 """
    # 获取Redis连接池（延迟初始化）
    from app.infra.db import get_redis_pool
    redis_pool_instance = get_redis_pool()
    redis_pool_instance.init_by_config(config=config)

    init_logger()
    logger.info("日志初始化成功！！!")

    # 初始化限流器（异步）
    await init_limiter(app)

    # 初始化Minio文件服务
    await init_minio()

    # 启动 APScheduler 定时任务调度器
    init_scheduler()
    # 注册绑定数据源定时同步 job
    try:
        from app.api.v1.Ntesterc_module.Ntesterc_api.datasource_sync import register_datasource_sync_job
        register_datasource_sync_job()
    except Exception:
        pass

    # 恢复性能测试待触发定时任务（MemoryJobStore 重启后清空）
    await load_perf_pending_jobs()

    yield

    
    try:
        shutdown_scheduler()
    except Exception as e:
        logger.warning(f"关闭 APScheduler 失败: {e}")

    try:
        redis = redis_pool_instance.redis
        if redis is not None:
            close = getattr(redis, "aclose", None) or redis.close
            await asyncio.wait_for(close(), timeout=3)
    except Exception as e:
        logger.warning(f"关闭 Redis 失败: {e}")

    try:
        from app.infra.db.sqlalchemy import engine
        await asyncio.wait_for(engine.dispose(), timeout=5)
    except Exception as e:
        logger.warning(f"关闭数据库引擎失败: {e}")

    # loguru enqueue=True 时需 complete，否则后台写日志线程会拖住进程
    try:
        await asyncio.wait_for(logger.complete(), timeout=2)
    except Exception:
        pass


def create_app() -> FastAPI:
    app: FastAPI = FastAPI(
        title="N-Tester2.0 API",
        description=config.SERVER_DESC,
        version=str(config.SERVER_VERSION),  # 确保版本号是字符串
        lifespan=start_app,
        docs_url=None,  # 禁用默认的 /docs
        redoc_url=None,  # 禁用默认的 /redoc
        openapi_url="/openapi.json",  # OpenAPI schema 路径
    )
    # /openapi.json Basic Auth 保护（平台自身接口文档不公开暴露）
    OPENAPI_BASIC_USER = "Genius"
    OPENAPI_BASIC_PASS = "86340365"

    @app.middleware("http")
    async def openapi_basic_auth(request: Request, call_next):
        if request.url.path == "/openapi.json":
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Basic "):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Basic"})
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8", "ignore")
                user, _, pwd = decoded.partition(":")
                ok = secrets.compare_digest(user, OPENAPI_BASIC_USER) and secrets.compare_digest(pwd, OPENAPI_BASIC_PASS)
            except Exception:
                ok = False
            if not ok:
                return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Basic"})
        if request.url.path.startswith("/assets/"):
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            return response
        return await call_next(request)

    init_exception(app)  # 注册捕获全局异常
    init_router(app)  # 注册路由
    init_middleware(app)  # 注册请求响应拦截
    init_cors(app)  # 初始化跨域
    init_mount(app)  # 挂载静态文件

    # 托管前端 dist（SPA）：静态资源 + 客户端路由回退 index.html
    _fe_cfg = getattr(config, "FRONTEND_DIST", None)
    if _fe_cfg:
        _frontend_dist = Path(_fe_cfg)
    else:
        # 默认：项目根下 frontend/dist
        _frontend_dist = Path(config.BASEDIR) / "frontend" / "dist"
    if _frontend_dist.is_dir():
        # 显式挂载子目录，避免与 /static、/media、/uploads 冲突
        for _sub in ("assets", "monacoeditorwork"):
            _sub_dir = _frontend_dist / _sub
            if _sub_dir.is_dir():
                app.mount(f"/{_sub}", StaticFiles(directory=str(_sub_dir)), name=f"frontend_{_sub}")

    # ===== 平台自建测试服务 =====
    # ① WebSocket Echo：连接后任何消息原样回显（文本/二进制），用于验证 WS 收发链路
    @app.websocket("/ws_test_echo")
    async def ws_test_echo(websocket: WebSocket):
        """平台自建 WebSocket 测试服务：连接后发消息原样回显"""
        await websocket.accept()
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("type") == "websocket.receive":
                    if msg.get("text") is not None:
                        await websocket.send_text(str(msg.get("text") or ""))
                    elif msg.get("bytes") is not None:
                        await websocket.send_bytes(msg.get("bytes") or b"")
        except WebSocketDisconnect:
            pass

    # ② Webhook 接收回显：接收任意请求，回显 method/url/headers/body/时间
    @app.post("/webhook_test")
    async def webhook_test(request: Request):
        """平台自建 Webhook 测试服务：接收请求并回显请求详情"""
        import json as _json
        from datetime import datetime as _dt
        try:
            raw = await request.body()
            body_text = raw.decode("utf-8", errors="replace") if raw else ""
            try:
                body_json = _json.loads(body_text) if body_text.strip() else {}
            except Exception:
                body_json = None
            return {
                "code": 200,
                "message": "平台 Webhook 测试服务：收到请求并回显",
                "data": {
                    "method": request.method,
                    "url": str(request.url),
                    "headers": {k: v for k, v in request.headers.items() if k.lower() not in ("cookie",)},
                    "body": body_json if body_json is not None else body_text,
                    "time": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            }
        except Exception as e:  # noqa: BLE001
            return {"code": 500, "data": None, "message": f"处理失败: {e}"}

    # 自定义 API 文档路由（必须在 catch-all 前面注册，否则被拦截）
    _swagger_dir = Path(__file__).resolve().parent / "static" / "swagger"

    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        """Swagger UI 文档"""
        with open(_swagger_dir / "swagger.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    @app.get("/redoc", include_in_schema=False)
    async def custom_redoc_html():
        """ReDoc 文档"""
        with open(_swagger_dir / "redoc.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    # 根路径与所有未匹配路径均回退到 index.html（SPA 客户端路由）
    @app.get("/", include_in_schema=False)
    async def _frontend_root():
        return FileResponse(str(_frontend_dist / "index.html"), headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_catch_all(full_path: str):
        # 排除 API、静态文件、文档等已注册路由
        _reserved = ("api/", "static/", "media/", "uploads/", "docs", "redoc", "openapi")
        if any(full_path.startswith(p) or full_path == p.rstrip("/") for p in _reserved):
            raise HTTPException(status_code=404, detail="Not Found")
        # 尝试直接返回静态文件（favicon 等）
        _file = _frontend_dist / full_path
        if _file.is_file():
            return FileResponse(str(_file))
        # 其余全部回退到 index.html
        return FileResponse(str(_frontend_dist / "index.html"), headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

    return app


app = create_app()


if __name__ == '__main__':
    # Windows 下 reload=True（WatchFiles 父子进程）Ctrl+C 后父进程经常挂死；
    # 默认关闭热重载；需要时设置环境变量 UVICORN_RELOAD=1
    _reload = os.getenv("UVICORN_RELOAD", "0").strip().lower() in {"1", "true", "yes", "on"}
    uvicorn.run(app='main:app', host="0.0.0.0", port=8100, reload=_reload)
    # gunicorn main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8101
