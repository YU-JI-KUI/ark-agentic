"""Tests for ``BaseAgent.build_skill_router`` default + override.

The old factory had four branches (dynamic-default / dynamic-explicit /
full-default / full-explicit-raises). After folding into ``BaseAgent``,
the wiring is a single hook. Subclasses opt into a custom router by
overriding ``build_skill_router()``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ark_agentic.core.runtime.base_agent import BaseAgent
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
    """Minimal langchain-compatible stub."""

    def bind_tools(self, *_args, **_kwargs):
        return self


class _DummyRouter:
    """Custom router used to verify override behavior."""

    history_window = 0
    timeout = 0.0

    async def route(self, ctx: RouteContext) -> RouteDecision:
        return RouteDecision(skill_id=None, reason="dummy")


def _make_agent(
    *, load_mode: SkillLoadMode, custom_router: SkillRouter | None = None
):
    """Create a BaseAgent subclass with ClassVar overrides + optional router."""

    attrs: dict = {
        "agent_id": "router_wiring_test",
        "agent_name": "T",
        "agent_description": "t",
        "skill_load_mode": load_mode,
    }
    if custom_router is not None:
        attrs["build_skill_router"] = lambda self, _r=custom_router: _r
    return type("Test_Router", (BaseAgent,), attrs)


def _instantiate(cls, tmp_path: Path) -> BaseAgent:
    fake_llm = _FakeLLM()
    with patch.object(BaseAgent, "build_llm", return_value=fake_llm), \
         patch(
             "ark_agentic.core.runtime.base_agent.prepare_agent_data_dir",
             return_value=tmp_path,
         ), \
         patch(
             "ark_agentic.core.runtime.base_agent.get_memory_base_dir",
             return_value=tmp_path,
         ):
        return cls()


def test_dynamic_default_wires_llm_skill_router(tmp_path: Path) -> None:
    """dynamic mode + default ``build_skill_router`` → ``LLMSkillRouter``."""
    cls = _make_agent(load_mode=SkillLoadMode.dynamic)
    agent = _instantiate(cls, tmp_path)
    assert isinstance(agent._skill_router, LLMSkillRouter)


def test_full_default_no_router(tmp_path: Path) -> None:
    """full mode + default ``build_skill_router`` → ``None``."""
    cls = _make_agent(load_mode=SkillLoadMode.full)
    agent = _instantiate(cls, tmp_path)
    assert agent._skill_router is None


def test_dynamic_override_uses_custom_router(tmp_path: Path) -> None:
    """Subclass overriding ``build_skill_router`` returns a custom instance."""
    custom = _DummyRouter()
    cls = _make_agent(load_mode=SkillLoadMode.dynamic, custom_router=custom)
    agent = _instantiate(cls, tmp_path)
    assert agent._skill_router is custom
