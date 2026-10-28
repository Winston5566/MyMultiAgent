"""第27课：在工作流成功完成后，安全地对教学采购报告自动评分。

只支持简单的单品采购题（数量 × 单价，可选明确折扣）。无法可靠推断时跳过，
避免沿用上一课固定的 30,000 元标准误评其他任务。
评分为启发式文本检查，不代表对引用真实性或工具调用的审计。
"""
from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from quality_store import save_quality

_QTY = re.compile(r"(?<!\d)(\d{1,8})\s*(?:只|个|件|台|套)")
_UNIT = re.compile(
    r"(?:单价|每\s*(?:只|个|件|台|套)\s*(?:价格|售价|单价)?)"
    r"\s*(?:为|是|:|：)?\s*(?:人民币|¥|￥)?\s*"
    r"(\d[\d,，]*(?:\.\d+)?)\s*(?:元)?"
)
_DISCOUNT = re.compile(r"(?<!\d)(\d(?:\.\d+)?)\s*折|([一二三四五六七八九])折")
_CN_DISCOUNT = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                "六": 6, "七": 7, "八": 8, "九": 9}


def infer_expected_amount(task: str) -> tuple[int | None, str]:
    """只在简单单品场景下计算应付总额；不能确定时返回 (None, 原因)。"""
    if not isinstance(task, str) or not task.strip():
        return None, "任务文本为空"
    # 以下复杂价格条件不能简单按数量 × 单价推断
    if re.search(r"运费|税率|增值税|阶梯价|满减|返利|优惠券|分批采购|多批次|多种型号|不同型号", task):
        return None, "涉及额外费用、复杂优惠或多种采购项目"
    qtys = _QTY.findall(task)
    prices = _UNIT.findall(task)
    if len(qtys) != 1 or len(prices) != 1:
        return None, "未能唯一识别采购数量和单价"
    try:
        qty = int(qtys[0])
        unit = Decimal(prices[0].replace(",", "").replace("，", ""))
        if qty <= 0 or unit <= 0:
            return None, "数量或单价不是正数"
        amount = unit * qty
        discounts = list(_DISCOUNT.finditer(task))
        if discounts:
            if len(discounts) != 1:
                return None, "存在多个折扣条件"
            m = discounts[0]
            rate = Decimal(m.group(1)) if m.group(1) else Decimal(_CN_DISCOUNT[m.group(2)])
            if not (Decimal(0) < rate <= Decimal(10)):
                return None, "折扣不在有效范围内"
            amount = amount * rate / Decimal(10)
        elif re.search(r"\d+\s*%|百分之|折优惠|折扣率|打折|减免", task):
            return None, "发现尚未支持的优惠计算方式"
        if amount != amount.to_integral_value():
            return None, "计算金额包含小数，当前规则评分仅支持整数元"
        return int(amount), "根据任务中的数量、单价和明确折扣计算"
    except (InvalidOperation, ValueError, OverflowError):
        return None, "无法解析采购金额"


def record_completed_workflow_quality(memory_data: dict[str, Any], *,
                                      job_id: str | None = None) -> dict | None:
    """在工作流完成后调用。失败不抛出异常，不改变任务的 completed 状态。"""
    try:
        if memory_data.get("status") != "completed":
            print("[质量评估] 工作流未完成，跳过")
            return None
        results = memory_data.get("results") or {}
        report = results.get("writer")
        if not isinstance(report, str) or not report.strip():
            print("[质量评估] 没有 writer 报告，跳过")
            return None
        task = memory_data.get("task", "")
        amount, reason = infer_expected_amount(task)
        if amount is None:
            print(f"[质量评估] 无法确定应付金额，跳过自动评分：{reason}")
            return None
        if amount < 30000:
            # 旧评分器固定检查两位负责人共同审批，不能用于低于门槛的案例。
            print(f"[质量评估] 金额 {amount} 元低于演示审批门槛；旧评分器不适用，跳过")
            return None
        key = job_id or os.getenv("MULTIAGENT_JOB_ID") or memory_data.get("run_id")
        if not key:
            print("[质量评估] 缺少任务 ID，跳过入库")
            return None
        result = save_quality(
            report, job_id=str(key), expected_amount=amount, source="workflow"
        )
        print(f"[质量评估] 任务 {key}：{result['score']}/100 · {result['grade']}"
              f"（应付金额 {amount} 元）")
        print("[质量评估] 结果已保存到 quality_evaluations")
        return result
    except Exception as exc:
        print(f"[质量评估] 评分或入库失败，不影响已完成任务：{type(exc).__name__}: {exc}")
        return None
