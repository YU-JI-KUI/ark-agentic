"""Tests for runner skill_load_mode (full / dynamic) and RunOptions wiring."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import (
    AgentMessage,
    AgentToolResult,
    MessageRole,
    SkillLoadMode,
    ToolCall,
)


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


def test_dynamic_renders_available_skills_menu_only(
    runner_with_one_skill_dynamic,
) -> None:
    """dynamic mode: <available_skills> menu shown, full body hidden, no
    mandatory protocol section (the router — wired by the factory — owns
    pre-loop activation; this prompt path stays uniform across all dynamic
    sub-flows)."""
    runner, session_id = runner_with_one_skill_dynamic
    prompt = runner._build_system_prompt(
        {}, session_id=session_id, skill_load_mode="dynamic"
    )
    assert "<available_skills>" in prompt
    assert "Test Skill" in prompt
    assert "When testing" in prompt
    assert "Full skill body here." not in prompt
    assert "<skill_loading_protocol>" not in prompt
    assert "mandatory" not in prompt


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


# ============ full mode SSOT bootstrap ============


class _StubLLM:
    """Minimal BaseChatModel-compatible stub for runner.run() tests."""

    model = "stub-model"
    temperature = 0.5
    top_p = 0.9

    def bind_tools(self, tools: list[Any], **kw: Any) -> "_StubLLM":
        return self

    def model_copy(self, update: dict[str, Any] | None = None) -> "_StubLLM":
        return self

    async def ainvoke(self, messages: list[Any], **kw: Any):
        from langchain_core.messages import AIMessage
        return AIMessage(content="ok")

    async def astream(self, messages: list[Any], **kw: Any):
        if False:  # pragma: no cover
            yield None


@pytest.mark.asyncio
async def test_full_mode_bootstraps_active_skill_ids_each_turn(
    tmp_sessions_dir: Path,
) -> None:
    """full mode: _run_turn writes session.active_skill_ids = all loaded skill ids,
    clobbering any pre-existing value (including external API overrides).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        for sid in ("s1", "s2"):
            d = Path(tmpdir) / sid
            d.mkdir()
            (d / "SKILL.md").write_text(
                f"---\nname: Skill {sid}\ndescription: d\n---\n\nBody."
            )
        skill_cfg = SkillConfig(skill_directories=[tmpdir], load_mode=SkillLoadMode.full)
        loader = SkillLoader(skill_cfg)
        loader.load_from_directories()

        sm = SessionManager(tmp_sessions_dir)
        session = await sm.create_session(user_id="u1")
        sm.set_active_skill_ids(session.session_id, ["pre-existing"])

        runner = AgentRunner(
            llm=_StubLLM(),  # type: ignore[arg-type]
            session_manager=sm,
            tool_registry=ToolRegistry(),
            skill_loader=loader,
            config=RunnerConfig(skill_config=skill_cfg, max_turns=2, auto_compact=False),
        )
        await runner.run(
            session_id=session.session_id,
            user_input="hi",
            user_id="u1",
            stream=False,
        )
        assert sorted(session.active_skill_ids) == ["s1", "s2"]


@pytest.mark.asyncio
async def test_dynamic_mode_does_not_bootstrap_active_skill_ids(
    tmp_sessions_dir: Path,
) -> None:
    """dynamic mode: _run_turn does NOT auto-populate active_skill_ids
    (router owns activation; absent router → list stays empty)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir) / "sk"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: S\ndescription: d\n---\n\nBody.")
        skill_cfg = SkillConfig(
            skill_directories=[tmpdir], load_mode=SkillLoadMode.dynamic
        )
        loader = SkillLoader(skill_cfg)
        loader.load_from_directories()

        sm = SessionManager(tmp_sessions_dir)
        session = await sm.create_session(user_id="u1")

        runner = AgentRunner(
            llm=_StubLLM(),  # type: ignore[arg-type]
            session_manager=sm,
            tool_registry=ToolRegistry(),
            skill_loader=loader,
            config=RunnerConfig(skill_config=skill_cfg, max_turns=2, auto_compact=False),
        )
        await runner.run(
            session_id=session.session_id,
            user_input="hi",
            user_id="u1",
            stream=False,
        )
        assert session.active_skill_ids == []


# ============ active_skill injection (Skill 一等公民) ============


class _AutoEchoTool(AgentTool):
    """visibility=auto 的占位工具，用于验证 dynamic 模式下的 gating 行为。"""

    name = "echo_auto"
    description = "Echo back the input (auto-visibility test tool)."
    visibility = "auto"
    parameters = [
        ToolParameter(name="text", type="string", description="text to echo"),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        return AgentToolResult.text_result(
            tool_call.id, str((tool_call.arguments or {}).get("text", "")),
        )


def _make_runner_with_two_skills(tmp_sessions_dir: Path):
    """两个 dynamic skill + 一个 auto 工具，用于验证激活/切换与工具 gating。"""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_a = Path(tmpdir) / "skill_a"
            skill_a.mkdir()
            (skill_a / "SKILL.md").write_text(
                "---\n"
                "name: Skill A\n"
                "description: alpha\n"
                "when_to_use: For alpha\n"
                "required_tools: [echo_auto]\n"
                "---\n\n"
                "ALPHA_BODY_MARKER"
            )

            skill_b = Path(tmpdir) / "skill_b"
            skill_b.mkdir()
            (skill_b / "SKILL.md").write_text(
                "---\n"
                "name: Skill B\n"
                "description: beta\n"
                "when_to_use: For beta\n"
                "---\n\n"
                "BETA_BODY_MARKER"
            )

            skill_cfg = SkillConfig(
                skill_directories=[tmpdir], load_mode=SkillLoadMode.dynamic,
            )
            loader = SkillLoader(skill_cfg)
            loader.load_from_directories()

            registry = ToolRegistry()
            registry.register(_AutoEchoTool())

            session_manager = SessionManager(tmp_sessions_dir)
            session = session_manager.create_session_sync()
            session_id = session.session_id
            session_manager.add_message_sync(
                session_id, AgentMessage.user("Hi", metadata={}),
            )

            runner = AgentRunner(
                llm=_MockLLM(),
                session_manager=session_manager,
                tool_registry=registry,
                skill_loader=loader,
                config=RunnerConfig(skill_config=skill_cfg),
            )
            yield runner, session_id

    return _ctx()


def test_dynamic_active_skill_injects_body_and_gates_tools(
    tmp_sessions_dir: Path,
) -> None:
    """激活 skill_a 后: prompt 含 <active_skill id="skill_a"> + ALPHA 正文;
    auto 工具 echo_auto 因 required_tools 匹配而可见（原先只有 always 的 read_skill）。
    """
    with _make_runner_with_two_skills(tmp_sessions_dir) as (runner, session_id):
        session = runner.session_manager.get_session_required(session_id)
        # 未激活: 正文不进 prompt, echo_auto 不可见
        prompt_none = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="dynamic", session=session,
        )
        assert "ALPHA_BODY_MARKER" not in prompt_none
        assert "<active_skill" not in prompt_none
        tools_none = {t.name for t in runner._filter_tools({}, session=session)}
        assert "read_skill" in tools_none
        assert "echo_auto" not in tools_none

        # 激活 skill_a: 正文注入 + auto 工具解锁
        session.set_active_skill_ids(["skill_a"])
        prompt_a = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="dynamic", session=session,
        )
        assert "<active_skill" in prompt_a
        assert 'id="skill_a"' in prompt_a
        assert "ALPHA_BODY_MARKER" in prompt_a
        assert "BETA_BODY_MARKER" not in prompt_a
        tools_a = {t.name for t in runner._filter_tools({}, session=session)}
        assert "echo_auto" in tools_a
        assert "read_skill" in tools_a


def test_dynamic_active_skill_switch_replaces_body(tmp_sessions_dir: Path) -> None:
    """切换 active_skill_ids: 旧 skill 正文退出上下文，新 skill 正文就位。"""
    with _make_runner_with_two_skills(tmp_sessions_dir) as (runner, session_id):
        session = runner.session_manager.get_session_required(session_id)
        session.set_active_skill_ids(["skill_a"])
        prompt_a = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="dynamic", session=session,
        )
        session.set_active_skill_ids(["skill_b"])
        prompt_b = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="dynamic", session=session,
        )
        assert "ALPHA_BODY_MARKER" in prompt_a
        assert "BETA_BODY_MARKER" not in prompt_a
        assert "BETA_BODY_MARKER" in prompt_b
        assert "ALPHA_BODY_MARKER" not in prompt_b
        assert 'id="skill_b"' in prompt_b


def test_filter_tools_and_build_tools_are_consistent(
    tmp_sessions_dir: Path,
) -> None:
    """_build_tools 必须是 _filter_tools 的薄包装: 两者工具集永远一致（单一事实源）。"""
    with _make_runner_with_two_skills(tmp_sessions_dir) as (runner, session_id):
        session = runner.session_manager.get_session_required(session_id)
        for active_ids in ([], ["skill_a"], ["skill_b"]):
            session.set_active_skill_ids(active_ids)
            filtered = {t.name for t in runner._filter_tools({}, session=session)}
            schema_names = {
                t["function"]["name"]
                for t in runner._build_tools({}, session=session)
            }
            assert filtered == schema_names, f"mismatch at active={active_ids}"


def test_dynamic_unknown_active_skill_id_is_safe(tmp_sessions_dir: Path) -> None:
    """active_skill_ids 末元素未知时: 不抛错, 无 <active_skill> 段。"""
    with _make_runner_with_two_skills(tmp_sessions_dir) as (runner, session_id):
        session = runner.session_manager.get_session_required(session_id)
        session.set_active_skill_ids(["ghost_skill"])
        prompt = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="dynamic", session=session,
        )
        assert "<active_skill" not in prompt
        tools = {t.name for t in runner._filter_tools({}, session=session)}
        assert "echo_auto" not in tools  # 未知 id => allowed=空 => auto 工具不放行


def test_dynamic_active_skill_cleared_unloads_body_and_tools(
    tmp_sessions_dir: Path,
) -> None:
    """卸载: 从已激活回到 active_skill_ids=[] — <active_skill> 与 skill 专属 auto 工具一并消失。"""
    with _make_runner_with_two_skills(tmp_sessions_dir) as (runner, session_id):
        session = runner.session_manager.get_session_required(session_id)
        session.set_active_skill_ids(["skill_a"])
        prompt_on = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="dynamic", session=session,
        )
        assert "ALPHA_BODY_MARKER" in prompt_on
        assert "echo_auto" in {t.name for t in runner._filter_tools({}, session=session)}

        session.set_active_skill_ids([])
        prompt_off = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="dynamic", session=session,
        )
        assert "<active_skill" not in prompt_off
        assert "ALPHA_BODY_MARKER" not in prompt_off
        assert "echo_auto" not in {t.name for t in runner._filter_tools({}, session=session)}


def test_multi_turn_active_skill_evolution_then_prompt_and_tools(
    tmp_sessions_dir: Path,
) -> None:
    """多轮: 通过 set_active_skill_ids 演进 SSOT 后，下一轮 _build_system_prompt /
    _filter_tools 读取 session.active_skill_ids 演进正确（state_delta 通道已不再承载）。
    """
    with _make_runner_with_two_skills(tmp_sessions_dir) as (runner, session_id):
        session = runner.session_manager.get_session_required(session_id)

        # Turn 0 — 无激活
        p0 = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="dynamic", session=session,
        )
        assert "<active_skill" not in p0
        assert "echo_auto" not in {t.name for t in runner._filter_tools({}, session=session)}

        # Turn 1 — 激活 skill_a（等同 read_skill 调用后 SSOT 写入）
        session.set_active_skill_ids(["skill_a"])
        p1 = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="dynamic", session=session,
        )
        assert "ALPHA_BODY_MARKER" in p1
        assert "echo_auto" in {t.name for t in runner._filter_tools({}, session=session)}

        # Turn 2 — 切换 skill_b（无 required_tools => echo_auto 重新门控掉）
        session.set_active_skill_ids(["skill_b"])
        p2 = runner._build_system_prompt(
            {}, session_id=session_id, skill_load_mode="dynamic", session=session,
        )
        assert "BETA_BODY_MARKER" in p2
        assert "ALPHA_BODY_MARKER" not in p2
        assert "echo_auto" not in {t.name for t in runner._filter_tools({}, session=session)}
