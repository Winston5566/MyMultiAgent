
import json
import os
import runpy
import sys
import traceback

from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent



def write_status(job_dir, status, error=None):

    # 如果用户已请求取消，不再写入完成状态
    if (job_dir / "cancel.request").exists():
        status = "cancelled"
        error = None

    data = {
        "status": status,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "error": error
    }

    temp_file = job_dir / (
        f"worker_status.{os.getpid()}.tmp"
    )

    final_file = job_dir / "worker_status.json"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp_file, final_file)


def main():

    if len(sys.argv) != 2:
        raise ValueError("需要提供任务目录")

    job_dir = Path(sys.argv[1]).resolve()

    with open(
        job_dir / "job.json",
        "r",
        encoding="utf-8"
    ) as f:
        job = json.load(f)

    # 为当前子进程设置独立任务环境
    os.environ["MULTIAGENT_TASK"] = job["task"]
    # 将任务编号传递给所有 Agent
    os.environ["MULTIAGENT_JOB_ID"] = str(job["id"])
    os.environ["MULTIAGENT_CHECKPOINT"] = str(
        job_dir / "checkpoint.json"
    )

    os.environ["MULTIAGENT_LOG_DIR"] = str(
        job_dir / "logs"
    )

    write_status(job_dir, "running")

    try:

        print("开始执行网页任务", flush=True)

        runpy.run_path(
            str(BASE_DIR / "resilient_workflow.py"),
            run_name="__main__"
        )

        write_status(job_dir, "completed")

    except Exception as e:

        traceback.print_exc()

        write_status(
            job_dir,
            "failed",
            f"{type(e).__name__}: {str(e)[:300]}"
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
