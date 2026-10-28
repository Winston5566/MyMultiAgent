"""第24课：Agent 性能 Dashboard，每 5 秒自动刷新（只读）。"""
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "multiagent.db"

st.set_page_config(page_title="Agent 性能监控", page_icon="⚡", layout="wide")
st.title("⚡ Agent 性能监控")
st.caption("SQLite agent_executions · 每 5 秒自动刷新 · 每行代表一次执行实例")

if not hasattr(st, "fragment"):
    st.error("请升级 Streamlit：python -m pip install -U streamlit")
    st.stop()


def load_executions():
    if not DB.is_file():
        raise FileNotFoundError(f"找不到数据库：{DB}")
    with sqlite3.connect(DB, timeout=10) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_executions)")}
        required = {"id", "job_id", "run_id", "agent_name", "attempt", "execution_seq",
                    "started_seen", "status", "duration_seconds", "created_at", "ended_at",
                    "error_message"}
        if not required.issubset(columns):
            raise ValueError("缺少 V2 执行明细字段，请检查 import_agent_logs_v2.py 的数据库迁移结果。")
        return pd.read_sql_query("""
            SELECT id, job_id, run_id, agent_name, attempt, execution_seq,
                   status, started_seen, duration_seconds, error_message,
                   created_at, ended_at
            FROM agent_executions
            WHERE run_id IS NOT NULL
            ORDER BY created_at DESC, id DESC
        """, conn)


@st.fragment(run_every="5s")
def render_dashboard():
    try:
        df = load_executions()
    except (sqlite3.Error, OSError, ValueError) as exc:
        st.error(f"读取 Agent 执行明细失败：{exc}")
        return

    if df.empty:
        st.info("暂无 Agent 执行数据。等待日志同步服务写入。")
        return

    st.subheader("🔍 筛选")
    agent_options = sorted(df["agent_name"].dropna().unique().tolist())
    status_options = sorted(df["status"].dropna().unique().tolist())

    c1, c2 = st.columns(2)
    with c1:
        selected_agents = st.multiselect(
            "Agent", agent_options, default=agent_options, key="perf_agents"
        )
    with c2:
        selected_status = st.multiselect(
            "执行状态", status_options, default=status_options, key="perf_status"
        )
    job_keyword = st.text_input("搜索任务 ID", placeholder="输入部分任务编号", key="perf_job")

    filtered = df[
        df["agent_name"].isin(selected_agents)
        & df["status"].isin(selected_status)
        & df["job_id"].astype(str).str.contains(job_keyword.strip(), case=False, regex=False)
    ].copy()

    if filtered.empty:
        st.info("当前筛选条件下没有执行记录。")
        return

    completed = filtered[filtered["status"] == "completed"]
    failed = filtered[filtered["status"] == "failed"]
    finished = len(completed) + len(failed)
    started = filtered[filtered["started_seen"] == 1]
    actual_retries = started[started["attempt"] > 1]
    repeat_same_attempt = started[started["execution_seq"] > 1]
    rate = len(completed) / finished * 100 if finished else 0.0
    avg_seconds = completed["duration_seconds"].mean()

    st.subheader("📈 执行概览")
    a, b, c, d = st.columns(4)
    a.metric("执行实例", len(filtered))
    b.metric("成功 / 失败", f"{len(completed)} / {len(failed)}")
    c.metric("尝试级成功率", f"{rate:.1f}%")
    d.metric("成功平均耗时", f"{avg_seconds:.2f} 秒" if pd.notna(avg_seconds) else "暂无")

    x, y, z = st.columns(3)
    x.metric("实际启动", len(started))
    y.metric("attempt > 1 重试", len(actual_retries))
    z.metric("同编号再次执行", len(repeat_same_attempt))
    st.caption("成功率仅统计 completed 和 failed；同编号再次执行可能与恢复有关。")

    st.divider()
    st.subheader("📊 各 Agent 性能")
    rows = []
    for agent, part in filtered.groupby("agent_name", sort=True):
        ok = part[part["status"] == "completed"]
        bad = part[part["status"] == "failed"]
        started_part = part[part["started_seen"] == 1]
        denominator = len(ok) + len(bad)
        mean = ok["duration_seconds"].mean()
        rows.append({
            "Agent": agent,
            "执行实例": len(part),
            "实际启动": len(started_part),
            "成功": len(ok),
            "失败": len(bad),
            "成功率(%)": round(100 * len(ok) / denominator, 1) if denominator else None,
            "成功平均耗时(秒)": round(float(mean), 3) if pd.notna(mean) else None,
            "attempt重试": int((started_part["attempt"] > 1).sum()),
            "同编号再次执行": int((started_part["execution_seq"] > 1).sum()),
        })
    summary = pd.DataFrame(rows)
    st.dataframe(summary, width="stretch", hide_index=True)

    chart = summary.dropna(subset=["成功平均耗时(秒)"]).set_index("Agent")
    if not chart.empty:
        st.subheader("成功执行平均耗时对比")
        st.bar_chart(chart[["成功平均耗时(秒)"]])

    st.divider()
    st.subheader("📋 执行明细")
    st.dataframe(
        filtered.rename(columns={
            "job_id": "任务ID", "run_id": "运行批次", "agent_name": "Agent",
            "attempt": "尝试编号", "execution_seq": "同编号执行序号",
            "status": "状态", "duration_seconds": "耗时(秒)",
            "created_at": "开始时间", "ended_at": "结束时间",
            "error_message": "错误信息", "started_seen": "已记录启动",
        }),
        width="stretch", hide_index=True,
    )
    st.caption("页面每 5 秒局部刷新；SQLite 更新由日志同步服务独立执行。")
    if st.button("🔄 立即刷新", key="perf_refresh"):
        st.rerun(scope="fragment")


render_dashboard()
