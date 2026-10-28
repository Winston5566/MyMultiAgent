"""Import Agent events.jsonl files into SQLite, idempotently.

Usage:
    python import_agent_logs.py --dry-run
    python import_agent_logs.py
    python import_agent_logs.py  # safe to repeat
"""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "multiagent.db"
JOBS_DIR = ROOT / "jobs"
TERMINAL = {"completed", "failed"}


def read_attempts():
    """Combine event lines by (job_id, run_id, agent, attempt)."""
    attempts = {}
    counters = Counter()
    files = sorted(JOBS_DIR.glob("*/logs/events.jsonl"))

    for path in files:
        job_id = path.parent.parent.name
        counters["files"] += 1
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        counters["invalid_json"] += 1
                        continue  # A partially written final line can be imported next time.
                    if not isinstance(event, dict):
                        counters["invalid_events"] += 1
                        continue
                    kind = event.get("event")
                    if kind == "retry_scheduled":
                        counters["scheduled_retries"] += 1
                        continue
                    if kind not in {"started", "completed", "failed"}:
                        counters["other_events"] += 1
                        continue

                    run_id = event.get("run_id")
                    agent = event.get("agent")
                    attempt = event.get("attempt")
                    timestamp = event.get("timestamp")
                    if (
                        not isinstance(run_id, str) or not run_id.strip()
                        or not isinstance(agent, str) or not agent.strip()
                        or type(attempt) is not int or attempt < 1
                        or not isinstance(timestamp, str) or not timestamp.strip()
                    ):
                        counters["invalid_events"] += 1
                        continue

                    key = (job_id, run_id, agent, attempt)
                    row = attempts.setdefault(key, {
                        "job_id": job_id,
                        "run_id": run_id,
                        "agent_name": agent,
                        "attempt": attempt,
                        "status": "running",
                        "duration_seconds": None,
                        "error_message": None,
                        "created_at": timestamp,
                        "started_seen": 0,
                    })
                    # Timestamps are ISO-8601 strings from the same logger.
                    if timestamp < row["created_at"]:
                        row["created_at"] = timestamp
                    if kind == "started":
                        row["started_seen"] = 1
                    elif kind in TERMINAL:
                        row["status"] = kind
                        duration = event.get("duration_seconds")
                        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
                            row["duration_seconds"] = float(duration)
                        else:
                            row["duration_seconds"] = None
                        if kind == "failed":
                            error_type = event.get("error_type")
                            error_message = event.get("error_message")
                            parts = [str(x) for x in (error_type, error_message) if x]
                            row["error_message"] = ": ".join(parts)[:2000] if parts else None
                        else:
                            row["error_message"] = None
                    counters["accepted_events"] += 1
        except OSError as exc:
            counters["unreadable_files"] += 1
            print(f"无法读取 {path}: {exc}")

    return attempts, counters


def ensure_schema(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_executions)")}
    required = {
        "id", "job_id", "agent_name", "attempt", "status",
        "duration_seconds", "error_message", "created_at",
    }
    if not required <= cols:
        raise RuntimeError("agent_executions 表缺少原始字段，请先检查 database.py")
    if "run_id" not in cols:
        conn.execute("ALTER TABLE agent_executions ADD COLUMN run_id TEXT")
    if "started_seen" not in cols:
        conn.execute(
            "ALTER TABLE agent_executions ADD COLUMN started_seen INTEGER NOT NULL DEFAULT 0"
        )
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_execution_attempt
        ON agent_executions (job_id, run_id, agent_name, attempt)
    """)


def import_rows(conn, attempts):
    job_ids = {r[0] for r in conn.execute("SELECT id FROM jobs")}
    skipped_missing_job = sum(1 for row in attempts.values() if row["job_id"] not in job_ids)
    eligible = [row for row in attempts.values() if row["job_id"] in job_ids]
    before = conn.execute("SELECT COUNT(*) FROM agent_executions").fetchone()[0]
    for row in eligible:
        conn.execute("""
            INSERT INTO agent_executions (
                job_id, run_id, agent_name, attempt, status,
                duration_seconds, error_message, created_at, started_seen
            ) VALUES (
                :job_id, :run_id, :agent_name, :attempt, :status,
                :duration_seconds, :error_message, :created_at, :started_seen
            )
            ON CONFLICT(job_id, run_id, agent_name, attempt)
            DO UPDATE SET
                status = excluded.status,
                duration_seconds = excluded.duration_seconds,
                error_message = excluded.error_message,
                created_at = excluded.created_at,
                started_seen = excluded.started_seen
            WHERE
                agent_executions.status IS NOT excluded.status
                OR agent_executions.duration_seconds IS NOT excluded.duration_seconds
                OR agent_executions.error_message IS NOT excluded.error_message
                OR agent_executions.created_at IS NOT excluded.created_at
                OR agent_executions.started_seen IS NOT excluded.started_seen
        """, row)
    after = conn.execute("SELECT COUNT(*) FROM agent_executions").fetchone()[0]
    return len(eligible), after - before, skipped_missing_job


def print_stats(conn):
    print("\n===== Agent 性能统计（数据库） =====")
    rows = conn.execute("""
        SELECT agent_name,
               COUNT(*) AS total,
               SUM(CASE WHEN started_seen = 1 THEN 1 ELSE 0 END) AS starts,
               SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS successes,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failures,
               SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
               SUM(CASE WHEN attempt > 1 AND started_seen = 1 THEN 1 ELSE 0 END) AS retries,
               AVG(CASE WHEN status = 'completed' THEN duration_seconds END) AS avg_seconds
        FROM agent_executions
        WHERE run_id IS NOT NULL
        GROUP BY agent_name
        ORDER BY agent_name
    """).fetchall()
    for agent, total, starts, success, failure, running, retries, avg_seconds in rows:
        finished = success + failure
        rate = 100 * success / finished if finished else 0
        avg = f"{avg_seconds:.3f}s" if avg_seconds is not None else "暂无"
        print(
            f"{agent}: 记录={total}, 启动={starts}, 成功={success}, "
            f"失败={failure}, 运行中={running}, 实际重试={retries}, "
            f"成功率={rate:.1f}%, 成功平均耗时={avg}"
        )
    if not rows:
        print("暂无已导入的 Agent 执行记录")


def main():
    parser = argparse.ArgumentParser(description="导入 Agent 事件日志到 SQLite")
    parser.add_argument("--dry-run", action="store_true", help="只检查，不修改数据库")
    args = parser.parse_args()

    if not DB_PATH.is_file():
        raise SystemExit(f"数据库不存在：{DB_PATH}")
    attempts, counters = read_attempts()
    print("===== 日志扫描 =====")
    for key in (
        "files", "accepted_events", "scheduled_retries", "invalid_json",
        "invalid_events", "unreadable_files", "other_events",
    ):
        print(f"{key}: {counters[key]}")
    print(f"识别出的 Agent 执行尝试：{len(attempts)}")

    if args.dry_run:
        print("DRY RUN：未修改数据库。")
        return

    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # SQLite's online backup API creates a consistent snapshot.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = ROOT / f"multiagent_backup_{stamp}.db"
        with sqlite3.connect(backup_path) as backup_conn:
            conn.backup(backup_conn)
        print(f"数据库备份：{backup_path.name}")

        with conn:
            ensure_schema(conn)
            eligible, inserted, skipped = import_rows(conn, attempts)
        print("\n===== 导入结果 =====")
        print(f"可导入记录：{eligible}")
        print(f"新增记录：{inserted}")
        print(f"已有记录：{eligible - inserted}（重复执行不会新增）")
        print(f"跳过（jobs 表缺少对应 job_id）：{skipped}")
        print_stats(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
