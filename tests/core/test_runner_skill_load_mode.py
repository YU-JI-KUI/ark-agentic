"""Tests for runner skill_load_mode (full / dynamic / semantic) and RunOptions wiring."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import pytest

from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import AgentMessage, MessageRole, SkillLoadMode


class _MockLLM:
    """Minimal mock LLM for prompt-building tests."""

    async def chat(self, messages, tools=None, stream=False, **kwargs):
        return AgentMessage.assistant(content="ok")


@pytest.fixture
def runner_with_one_skill(tmp_sessions_dir: Path):
    """AgentRunner with one skill (metadata + body)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "test_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: Test Skill\ndescription: A test\nwhen_to_use: When testing\n---\n\nFull skill body here."
        )
        config = SkillConfig(skill_directories=[tmpdir], default_load_mode=SkillLoadMode.full)
        loader = SkillLoader(config)
        loader.load_from_directories()

        session_manager = SessionManager(tmp_sessions_dir)
        session = session_manager.create_session_sync()
        session_id = session.session_id
        session_manager.add_message_sync(
            session_id,
            AgentMessage.user("Hello", metadata={}),
        )

        runner = AgentRunner(
            llm=_MockLLM(),
            session_manager=session_manager,
            tool_registry=ToolRegistry(),
            skill_loader=loader,
            config=RunnerConfig(),
        )
        yield runner, session_id


# ============ full mode ============


def test_full_mode_contains_skill_body(runner_with_one_skill) -> None:
    """skill_load_mode=full: prompt contains full skill content."""
    runner, session_id = runner_with_one_skill
    prompt = runner._build_system_prompt(
        {}, session_id=session_id, skill_load_mode="full"
    )
    assert "Full skill body here." in prompt
    assert "Test Skill" in prompt
    # full mode should NOT include read_skill dynamic instructions
    assert "业务必选协议" not in prompt


# ============ dynamic mode ============


def test_dynamic_mode_contains_read_skill_instruction(
    runner_with_one_skill,
) -> None:
    """skill_load_mode=dynamic: prompt contains read_skill instructions, not full body."""
    runner, session_id = runner_with_one_skill
    prompt = runner._build_system_prompt(
        {}, session_id=session_id, skill_load_mode="dynamic"
    )
    assert "read_skill" in prompt
    assert "业务必选协议" in prompt
    assert "Full skill body here." not in prompt
    assert "Test Skill" in prompt
    assert "When testing" in prompt


# ============ semantic mode (fallback) ============


def test_semantic_mode_falls_back_to_dynamic(
    runner_with_one_skill, caplog
) -> None:
    """skill_load_mode=semantic: falls back to dynamic with warning."""
    runner, session_id = runner_with_one_skill
    with caplog.at_level(logging.WARNING):
        prompt = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="semantic"
        )
    assert "not yet implemented" in caplog.text
    # should behave like dynamic mode
    assert "read_skill" in prompt
    assert "Full skill body here." not in prompt



# ============ SkillConfig default_load_mode ============


def test_skill_config_default_load_mode() -> None:
    """SkillConfig.default_load_mode defaults to full."""
    config = SkillConfig()
    assert config.default_load_mode == SkillLoadMode.full


def test_skill_config_custom_load_mode() -> None:
    """SkillConfig.default_load_mode can be set to dynamic."""
    config = SkillConfig(default_load_mode=SkillLoadMode.dynamic)
    assert config.default_load_mode == SkillLoadMode.dynamic
