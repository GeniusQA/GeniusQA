import asyncio
from app.infra.db.sqlalchemy import async_session_factory
from sqlalchemy import text


async def main():
    async with async_session_factory() as db:
        res = await db.execute(
            text("SHOW COLUMNS FROM ntest_coverage_report LIKE 'progress'")
        )
        if res.fetchone() is None:
            await db.execute(
                text(
                    "ALTER TABLE ntest_coverage_report ADD COLUMN progress json "
                    "NULL COMMENT '采集步骤进度 JSON: [{step,name,status,detail}]'"
                )
            )
            await db.commit()
            print("ALTER done: progress column added")
        else:
            print("progress column already exists, skip")


asyncio.run(main())
