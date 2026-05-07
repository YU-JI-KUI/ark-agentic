"""Tests for _build_tools skill-aware tool filtering (dynamic mode)."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ark_agentic.core.runtime._runner_helpers import filter_visible_tools
from ark_agentic.core.runtime.base_agent import BaseAgent, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import (
    AgentToolResult,
    SessionEntry,
    SkillEntry,
    SkillLoadMode,
    SkillMetadata,
    ToolCall,
)


def _session_with_active(skill_ids: list[str]) -> SessionEntry:
    s = SessionEntry.create()
    s.active_skill_ids = list(skill_ids)
    return s


# ── helpers ──────────────────────────────────────────────────────────────────

class _Tool(AgentTool):
    """Minimal no-param tool for testing."""

    name = "base"
    description = "base"
    parameters: list[ToolParameter] = []

    def __init__(self, name: str, *, always: bool = False) -> None:
        self.name = name
        self.description = name
        self.parameters = []
        if always:
            self.visibility = "always"

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        return AgentToolResult.text_result(tool_call.id, "ok")


def _make_skill(skill_id: str, required_tools: list[str] | None = None) -> SkillEntry:
    return SkillEntry(
        id=skill_id,
        path=f"/skills/{skill_id}",
        content="",
        metadata=SkillMetadata(
            name=skill_id,
            description=skill_id,
            required_tools=required_tools,
        ),
    )


def _make_runner(
    tmp_path: Path,
    tools: list[AgentTool],
    all_skills: list[SkillEntry] | None = None,
    load_mode: SkillLoadMode = SkillLoadMode.dynamic,
) -> BaseAgent:
    mock_llm = MagicMock()
    registry = ToolRegistry()
    for t in tools:
        registry.register(t)

    skill_loader = None
    if all_skills is not None:
        skill_loader = MagicMock()
        skill_loader.list_skills.return_value = all_skills
        skill_loader.get_skill.side_effect = lambda sid: next(
            (s for s in all_skills if s.id == sid), None
        )

    skill_config = SkillConfig(load_mode=load_mode)
    runner = BaseAgent._construct(
        llm=mock_llm,
        tool_registry=registry,
        session_manager=SessionManager(tmp_path, agent_id="test"),
        config=RunnerConfig(max_turns=1, auto_compact=False, skill_config=skill_config),
        skill_loader=skill_loader,
    )
    return runner


# ── tests ─────────────────────────────────────────────────────────────────────

class TestBuildToolsFullMode:

    def test_full_mode_returns_all_tools(self, tmp_path: Path) -> None:
        """full 模式不过滤，全部返回。"""
        all_skills = [_make_skill("s1", required_tools=["tool_a"])]
        runner = _make_runner(
            tmp_path,
            [_Tool("tool_a"), _Tool("tool_b"), _Tool("read_skill", always=True)],
            all_skills=all_skills,
            load_mode=SkillLoadMode.full,
        )
        schemas = [t.get_json_schema() for t in filter_visible_tools(runner.tool_registry, runner.skill_loader, runner.config.skill_config.load_mode, _session_with_active(["s1"]))]
        names = {s["function"]["name"] for s in schemas}
        assert names == {"tool_a", "tool_b", "read_skill"}

    def test_full_mode_no_state_returns_all(self, tmp_path: Path) -> None:
        runner = _make_runner(
            tmp_path,
            [_Tool("tool_a"), _Tool("tool_b")],
            load_mode=SkillLoadMode.full,
        )
        schemas = [t.get_json_schema() for t in filter_visible_tools(runner.tool_registry, runner.skill_loader, runner.config.skill_config.load_mode, None)]
        names = {s["function"]["name"] for s in schemas}
        assert names == {"tool_a", "tool_b"}


class TestBuildToolsDynamicMode:
    """
    BaseAgent 在 dynamic 模式下会自动注册 ReadSkillTool（visibility=always）。
    测试工具列表里不要重复传 read_skill，让 runner 自行注册。
    """

    def test_no_state_returns_only_always_tools(self, tmp_path: Path) -> None:
        """dynamic 模式，session.active_skill_ids 为空：只暴露 always 工具。"""
        all_skills = [_make_skill("s1", required_tools=["business_tool"])]
        runner = _make_runner(
            tmp_path,
            [_Tool("business_tool")],
            all_skills=all_skills,
        )
        schemas = [t.get_json_schema() for t in filter_visible_tools(runner.tool_registry, runner.skill_loader, runner.config.skill_config.load_mode, _session_with_active([]))]
        names = {s["function"]["name"] for s in schemas}
        assert "read_skill" in names  # auto-registered by runner
        assert "business_tool" not in names

    def test_none_session_returns_only_always_tools(self, tmp_path: Path) -> None:
        """session=None 时降级为只返回 always 工具。"""
        all_skills = [_make_skill("s1", required_tools=["business_tool"])]
        runner = _make_runner(
            tmp_path,
            [_Tool("business_tool")],
            all_skills=all_skills,
        )
        schemas = [t.get_json_schema() for t in filter_visible_tools(runner.tool_registry, runner.skill_loader, runner.config.skill_config.load_mode, None)]
        names = {s["function"]["name"] for s in schemas}
        assert "read_skill" in names
        assert "business_tool" not in names

    def test_active_skill_exposes_its_tools(self, tmp_path: Path) -> None:
        """active_skill_ids[-1]=s1，s1 的工具被暴露，s2 的工具不暴露。"""
        all_skills = [
            _make_skill("s1", required_tools=["tool_a", "tool_b"]),
            _make_skill("s2", required_tools=["tool_c"]),
        ]
        runner = _make_runner(
            tmp_path,
            [_Tool("tool_a"), _Tool("tool_b"), _Tool("tool_c")],
            all_skills=all_skills,
        )
        schemas = [t.get_json_schema() for t in filter_visible_tools(runner.tool_registry, runner.skill_loader, runner.config.skill_config.load_mode, _session_with_active(["s1"]))]
        names = {s["function"]["name"] for s in schemas}
        assert "read_skill" in names
        assert "tool_a" in names
        assert "tool_b" in names
        assert "tool_c" not in names

    def test_newest_wins_when_multiple_active(self, tmp_path: Path) -> None:
        """active_skill_ids 多元素时取末元素（newest-wins）。"""
        all_skills = [
            _make_skill("s1", required_tools=["tool_a"]),
            _make_skill("s2", required_tools=["tool_b"]),
        ]
        runner = _make_runner(
            tmp_path,
            [_Tool("tool_a"), _Tool("tool_b")],
            all_skills=all_skills,
        )
        # 末元素 s2 → tool_b 暴露，tool_a 不暴露
        schemas = [t.get_json_schema() for t in filter_visible_tools(runner.tool_registry, runner.skill_loader, runner.config.skill_config.load_mode, _session_with_active(["s1", "s2"]))]
        names = {s["function"]["name"] for s in schemas}
        assert "tool_b" in names
        assert "tool_a" not in names

    def test_always_tools_never_excluded(self, tmp_path: Path) -> None:
        """always 工具无论技能状态都存在。"""
        all_skills = [_make_skill("s1", required_tools=["biz_tool"])]
        runner = _make_runner(
            tmp_path,
            [_Tool("memory_write", always=True), _Tool("biz_tool")],
            all_skills=all_skills,
        )
        for active_ids in [[], ["s1"], ["unknown"]]:
            session = _session_with_active(active_ids)
            schemas = [t.get_json_schema() for t in filter_visible_tools(runner.tool_registry, runner.skill_loader, runner.config.skill_config.load_mode, session)]
            names = {s["function"]["name"] for s in schemas}
            assert "read_skill" in names, f"read_skill missing for active={active_ids}"
            assert "memory_write" in names, f"memory_write missing for active={active_ids}"

    def test_unknown_skill_id_returns_always_only(self, tmp_path: Path) -> None:
        """skill_id 在 loader 中不存在时，降级为只返回 always 工具。"""
        all_skills = [_make_skill("s1", required_tools=["biz_tool"])]
        runner = _make_runner(
            tmp_path,
            [_Tool("biz_tool")],
            all_skills=all_skills,
        )
        schemas = [t.get_json_schema() for t in filter_visible_tools(runner.tool_registry, runner.skill_loader, runner.config.skill_config.load_mode, _session_with_active(["nonexistent"]))]
        names = {s["function"]["name"] for s in schemas}
        assert "read_skill" in names
        assert "biz_tool" not in names


class TestInsuranceScenario:

    def _make_insurance_runner(self, tmp_path: Path) -> BaseAgent:
        withdraw = _make_skill(
            "insurance.withdraw_money",
            required_tools=["customer_info", "rule_engine", "render_a2ui"],
        )
        execute = _make_skill(
            "insurance.execute_withdrawal",
            required_tools=["submit_withdrawal"],
        )
        tools = [
            _Tool("memory_write", always=True),
            _Tool("customer_info"),
            _Tool("rule_engine"),
            _Tool("render_a2ui"),
            _Tool("submit_withdrawal"),
        ]
        return _make_runner(tmp_path, tools, all_skills=[withdraw, execute])

    def test_withdraw_money_active(self, tmp_path: Path) -> None:
        """withdraw_money 加载后: render_a2ui 可见，submit_withdrawal 不可见。"""
        runner = self._make_insurance_runner(tmp_path)
        schemas = [
            t.get_json_schema()
            for t in filter_visible_tools(
                runner.tool_registry, runner.skill_loader,
                runner.config.skill_config.load_mode,
                _session_with_active(["insurance.withdraw_money"]),
            )
        ]
        names = {s["function"]["name"] for s in schemas}

        assert "render_a2ui" in names
        assert "customer_info" in names
        assert "rule_engine" in names
        assert "submit_withdrawal" not in names
        assert "read_skill" in names
        assert "memory_write" in names

    def test_execute_withdrawal_active(self, tmp_path: Path) -> None:
        """execute_withdrawal 加载后: submit_withdrawal 可见，render_a2ui 不可见。"""
        runner = self._make_insurance_runner(tmp_path)
        schemas = [
            t.get_json_schema()
            for t in filter_visible_tools(
                runner.tool_registry, runner.skill_loader,
                runner.config.skill_config.load_mode,
                _session_with_active(["insurance.execute_withdrawal"]),
            )
        ]
        names = {s["function"]["name"] for s in schemas}

        assert "submit_withdrawal" in names
        assert "render_a2ui" not in names
        assert "customer_info" not in names
        assert "rule_engine" not in names
        assert "read_skill" in names
        assert "memory_write" in names

    def test_no_skill_loaded_shows_only_framework_tools(self, tmp_path: Path) -> None:
        """未加载任何技能时 LLM 只能调框架工具。"""
        runner = self._make_insurance_runner(tmp_path)
        schemas = [t.get_json_schema() for t in filter_visible_tools(runner.tool_registry, runner.skill_loader, runner.config.skill_config.load_mode, _session_with_active([]))]
        names = {s["function"]["name"] for s in schemas}

        assert "read_skill" in names
        assert "memory_write" in names
        assert "customer_info" not in names
        assert "render_a2ui" not in names
        assert "submit_withdrawal" not in names
