"""V2 Agent JSONL log importer for the MyMultiAgent teaching project.

Keeps distinct executions of the same (job, run, agent, attempt) via execution_seq.
Does not invoke any model API. Run `python setup_project.py` first on a new install.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "multiagent.db"
JOBS_DIR = ROOT / "jobs"
TERMINAL = {"completed", "failed"}


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Upgrade base agent_executions schema in place. Back up DB before migration."""
    columns = {r[1] for r in conn.execute("PRAGMA table_info(agent_executions)")}
    base = {"id", "job_id", "agent_name", "attempt", "status",
            "duration_seconds", "error_message", "created_at"}
    if not base <= columns:
        raise RuntimeError("缺少 agent_executions 基础表，请先执行 python setup_project.py")
    for name, definition in (
        ("run_id", "TEXT"),
        ("execution_seq", "INTEGER NOT NULL DEFAULT 1"),
        ("started_seen", "INTEGER NOT NULL DEFAULT 0"),
        ("ended_at", "TEXT"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE agent_executions ADD COLUMN {name} {definition}")
    conn.execute("UPDATE agent_executions SET execution_seq=1 WHERE execution_seq IS NULL")
    # Legacy V1 index prevents a repeated attempt from having execution_seq > 1.
    conn.execute("DROP INDEX IF EXISTS ux_agent_execution_attempt")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_execution_instance
        ON agent_executions(job_id, run_id, agent_name, attempt, execution_seq)
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_execution_job ON agent_executions(job_id)")


def parse_logs(jobs_dir: Path = JOBS_DIR):
    """Return (execution rows, counters), reading only valid JSONL events.

    Each 'started' creates a new execution instance. Terminal events attach to
    the latest unfinished matching instance, or form an orphan terminal row.
    """
    records = []
    counts = Counter()
    for path in sorted(Path(jobs_dir).glob("*/logs/events.jsonl")):
        job_id = path.parent.parent.name
        counts["files"] += 1
        seqs = defaultdict(int)
        pending = defaultdict(list)
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        counts["invalid_json"] += 1
                        continue
                    if not isinstance(event, dict):
                        counts["invalid_events"] += 1
                        continue
                    kind = event.get("event")
                    if kind not in {"started", "completed", "failed"}:
                        continue
                    run_id = event.get("run_id")
                    agent = event.get("agent")
                    attempt = event.get("attempt")
                    timestamp = event.get("timestamp")
                    if (not isinstance(run_id, str) or not run_id.strip()
                            or not isinstance(agent, str) or not agent.strip()
                            or type(attempt) is not int or attempt < 1
                            or not isinstance(timestamp, str) or not timestamp.strip()):
                        counts["invalid_events"] += 1
                        continue
                    key = (run_id, agent, attempt)
                    if kind == "started" or not pending[key]:
                        seqs[key] += 1
                        row = dict(job_id=job_id, run_id=run_id, agent_name=agent,
                                   attempt=attempt, execution_seq=seqs[key],
                                   status="running", duration_seconds=None,
                                   error_message=None, created_at=timestamp,
                                   ended_at=None, started_seen=int(kind == "started"))
                        records.append(row)
                        if kind == "started":
                            pending[key].append(row)
                    else:
                        row = pending[key].pop()
                    if kind in TERMINAL:
                        row["status"] = kind
                        row["ended_at"] = timestamp
                        duration = event.get("duration_seconds")
                        if type(duration) in (int, float) and 0 <= duration < float("inf"):
                            row["duration_seconds"] = float(duration)
                        if kind == "failed":
                            parts = [str(event[x]) for x in ("error_type", "error_message") if event.get(x)]
                            row["error_message"] = ": ".join(parts)[:2000] if parts else None
                    counts["accepted_events"] += 1
        except (OSError, UnicodeDecodeError):
            counts["unreadable_files"] += 1
    return records, counts


def import_records(conn: sqlite3.Connection, records):
    """Upsert valid executions; returns (eligible, new, missing_job)."""
    valid_jobs = {r[0] for r in conn.execute("SELECT id FROM jobs")}
    eligible = [r for r in records if r["job_id"] in valid_jobs]
    missing = len(records) - len(eligible)
    before = conn.execute("SELECT COUNT(*) FROM agent_executions").fetchone()[0]
    sql = """
        INSERT INTO agent_executions
        (job_id, run_id, agent_name, attempt, execution_seq, status,
         duration_seconds, error_message, created_at, ended_at, started_seen)
        VALUES
        (:job_id, :run_id, :agent_name, :attempt, :execution_seq, :status,
         :duration_seconds, :error_message, :created_at, :ended_at, :started_seen)
        ON CONFLICT(job_id, run_id, agent_name, attempt, execution_seq)
        DO UPDATE SET status=excluded.status,
            duration_seconds=excluded.duration_seconds,
            error_message=excluded.error_message,
            created_at=excluded.created_at,
            ended_at=excluded.ended_at,
            started_seen=excluded.started_seen
    """
    for row in eligible:
        conn.execute(sql, row)
    after = conn.execute("SELECT COUNT(*) FROM agent_executions").fetchone()[0]
    return len(eligible), after - before, missing


def main():
    parser = argparse.ArgumentParser(description="V2 日志导入及数据库迁移")
    parser.add_argument("--dry-run", action="store_true", help="只扫描日志，不修改数据库")
    args = parser.parse_args()
    rows, counts = parse_logs()
    print(f"扫描到 {len(rows)} 个执行实例；无效 JSON {counts['invalid_json']} 行")
    if args.dry_run:
        return
    if not DB_PATH.exists():
        raise SystemExit("数据库不存在，请先运行 python setup_project.py")
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        ensure_schema(conn)
        eligible, added, missing = import_records(conn, rows)
    print(f"可导入 {eligible}，新增 {added}，缺少任务主记录 {missing}")


if __name__ == "__main__":
    main()
