"""第24课：实时 Agent 执行时间线（只读 SQLite 和 JSONL）。"""
import json
import sqlite3
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "multiagent.db"
JOBS = ROOT / "jobs"
REFRESH_SECONDS = 5

st.set_page_config(page_title="Agent 实时执行时间线", page_icon="⏱️", layout="wide")
st.title("⏱️ Agent 实时执行时间线")
st.caption("每 5 秒自动刷新一次；数据来自 SQLite 和 events.jsonl（只读）。")

if not hasattr(st, "fragment"):
    st.error("当前 Streamlit 版本不支持 st.fragment，请先升级：python -m pip install -U streamlit")
    st.stop()


def load_jobs():
    if not DB.exists():
        return []
    with sqlite3.connect(DB, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, task, status, created_at FROM jobs ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def load_agent_executions(job_id):
    with sqlite3.connect(DB, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_executions)")}
        wanted = ["agent_name", "attempt", "execution_seq", "status",
                  "duration_seconds", "run_id", "created_at"]
        available = [col for col in wanted if col in cols]
        if not available:
            return pd.DataFrame()
        query = f"SELECT {', '.join(available)} FROM agent_executions WHERE job_id = ? ORDER BY id"
        rows = conn.execute(query, (job_id,)).fetchall()
        return pd.DataFrame([dict(r) for r in rows], columns=available)


def load_events(job_id):
    # 任务 ID 只能来自 SQLite；再次验证，避免构造任意文件路径。
    if len(job_id) != 12 or any(c not in "0123456789abcdef" for c in job_id):
        return [], 0
    path = JOBS / job_id / "logs" / "events.jsonl"
    if not path.is_file():
        return [], 0
    events = []
    invalid = 0
    try:
        with path.open(encoding="utf-8") as f:
            for line_number, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    invalid += 1
                    continue
                if not isinstance(obj, dict):
                    invalid += 1
                    continue
                events.append({
                    "line": line_number,
                    "timestamp": obj.get("timestamp"),
                    "agent": str(obj.get("agent") or "unknown"),
                    "event": str(obj.get("event") or "unknown"),
                    "attempt": obj.get("attempt"),
                    "next_attempt": obj.get("next_attempt"),
                    "duration_seconds": obj.get("duration_seconds"),
                    "run_id": str(obj.get("run_id") or ""),
                    "error_type": str(obj.get("error_type") or ""),
                })
    except OSError as e:
        st.warning(f"暂时无法读取事件日志：{e}")
    return events, invalid


@st.fragment(run_every=f"{REFRESH_SECONDS}s")
def live_dashboard():
    try:
        jobs = load_jobs()
    except sqlite3.Error as e:
        st.error(f"读取 SQLite 失败：{e}")
        return

    if not jobs:
        st.info("数据库中暂无任务。")
        return

    job_map = {j["id"]: j for j in jobs}
    job_id = st.selectbox(
        "选择任务（最新任务排在最前面）",
        options=list(job_map),
        format_func=lambda x: f"{x} · {str(job_map[x].get('task') or '')[:35]}",
        key="timeline_job",
    )
    job = job_map[job_id]
    events, invalid = load_events(job_id)

    a, b, c, d = st.columns(4)
    a.metric("任务状态", str(job.get("status") or "unknown"))
    b.metric("事件数量", len(events))
    c.metric("计划重试事件", sum(e["event"] == "retry_scheduled" for e in events))
    d.metric("实际重试启动", sum(
        e["event"] == "started"
        and isinstance(e["attempt"], int)
        and e["attempt"] > 1
        for e in events
    ))
    if invalid:
        st.warning(f"跳过 {invalid} 条不完整或无效的 JSON 日志行；写入过程中短暂出现此情况可能正常。")

    if not events:
        st.info("该任务还没有 events.jsonl 日志，或尚未开始执行。")
    else:
        all_agents = sorted({e["agent"] for e in events})
        all_runs = sorted({e["run_id"] for e in events if e["run_id"]})
        c1, c2 = st.columns(2)
        with c1:
            agent = st.selectbox("筛选 Agent", ["全部"] + all_agents, key="timeline_agent")
        with c2:
            run = st.selectbox("筛选 run_id", ["全部"] + all_runs, key="timeline_run")

        filtered = [
            e for e in events
            if (agent == "全部" or e["agent"] == agent)
            and (run == "全部" or e["run_id"] == run)
        ]
        df = pd.DataFrame(filtered)
        df["时间（UTC）"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.sort_values(["时间（UTC）", "line"], kind="stable", na_position="last")

        st.subheader("事件时间线")
        chart_data = df.dropna(subset=["时间（UTC）"])
        if not chart_data.empty:
            chart = (
                alt.Chart(chart_data)
                .mark_circle(size=110)
                .encode(
                    x=alt.X("时间（UTC）:T", title="事件时间（UTC）"),
                    y=alt.Y("agent:N", title="Agent"),
                    color=alt.Color("event:N", title="事件类型"),
                    tooltip=[
                        alt.Tooltip("时间（UTC）:T"),
                        "agent:N", "event:N", "attempt:Q",
                        "run_id:N", "duration_seconds:Q", "error_type:N",
                    ],
                )
                .properties(height=max(220, 65 * len(all_agents)))
                .interactive()
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("没有可解析的时间戳，暂时无法绘制时间轴。")

        st.subheader("事件明细")
        columns = [
            "timestamp", "agent", "event", "attempt",
            "next_attempt", "duration_seconds", "run_id", "error_type",
        ]
        st.dataframe(df[columns], hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("SQLite Agent 执行实例")
    try:
        executions = load_agent_executions(job_id)
    except sqlite3.Error as e:
        st.error(f"读取执行明细失败：{e}")
        return
    if executions.empty:
        st.info("尚无已同步的 Agent 执行记录；可等待下一次日志同步。")
    else:
        st.dataframe(executions, hide_index=True, use_container_width=True)
        finished = executions[executions["status"].isin(["completed", "failed"])]
        if not finished.empty:
            ok = int((finished["status"] == "completed").sum())
            st.caption(f"已结束执行实例：{len(finished)}；成功 {ok}；失败 {len(finished)-ok}。")

    st.caption("页面局部每 5 秒刷新；日志同步服务也有独立检查间隔，因此数据可能延迟数秒。")


live_dashboard()
