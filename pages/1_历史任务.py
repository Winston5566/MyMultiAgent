"""第24课：历史任务 Dashboard，每 5 秒自动刷新（只读）。"""
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "multiagent.db"

st.set_page_config(page_title="历史任务 Dashboard", page_icon="📊", layout="wide")
st.title("📊 Multi-Agent 历史任务 Dashboard")
st.caption("SQLite 数据源 · 每 5 秒自动刷新 · 不会调用大模型")

if not hasattr(st, "fragment"):
    st.error("请升级 Streamlit：python -m pip install -U streamlit")
    st.stop()


def load_jobs():
    if not DB.is_file():
        raise FileNotFoundError(f"找不到数据库：{DB}")
    with sqlite3.connect(DB, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            """SELECT id, task, status, created_at, updated_at, error
               FROM jobs ORDER BY created_at DESC, id DESC"""
        )]


@st.fragment(run_every="5s")
def render_dashboard():
    try:
        jobs = load_jobs()
    except (sqlite3.Error, OSError) as exc:
        st.error(f"读取 SQLite 失败：{exc}")
        return

    total = len(jobs)
    counts = {s: sum(str(j.get("status") or "").lower() == s for j in jobs)
              for s in ("completed", "failed", "running", "queued", "cancelled", "cancelling")}
    finished = counts["completed"] + counts["failed"]
    rate = counts["completed"] / finished * 100 if finished else 0.0

    st.subheader("📈 任务概览")
    a, b, c, d = st.columns(4)
    a.metric("历史任务总数", total)
    b.metric("已完成", counts["completed"])
    c.metric("失败任务", counts["failed"])
    d.metric("执行成功率", f"{rate:.1f}%")
    st.caption("执行成功率 = completed / (completed + failed)，取消和运行中任务不计入分母。")

    st.subheader("📊 状态分布")
    chart = pd.DataFrame([
        {"状态": status, "任务数量": count}
        for status, count in counts.items()
    ])
    st.bar_chart(chart.set_index("状态"), y="任务数量")

    st.divider()
    st.subheader("🔍 历史任务查询")
    search = st.text_input("搜索任务编号或任务内容", placeholder="例如：800G、采购、风险", key="hist_search")
    status = st.selectbox(
        "按状态筛选",
        ["全部", "completed", "failed", "running", "queued", "cancelled", "cancelling"],
        key="hist_status",
    )
    keyword = search.strip().lower()
    filtered = [
        j for j in jobs
        if (not keyword or keyword in str(j.get("id") or "").lower()
            or keyword in str(j.get("task") or "").lower())
        and (status == "全部" or str(j.get("status") or "").lower() == status)
    ]
    st.write(f"找到 **{len(filtered)}** 条任务")

    if not filtered:
        st.info("没有符合条件的任务。")
    else:
        df = pd.DataFrame([{
            "任务编号": j.get("id"),
            "任务状态": j.get("status"),
            "任务内容": j.get("task"),
            "创建时间": j.get("created_at"),
            "更新时间": j.get("updated_at"),
        } for j in filtered])
        st.dataframe(df, width="stretch", hide_index=True)

        st.divider()
        st.subheader("📋 任务详情")
        mapping = {j["id"]: j for j in filtered}
        selected = st.selectbox("选择任务", list(mapping), key="hist_selected")
        chosen = mapping[selected]
        st.write("**任务编号：**", chosen["id"])
        st.write("**任务状态：**", chosen.get("status"))
        st.write("**任务内容：**", chosen.get("task"))
        st.write("**创建时间：**", chosen.get("created_at"))
        st.write("**更新时间：**", chosen.get("updated_at"))
        if chosen.get("error"):
            st.error(str(chosen["error"]))
        with st.expander("查看数据库原始记录"):
            st.json(chosen)

    st.caption("本页面局部每 5 秒刷新；刷新不会改变搜索和筛选条件。")
    if st.button("🔄 立即刷新", key="hist_refresh"):
        st.rerun(scope="fragment")


render_dashboard()
