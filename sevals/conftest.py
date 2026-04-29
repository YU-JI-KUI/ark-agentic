"""
conftest — pytest 全局 fixture

data 隔离策略：
  每个 test function 通过 pytest 内置的 tmp_path fixture 获得独立临时目录。
  monkeypatch 将 SESSIONS_DIR / MEMORY_DIR 指向该目录。
  测试结束后 pytest 自动清理，不影响 data/ 目录下的任何生产数据。

报告策略：
  eval_report_collector 是 session 级 fixture，收集所有 CaseScore。
  整个测试 session 结束后（yield 之后）自动渲染 HTML 报告到 sevals/reports/。
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()  # 从项目根目录的 .env 加载 MODEL_NAME / API_KEY 等配置

import pytest

from sevals.runner.agent_factory import create_eval_agent
from sevals.runner.reporter import EvalReport, SkillReport, write_report
from sevals.runner.scorer import CaseScore
from ark_agentic.core.runner import AgentRunner


# ── agent fixtures（function scope，每个测试独立隔离）────────────────────────

@pytest.fixture
def insurance_agent(tmp_path, monkeypatch) -> AgentRunner:
    """每个测试函数独立的保险 agent，使用临时 data 目录。"""
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    return create_eval_agent("insurance", tmp_path)


@pytest.fixture
def securities_agent(tmp_path, monkeypatch) -> AgentRunner:
    """每个测试函数独立的证券 agent，使用临时 data 目录。"""
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    return create_eval_agent("securities", tmp_path)


# ── 报告收集器（session scope，贯穿整个测试运行）────────────────────────────

@pytest.fixture(scope="session")
def eval_collector() -> dict:
    """收集所有 case 结果的共享容器。

    结构：
      {
        ("insurance", "withdraw_money"): [CaseScore, ...],
        ("securities", "asset_overview"):  [CaseScore, ...],
      }
    """
    return {}


@pytest.fixture(scope="session", autouse=True)
def generate_report(eval_collector: dict):
    """session 结束后自动生成 HTML 报告。autouse=True 无需显式引用。"""
    yield  # 等待所有测试执行完毕

    if not eval_collector:
        return

    # 按 (agent, skill) 分组构建报告
    skills = []
    for (agent, skill), scores in eval_collector.items():
        skills.append(SkillReport(skill=skill, agent=agent, cases=scores))

    report = EvalReport(skills=skills)
    output_path = write_report(report)
    print(f"\n📊 评测报告已生成：{output_path.resolve()}")
