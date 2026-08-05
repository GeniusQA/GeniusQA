import asyncio
from app.infra.db.sqlalchemy import async_session_factory
from sqlalchemy import text


async def main():
    async with async_session_factory() as db:
        res = await db.execute(
            text(
                "SELECT id,name,status,coverage_rate FROM ntest_coverage_report "
                "ORDER BY id DESC LIMIT 3"
            )
        )
        for row in res.fetchall():
            print(row)


asyncio.run(main())
