"""第27课：Streamlit 采购报告质量评估。"""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from quality_eval import evaluate

st.set_page_config(page_title='Agent 质量评估', page_icon='🧪', layout='wide')
st.title('🧪 Agent 质量评估')
st.caption('第27课 · 规则化验收 · 本地执行，不调用大模型 API')
st.info('将网页任务生成的最终报告粘贴到下方。此页面不会自动读取历史任务，也不能确认 Agent 是否实际调用过知识库工具。')
expected_amount = st.number_input('本次采购预期金额（元）', min_value=0, value=30000, step=1000)
report = st.text_area('粘贴完整采购报告', height=300, placeholder='在这里粘贴财务、风险、审批和引用来源等完整报告...')
if st.button('开始验收', type='primary'):
    if not report.strip():
        st.warning('请先粘贴报告。')
    else:
        result = evaluate(report, expected_amount=int(expected_amount))
        a, b = st.columns(2)
        a.metric('质量得分', f'{result["score"]} / 100')
        b.metric('验收结果', result['grade'])
        for check in result['checks']:
            st.write(('✅' if check['passed'] else '❌') + f' **{check["name"]}**（{check["points"]}分）— {check["detail"]}')
        if not result['known_sources']:
            st.warning('没有读取到本地知识库索引。请检查 knowledge_base.db 是否存在并完成索引。')
        st.caption(result['limitations'])
