"""
Memory System - 端到端测试 (Lifecycle Redesign)
================================================

Session JSONL (raw) → MEMORY.md (distilled) → System Prompt (consumption).

运行:
    uv run pytest tests/e2e/test_memory_e2e.py -v
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from ark_agentic.core.compaction import CompactionConfig, SimpleSummarizer
from ark_agentic.core.memory.extractor import FlushResult, MemoryFlusher
from ark_agentic.core.memory.manager import build_memory_manager
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.llm.caller import LLMCaller
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import AgentMessage, ToolCall

logger = logging.getLogger(__name__)


def _stub_chat_model() -> MagicMock:
    llm = MagicMock(name="StubChatModel")
    llm.bind_tools = MagicMock(side_effect=lambda *a, **k: llm)
    llm.model_copy = MagicMock(side_effect=lambda update=None: llm)
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="stub"))
    return llm


@pytest.fixture(scope="session", autouse=True)
def setup_logging():
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("ark_agentic").setLevel(logging.INFO)


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test_memory"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def base_sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest_asyncio.fixture
async def base_agent(memory_dir: Path, base_sessions_dir: Path):
    llm = _stub_chat_model()

    memory_manager = build_memory_manager(memory_dir)

    session_manager = SessionManager(
        compaction_config=CompactionConfig(
            context_window=128000,
            preserve_recent=4,
        ),
        sessions_dir=base_sessions_dir,
        summarizer=SimpleSummarizer(),
    )

    runner_config = RunnerConfig(
        max_turns=10,
        prompt_config=PromptConfig(
            agent_name="记忆测试助手",
            agent_description="专门用于测试长期记忆能力的助手。",
        ),
        skill_config=SkillConfig(),
    )

    runner = AgentRunner(
        llm=llm,
        tool_registry=ToolRegistry(),
        session_manager=session_manager,
        config=runner_config,
        memory_manager=memory_manager,
    )
    return runner


@pytest.mark.asyncio
async def test_compact_flush_writes_memory(
    base_agent: AgentRunner,
    memory_dir: Path,
    base_sessions_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test: context compaction triggers flush → writes to MEMORY.md."""
    tiny_compaction_config = CompactionConfig(
        context_window=200,
        preserve_recent=2,
    )
    base_agent.session_manager = SessionManager(
        compaction_config=tiny_compaction_config,
        sessions_dir=str(base_sessions_dir),
        summarizer=SimpleSummarizer(),
    )

    async def fake_flush(
        self: MemoryFlusher,
        conversation_text: str,
        current_memory: str,
        agent_name: str,
        agent_description: str,
    ) -> FlushResult:
        return FlushResult(
            memory="## 理赔记录\n用户咨询了理赔与车险相关问题。\n",
        )

    monkeypatch.setattr(MemoryFlusher, "flush", fake_flush)

    async def fake_call_llm(
        self: LLMCaller, messages: list, tools: list, **kwargs,
    ) -> AgentMessage:
        return AgentMessage.assistant(content="简要回复：理赔请咨询承保方。")

    monkeypatch.setattr(LLMCaller, "call", fake_call_llm)
    monkeypatch.setattr(LLMCaller, "call_streaming", fake_call_llm)

    user_id = "compacttest"
    session_id = await base_agent.create_session(
        user_id=user_id,
        state={"user:id": user_id},
    )

    seed_file = memory_dir / user_id / "MEMORY.md"
    seed_file.parent.mkdir(parents=True, exist_ok=True)
    seed_file.write_text("# Agent Memory\n\n", encoding="utf-8")

    for turn in [
        "你好，我想了解一下理赔流程。",
        "好的，车祸的话怎么理赔？",
        "对方逃逸怎么处理？非常急。",
    ]:
        await base_agent.run(
            session_id=session_id, user_input=turn,
            user_id=user_id, stream=False,
            input_context={"user:id": user_id},
        )

    assert seed_file.exists()
    content = seed_file.read_text(encoding="utf-8")
    assert "理赔" in content


@pytest.mark.asyncio
async def test_memory_injected_into_system_prompt(
    base_agent: AgentRunner,
    memory_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test: MEMORY.md content is injected into system prompt for every turn."""
    user_id = "prompttest"
    user_dir = memory_dir / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    mem_file = user_dir / "MEMORY.md"
    mem_file.write_text(
        "## 身份信息\n姓名：李四\n\n## 风险偏好\n保守型\n", encoding="utf-8",
    )

    captured_messages: list = []

    async def fake_call_llm(
        self: LLMCaller, messages: list, tools: list, **kwargs,
    ) -> AgentMessage:
        captured_messages.extend(messages)
        return AgentMessage.assistant(content="你好李四。")

    monkeypatch.setattr(LLMCaller, "call", fake_call_llm)
    monkeypatch.setattr(LLMCaller, "call_streaming", fake_call_llm)

    base_agent.config.auto_compact = False

    session_id = await base_agent.create_session(
        user_id=user_id,
        state={"user:id": user_id},
    )

    await base_agent.run(
        session_id=session_id, user_input="你好",
        user_id=user_id, stream=False,
        input_context={"user:id": user_id},
    )

    if not captured_messages:
        pytest.fail("No messages captured")
    first = captured_messages[0]
    system_prompt = first.get("content", "") if isinstance(first, dict) else getattr(first, "content", "")
    assert "李四" in system_prompt, "MEMORY.md content should appear in system prompt"
    assert "保守型" in system_prompt


@pytest.mark.asyncio
async def test_memory_write_tool_works_in_runner(
    base_agent: AgentRunner,
    memory_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test: Agent calls memory_write → content persists in MEMORY.md."""
    llm_round: dict[str, int] = {"n": 0}

    async def fake_call_llm(
        self: LLMCaller, messages: list, tools: list, **kwargs,
    ) -> AgentMessage:
        llm_round["n"] += 1
        if llm_round["n"] == 1:
            return AgentMessage.assistant(
                content="",
                tool_calls=[
                    ToolCall.create(
                        name="memory_write",
                        arguments={"content": "## 回复风格\n用户要求简洁回复"},
                    ),
                ],
            )
        return AgentMessage.assistant(content="好的，已记住。")

    monkeypatch.setattr(LLMCaller, "call", fake_call_llm)
    monkeypatch.setattr(LLMCaller, "call_streaming", fake_call_llm)

    base_agent.config.auto_compact = False

    user_id = "writetest"
    session_id = await base_agent.create_session(
        user_id=user_id,
        state={"user:id": user_id},
    )

    r = await base_agent.run(
        session_id=session_id, user_input="太啰嗦了，简洁点",
        user_id=user_id, stream=False,
        input_context={"user:id": user_id},
    )

    mem = memory_dir / user_id / "MEMORY.md"
    assert mem.exists()
    content = mem.read_text(encoding="utf-8")
    assert "简洁" in content

    used_write = any(tc.name == "memory_write" for tc in r.tool_calls)
    assert used_write
