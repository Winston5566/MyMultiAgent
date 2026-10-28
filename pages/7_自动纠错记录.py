"""第28课：展示自动修订历史，不调用 API，也不显示报告全文。"""
from pathlib import Path
import sqlite3
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB = ROOT / "multiagent.db"
st.set_page_config(page_title="Agent 自动纠错记录", page_icon="🔧", layout="wide")
st.title("🔧 Agent 自动纠错记录")
st.caption("读取 SQLite 修订历史 · 不调用 API · 候选稿只保存在本机 quality_reports 文件夹")

if not DB.exists():
    st.info("还没有 multiagent.db 数据库")
    st.stop()

try:
    with sqlite3.connect(DB, timeout=10) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='quality_revision_attempts'").fetchone()
        if not exists:
            st.info("暂无自动修订记录。请先执行一次评分低于90分的工作流任务。")
            st.stop()
        df = pd.read_sql_query("""
            SELECT job_id, attempt, previous_score, candidate_score,
                   accepted, reason, created_at
            FROM quality_revision_attempts
            ORDER BY created_at DESC, id DESC
            LIMIT 500
        """, conn)
except sqlite3.Error as exc:
    st.error(f"读取数据库失败：{exc}")
    st.stop()

if df.empty:
    st.info("暂无自动修订记录")
    st.stop()

a, b, c = st.columns(3)
a.metric("涉及任务", int(df['job_id'].nunique()))
b.metric("修订尝试", len(df))
c.metric("接受修订", int(df['accepted'].sum()))

jobs = df['job_id'].drop_duplicates().tolist()
selected = st.selectbox("查看任务", jobs)
subset = df[df['job_id'] == selected].sort_values('attempt')
subset = subset.copy()
subset['结果'] = subset['accepted'].map({1: '接受', 0: '拒绝'})
st.dataframe(subset[["attempt", "previous_score", "candidate_score", "结果", "reason", "created_at"]].rename(columns={
    "attempt": "第几次", "previous_score": "修订前分数", "candidate_score": "候选分数",
    "reason": "判断依据", "created_at": "时间（UTC）"
}), hide_index=True, use_container_width=True)

st.caption("评分提高且原有检查项没有退步，才会接受修订。评分是规则化文本验收，不等于事实准确性证明。")
st.caption("原稿和候选稿在项目目录 quality_reports/<任务文件夹> 中，请勿上传含敏感信息的报告到公共仓库。")
