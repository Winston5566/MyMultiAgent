"""第27课扩展：命令行将一份报告评分后写入数据库。"""
from __future__ import annotations

import argparse
from pathlib import Path
import uuid

from quality_store import save_quality


def main() -> None:
    p = argparse.ArgumentParser(description="采购报告评分入库，不调用大模型 API")
    p.add_argument("--report", type=Path, required=True, help="UTF-8 报告文件")
    p.add_argument("--job-id", help="关联任务 ID；不指定则创建 demo- 开头的独立记录")
    p.add_argument("--expected-amount", type=int, default=30000)
    p.add_argument("--source", default="manual", help="来源标识：manual/workflow/demo")
    args = p.parse_args()
    if not args.report.is_file():
        p.error(f"文件不存在：{args.report}")
    report = args.report.read_text(encoding="utf-8-sig")
    job_id = args.job_id or ("demo-" + uuid.uuid4().hex[:12])
    result = save_quality(report, job_id=job_id,
                          expected_amount=args.expected_amount, source=args.source)
    print(f"任务 ID：{job_id}")
    print(f"验收结果：{result['score']}/100 · {result['grade']}")
    for c in result["checks"]:
        print(f"{'✓' if c['passed'] else '✗'} {c['name']}：{c['points'] if c['passed'] else 0}/{c['points']}")
    print("结果已写入 multiagent.db 的 quality_evaluations 表（不保存报告全文）。")
    print("提示：这是文本规则评估，不等于已验证实际 RAG 工具调用或引用真实性。")


if __name__ == "__main__":
    main()
