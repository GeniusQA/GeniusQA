"""一次性脚本：给 ntest_coverage_report 表添加 duration 列"""
import pymysql

conn = pymysql.connect(
    host="localhost", port=3306,
    user="root", password="86340365",
    database="geniusqa", charset="utf8mb4"
)
cur = conn.cursor()
cur.execute(
    "SELECT COUNT(*) FROM information_schema.COLUMNS "
    "WHERE TABLE_SCHEMA='geniusqa' AND TABLE_NAME='ntest_coverage_report' AND COLUMN_NAME='duration'"
)
if cur.fetchone()[0] > 0:
    print("duration 列已存在，跳过")
else:
    cur.execute("ALTER TABLE ntest_coverage_report ADD COLUMN duration INT NULL DEFAULT NULL COMMENT '采集耗时(秒)' AFTER method_count")
    conn.commit()
    print("OK: 已添加 duration 列")
cur.close(); conn.close()
