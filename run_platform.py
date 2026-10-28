
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "service_logs"
LOG_DIR.mkdir(exist_ok=True)

PORT = 8501

services = {}
log_files = {}


def port_in_use(port):
    """检查本地端口是否已被占用。"""
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    ) as sock:
        return sock.connect_ex(
            ("127.0.0.1", port)
        ) == 0


def check_files():
    """检查三个服务的入口文件。"""
    required = [
        "web_app.py",
        "job_control.py",
        "agent_log_sync.py",
        "database.py",
    ]

    missing = [
        name
        for name in required
        if not (BASE_DIR / name).is_file()
    ]

    if missing:
        raise FileNotFoundError(
            "缺少文件：" + ", ".join(missing)
        )

    if not (BASE_DIR / "multiagent.db").exists():
        raise FileNotFoundError(
            "找不到 multiagent.db"
        )


def start_service(name, command):
    """启动子服务并记录日志。"""

    log_path = LOG_DIR / f"{name}.log"

    log_file = open(
        log_path,
        "a",
        encoding="utf-8"
    )

    log_files[name] = log_file

    print(f"[启动] {name}", flush=True)

    process = subprocess.Popen(
        command,
        cwd=str(BASE_DIR),
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    services[name] = process

    print(
        f"  PID: {process.pid}",
        flush=True
    )
    print(
        f"  日志: {log_path}",
        flush=True
    )


def print_log_tail(name, lines=15):
    """子服务异常退出时显示最近的日志。"""

    path = LOG_DIR / f"{name}.log"

    if not path.exists():
        return

    try:
        content = path.read_text(
            encoding="utf-8",
            errors="replace"
        ).splitlines()

        print(f"\n===== {name} 最近日志 =====")

        for line in content[-lines:]:
            print(line)

    except OSError as e:
        print(f"读取日志失败：{e}")


def stop_services():
    """停止本次启动的三个服务。"""

    print("\n正在停止管理服务...")

    # 先停止调度，避免继续启动新任务
    order = [
        "scheduler",
        "log_sync",
        "streamlit",
    ]

    for name in order:
        process = services.get(name)

        if process is None:
            continue

        if process.poll() is not None:
            continue

        print(f"[停止] {name}")

        try:
            os.killpg(
                process.pid,
                signal.SIGTERM
            )
        except ProcessLookupError:
            pass

    for name in order:
        process = services.get(name)

        if process is None:
            continue

        try:
            process.wait(timeout=5)

        except subprocess.TimeoutExpired:
            try:
                os.killpg(
                    process.pid,
                    signal.SIGKILL
                )
            except ProcessLookupError:
                pass

            process.wait()

    for log_file in log_files.values():
        log_file.close()

    print("三个管理服务已停止。")
    print(
        "注意：已独立启动的 Agent 工作进程"
        "可能仍在运行。"
    )


def main():

    print("=" * 50)
    print("Multi-Agent Platform")
    print("统一启动管理器")
    print("=" * 50)

    check_files()

    if port_in_use(PORT):
        print(
            f"\n错误：端口 {PORT} 已被占用。"
        )
        print(
            "请先停止原来的 Streamlit 服务。"
        )
        return

    try:
        start_service(
            "scheduler",
            [
                sys.executable,
                "-u",
                str(BASE_DIR / "job_control.py")
            ]
        )

        start_service(
            "log_sync",
            [
                sys.executable,
                "-u",
                str(BASE_DIR / "agent_log_sync.py")
            ]
        )

        start_service(
            "streamlit",
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(BASE_DIR / "web_app.py"),
                "--server.port",
                str(PORT),
                "--server.headless",
                "true",
            ]
        )

        # 给子进程一点启动时间
        time.sleep(3)

        for name, process in services.items():
            if process.poll() is not None:
                print(
                    f"\n[错误] {name} 启动失败，"
                    f"退出码：{process.returncode}"
                )
                print_log_tail(name)
                return

        print("\n" + "=" * 50)
        print("三个管理服务已启动")
        print(f"网页地址：http://localhost:{PORT}")
        print("按 Control + C 停止管理服务")
        print("=" * 50)

        while True:

            for name, process in services.items():

                if process.poll() is not None:
                    print(
                        f"\n[错误] {name} 意外退出，"
                        f"退出码：{process.returncode}"
                    )

                    print_log_tail(name)

                    print(
                        "\n为避免服务状态不一致，"
                        "将停止其他管理服务。"
                    )

                    return

            time.sleep(2)

    except KeyboardInterrupt:
        print("\n收到停止指令。")

    finally:
        stop_services()


def handle_sigterm(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(
        signal.SIGTERM,
        handle_sigterm
    )

    main()
