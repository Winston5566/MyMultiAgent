#!/usr/bin/env python3
"""第30课：只读离线验收。不会调用大模型或修改现有数据库。"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

REQUIRED_FILES = [
    'my_agent.py', 'multi_agent.py', 'resilient_workflow.py',
    'run_platform.py', 'rag_kb.py', 'rag_tool.py',
    'safe_rag_tool.py', 'security_guard.py',
    'quality_eval.py', 'quality_store.py',
    'workflow_quality.py', 'report_repair.py',
]
RECOMMENDED_PAGES = [
    '4_Token成本.py', '5_质量评估.py', '6_质量趋势.py',
    '7_自动纠错记录.py', '8_RAG安全审计.py',
]


def audit(project: Path) -> dict:
    project = project.resolve()
    checks = []

    def add(key, status, message):
        checks.append({'key': key, 'status': status, 'message': message})

    for name in REQUIRED_FILES:
        add('file:' + name, 'PASS' if (project / name).is_file() else 'FAIL',
            f'{name}: ' + ('存在' if (project / name).is_file() else '缺失'))

    # 仅解析源码，不执行模块顶层代码（特别是 resilient_workflow）。
    source_map = {}
    for name in REQUIRED_FILES + ['token_usage.py', 'web_runner.py']:
        p = project / name
        if p.is_file():
            try:
                src = p.read_text(encoding='utf-8-sig')
                ast.parse(src, filename=name)
                source_map[name] = src
                add('syntax:' + name, 'PASS', f'{name}: Python 语法正确')
            except (SyntaxError, UnicodeError, OSError) as e:
                add('syntax:' + name, 'FAIL', f'{name}: {type(e).__name__}，行号 {getattr(e, "lineno", "未知")}')

    pages = project / 'pages'
    if not pages.is_dir():
        add('pages', 'FAIL', 'pages/ 目录缺失')
    else:
        for name in RECOMMENDED_PAGES:
            p = pages / name
            add('page:' + name, 'PASS' if p.is_file() else 'WARN',
                f'pages/{name}: ' + ('存在' if p.is_file() else '未找到（可能尚未安装）'))
        for p in sorted(pages.glob('*.py'))[:80]:
            try:
                ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p.name))
            except (SyntaxError, UnicodeError, OSError) as e:
                add('page_syntax:' + p.name, 'FAIL', f'pages/{p.name}: {type(e).__name__}')

    for module in ('openai', 'dotenv', 'streamlit'):
        found = importlib.util.find_spec(module) is not None
        add('dependency:' + module, 'PASS' if found else 'FAIL',
            f'Python 依赖 {module}: ' + ('已安装' if found else '未安装（请在项目 .venv 中运行）'))

    ma = source_map.get('multi_agent.py', '')
    add('rag_agent_import', 'PASS' if 'from safe_rag_tool import' in ma else 'WARN',
        'Agent 使用 safe_rag_tool 导入' if 'from safe_rag_tool import' in ma else '未发现安全 RAG 导入，请确认第29课安装')
    add('calculator', 'PASS' if '"calculate": calculate' in ma or "'calculate': calculate" in ma else 'WARN',
        '财务计算器注册静态检查（不执行模型）')
    wf = source_map.get('resilient_workflow.py', '')
    add('repair_hook', 'PASS' if 'finalize_report_with_quality(' in wf else 'WARN',
        '检测第28课自动评分与修订钩子' if 'finalize_report_with_quality(' in wf else '未检测到自动修订钩子')
    add('token_tracking', 'PASS' if 'tracked_create' in source_map.get('my_agent.py', '') else 'WARN',
        '检查 Agent 中是否出现 Token 跟踪调用')

    def check_db(file, table_names, *, optional=False):
        db = project / file
        if not db.is_file():
            add('db:' + file, 'WARN' if optional else 'FAIL', f'{file}: 数据库不存在')
            return
        try:
            # 只读模式，绝不新建或迁移数据库。
            conn = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=3)
            try:
                ok = conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                add('db_integrity:' + file, 'PASS' if ok else 'FAIL', f'{file}: SQLite quick_check ' + ('通过' if ok else '异常'))
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in table_names:
                    if table in tables:
                        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        add('table:' + table, 'PASS', f'{file} / {table}: {count} 条记录')
                    else:
                        add('table:' + table, 'WARN', f'{file}: 尚未创建 {table} 表（可能尚未产生记录）')
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as e:
            add('db:' + file, 'FAIL', f'{file}: 数据库读取失败：{type(e).__name__}')

    check_db('knowledge_base.db', ['kb_documents', 'kb_chunks'])
    check_db('multiagent.db', ['jobs', 'api_usage', 'quality_evaluations',
                               'quality_revision_attempts', 'rag_security_events'], optional=True)

    if not (project / '.env').is_file():
        add('env', 'WARN', '.env 未找到：请确认 API 配置；不会读取或输出密钥')
    else:
        add('env', 'PASS', '.env 文件存在（未读取内容）')

    failed = sum(c['status'] == 'FAIL' for c in checks)
    warned = sum(c['status'] == 'WARN' for c in checks)
    passed = sum(c['status'] == 'PASS' for c in checks)
    return {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'project': str(project),
        'result': 'FAIL' if failed else ('WARN' if warned else 'PASS'),
        'summary': {'passed': passed, 'warnings': warned, 'failed': failed},
        'scope': '静态检查 + SQLite 只读检查；不调用 API、不执行工作流、不测试网页可访问性',
        'checks': checks,
    }


def format_markdown(data: dict) -> str:
    s = data['summary']
    lines = [
        '# 第30课：Multi-Agent 系统离线验收报告', '',
        f'生成时间（UTC）：{data["generated_at_utc"]}',
        f'项目目录：`{data["project"]}`',
        f'总体结果：**{data["result"]}**',
        f'检查项：通过 {s["passed"]}，提醒 {s["warnings"]}，失败 {s["failed"]}',
        '', '## 检查明细', '', '| 状态 | 检查项 | 说明 |', '|---|---|---|',
    ]
    for c in data['checks']:
        safe = lambda v: str(v).replace('|', '\\|').replace('\n', ' ')
        lines.append(f'| {safe(c["status"])} | {safe(c["key"])} | {safe(c["message"])} |')
    lines.extend(['', '## 验收边界', '', data['scope'],
                  '', '注意：通过离线验收不代表 API 调用、真实工具执行、自动修订或公网部署已验证。',
                  '企业数据上线前需进行访问控制、合规和人工安全审查。', ''])
    return '\n'.join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='第30课：离线只读验收，不调用 API')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, default=Path('lesson30_acceptance_report.md'))
    parser.add_argument('--json', action='store_true', help='同时保存 JSON 格式结果')
    parser.add_argument('--no-write', action='store_true', help='只输出，不保存报告')
    args = parser.parse_args(argv)
    if not args.project.is_dir():
        parser.error(f'项目目录不存在：{args.project}')
    data = audit(args.project)
    print(f'离线验收：{data["result"]} | 通过 {data["summary"]["passed"]} | 提醒 {data["summary"]["warnings"]} | 失败 {data["summary"]["failed"]}')
    for c in data['checks']:
        if c['status'] != 'PASS':
            print(f'[{c["status"]}] {c["message"]}')
    if not args.no_write:
        path = args.output.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(format_markdown(data), encoding='utf-8')
        print(f'已生成报告：{path}')
        if args.json:
            json_path = path.with_suffix('.json')
            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'已生成 JSON：{json_path}')
    return 1 if data['summary']['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
