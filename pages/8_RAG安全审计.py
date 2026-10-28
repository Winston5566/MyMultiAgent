"""第29课：安全审计只读仪表板，不调用大模型。"""
from pathlib import Path
import sys
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from security_guard import list_events

st.set_page_config(page_title="RAG 安全审计", layout="wide")
st.title(" RAG 安全审计")
st.caption("只展示规则检测事件；不保存原始问题、文档内容或密钥。检测结果不等于全面安全认证。")

DB = Path(__file__).resolve().parents[1] / "multiagent.db"
rows = list_events(db_path=DB, limit=500)
blocked = sum(r["event_type"] == "blocked_prompt_injection" for r in rows)
redacted = sum(r["event_type"] == "redacted_secret" for r in rows)
a, b, c = st.columns(3)
a.metric("最近最多 500 条事件", len(rows))
b.metric("可疑指令过滤", blocked)
c.metric("敏感信息遮盖", redacted)

if rows:
    st.subheader("事件明细（仅哈希摘要）")
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.info("事件记录的是规则命中情况；没有事件不代表没有风险。")
else:
    st.info("尚无安全审计事件。可以运行第29课离线测试或检索真实知识库。")
