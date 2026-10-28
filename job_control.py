
import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import uuid

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import psutil

# 新增：SQLite 数据库功能
from database import (
    init_database,
    get_job,
    upsert_job
)


BASE_DIR = Path(__file__).resolve().parent
JOBS_DIR = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

MAX_CONCURRENT = 2
LOCK_FILE = JOBS_DIR / ".scheduler.lock"


def write_json(path, data):
    temp = path.with_name(
        f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp, path)


def read_json(path):
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, dict) else {}

    except (OSError, json.JSONDecodeError):
        return {}


# 新增：将一个任务的 JSON 状态同步到 SQLite
def sync_job_to_db(folder):
    job_data = read_json(folder / "job.json")
    worker_data = read_json(
        folder / "worker_status.json"
    )

    job_id = job_data.get("id")
    task = job_data.get("task")

    if job_id != folder.name:
        return False

    if not isinstance(task, str) or not task.strip():
        return False

    status = worker_data.get("status", "queued")
    created_at = job_data.get("created_at")
    updated_at = worker_data.get("updated_at")
    error = worker_data.get("error")

    if not isinstance(status, str):
        return False

    status = status.strip().lower()

    if not status:
        return False

    try:
        existing = get_job(job_id)

        # 数据没有变化时，不重复写入数据库
        if existing is not None:
            if (
                existing["task"] == task
                and existing["status"] == status
                and existing["updated_at"] == updated_at
                and existing["error"] == error
            ):
                return True

        upsert_job(
            job_id=job_id,
            task=task,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            error=error
        )

        print(
            f"[SQLite] 同步任务 {job_id}: {status}",
            flush=True
        )

        return True

    except (sqlite3.Error, OSError, ValueError) as e:
        # 数据库故障不应直接破坏原有调度流程
        print(
            f"[SQLite] 同步失败 {job_id}: {e}",
            flush=True
        )
        return False


def set_status(folder, status, error=None):
    write_json(
        folder / "worker_status.json",
        {
            "status": status,
            "updated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "error": error
        }
    )

    # 新增：写完 JSON 后立即同步数据库
    sync_job_to_db(folder)


@contextmanager
def control_lock():
    with open(LOCK_FILE, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)

        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def get_jobs():
    jobs = []

    for folder in JOBS_DIR.iterdir():
        if not folder.is_dir():
            continue

        info = read_json(folder / "job.json")

        if info.get("id") == folder.name:
            jobs.append((folder, info))

    jobs.sort(
        key=lambda item: item[1].get("created_at", "")
    )

    return jobs


def get_folder(job_id):
    if (
        len(job_id) != 12
        or any(
            c not in "0123456789abcdef"
            for c in job_id
        )
    ):
        raise ValueError("无效的任务ID")

    folder = JOBS_DIR / job_id

    if not (folder / "job.json").exists():
        raise ValueError("任务不存在")

    return folder


def is_worker_alive(folder):
    info = read_json(folder / "process.json")

    pid = info.get("pid")
    created = info.get("created_at")

    if not isinstance(pid, int) or created is None:
        return False

    try:
        proc = psutil.Process(pid)

        if not proc.is_running():
            return False

        if proc.status() == psutil.STATUS_ZOMBIE:
            return False

        if abs(proc.create_time() - created) > 0.1:
            return False

        args = proc.cmdline()

        return (
            any(
                "web_runner.py" in arg
                for arg in args
            )
            and str(folder) in args
        )

    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        psutil.ZombieProcess
    ):
        return False


def create_queued_job(task):
    task = task.strip()

    if not task:
        raise ValueError("任务不能为空")

    with control_lock():
        job_id = uuid.uuid4().hex[:12]
        folder = JOBS_DIR / job_id
        folder.mkdir()

        write_json(
            folder / "job.json",
            {
                "id": job_id,
                "task": task,
                "created_at": datetime.now(
                    timezone.utc
                ).isoformat()
            }
        )

        set_status(folder, "queued")

    return job_id


def request_resume(job_id):
    with control_lock():
        folder = get_folder(job_id)

        status = read_json(
            folder / "worker_status.json"
        ).get("status")

        if status not in ("failed", "cancelled"):
            raise ValueError(
                "只有失败或取消的任务可以恢复"
            )

        if is_worker_alive(folder):
            raise RuntimeError(
                "原任务进程尚未退出"
            )

        if not (
            folder / "checkpoint.json"
        ).exists():
            raise ValueError(
                "没有Checkpoint，无法断点恢复"
            )

        (folder / "cancel.request").unlink(
            missing_ok=True
        )

        set_status(folder, "queued")

    return True


def request_cancel(job_id):
    with control_lock():
        folder = get_folder(job_id)

        status = read_json(
            folder / "worker_status.json"
        ).get("status")

        if status == "queued":
            set_status(folder, "cancelled")
            return True

        if status in ("running", "cancelling"):
            (folder / "cancel.request").touch()
            set_status(folder, "cancelling")
            return True

        raise ValueError(
            f"当前状态 {status} 不允许取消"
        )


def stop_worker(folder):
    info = read_json(
        folder / "process.json"
    )

    if not is_worker_alive(folder):
        return False

    pid = info["pid"]
    sent_at = info.get("cancel_sent_at")

    try:
        if sent_at is None:
            os.killpg(
                pid,
                signal.SIGTERM
            )

            info["cancel_sent_at"] = time.time()

            write_json(
                folder / "process.json",
                info
            )

        elif time.time() - sent_at > 5:
            os.killpg(
                pid,
                signal.SIGKILL
            )

    except ProcessLookupError:
        return False

    return True


def scheduler_tick():
    with control_lock():
        jobs = get_jobs()

        # 先检查已有任务
        for folder, _ in jobs:
            status = read_json(
                folder / "worker_status.json"
            ).get("status")

            cancelled = (
                folder / "cancel.request"
            ).exists()

            alive = is_worker_alive(folder)

            if cancelled:
                if alive:
                    stop_worker(folder)
                elif status != "cancelled":
                    set_status(folder, "cancelled")

                # 新增：同步最终取消状态
                sync_job_to_db(folder)
                continue

            if (
                status in ("running", "cancelling")
                and not alive
            ):
                latest = read_json(
                    folder / "worker_status.json"
                ).get("status")

                if latest in ("running", "cancelling"):
                    set_status(
                        folder,
                        "failed",
                        "工作进程已退出，未正常完成"
                    )

            # 新增：检测 web_runner.py 写入的
            # completed / failed 等状态
            sync_job_to_db(folder)

        active = sum(
            is_worker_alive(folder)
            for folder, _ in jobs
        )

        slots = max(
            0,
            MAX_CONCURRENT - active
        )

        if slots == 0:
            return

        for folder, _ in jobs:
            if slots == 0:
                break

            status = read_json(
                folder / "worker_status.json"
            ).get("status")

            if status != "queued":
                continue

            if (
                folder / "cancel.request"
            ).exists():
                set_status(
                    folder,
                    "cancelled"
                )
                continue

            set_status(folder, "running")

            log_path = folder / "console.log"

            try:
                with open(
                    log_path,
                    "a",
                    encoding="utf-8"
                ) as log:

                    proc = subprocess.Popen(
                        [
                            sys.executable,
                            "-u",
                            str(
                                BASE_DIR /
                                "web_runner.py"
                            ),
                            str(folder)
                        ],
                        cwd=str(BASE_DIR),
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True
                    )

                try:
                    created = psutil.Process(
                        proc.pid
                    ).create_time()

                except psutil.NoSuchProcess:
                    created = None

                write_json(
                    folder / "process.json",
                    {
                        "pid": proc.pid,
                        "created_at": created,
                        "cancel_sent_at": None
                    }
                )

                print(
                    f"启动任务 {folder.name}，"
                    f"PID={proc.pid}",
                    flush=True
                )

                slots -= 1

            except Exception as e:
                set_status(
                    folder,
                    "failed",
                    f"启动失败：{e}"
                )


def run_scheduler():
    # 新增：启动时确保数据库存在
    init_database()

    print(
        f"任务控制器已启动，"
        f"最大并发数：{MAX_CONCURRENT}",
        flush=True
    )

    while True:
        try:
            scheduler_tick()

        except Exception as e:
            print(
                f"调度错误："
                f"{type(e).__name__}: {e}",
                flush=True
            )

        time.sleep(2)


if __name__ == "__main__":
    try:
        run_scheduler()

    except KeyboardInterrupt:
        print("\n任务控制器已停止")
