"""第25课：Token 与 API 成本 Dashboard。"""
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'multiagent.db'

st.set_page_config(page_title='Token 与 API 成本', page_icon='💰', layout='wide')
st.title('💰 Token 与 API 成本')
st.caption('每 5 秒自动刷新 · 仅统计实际记录的 API 响应 · 不包含未接入追踪的历史请求')

if not hasattr(st, 'fragment'):
    st.error('请升级 Streamlit：python -m pip install -U streamlit')
    st.stop()


def read_usage():
    if not DB.is_file():
        return pd.DataFrame()
    with sqlite3.connect(DB, timeout=10) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='api_usage'").fetchone()
        if not exists:
            return pd.DataFrame()
        return pd.read_sql_query('''
            SELECT job_id, agent_name, model, prompt_tokens,
                   completion_tokens, total_tokens, estimated_cost,
                   currency, usage_available, created_at, request_id
            FROM api_usage ORDER BY id DESC
        ''', conn)


@st.fragment(run_every='5s')
def render_dashboard():
    try:
        df = read_usage()
    except (OSError, sqlite3.Error) as e:
        st.error(f'读取数据库失败：{e}')
        return
    if df.empty:
        st.info('暂无 Token 记录。先运行 python token_usage.py 初始化数据库，再完成测试或接入真实 API 调用。')
        return

    st.subheader('筛选')
    a, b = st.columns(2)
    with a:
        agent = st.selectbox('Agent', ['全部'] + sorted(df['agent_name'].dropna().unique().tolist()), key='token_agent')
    with b:
        model = st.selectbox('模型', ['全部'] + sorted(df['model'].dropna().unique().tolist()), key='token_model')
    job = st.text_input('搜索任务 ID', key='token_job', placeholder='输入任务编号的一部分')
    part = df.copy()
    if agent != '全部':
        part = part[part['agent_name'] == agent]
    if model != '全部':
        part = part[part['model'] == model]
    part = part[part['job_id'].astype(str).str.contains(job.strip(), case=False, regex=False)]
    if part.empty:
        st.info('当前筛选条件下没有记录。')
        return

    calls = len(part)
    known_usage = part['usage_available'].fillna(0).astype(int).sum()
    in_tokens = int(part['prompt_tokens'].sum())
    out_tokens = int(part['completion_tokens'].sum())
    unknown_price = int(part['estimated_cost'].isna().sum())

    st.subheader('总体概览')
    a, b, c, d = st.columns(4)
    a.metric('API 响应次数', calls)
    b.metric('输入 Token（已记录）', f'{in_tokens:,}')
    c.metric('输出 Token（已记录）', f'{out_tokens:,}')
    d.metric('缺少完整 usage', calls - int(known_usage))

    st.subheader('估算费用')
    priced = part.dropna(subset=['estimated_cost', 'currency'])
    if priced.empty:
        st.warning('暂无可计算费用：请核对模型定价配置和 API 响应中的 usage 字段。')
    else:
        totals = priced.groupby('currency', as_index=False)['estimated_cost'].sum()
        for row in totals.itertuples(index=False):
            st.metric(f'已计算费用（{row.currency}）', f'{row.estimated_cost:,.6f}')
    if unknown_price:
        st.warning(f'有 {unknown_price} 次 API 响应未计算费用，因此上述金额不是完整账单。')
    st.caption('按模型配置的每百万 Token 单价计算；不包括服务商额外收费、缓存折扣、税费等特殊计费规则。')

    st.divider()
    st.subheader('按 Agent 统计')
    grouped = part.groupby('agent_name', as_index=False).agg(
        调用次数=('request_id', 'count'),
        输入Token=('prompt_tokens', 'sum'),
        输出Token=('completion_tokens', 'sum'),
        总Token=('total_tokens', 'sum'),
        费用已知次数=('estimated_cost', 'count'),
    ).rename(columns={'agent_name': 'Agent'})
    st.dataframe(grouped, hide_index=True, use_container_width=True)
    st.bar_chart(grouped.set_index('Agent')[['输入Token', '输出Token']])

    st.divider()
    st.subheader('API 调用明细')
    st.dataframe(part.rename(columns={
        'job_id': '任务ID', 'agent_name': 'Agent', 'model': '模型',
        'prompt_tokens': '输入Token', 'completion_tokens': '输出Token',
        'total_tokens': '总Token', 'estimated_cost': '估算费用',
        'currency': '币种', 'usage_available': 'usage完整',
        'created_at': '记录时间', 'request_id': '请求ID',
    }), hide_index=True, use_container_width=True)
    if st.button('🔄 立即刷新', key='token_refresh'):
        st.rerun(scope='fragment')


render_dashboard()
