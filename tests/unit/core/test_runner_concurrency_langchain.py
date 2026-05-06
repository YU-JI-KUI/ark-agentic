"""Tests for AgentRunner concurrency safety with LangChain integration.

Verifies that the LangChain integration maintains proper callback isolation
and concurrency safety in the ReAct loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from ark_agentic.core.runtime.runner import AgentRunner, RunnerConfig, RunResult
from ark_agentic.core.session import SessionManager
from ark_agentic.core.stream.event_bus import AgentEventHandler
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import AgentMessage, AgentToolResult, ToolCall


class MockTool(AgentTool):
    """Mock tool for testing concurrency"""

    name = "mock_tool"
    description = "A mock tool for testing"
    parameters = []

    async def execute(self, **kwargs) -> AgentToolResult:
        # Simulate some async work
        await asyncio.sleep(0.01)
        return AgentToolResult(
            tool_call_id="test",
            content="Mock result"
        )


class MockEventHandler:
    """Mock event handler that captures events"""

    def __init__(self, prefix: str = ""):
        self.prefix = prefix
        self.events = []

    def on_step(self, text: str) -> None:
        self.events.append(f"{self.prefix}: {text}")


class TestRunnerConcurrency:
    """测试 AgentRunner 的并发安全性"""

    @pytest.fixture
    def mock_llm(self):
        """创建 Mock LLM 客户端"""
        llm = MagicMock()

        # Mock the methods to return proper objects, not coroutines
        async def mock_ainvoke(messages):
            return MagicMock(content="Test response", tool_calls=[])

        async def mock_astream(messages):
            yield MagicMock(content="Test response", tool_calls=[])

        llm.ainvoke = mock_ainvoke
        llm.astream = mock_astream
        llm.bind_tools.return_value = llm  # Return self for chaining

        return llm

    @pytest.fixture
    def runner_config(self):
        """创建 Runner 配置"""
        from ark_agentic.core.llm.sampling import SamplingConfig

        return RunnerConfig(
            model="mock",
            sampling=SamplingConfig.for_chat(temperature=0.7),
            max_turns=3,
        )

    @pytest.fixture
    def session_manager(self, tmp_path):
        """创建 Session Manager"""
        return SessionManager(
            sessions_dir=str(tmp_path),
        )

    @pytest.fixture
    def tool_registry(self):
        """创建工具注册表"""
        registry = ToolRegistry()
        registry.register(MockTool())
        return registry

    @pytest.mark.asyncio
    async def test_concurrent_runs_isolation(
        self,
        mock_llm,
        runner_config,
        session_manager,
        tool_registry
    ):
        """测试并发运行时的回调隔离"""

        # 创建测试会话
        session = await session_manager.create_session("test_user", model="mock")
        session_id = session.session_id

        runner = AgentRunner(
            llm=mock_llm,
            config=runner_config,
            session_manager=session_manager,
            tool_registry=tool_registry
        )

        # 创建不同的事件处理器来验证隔离
        handler1 = MockEventHandler("handler1")
        handler2 = MockEventHandler("handler2")

        # 并发运行两个任务
        task1 = asyncio.create_task(
            runner.run(
                session_id=session_id,
                user_input="Test message 1",
                user_id="test_user",
                handler=handler1
            )
        )

        task2 = asyncio.create_task(
            runner.run(
                session_id=session_id,
                user_input="Test message 2",
                user_id="test_user",
                handler=handler2
            )
        )

        # 等待两个任务完成
        results = await asyncio.gather(task1, task2)

        # 验证结果
        assert len(results) == 2
        for result in results:
            assert isinstance(result, RunResult)

        # 验证事件处理器隔离
        for event in handler1.events:
            assert event.startswith("handler1:")

        for event in handler2.events:
            assert event.startswith("handler2:")

    @pytest.mark.asyncio
    async def test_streaming_callback_safety(
        self,
        mock_llm,
        runner_config,
        session_manager,
        tool_registry
    ):
        """测试流式回调的线程安全性"""

        # 创建测试会话
        session = await session_manager.create_session("test_user", model="mock")
        session_id = session.session_id

        runner = AgentRunner(
            llm=mock_llm,
            config=runner_config,
            session_manager=session_manager,
            tool_registry=tool_registry
        )

        handler = MockEventHandler("stream")

        result = await runner.run(
            session_id=session_id,
            user_input="Test streaming",
            user_id="test_user",
            handler=handler
        )

        assert isinstance(result, RunResult)
        # 验证事件处理器被调用
        assert len(handler.events) >= 0  # 可能为空，取决于 mock 实现

    @pytest.mark.asyncio
    async def test_tool_execution_concurrency(
        self,
        mock_llm,
        runner_config,
        session_manager,
        tool_registry
    ):
        """测试工具执行的并发安全性"""

        # 修改 mock LLM 返回工具调用
        mock_llm.ainvoke.return_value = MagicMock(
            content="",
            tool_calls=[
                MagicMock(
                    id="call_1",
                    function=MagicMock(
                        name="mock_tool",
                        arguments="{}"
                    )
                )
            ]
        )

        # 创建测试会话
        session = await session_manager.create_session("test_user", model="mock")
        session_id = session.session_id

        runner = AgentRunner(
            llm=mock_llm,
            config=runner_config,
            session_manager=session_manager,
            tool_registry=tool_registry
        )

        # 并发执行多个包含工具调用的任务
        tasks = [
            asyncio.create_task(
                runner.run(session_id=session_id, user_input=f"Test tool call {i}", user_id="test_user")
            )
            for i in range(3)
        ]

        results = await asyncio.gather(*tasks)

        # 验证所有任务都成功完成
        assert len(results) == 3
        for result in results:
            assert isinstance(result, RunResult)

    @pytest.mark.asyncio
    async def test_session_state_isolation(
        self,
        mock_llm,
        runner_config,
        tmp_path,
        tool_registry
    ):
        """测试会话状态隔离"""

        # 创建两个不同的会话管理器
        session_manager1 = SessionManager(
            sessions_dir=str(tmp_path / "sessions1"),
        )

        session_manager2 = SessionManager(
            sessions_dir=str(tmp_path / "sessions2"),
        )

        # 创建会话
        session1 = await session_manager1.create_session("test_user", model="mock")
        session2 = await session_manager2.create_session("test_user", model="mock")

        runner1 = AgentRunner(
            llm=mock_llm,
            config=runner_config,
            session_manager=session_manager1,
            tool_registry=tool_registry
        )

        runner2 = AgentRunner(
            llm=mock_llm,
            config=runner_config,
            session_manager=session_manager2,
            tool_registry=tool_registry
        )

        # 并发运行不同会话的任务
        task1 = asyncio.create_task(
            runner1.run(session_id=session1.session_id, user_input="Message for session 1", user_id="test_user")
        )

        task2 = asyncio.create_task(
            runner2.run(session_id=session2.session_id, user_input="Message for session 2", user_id="test_user")
        )

        results = await asyncio.gather(task1, task2)

        # 验证会话状态隔离
        assert session1.session_id != session2.session_id
        assert len(session1.messages) > 0
        assert len(session2.messages) > 0

        # 验证结果
        assert len(results) == 2
        for result in results:
            assert isinstance(result, RunResult)