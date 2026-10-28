"""Initialize the teaching project databases on a fresh installation.

No API calls; safe to repeat. Back up an existing SQLite DB before schema
migration. Run from the project directory after installing dependencies.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from database import init_database
from import_agent_logs_v2 import ensure_schema
from quality_store import init_quality_db
from token_usage import init_db as init_usage_db
from rag_kb import init_db as init_kb_db

ROOT = Path(__file__).resolve().parent
DB = ROOT / "multiagent.db"


def main():
    if DB.exists():
        backup_dir = ROOT / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"multiagent_before_setup_{datetime.now():%Y%m%d_%H%M%S_%f}.db"
        with sqlite3.connect(DB) as src, sqlite3.connect(backup) as dst:
            src.backup(dst)
        print(f"已备份原数据库：{backup}")
    init_database()
    with sqlite3.connect(DB, timeout=30) as conn:
        ensure_schema(conn)
    init_usage_db()
    init_quality_db()
    init_kb_db()
    print("基础数据库、V2 Agent 执行记录、Token、质量评分和 RAG 表已初始化。")
    print("若有知识库文件，放入 knowledge_docs/ 后执行 python rag_kb.py index。")


if __name__ == "__main__":
    main()
