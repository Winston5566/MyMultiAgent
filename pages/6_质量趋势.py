"""第27课扩展：质量评分历史趋势，独立读取 SQLite。"""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from quality_store import get_quality_rows

st.set_page_config(page_title="Agent 质量趋势", page_icon="📈", layout="wide")
st.title("📈 Agent 报告质量趋势")
st.caption("读取 multiagent.db / quality_evaluations · 不调用 API · 只展示已记录的评分")

try:
    rows = get_quality_rows()
except Exception as exc:
    st.error(f"读取质量记录失败：{exc}")
    st.stop()

if not rows:
    st.info("还没有质量评分记录。先运行 python quality_record.py --report 第27课_示例报告.txt")
    st.stop()

frame = pd.DataFrame(rows)
a, b, c = st.columns(3)
a.metric("已评估任务", len(frame))
b.metric("平均分", f"{frame['score'].mean():.1f} / 100")
c.metric("通过率", f"{(frame['grade'] == '通过').mean() * 100:.1f}%")

st.subheader("质量分数趋势")
trend = frame.iloc[::-1].copy()
trend["记录"] = range(1, len(trend) + 1)
st.line_chart(trend.set_index("记录")["score"], y_label="分数", x_label="评估顺序")
st.caption("横轴为评估记录顺序；同一任务重新评分会覆盖旧记录。不同采购任务的评分标准可能不同，不宜直接横向比较。")

st.subheader("评分历史")
st.dataframe(frame[["job_id", "source", "expected_amount", "score", "grade", "evaluated_at"]]
             .rename(columns={"job_id": "任务 ID", "source": "来源", "expected_amount": "预期金额", "score": "得分", "grade": "结果", "evaluated_at": "评估时间（UTC）"}),
             hide_index=True, use_container_width=True)

chosen = st.selectbox("查看单次评分详情", frame["job_id"].tolist())
row = frame[frame["job_id"] == chosen].iloc[0]
for check in json.loads(row["checks_json"]):
    st.write(("✅" if check["passed"] else "❌") + f" **{check['name']}**：{check['detail']}")
st.caption("数据库只保存分数、检查结果和报告哈希，不保存报告全文。")
