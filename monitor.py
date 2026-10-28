
import json
import logging
import threading
import time
import uuid
import os

from datetime import datetime, timezone
from pathlib import Path


LOG_DIR = Path(
    os.getenv("MULTIAGENT_LOG_DIR", "logs")
)
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "agent.log"
EVENT_FILE = LOG_DIR / "events.jsonl"

# 防止多个线程同时写入结构化事件
event_lock = threading.Lock()

logger = logging.getLogger("MultiAgent")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    handler = logging.FileHandler(
        LOG_FILE,
        encoding="utf-8"
    )

    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )
    )

    logger.addHandler(handler)


class AgentMonitor:

    def __init__(self, run_id=None):
        self.run_id = run_id or uuid.uuid4().hex

    def record(self, agent_name, event, **details):

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        data = {
            "run_id": self.run_id,
            "timestamp": timestamp,
            "agent": agent_name,
            "event": event,
            **details
        }

        # 写入普通日志
        logger.info(
            "%s | %s | %s",
            agent_name,
            event,
            details
        )

        # 写入结构化事件
        with event_lock:
            with open(
                EVENT_FILE,
                "a",
                encoding="utf-8"
            ) as f:
                f.write(
                    json.dumps(
                        data,
                        ensure_ascii=False,
                        default=str
                    ) + "\n"
                )

    def timed_call(self, agent_name, attempt, func):

        start = time.perf_counter()

        self.record(
            agent_name,
            "started",
            attempt=attempt
        )

        try:
            result = func()

            elapsed = time.perf_counter() - start

            self.record(
                agent_name,
                "completed",
                attempt=attempt,
                duration_seconds=round(elapsed, 3)
            )

            return result

        except Exception as e:

            elapsed = time.perf_counter() - start

            self.record(
                agent_name,
                "failed",
                attempt=attempt,
                duration_seconds=round(elapsed, 3),
                error_type=type(e).__name__,
                error_message=str(e)[:300]
            )

            raise
