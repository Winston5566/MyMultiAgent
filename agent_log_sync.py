
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from import_agent_logs_v2 import (
    parse_logs,
    ensure_schema,
    import_records,
)


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "multiagent.db"

SYNC_INTERVAL = 5


def sync_once(previous_signature=None):
    """
    扫描 Agent 日志，并同步到 SQLite。

    只有日志内容或 jobs 主记录发生变化时，
    才执行数据库写入。
    """

    records, counts = parse_logs()

    with sqlite3.connect(DB_PATH, timeout=30) as conn:

        conn.execute("PRAGMA busy_timeout = 30000")

        # 检查 V2 所需字段
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(agent_executions)"
            )
        }

        required = {
            "run_id",
            "execution_seq",
            "started_seen",
            "ended_at",
        }

        if not required.issubset(columns):
            raise RuntimeError(
                "数据库尚未升级到 V2，"
                "请先运行 import_agent_logs_v2.py"
            )

        # 读取有效任务 ID
        job_ids = sorted(
            row[0]
            for row in conn.execute(
                "SELECT id FROM jobs"
            )
        )

        # 计算数据签名，避免无变化时重复写库
        payload = {
            "records": records,
            "job_ids": job_ids,
        }

        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        signature = hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

        # 只有全部日志可读、没有异常时才跳过
        if (
            signature == previous_signature
            and counts["unreadable_files"] == 0
            and counts["invalid_json"] == 0
        ):
            return signature, False

        # 使用已有 V2 导入逻辑
        with conn:
            eligible, added, missing = import_records(
                conn,
                records,
            )

    print(
        f"[SQLite] 同步完成："
        f"执行实例={eligible}，"
        f"新增={added}，"
        f"缺少任务主记录={missing}",
        flush=True,
    )

    if counts["invalid_json"]:
        print(
            f"[SQLite] 本轮跳过无效 JSON 行："
            f"{counts['invalid_json']}",
            flush=True,
        )

    if counts["unreadable_files"]:
        print(
            f"[SQLite] 本轮无法读取的日志文件："
            f"{counts['unreadable_files']}",
            flush=True,
        )

    # 如果文件暂时不可读，下一轮继续检查
    if (
        counts["unreadable_files"]
        or counts["invalid_json"]
    ):
        return None, True

    return signature, True


def main():

    if not DB_PATH.exists():
        print("错误：找不到 multiagent.db")
        return

    print("=" * 45)
    print("Agent 日志自动同步服务已启动")
    print(f"SQLite：{DB_PATH}")
    print(f"检查间隔：{SYNC_INTERVAL} 秒")
    print("按 Control + C 停止")
    print("=" * 45)

    previous_signature = None

    try:
        while True:

            try:
                previous_signature, changed = sync_once(
                    previous_signature
                )

            except (sqlite3.Error, OSError, ValueError,
                    RuntimeError) as e:
                print(
                    f"[SQLite] 同步错误：{e}",
                    flush=True,
                )
                previous_signature = None

            time.sleep(SYNC_INTERVAL)

    except KeyboardInterrupt:
        print("\nAgent 日志同步服务已停止")


if __name__ == "__main__":
    main()
