"""
scorer — 评测评分逻辑

第一版：仅校验工具调用命中率（expect_tools）。
后续版本在此追加新维度（参数、顺序、回复内容等），旧 case 无需改动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ark_agentic.core.runner import RunResult


@dataclass
class CaseScore:
    """单个 case 的评分结果。"""

    case_id: str
    description: str
    user_input: str                     # 原始用户输入，供报告展示
    passed: bool
    score: float                        # 0.0 ~ 1.0
    hit: set[str] = field(default_factory=set)       # 命中的工具
    missing: set[str] = field(default_factory=set)   # 遗漏的工具
    extra: set[str] = field(default_factory=set)     # 多调的工具（第一版不扣分，仅记录）
    reason: str = ""                    # 失败原因，供 assert 输出

    def __str__(self) -> str:
        parts = [f"[{self.case_id}] {'PASS' if self.passed else 'FAIL'} score={self.score:.2f}"]
        if self.missing:
            parts.append(f"  missing tools : {sorted(self.missing)}")
        if self.extra:
            parts.append(f"  extra tools   : {sorted(self.extra)}  (not penalized)")
        if self.reason:
            parts.append(f"  reason        : {self.reason}")
        return "\n".join(parts)


def compute_score(result: RunResult, case: dict[str, Any]) -> CaseScore:
    """根据 RunResult 和 case 定义计算评分。

    当前支持的校验维度（按 case 字段是否存在决定是否启用）：
      - expect_tools : 工具命中率（第一版，必须）

    Args:
        result : AgentRunner.run() 返回的 RunResult
        case   : 单条用例 dict（含 id / description / input / expect_tools）

    Returns:
        CaseScore
    """
    case_id = case["id"]
    description = case.get("description", "")
    user_input = case.get("input", "")

    # ── 维度 1：工具命中率 ────────────────────────────────────────────────────
    actual: set[str] = {tc.name for tc in (result.tool_calls or [])}
    expect: set[str] = set(case.get("expect_tools", []))

    hit = expect & actual
    missing = expect - actual
    extra = actual - expect

    if expect:
        score = len(hit) / len(expect)
    else:
        # expect 为空：actual 也为空得满分，actual 非空说明不该调却调了
        score = 1.0 if not actual else 0.0

    passed = score == 1.0 and (not extra if not expect else True)
    # 当 expect 非空时，extra 不扣分；当 expect 为空时，extra 意味着失败

    reason = ""
    if not passed:
        if missing:
            reason = f"工具未被调用: {sorted(missing)}"
        elif not expect and actual:
            reason = f"不应调用任何工具，但实际调用了: {sorted(actual)}"

    return CaseScore(
        case_id=case_id,
        description=description,
        user_input=user_input,
        passed=passed,
        score=score,
        hit=hit,
        missing=missing,
        extra=extra,
        reason=reason,
    )
