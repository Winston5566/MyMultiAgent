"""第29课：RAG 检索片段的启发式安全检查和最小化审计。

只用于教学级防护：无法保证发现所有提示词注入、隐私或密钥泄露。
日志不存储原始问题、文件名或文档内容。
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import hashlib
import re
import sqlite3

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "multiagent.db"

INJECTION_RULES = (
    ("override_zh", re.compile(r"忽略.{0,20}(之前|以上|此前|所有).{0,15}(指令|规则|要求|提示)", re.I | re.S)),
    ("override_en", re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions", re.I)),
    ("role_spoofing", re.compile(r"<\|im_start\|>\s*(?:system|developer)|\[INST\]|\[SYSTEM\]", re.I)),
    ("prompt_disclosure", re.compile(r"(?:系统提示词|system\s+prompt|developer\s+message).{0,35}(?:输出|打印|展示|泄露|发送|reveal|print|show)", re.I | re.S)),
    ("secret_exfiltration", re.compile(r"(?:读取|输出|打印|泄露|发送|上传|窃取|read|send|upload|exfiltrate).{0,55}(?:API_KEY|OPENAI_API_KEY|\.env|密钥|secret[_ -]?key|access[_ -]?token)", re.I | re.S)),
    ("shell_execution", re.compile(r"(?:执行|运行|execute|run)\s*(?:shell|终端|命令|command).{0,45}(?:curl|wget|rm\s+-rf|bash\s+-c)", re.I | re.S)),
)

SECRET_PATTERNS = (
    ("api_key", re.compile(r"(?i)\b(API_KEY|OPENAI_API_KEY|SECRET_KEY|ACCESS_TOKEN|PASSWORD)\s*[:=]\s*['\"]?[A-Za-z0-9_./+\-]{8,}")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{12,}")),
    ("sk_token", re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")),
)


def inspect_chunk(text: str) -> dict:
    """返回 blocked / rules / sanitized / redactions；不执行文本里的任何内容。"""
    if not isinstance(text, str):
        raise TypeError("text 必须为字符串")
    triggered = [name for name, pattern in INJECTION_RULES if pattern.search(text)]
    sanitized = text
    redactions = []
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(sanitized):
            redactions.append(name)
            if name == "api_key":
                sanitized = pattern.sub(lambda m: m.group(1) + "=[REDACTED]", sanitized)
            elif name == "bearer":
                sanitized = pattern.sub("Bearer [REDACTED]", sanitized)
            else:
                sanitized = pattern.sub("[REDACTED_API_KEY]", sanitized)
    return {
        "blocked": bool(triggered),
        "rules": triggered,
        "sanitized": sanitized,
        "redactions": redactions,
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def record_event(*, event_type: str, rule: str, source: str, content: str,
                 db_path: Path = DEFAULT_DB) -> None:
    """仅写入事件类型、规则和 SHA256 摘要，不记录原文。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path, timeout=5)) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                rule TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                content_sha256 TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO rag_security_events
            (created_at, event_type, rule, source_sha256, content_sha256)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            event_type, rule[:100], _digest(source), _digest(content),
        ))


def list_events(*, db_path: Path = DEFAULT_DB, limit: int = 200) -> list[dict]:
    db_path = Path(db_path)
    if not db_path.is_file():
        return []
    try:
        with closing(sqlite3.connect(db_path, timeout=5)) as conn:
            exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rag_security_events'").fetchone()
            if not exists:
                return []
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, created_at, event_type, rule,
                       substr(source_sha256, 1, 12) AS source_hash,
                       substr(content_sha256, 1, 12) AS content_hash
                FROM rag_security_events ORDER BY id DESC LIMIT ?
            """, (max(1, min(int(limit), 1000)),)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
