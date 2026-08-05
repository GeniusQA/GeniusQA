import asyncio
from app.infra.db.sqlalchemy import async_session_factory
from sqlalchemy import text


async def main():
    async with async_session_factory() as db:
        res = await db.execute(
            text("SHOW COLUMNS FROM ntest_coverage_report LIKE 'status'")
        )
        if res.fetchone() is None:
            await db.execute(
                text(
                    "ALTER TABLE ntest_coverage_report ADD COLUMN status varchar(32) "
                    "NULL DEFAULT NULL COMMENT '采集状态: pending/collecting/completed/failed'"
                )
            )
            await db.commit()
            print("ALTER done: status column added")
        else:
            print("status column already exists, skip")


asyncio.run(main())
