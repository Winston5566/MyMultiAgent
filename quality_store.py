"""第27课扩展：将规则化质量验收结果写入独立 SQLite 表。

只保存评分、检查结果和报告 SHA256，不保存完整报告正文。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from quality_eval import evaluate

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "multiagent.db"


def init_quality_db(db_path: Path = DEFAULT_DB) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quality_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                expected_amount INTEGER NOT NULL,
                score INTEGER NOT NULL,
                grade TEXT NOT NULL,
                checks_json TEXT NOT NULL,
                report_sha256 TEXT NOT NULL,
                report_chars INTEGER NOT NULL,
                evaluated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_quality_evaluated_at ON quality_evaluations(evaluated_at)")


def save_quality(report: str, *, job_id: str, expected_amount: int = 30000,
                 source: str = "manual", db_path: Path = DEFAULT_DB,
                 kb_db_path: Path | None = None) -> dict:
    """幂等记录：同一 job_id 重评会更新原记录，不会重复插入。"""
    if not job_id or not str(job_id).strip():
        raise ValueError("job_id 不能为空")
    if not report or not report.strip():
        raise ValueError("报告不能为空")
    kwargs = {"expected_amount": expected_amount}
    if kb_db_path is not None:
        kwargs["db_path"] = Path(kb_db_path)
    result = evaluate(report, **kwargs)
    db_path = Path(db_path)
    init_quality_db(db_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    digest = hashlib.sha256(report.encode("utf-8")).hexdigest()
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute("""
            INSERT INTO quality_evaluations (
                job_id, source, expected_amount, score, grade,
                checks_json, report_sha256, report_chars, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                source=excluded.source,
                expected_amount=excluded.expected_amount,
                score=excluded.score,
                grade=excluded.grade,
                checks_json=excluded.checks_json,
                report_sha256=excluded.report_sha256,
                report_chars=excluded.report_chars,
                evaluated_at=excluded.evaluated_at
        """, (
            str(job_id), source, expected_amount, result["score"], result["grade"],
            json.dumps(result["checks"], ensure_ascii=False), digest, len(report), now,
        ))
    return result


def get_quality_rows(db_path: Path = DEFAULT_DB, limit: int = 500) -> list[dict]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path, timeout=10) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='quality_evaluations'").fetchone()
        if not exists:
            return []
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("""
            SELECT job_id, source, expected_amount, score, grade, checks_json,
                   report_sha256, report_chars, evaluated_at
            FROM quality_evaluations ORDER BY evaluated_at DESC, id DESC LIMIT ?
        """, (max(1, min(int(limit), 10000)),))]
