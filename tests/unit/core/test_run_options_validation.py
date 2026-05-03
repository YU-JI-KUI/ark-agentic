"""Tests for RunOptions validation and Runner configuration precedence."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch
import pytest
from pydantic import ValidationError

from ark_agentic.core.llm.sampling import SamplingConfig
from ark_agentic.core.types import AgentMessage, RunOptions, SessionEntry, SkillLoadMode
from ark_agentic.core.runner import AgentRunner, RunnerConfig, RunResult
from ark_agentic.core.skills.base import SkillConfig


class TestRunOptionsValidation:
    """Test Pydantic validation for RunOptions."""

    def test_valid_options(self) -> None:
        """Test valid RunOptions creation."""
        opts = RunOptions(model="gpt-4", temperature=0.7)
        assert opts.model == "gpt-4"
        assert opts.temperature == 0.7

    def test_temperature_range_high(self) -> None:
        """Test temperature upper bound validation."""
        with pytest.raises(ValidationError) as exc:
            RunOptions(temperature=2.1)
        # Check for 'less_than_equal' error type
        assert any(e["type"] == "less_than_equal" for e in exc.value.errors())

    def test_temperature_range_low(self) -> None:
        """Test temperature lower bound validation."""
        with pytest.raises(ValidationError) as exc:
            RunOptions(temperature=-0.1)
        # Check for 'greater_than_equal' error type
        assert any(e["type"] == "greater_than_equal" for e in exc.value.errors())


class TestRunnerConfigurationPrecedence:
    """Test AgentRunner configuration precedence logic."""

    @pytest.fixture
    def runner(self) -> AgentRunner:
        """Create a runner with known default config."""
        config = RunnerConfig(
            model="default-model",
            sampling=SamplingConfig.for_chat(temperature=0.5),
            skill_config=SkillConfig(load_mode=SkillLoadMode.full),
        )
        
        # Mock ALL required dependencies
        runner = AgentRunner(
            llm=Mock(),
            session_manager=Mock(),
            tool_registry=Mock(),
            config=config
        )
        
        runner._run_loop = AsyncMock(
            return_value=RunResult(response=AgentMessage.assistant("mock")),
        )  # type: ignore

        runner.session_manager.get_session_required = Mock(
            side_effect=lambda sid: SessionEntry(session_id=sid, user_id="test_user"),
        )
        
        # Mock session manager sync methods used in run()
        runner.session_manager.add_message_sync = Mock()
        runner.session_manager.add_message = AsyncMock()
        runner.session_manager.auto_compact_if_needed = AsyncMock()
        runner.session_manager.sync_pending_messages = AsyncMock()
        runner.session_manager.sync_session_state = AsyncMock()
        runner.session_manager.finalize_session = AsyncMock()
        
        # Prevent lazy init from failing
        runner._memory_manager = None 
        
        return runner

    @pytest.mark.asyncio
    async def test_run_options_override(self, runner: AgentRunner) -> None:
        """Test that run_options overrides config defaults."""
        run_opts = RunOptions(model="override-model", temperature=0.1)
        
        await runner.run(
            session_id="test-session",
            user_input="hello",
            user_id="test_user",
            run_options=run_opts
        )
        
        call_args = runner._run_loop.call_args
        assert call_args is not None
        _, kwargs = call_args
        assert kwargs["model_override"] == "override-model"
        assert kwargs["sampling_override"] is not None
        assert kwargs["sampling_override"].temperature == 0.1

    @pytest.mark.asyncio
    async def test_run_options_partial_override(self, runner: AgentRunner) -> None:
        """Test partial override (only model)."""
        run_opts = RunOptions(model="override-model")
        
        await runner.run(
            session_id="test-session",
            user_input="hello",
            user_id="test_user",
            run_options=run_opts
        )
        
        _, kwargs = runner._run_loop.call_args
        assert kwargs["model_override"] == "override-model"
        assert kwargs["sampling_override"] is None

    @pytest.mark.asyncio
    async def test_no_options_uses_defaults(self, runner: AgentRunner) -> None:
        """Test behavior when run_options is None."""
        await runner.run(
            session_id="test-session",
            user_input="hello",
            user_id="test_user",
            run_options=None
        )
        
        _, kwargs = runner._run_loop.call_args
        assert kwargs["model_override"] == "default-model"
        assert kwargs["sampling_override"] is None

    @pytest.mark.asyncio
    async def test_skill_load_mode_precedence(self, runner: AgentRunner) -> None:
        """Test skill_load_mode comes from config only (no run_options, no env)."""
        # 1. Config default "full"
        await runner.run(session_id="s1", user_input="hi", user_id="test_user")
        _, kwargs = runner._run_loop.call_args
        assert kwargs["skill_load_mode"] == "full"

        # 2. Config "dynamic"
        runner.config.skill_config.load_mode = SkillLoadMode.dynamic
        await runner.run(session_id="s2", user_input="hi", user_id="test_user", run_options=RunOptions(model="foo"))
        _, kwargs = runner._run_loop.call_args
        assert kwargs["skill_load_mode"] == "dynamic"

    @pytest.mark.asyncio
    async def test_skill_load_mode_ignores_env(self, runner: AgentRunner) -> None:
        """Test that skill_load_mode is taken from config only (env has no effect)."""
        runner.config.skill_config.load_mode = SkillLoadMode.full
        with patch.dict("os.environ", {"ARK_SKILL_LOAD_MODE": "dynamic"}, clear=False):
            await runner.run(session_id="s1", user_input="hi", user_id="test_user")
        _, kwargs = runner._run_loop.call_args
        assert kwargs["skill_load_mode"] == "full"
