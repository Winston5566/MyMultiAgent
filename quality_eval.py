"""第27课：针对教学采购案例的可解释、零 API 成本报告质量检查。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'knowledge_base.db'


def _has_amount(text: str, amount: int) -> bool:
    """查找金额，避免把 300000 当成 30000。"""
    candidates = re.findall(r'(?<![\d.])\d[\d,，]*(?:\.\d+)?\s*(?:元|人民币|RMB|¥|￥)?(?![\d.])', text, flags=re.I)
    for item in candidates:
        cleaned = re.sub(r'(?:元|人民币|RMB|¥|￥|\s)', '', item, flags=re.I).replace(',', '').replace('，', '')
        try:
            if float(cleaned) == amount:
                return True
        except ValueError:
            pass
    return False


def _get_sources(db_path: Path) -> list[str]:
    if not db_path.is_file():
        return []
    try:
        with sqlite3.connect(db_path, timeout=5) as conn:
            rows = conn.execute('SELECT source_path FROM kb_documents ORDER BY source_path').fetchall()
        return [str(r[0]) for r in rows]
    except sqlite3.Error:
        return []


def evaluate(report: str, *, expected_amount: int = 30000, db_path: Path = DB) -> dict:
    """只评估报告文本；无法确认是否真的发生过工具调用。"""
    if not isinstance(report, str):
        raise TypeError('report 必须是字符串')
    if expected_amount < 0:
        raise ValueError('expected_amount 不能为负数')
    compact = re.sub(r'\s+', '', report)
    sources = _get_sources(Path(db_path))
    cited_sources = [s for s in sources if s in report or Path(s).name in report]
    has_location = bool(re.search(r'(?:片段\s*\d+|第\s*\d+\s*页|全文|正文及表格)', report))
    # 这里只验证存在已索引的文件名与位置标识，不验证引用内容是否支持结论。
    source_ok = bool(cited_sources and has_location)
    approval_roles = '部门负责人' in compact and '财务负责人' in compact
    approval_together = bool(re.search(r'共同审批|联合审批|双方审批|两人审批|两级审批|均需审批|都需审批|分别审批|同时审批', compact))
    approval_ok = approval_roles and approval_together
    risk_groups = {
        '兼容性': ('兼容', '接口类型', '传输距离', '功耗'),
        '供应商': ('供应商', '资质', '售后', '质保'),
        '质量': ('质量', '测试报告', '验收', '检测'),
        '交付': ('交付', '交货', '交期', '供货周期'),
    }
    covered = [name for name, words in risk_groups.items() if any(w in compact for w in words)]
    # 风险项必须至少覆盖三类；这只是关键词覆盖率检查。
    risks_ok = len(covered) >= 3
    caveat_ok = ('教学' in compact or '演示' in compact or '虚构' in compact) and (
        '不代表' in compact or '仅供' in compact or '测试' in compact or '正式制度' in compact or '实际采购' in compact
    )
    checks = [
        {'name': '采购金额', 'points': 25, 'passed': _has_amount(report, expected_amount), 'detail': f'应明确写出 {expected_amount:,} 元'},
        {'name': '审批要求', 'points': 20, 'passed': approval_ok, 'detail': '应说明部门负责人和财务负责人共同审批'},
        {'name': '风险覆盖', 'points': 20, 'passed': risks_ok, 'detail': f'至少覆盖3类风险；检测到：{", ".join(covered) if covered else "无"}'},
        {'name': '知识库来源', 'points': 20, 'passed': source_ok, 'detail': f'已索引文件名与片段位置：{", ".join(cited_sources) if cited_sources else "未找到"}'},
        {'name': '教学资料声明', 'points': 15, 'passed': caveat_ok, 'detail': '需明确资料是演示/教学资料，不应当作真实公司政策'},
    ]
    score = sum(c['points'] for c in checks if c['passed'])
    return {
        'score': score,
        'max_score': 100,
        'grade': '通过' if score >= 80 and checks[0]['passed'] and checks[1]['passed'] else '待改进',
        'checks': checks,
        'known_sources': sources,
        'limitations': '仅检查文本格式、金额、关键词和索引文件名；不核验事实支持关系、模型是否实际调用工具，也不能证明没有幻觉。',
    }


def main() -> None:
    p = argparse.ArgumentParser(description='第27课：Agent 采购报告自动验收（无需 API）')
    p.add_argument('--report', type=Path, help='UTF-8 文本报告路径；不指定则从标准输入读取')
    p.add_argument('--expected-amount', type=int, default=30000)
    p.add_argument('--db', type=Path, default=DB)
    p.add_argument('--json', action='store_true', help='输出机器可读 JSON')
    args = p.parse_args()
    if args.report:
        if not args.report.is_file():
            p.error(f'找不到报告：{args.report}')
        content = args.report.read_text(encoding='utf-8-sig')
    else:
        if sys.stdin.isatty():
            p.error('请使用 --report 报告.txt，或通过管道传入报告内容')
        content = sys.stdin.read()
    if not content.strip():
        p.error('报告内容为空')
    result = evaluate(content, expected_amount=args.expected_amount, db_path=args.db)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f'\n=== Agent 报告质量验收：{result["score"]}/100 · {result["grade"]} ===')
        for c in result['checks']:
            print(f'{"[通过]" if c["passed"] else "[未通过]"} {c["name"]}（{c["points"]}分）：{c["detail"]}')
        print('\n说明：' + result['limitations'])


if __name__ == '__main__':
    main()
