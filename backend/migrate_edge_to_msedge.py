# -*- coding: utf-8 -*-
"""
一次性迁移脚本：将 UI 自动化相关配置表中 browser_type='edge' 的记录更新为 'msedge'。
配合"全量切到系统 Edge"改造，使存量项目/套件与新默认值保持一致。
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, r"D:\GeniusQA\backend")

env_path = Path(r"D:\GeniusQA\backend\.env")
if env_path.exists():
    load_dotenv(env_path, override=True)

from config import config


def run():
    db_uri = config.DATABASE_URI_SYNC or config.DATABASE_URI
    if not db_uri:
        print("未配置同步数据库连接，尝试从 DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME 拼接...")
        if not all([config.DB_HOST, config.DB_USER, config.DB_NAME]):
            raise RuntimeError("数据库连接信息缺失，无法执行迁移")
        db_uri = (
            f"mysql+pymysql://{config.DB_USER}:{config.DB_PASSWORD}"
            f"@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"
        )

    engine = create_engine(db_uri, future=True)
    tables = ["ui_projects", "ui_test_suites"]

    with engine.begin() as conn:
        for table in tables:
            try:
                result = conn.execute(
                    text(f"UPDATE {table} SET browser_type = 'msedge' WHERE browser_type = 'edge'")
                )
                print(f"[{table}] 更新 {result.rowcount} 条 edge -> msedge")
            except Exception as e:
                print(f"[{table}] 更新失败: {e}")

    print("迁移完成")


if __name__ == "__main__":
    run()
