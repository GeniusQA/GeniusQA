# -*- coding: utf-8 -*-
"""绑定数据源定时同步：按导入频率到期自动拉取更新接口数据"""
import asyncio
from datetime import datetime
from typing import Optional

from apscheduler.triggers.interval import IntervalTrigger
from app.core.logger import logger

_FREQ_SECONDS = {
    "30m": 30 * 60,
    "1h": 60 * 60,
    "3h": 3 * 60 * 60,
    "6h": 6 * 60 * 60,
    "12h": 12 * 60 * 60,
    "24h": 24 * 60 * 60,
}


async def sync_due_datasources() -> None:
    """扫描所有已绑定数据源的服务，频率到期的执行同步"""
    try:
        from app.infra.db.sqlalchemy import async_session_factory
        from sqlalchemy import select
        from app.api.v1.Ntesterc_module.Ntesterc_api.model import ApiServiceModel
        from app.api.v1.Ntesterc_module.Ntesterc_api.service import ApiAutomationService

        async with async_session_factory() as db:
            svcs = (
                await db.execute(
                    select(ApiServiceModel).where(ApiServiceModel.enabled_flag == 1)
                )
            ).scalars().all()
            now = datetime.now()
            for svc in svcs:
                cfg = svc.data_source_config or {}
                if not isinstance(cfg, dict) or not cfg.get("url"):
                    continue
                freq = str(cfg.get("frequency") or "3h")
                if freq == "manual":
                    continue  # 手动触发：不自动同步，仅由「立即导入」执行
                interval = _FREQ_SECONDS.get(freq, 3 * 60 * 60)
                last = str(cfg.get("last_sync_at") or "")
                if last:
                    try:
                        last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
                        if (now - last_dt).total_seconds() < interval:
                            continue
                    except Exception:
                        pass
                try:
                    logger.info(f"[datasource-sync] 自动同步 服务#{svc.id} url={str(cfg.get('url'))[:60]}")
                    await ApiAutomationService.sync_data_source(db, int(svc.id), int(svc.created_by or 1))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[datasource-sync] 服务#{svc.id} 同步失败: {e}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[datasource-sync] 扫描失败: {e}")


def register_datasource_sync_job() -> None:
    """注册定时同步 job（每 10 分钟扫描一次）"""
    try:
        from app.api.v1.Ntesterc_module.Ntesterc_task_scheduler.scheduler import get_scheduler
        sched = get_scheduler()
        sched.add_job(
            sync_due_datasources,
            IntervalTrigger(minutes=10),
            id="datasource_sync",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        logger.info("数据源定时同步 job 已注册（每 10 分钟扫描）")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"数据源定时同步 job 注册失败: {e}")
