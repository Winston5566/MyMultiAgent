
import sqlite3

from pathlib import Path
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "multiagent.db"


def now():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    # 允许读写更好地并发
    conn.execute("PRAGMA journal_mode=WAL")

    return conn


def init_database():

    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                status TEXT NOT NULL,
                duration_seconds REAL,
                error_message TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
        """)

    print("数据库初始化成功：", DB_FILE)


def create_job(job_id, task):

    timestamp = now()

    with get_connection() as conn:

        conn.execute("""
            INSERT INTO jobs (
                id, task, status,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            job_id,
            task,
            "queued",
            timestamp,
            timestamp
        ))


def update_job_status(job_id, status, error=None):

    with get_connection() as conn:

        cursor = conn.execute("""
            UPDATE jobs
            SET status = ?,
                updated_at = ?,
                error = ?
            WHERE id = ?
        """, (
            status,
            now(),
            error,
            job_id
        ))

        if cursor.rowcount == 0:
            raise ValueError("任务不存在")


def get_job(job_id):

    with get_connection() as conn:

        row = conn.execute("""
            SELECT *
            FROM jobs
            WHERE id = ?
        """, (job_id,)).fetchone()

        return dict(row) if row else None


def list_jobs():

    with get_connection() as conn:

        rows = conn.execute("""
            SELECT *
            FROM jobs
            ORDER BY created_at DESC
        """).fetchall()

        return [dict(row) for row in rows]


def upsert_job(
    job_id,
    task,
    status,
    created_at=None,
    updated_at=None,
    error=None
):
    """
    新任务：插入数据库。
    已有任务：更新状态等信息。
    """

    timestamp = now()

    created_at = created_at or timestamp
    updated_at = updated_at or timestamp

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO jobs (
                id,
                task,
                status,
                created_at,
                updated_at,
                error
            )
            VALUES (?, ?, ?, ?, ?, ?)

            ON CONFLICT(id) DO UPDATE SET
                task = excluded.task,
                status = excluded.status,
                updated_at = excluded.updated_at,
                error = excluded.error
        """, (
            job_id,
            task,
            status,
            str(created_at),
            str(updated_at),
            error
        ))

if __name__ == "__main__":
    init_database()
