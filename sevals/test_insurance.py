"""
test_insurance — 保险 agent 评测入口

用 pytest.mark.parametrize 将每个 JSON case 展开为独立测试用例，
失败时打印详细的工具命中/遗漏信息，同时把结果推入 eval_collector 供报告生成。
"""

from __future__ import annotations

import pytest

from sevals.runner.case_loader import load_cases
from sevals.runner.scorer import compute_score

# ── 加载用例 ──────────────────────────────────────────────────────────────────

_META, _WITHDRAW_CASES = load_cases("cases/insurance/withdraw_money.json")

# ── 测试：保险取款 skill ──────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    _WITHDRAW_CASES,
    ids=[c["id"] for c in _WITHDRAW_CASES],
)
async def test_withdraw_money(case: dict, insurance_agent, eval_collector) -> None:
    """验证 withdraw_money skill 的工具调用准确率。"""
    session = insurance_agent.session_manager.create_session_sync()

    result = await insurance_agent.run(
        session_id=session.session_id,
        user_input=case["input"],
        user_id=_META["user_id"],
        stream=False,
    )

    score = compute_score(result, case)
    print(f"\n{score}")

    # 推入收集器，key = (agent, skill)
    key = (_META["agent"], _META["skill"])
    eval_collector.setdefault(key, []).append(score)

    assert score.passed, score.reason
