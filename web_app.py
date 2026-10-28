
import json
import subprocess
import sys
import uuid

from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from job_control import (
    create_queued_job,
    request_cancel,
    request_resume
)
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
JOBS_DIR = BASE_DIR / "jobs"

JOBS_DIR.mkdir(exist_ok=True)


def read_json(path):

    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except (OSError, json.JSONDecodeError):
        return None


def list_jobs():

    jobs = []

    for folder in JOBS_DIR.iterdir():

        if not folder.is_dir():
            continue

        info = read_json(folder / "job.json")

        if isinstance(info, dict):
            jobs.append((folder, info))

    jobs.sort(
        key=lambda item: item[1].get("created_at", ""),
        reverse=True
    )

    return jobs


def create_job(task):
    return create_queued_job(task)

def load_events(job_dir, run_id):

    path = job_dir / "logs" / "events.jsonl"

    if not path.exists() or not run_id:
        return []

    events = []

    with open(path, "r", encoding="utf-8") as f:

        for line in f:

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if (
                isinstance(event, dict)
                and event.get("run_id") == run_id
            ):
                events.append(event)

    return events


# ---------- 页面设置 ----------

st.set_page_config(
    page_title="MyMultiAgent Console",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 MyMultiAgent Console")
st.caption(
    "动态任务规划 · 任务队列 · 并发控制 · "
    "失败恢复 · 任务取消 · 实时监控"
)

# ---------- 创建任务 ----------

st.subheader("创建新任务")

with st.form("new_task_form"):

    task = st.text_area(
        "请输入需要Multi-Agent完成的任务",
        value=(
            "采购20只800G光模块，单价2800元，"
            "供应商提供九折优惠。"
            "请计算采购金额、分析风险并生成报告。"
        ),
        height=110,
        max_chars=2000
    )

    submitted = st.form_submit_button(
        "🚀 启动 Multi-Agent",
        type="primary"
    )

if submitted:

    if not task.strip():
        st.error("任务内容不能为空")

    else:

        try:
            job_id = create_job(task.strip())

            st.session_state["selected_job"] = job_id
            st.rerun()

        except Exception as e:
            st.error(f"启动失败：{e}")


# ---------- 选择历史任务 ----------

st.divider()
st.subheader("任务执行监控")

jobs = list_jobs()

if not jobs:
    st.info("还没有任务，请先在上方创建任务。")
    st.stop()

job_map = {
    info["id"]: (folder, info)
    for folder, info in jobs
}

job_ids = list(job_map)

if (
    st.session_state.get("selected_job")
    not in job_map
):
    st.session_state["selected_job"] = job_ids[0]

selected_id = st.selectbox(
    "选择任务",
    options=job_ids,
    format_func=lambda job_id: (
        job_map[job_id][1]["task"][:45]
        + f"  ({job_id})"
    ),
    key="selected_job"
)

selected_dir, selected_info = job_map[selected_id]


# ---------- 自动刷新监控区域 ----------

@st.fragment(run_every="2s")
def show_monitor(job_dir, job_info):

    worker = read_json(
        job_dir / "worker_status.json"
    ) or {}

    checkpoint = read_json(
        job_dir / "checkpoint.json"
    ) or {}

    worker_status = worker.get("status", "starting")

    st.write("**任务编号：**", job_info["id"])
    st.write("**任务内容：**", job_info["task"])

    
    if worker_status == "completed":
        st.success("任务已完成")

    elif worker_status == "queued":
        st.warning("任务正在排队，等待执行槽位")

    elif worker_status == "running":
        st.info("任务正在执行")

    elif worker_status == "cancelling":
        st.warning("正在取消任务...")

    elif worker_status == "cancelled":
        st.warning("任务已取消")

    elif worker_status == "failed":
        st.error(
            "任务执行失败："
            + str(worker.get("error") or "请查看日志")
        )

    else:
        st.info("任务正在启动")

    # ---------- 任务控制按钮 ----------

    left, right = st.columns(2)

    with left:
        if worker_status in ("queued", "running"):

            if st.button(
                "⏹ 取消任务",
                key=f"cancel_{job_info['id']}",
                type="secondary"
            ):
                try:
                    request_cancel(job_info["id"])
                    st.rerun(scope="fragment")
                except Exception as e:
                    st.error(f"取消失败：{e}")

    with right:
        if worker_status in ("failed", "cancelled"):

            has_checkpoint = (
                job_dir / "checkpoint.json"
            ).exists()

            if st.button(
                "🔄 从断点恢复",
                key=f"resume_{job_info['id']}",
                disabled=not has_checkpoint
            ):
                try:
                    request_resume(job_info["id"])
                    st.rerun(scope="fragment")
                except Exception as e:
                    st.error(f"恢复失败：{e}")

            if not has_checkpoint:
                st.caption(
                    "该任务没有Checkpoint，"
                    "不能断点恢复，请重新提交。"
                )


    tasks = checkpoint.get("plan", {})
    statuses = checkpoint.get("step_status", {})
    results = checkpoint.get("results", {})

    run_id = checkpoint.get("run_id")

    events = load_events(job_dir, run_id)

    if not isinstance(tasks, dict):
        tasks = {}

    if not isinstance(statuses, dict):
        statuses = {}

    if not isinstance(results, dict):
        results = {}

    total = len(tasks)

    completed = sum(
        statuses.get(name) == "completed"
        for name in tasks
    )

    failed = sum(
        statuses.get(name) == "failed"
        for name in tasks
    )

    attempt_counts = Counter(
        event.get("agent")
        for event in events
        if event.get("event") == "started"
    )

    retries = sum(
        max(0, count - 1)
        for count in attempt_counts.values()
    )

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("任务总数", total)
    c2.metric("已完成", completed)
    c3.metric("失败任务", failed)
    c4.metric("重试次数", retries)

    st.progress(
        completed / total if total else 0
    )

    if tasks:

        st.markdown("#### Agent执行状态")

        rows = []

        for name, info in tasks.items():

            rows.append({
                "Agent": name,
                "状态": statuses.get(name, "pending"),
                "尝试次数": attempt_counts.get(name, 0),
                "依赖": ", ".join(
                    info.get("depends_on", [])
                ) or "无"
            })

        st.dataframe(
            rows,
            width="stretch",
            hide_index=True
        )

        st.markdown("#### 任务依赖图")

        dot = [
            "digraph G {",
            "rankdir=LR;",
            'node [shape=box, style=rounded];'
        ]

        for name, info in tasks.items():

            dot.append(
                f"{json.dumps(name)};"
            )

            for dep in info.get("depends_on", []):

                dot.append(
                    f"{json.dumps(dep)} -> "
                    f"{json.dumps(name)};"
                )

        dot.append("}")

        st.graphviz_chart("\n".join(dot))

    if events:

        st.markdown("#### 最近执行事件")

        event_rows = []

        for event in reversed(events[-20:]):

            event_rows.append({
                "时间": event.get("timestamp"),
                "Agent": event.get("agent"),
                "事件": event.get("event"),
                "耗时": event.get("duration_seconds")
            })

        st.dataframe(
            event_rows,
            width="stretch",
            hide_index=True
        )

    if results:

        st.markdown("#### Agent执行结果")

        for name, result in results.items():

            with st.expander(f"{name} 的结果"):

                st.text(str(result))

    if "writer" in results:

        st.markdown("#### 最终报告")
        st.text_area(
            "Writer报告",
            value=str(results["writer"]),
            height=300,
            disabled=True
        )

    # 展示子进程终端输出
    log_path = job_dir / "console.log"

    with st.expander("查看执行日志"):

        if log_path.exists():

            with open(
                log_path,
                "r",
                encoding="utf-8",
                errors="replace"
            ) as f:
                recent_lines = deque(f, maxlen=60)

            st.code(
                "".join(recent_lines),
                language="text"
            )

        else:
            st.write("暂无日志")


show_monitor(selected_dir, selected_info)
