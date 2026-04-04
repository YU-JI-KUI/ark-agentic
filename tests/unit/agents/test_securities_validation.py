"""证券智能体 Cite 幻觉检测回调 — 单元测试"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ark_agentic.agents.securities.validation import (
    SecuritiesValidationConfig,
    create_securities_validation_callback,
)
from ark_agentic.core.callbacks import CallbackContext
from ark_agentic.core.session import SessionEntry
from ark_agentic.core.types import AgentMessage


@pytest.fixture
def csv_path(tmp_path: Path) -> Path:
    csv_file = tmp_path / "a_shares.csv"
    csv_file.write_text(
        "code,name,exchange\n000001,平安银行,SZ\n600036,招商银行,SH\n",
        encoding="utf-8",
    )
    return csv_file


@pytest.fixture
def mock_session() -> SessionEntry:
    return SessionEntry(session_id="test_session", messages=[], state={})


# ============ 无工具数据：跳过校验 ============


@pytest.mark.asyncio
async def test_no_tool_data_skips_validation(csv_path: Path, mock_session: SessionEntry) -> None:
    cb = create_securities_validation_callback(csv_path=csv_path)
    ctx = CallbackContext(user_input="看看平安银行", input_context={}, session=mock_session)
    response = AgentMessage.assistant(content="平安银行总资产 150000 元")

    result = await cb(ctx, response=response)
    assert result is None
    assert response.metadata["validation"]["route"] == "skip"


# ============ 纯文本回复（无结构化 JSON）============


@pytest.mark.asyncio
async def test_plain_text_response_runs_validation(
    csv_path: Path, mock_session: SessionEntry
) -> None:
    mock_session.state["account_overview"] = {"total_assets": 150000, "business_date": "2026-04-02"}
    cb = create_securities_validation_callback(csv_path=csv_path)
    ctx = CallbackContext(user_input="看看账户总资产", input_context={}, session=mock_session)
    # 纯文本：数字未标注 → UNCITED errors
    response = AgentMessage.assistant(content="您的总资产为 150000 元")

    result = await cb(ctx, response=response)
    # 纯文本回退不替换 response，返回 None
    assert result is None
    meta = response.metadata["validation"]
    assert meta["structured"] is False
    # 150000 未标注 → 有 errors
    assert len(meta["errors"]) >= 1


# ============ 结构化输出（带 citations），全部命中 ============


@pytest.mark.asyncio
async def test_structured_response_all_cited_passes(
    csv_path: Path, mock_session: SessionEntry
) -> None:
    mock_session.state["account_overview"] = {"total_assets": 150000, "business_date": "2026-04-02"}
    cb = create_securities_validation_callback(csv_path=csv_path)
    ctx = CallbackContext(user_input="看看账户总资产", input_context={}, session=mock_session)

    structured = json.dumps(
        {
            "answer": "您的总资产为 150000 元",
            "citations": [
                {"value": "150000", "type": "NUMBER", "source": "tool_account_overview"}
            ],
        },
        ensure_ascii=False,
    )
    response = AgentMessage.assistant(content=structured)

    result = await cb(ctx, response=response)
    assert result is not None
    # 提取 answer 作为最终 response
    assert result.response is not None
    assert result.response.content == "您的总资产为 150000 元"
    meta = result.response.metadata["validation"]
    assert meta["structured"] is True
    assert meta["route"] in {"safe", "warn"}
    assert meta["score"] >= 0.8


# ============ 结构化输出，citation 数据与工具不符 ============


@pytest.mark.asyncio
async def test_structured_response_cite_mismatch_lowers_score(
    csv_path: Path, mock_session: SessionEntry
) -> None:
    mock_session.state["account_overview"] = {"total_assets": 150000}
    cb = create_securities_validation_callback(csv_path=csv_path)
    ctx = CallbackContext(user_input="看看总资产", input_context={}, session=mock_session)

    # 声称 200000 但工具只有 150000
    structured = json.dumps(
        {
            "answer": "您的总资产为 200000 元",
            "citations": [
                {"value": "200000", "type": "NUMBER", "source": "tool_account_overview"}
            ],
        },
        ensure_ascii=False,
    )
    response = AgentMessage.assistant(content=structured)

    result = await cb(ctx, response=response)
    assert result is not None
    meta = result.response.metadata["validation"]
    # 200000 不在工具数据中 → CITE_NOT_FOUND + 可能 UNCITED
    assert any(e["type"] == "CITE_NOT_FOUND" for e in meta["errors"])
    assert meta["score"] < 1.0


# ============ 幻觉兜底：结构化输出 retry → 插入免责声明 ============


@pytest.mark.asyncio
async def test_hallucination_structured_inserts_disclaimer(
    csv_path: Path, mock_session: SessionEntry
) -> None:
    mock_session.state["account_overview"] = {"total_assets": 150000}
    cb = create_securities_validation_callback(csv_path=csv_path)
    ctx = CallbackContext(user_input="看账户", input_context={}, session=mock_session)

    # 5 个未标注大数字 → score ≤ 0 → retry
    structured = json.dumps(
        {
            "answer": "总资产 200000、300000、400000、500000、600000 元",
            "citations": [],
        },
        ensure_ascii=False,
    )
    response = AgentMessage.assistant(content=structured)

    result = await cb(ctx, response=response)
    assert result is not None
    assert result.response is not None
    content = result.response.content or ""
    assert "⚠️" in content or "请以实际" in content
    assert result.response.metadata["validation"]["route"] == "retry"


# ============ 幻觉兜底：纯文本 retry → 兜底话术 ============


@pytest.mark.asyncio
async def test_hallucination_plain_text_returns_fallback(
    csv_path: Path, mock_session: SessionEntry
) -> None:
    mock_session.state["account_overview"] = {"total_assets": 150000}
    cb = create_securities_validation_callback(csv_path=csv_path)
    ctx = CallbackContext(user_input="看账户", input_context={}, session=mock_session)

    # 纯文本 + 多个未标注大数字 → retry
    response = AgentMessage.assistant(
        content="总资产 200000、300000、400000、500000、600000 元"
    )

    result = await cb(ctx, response=response)
    assert result is not None
    assert result.response is not None
    assert "暂时无法核对" in (result.response.content or "")
    assert result.response.metadata["validation"]["route"] == "retry"


# ============ 实体张冠李戴：回复招商银行但数据来自平安银行 ============


@pytest.mark.asyncio
async def test_entity_substitution_detected(
    csv_path: Path, mock_session: SessionEntry
) -> None:
    mock_session.state["security_detail"] = {"stock_name": "平安银行", "market_value": 150000}
    cb = create_securities_validation_callback(csv_path=csv_path)
    ctx = CallbackContext(user_input="看看平安银行", input_context={}, session=mock_session)

    # LLM 错误将"平安银行"写成"招商银行"，且 citations 引用的也是错误实体
    structured = json.dumps(
        {
            "answer": "招商银行市值 150000 元",
            "citations": [
                {"value": "招商银行", "type": "ENTITY", "source": "tool_security_detail"},
                {"value": "150000", "type": "NUMBER", "source": "tool_security_detail"},
            ],
        },
        ensure_ascii=False,
    )
    response = AgentMessage.assistant(content=structured)

    result = await cb(ctx, response=response)
    assert result is not None
    meta = result.response.metadata["validation"]
    # "招商银行" 不在工具数据 → CITE_NOT_FOUND
    assert any(e["type"] == "CITE_NOT_FOUND" and "招商银行" in e["value"] for e in meta["errors"])


# ============ llm 参数已弃用但不报错 ============


@pytest.mark.asyncio
async def test_llm_param_ignored(csv_path: Path, mock_session: SessionEntry) -> None:
    from unittest.mock import MagicMock

    mock_llm = MagicMock()
    cb = create_securities_validation_callback(csv_path=csv_path, llm=mock_llm)
    ctx = CallbackContext(user_input="test", input_context={}, session=mock_session)
    response = AgentMessage.assistant(content="test")
    # 无工具数据 → skip，不调用 llm
    await cb(ctx, response=response)
    mock_llm.ainvoke.assert_not_called()
