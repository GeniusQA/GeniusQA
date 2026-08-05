import asyncio
from app.infra.db.sqlalchemy import async_session_factory
from sqlalchemy import text


async def main():
    async with async_session_factory() as db:
        # 补齐旧报告 status：有真实覆盖率 → completed，否则 pending
        await db.execute(
            text(
                "UPDATE ntest_coverage_report "
                "SET status = CASE "
                "  WHEN coverage_rate IS NULL OR coverage_rate IN ('0.0%', 'ERROR') THEN 'pending' "
                "  ELSE 'completed' "
                "END "
                "WHERE status IS NULL"
            )
        )
        await db.commit()
        print("status patched")

        res = await db.execute(
            text(
                "SELECT id,name,status,coverage_rate FROM ntest_coverage_report "
                "ORDER BY id DESC LIMIT 5"
            )
        )
        for row in res.fetchall():
            print(row)


asyncio.run(main())
