#!/usr/bin/env python3
"""Strict allow-list source release for the MyMultiAgent teaching project."""
from __future__ import annotations
import argparse
import ast
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT_FILES = {
    'README_交付说明.md', '.env.example', 'requirements.txt',
    'requirements-optional.txt', 'token_prices.example.json',
    'my_agent.py', 'multi_agent.py', 'tools.py', 'dynamic_planner.py',
    'scheduler.py', 'checkpoint.py', 'memory.py', 'monitor.py',
    'resilient_workflow.py', 'web_runner.py', 'job_control.py',
    'web_app.py', 'run_platform.py', 'agent_log_sync.py', 'database.py',
    'import_agent_logs.py', 'import_agent_logs_v2.py', 'setup_project.py',
    'token_usage.py', 'rag_kb.py', 'rag_ask.py', 'rag_tool.py',
    'safe_rag_tool.py', 'security_guard.py', 'quality_eval.py',
    'quality_store.py', 'quality_record.py', 'workflow_quality.py',
    'report_repair.py', 'final_acceptance.py', 'make_release.py',
}


def build(project: Path, output: Path):
    project = project.resolve()
    output = output.resolve()
    missing = sorted(n for n in ROOT_FILES if not (project / n).is_file())
    if missing:
        raise FileNotFoundError('缺少必要文件，停止打包：' + ', '.join(missing))
    files = [(project / n, n) for n in sorted(ROOT_FILES)]
    pages = project / 'pages'
    if not pages.is_dir():
        raise FileNotFoundError('缺少 pages/ 文件夹')
    for p in sorted(pages.glob('*.py')):
        if p.is_file() and '_backup' not in p.name and not p.is_symlink():
            files.append((p, 'pages/' + p.name))
    for p, name in files:
        if p.is_symlink() or p.stat().st_size > 2_000_000:
            raise ValueError(f'拒绝打包符号链接或过大文件：{name}')
        if name.endswith('.py'):
            ast.parse(p.read_text(encoding='utf-8-sig'), filename=name)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', ZIP_DEFLATED) as z:
        for p, name in files:
            z.write(p, name)
    with ZipFile(output) as z:
        damaged = z.testzip()
        if damaged is not None:
            raise RuntimeError('ZIP 校验失败：' + damaged)
    print(f'已生成：{output}\n文件数：{len(files)}\nZIP 校验：通过')
    print('不包含数据库、.env、日志、任务数据或真实知识库文档。')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', type=Path, default=Path.cwd())
    ap.add_argument('--output', type=Path, default=Path('MultiAgent_交付源码_最终补全版.zip'))
    args = ap.parse_args()
    build(args.project, args.output)
