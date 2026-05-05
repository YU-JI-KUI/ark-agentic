"""Tests for build_standard_agent's skill_router wiring.

Covers:
  - dynamic + skill_router=None  → factory wires LLMSkillRouter
  - dynamic + explicit instance  → that instance verbatim
  - full    + skill_router=None  → no router
  - full    + any instance       → ValueError (fail-fast at factory)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ark_agentic.core.runtime.factory import AgentDef, build_standard_agent
from ark_agentic.core.skills.router import (
    LLMSkillRouter,
    RouteContext,
    RouteDecision,
    SkillRouter,
)
from ark_agentic.core.types import SkillLoadMode


@pytest.fixture(autouse=True)
def _force_file_db_type_router_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_TYPE", "file")


class _FakeLLM:
    """Minimal langchain-compatible stub. We only need attribute access here;
    no .ainvoke is exercised in these tests (router never gets called)."""

    def bind_tools(self, *_args, **_kwargs):
        return self


class _DummyRouter:
    """Custom router used to verify the explicit-instance branch."""

    history_window = 0
    timeout = 0.0

    async def route(self, ctx: RouteContext) -> RouteDecision:
        return RouteDecision(skill_id=None, reason="dummy")


@pytest.fixture
def empty_skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    return d


def _defn(load_mode: SkillLoadMode) -> AgentDef:
    return AgentDef(
        agent_id="router_wiring_test",
        agent_name="Test",
        agent_description="t",
        skill_load_mode=load_mode,
    )


def test_dynamic_default_wires_llm_skill_router(empty_skills_dir: Path) -> None:
    """dynamic mode + no skill_router arg → factory creates LLMSkillRouter."""
    runner = build_standard_agent(
        _defn(SkillLoadMode.dynamic),
        empty_skills_dir,
        tools=[],
        llm=_FakeLLM(),
        enable_dream=False,
    )
    assert isinstance(runner._skill_router, LLMSkillRouter)


def test_full_default_no_router(empty_skills_dir: Path) -> None:
    """full mode + no skill_router arg → no router wired."""
    runner = build_standard_agent(
        _defn(SkillLoadMode.full),
        empty_skills_dir,
        tools=[],
        llm=_FakeLLM(),
        enable_dream=False,
    )
    assert runner._skill_router is None


def test_explicit_custom_router_used(empty_skills_dir: Path) -> None:
    """Explicit custom router instance is used as-is."""
    custom: SkillRouter = _DummyRouter()
    runner = build_standard_agent(
        _defn(SkillLoadMode.dynamic),
        empty_skills_dir,
        tools=[],
        llm=_FakeLLM(),
        enable_dream=False,
        skill_router=custom,
    )
    assert runner._skill_router is custom


def test_full_mode_with_router_raises(empty_skills_dir: Path) -> None:
    """full mode + skill_router=<instance> → factory raises ValueError."""
    with pytest.raises(ValueError, match="dynamic mode"):
        build_standard_agent(
            _defn(SkillLoadMode.full),
            empty_skills_dir,
            tools=[],
            llm=_FakeLLM(),
            enable_dream=False,
            skill_router=_DummyRouter(),
        )
