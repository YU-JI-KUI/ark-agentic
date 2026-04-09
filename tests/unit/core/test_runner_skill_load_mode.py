"""Tests for runner skill_load_mode (full / dynamic) and RunOptions wiring."""

from __future__ import annotations

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


def _make_runner_with_skill(tmp_sessions_dir: Path, load_mode: SkillLoadMode):
    """Helper that creates an AgentRunner with one skill and the given load_mode."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "test_skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Test Skill\ndescription: A test\nwhen_to_use: When testing\n---\n\nFull skill body here."
            )
            skill_cfg = SkillConfig(skill_directories=[tmpdir], load_mode=load_mode)
            loader = SkillLoader(skill_cfg)
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
                config=RunnerConfig(skill_config=skill_cfg),
            )
            yield runner, session_id

    return _ctx()


@pytest.fixture
def runner_with_one_skill(tmp_sessions_dir: Path):
    """AgentRunner with one skill, load_mode=full."""
    with _make_runner_with_skill(tmp_sessions_dir, SkillLoadMode.full) as ctx:
        yield ctx


@pytest.fixture
def runner_with_one_skill_dynamic(tmp_sessions_dir: Path):
    """AgentRunner with one skill, load_mode=dynamic."""
    with _make_runner_with_skill(tmp_sessions_dir, SkillLoadMode.dynamic) as ctx:
        yield ctx


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


def test_full_mode_does_not_register_read_skill_tool(runner_with_one_skill) -> None:
    """When load_mode is full, read_skill is not in the tool registry."""
    runner, _ = runner_with_one_skill
    names = [t.name for t in runner.tool_registry.list_all()]
    assert "read_skill" not in names


# ============ dynamic mode ============


def test_dynamic_mode_contains_read_skill_instruction(
    runner_with_one_skill_dynamic,
) -> None:
    """load_mode=dynamic: prompt contains read_skill instructions, not full body."""
    runner, session_id = runner_with_one_skill_dynamic
    prompt = runner._build_system_prompt(
        {}, session_id=session_id, skill_load_mode="dynamic"
    )
    assert "read_skill" in prompt
    assert "业务必选协议" in prompt
    assert "Full skill body here." not in prompt
    assert "Test Skill" in prompt
    assert "When testing" in prompt


# ============ SkillConfig load_mode ============


def test_skill_config_default_load_mode() -> None:
    """SkillConfig.load_mode defaults to full."""
    config = SkillConfig()
    assert config.load_mode == SkillLoadMode.full


def test_skill_config_custom_load_mode() -> None:
    """SkillConfig.load_mode can be set to dynamic."""
    config = SkillConfig(load_mode=SkillLoadMode.dynamic)
    assert config.load_mode == SkillLoadMode.dynamic


def test_dynamic_mode_registers_read_skill_tool(tmp_sessions_dir: Path) -> None:
    """When load_mode is dynamic, read_skill is registered for on-demand loading."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "sk"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: S\ndescription: d\n---\n\nBody."
        )
        skill_cfg = SkillConfig(
            skill_directories=[tmpdir],
            load_mode=SkillLoadMode.dynamic,
        )
        loader = SkillLoader(skill_cfg)
        loader.load_from_directories()

        runner = AgentRunner(
            llm=_MockLLM(),
            session_manager=SessionManager(tmp_sessions_dir),
            tool_registry=ToolRegistry(),
            skill_loader=loader,
            config=RunnerConfig(skill_config=skill_cfg),
        )
        names = [t.name for t in runner.tool_registry.list_all()]
        assert "read_skill" in names
