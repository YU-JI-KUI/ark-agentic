"""证券智能体 before_complete 事实校验回调 — 单元测试"""

from __future__ import annotations

from pathlib import Path

import pytest

from ark_agentic.core.callbacks import CallbackContext
from ark_agentic.core.types import AgentMessage, AgentToolResult, SessionEntry, ToolCall
from ark_agentic.core.validation import EntityTrie, create_citation_validation_hook


def _inject_tool_turn(
    session: SessionEntry,
    tool_call_id: str,
    tool_name: str,
    result_content: dict | list | str,
) -> None:
    """向 session 注入一组 ASSISTANT(tool_calls) + TOOL(tool_results) 消息。"""
    tc = ToolCall(id=tool_call_id, name=tool_name, arguments={})
    session.add_message(AgentMessage.assistant(tool_calls=[tc]))
    tr = AgentToolResult.json_result(tool_call_id, result_content) if isinstance(result_content, (dict, list)) else AgentToolResult(tool_call_id=tool_call_id, content=result_content)
    session.add_message(AgentMessage.tool([tr]))


@pytest.fixture
def csv_path(tmp_path: Path) -> Path:
    csv_file = tmp_path / "a_shares.csv"
    csv_file.write_text(
        "code,name,exchange\n000001,平安银行,SZ\n600036,招商银行,SH\n",
        encoding="utf-8",
    )
    return csv_file


@pytest.fixture
def trie(csv_path: Path) -> EntityTrie:
    entity_trie = EntityTrie()
    entity_trie.load_from_csv(csv_path)
    return entity_trie


@pytest.fixture
def mock_session() -> SessionEntry:
    return SessionEntry(session_id="test_session", messages=[], state={})


@pytest.mark.asyncio
async def test_grounded_answer_passes(
    trie: EntityTrie,
    mock_session: SessionEntry,
) -> None:
    mock_session.add_message(AgentMessage.user("看看平安银行"))
    _inject_tool_turn(mock_session, "call_sd1", "security_detail", {"stock_name": "平安银行", "market_value": 150000})
    cb = create_citation_validation_hook(entity_trie=trie)
    ctx = CallbackContext(
        user_input="看看平安银行",
        input_context={},
        session=mock_session,
    )
    response = AgentMessage.assistant(content="平安银行市值 150000 元")

    result = await cb(ctx, response=response)
    assert result is None


@pytest.mark.asyncio
async def test_ungrounded_answer_requests_retry(
    trie: EntityTrie,
    mock_session: SessionEntry,
) -> None:
    mock_session.add_message(AgentMessage.user("看看平安银行"))
    _inject_tool_turn(mock_session, "call_sd1", "security_detail", {"stock_name": "平安银行", "market_value": 150000})
    cb = create_citation_validation_hook(entity_trie=trie)
    ctx = CallbackContext(
        user_input="看看平安银行",
        input_context={},
        session=mock_session,
    )
    response = AgentMessage.assistant(
        content="招商银行市值 200000 元，截至 2026-04-01 收益 300000 元"
    )

    result = await cb(ctx, response=response)
    assert result is not None
    assert result.halt is True
    assert result.response is not None
    assert result.response.role.value == "user"
    assert "回答事实出现偏差" in (result.response.content or "")
    assert "UNGROUNDED" in (result.response.content or "")


@pytest.mark.asyncio
async def test_second_before_complete_skips_validation_after_reflect(
    trie: EntityTrie,
    mock_session: SessionEntry,
) -> None:
    """每用户轮仅允许一次校验反思；第二次 before_complete 不再跑 grounding。"""
    mock_session.add_message(AgentMessage.user("看看平安银行"))
    _inject_tool_turn(mock_session, "call_sd1", "security_detail", {"stock_name": "平安银行", "market_value": 150000})
    cb = create_citation_validation_hook(entity_trie=trie)
    ctx = CallbackContext(
        user_input="看看平安银行",
        input_context={},
        session=mock_session,
    )
    bad = AgentMessage.assistant(
        content="招商银行市值 200000 元，截至 2026-04-01 收益 300000 元"
    )
    first = await cb(ctx, response=bad)
    assert first is not None and first.halt
    assert mock_session.state.get("temp:grounding_reflect_used") is True

    still_bad = AgentMessage.assistant(
        content="招商银行市值 200000 元，截至 2026-04-01 收益 300000 元"
    )
    second = await cb(ctx, response=still_bad)
    assert second is None


@pytest.mark.asyncio
async def test_warn_route_does_not_halt(mock_session: SessionEntry) -> None:
    mock_session.add_message(AgentMessage.user("看看账户"))
    _inject_tool_turn(mock_session, "c1", "account_overview", {"total_assets": 150000})
    cb = create_citation_validation_hook()
    ctx = CallbackContext(
        user_input="看看账户",
        input_context={},
        session=mock_session,
    )
    response = AgentMessage.assistant(
        content="总资产 150000 元，收益 300000 元，其它 999999 元"
    )

    result = await cb(ctx, response=response)
    assert result is None
