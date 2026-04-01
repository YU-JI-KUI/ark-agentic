"""
Tests for PAKnowledgeAPITool and PAKnowledgeAPIConfig.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ark_agentic.core.tools.pa_knowledge_api import (
    PAKnowledgeAPIConfig,
    PAKnowledgeAPITool,
    _fuse_results,
    create_pa_knowledge_api_tool,
)
from ark_agentic.core.types import ToolCall


# ---- Fixtures ----

def _make_config(**kwargs) -> PAKnowledgeAPIConfig:
    defaults = dict(
        faq_url="https://pa-api.test/kn/knSearch",
        tenant_id="test-tenant",
        kn_ids=["3106"],
        static_auth_token="test-token",
    )
    defaults.update(kwargs)
    return PAKnowledgeAPIConfig(**defaults)


def _make_tool_call(queries) -> ToolCall:
    return ToolCall.create("pa_knowledge_api", {"queries": queries})


def _api_response(items: list[dict]) -> dict:
    return {"code": "200", "data": items}


def _seg_item(question: str, answer: str) -> dict:
    return {"segContent": json.dumps({"question": question, "answer": answer})}


# ---- _fuse_results ----

class TestFuseResults:
    def test_empty(self):
        assert _fuse_results([]) == []

    def test_basic(self):
        resp = _api_response([_seg_item("Q1", "A1")])
        result = _fuse_results([resp])
        assert result == [{"hitQuestion": "Q1", "answer": "A1"}]

    def test_deduplication(self):
        item = _seg_item("Q1", "A1")
        resp = _api_response([item, item])
        result = _fuse_results([resp, resp])
        assert len(result) == 1

    def test_filters_exceptions(self):
        resp = _api_response([_seg_item("Q1", "A1")])
        result = _fuse_results([ValueError("oops"), resp])
        assert len(result) == 1
        assert result[0]["hitQuestion"] == "Q1"

    def test_all_exceptions_returns_empty(self):
        assert _fuse_results([ValueError("x"), RuntimeError("y")]) == []

    def test_non_json_segContent(self):
        item = {"segContent": "plain text fallback"}
        resp = _api_response([item])
        result = _fuse_results([resp])
        assert result == [{"raw": "plain text fallback"}]

    def test_missing_segContent_skipped(self):
        resp = _api_response([{"other": "field"}])
        assert _fuse_results([resp]) == []

    def test_non_200_code_skipped(self):
        resp = {"code": "500", "data": [_seg_item("Q", "A")]}
        assert _fuse_results([resp]) == []

    def test_multi_query_merge(self):
        r1 = _api_response([_seg_item("Q1", "A1")])
        r2 = _api_response([_seg_item("Q2", "A2")])
        result = _fuse_results([r1, r2])
        assert len(result) == 2


# ---- PAKnowledgeAPITool ----

class TestPAKnowledgeAPITool:
    def test_factory_returns_tool(self):
        cfg = _make_config()
        tool = create_pa_knowledge_api_tool(cfg)
        assert isinstance(tool, PAKnowledgeAPITool)

    def test_default_tool_name(self):
        tool = PAKnowledgeAPITool(_make_config())
        assert tool.name == "pa_knowledge_api"

    def test_custom_tool_name(self):
        tool = PAKnowledgeAPITool(_make_config(tool_name="search_product_faq"))
        assert tool.name == "search_product_faq"

    def test_two_instances_independent_names(self):
        t1 = PAKnowledgeAPITool(_make_config(tool_name="faq_a"))
        t2 = PAKnowledgeAPITool(_make_config(tool_name="faq_b"))
        assert t1.name == "faq_a"
        assert t2.name == "faq_b"

    def test_parameters_schema(self):
        tool = PAKnowledgeAPITool(_make_config())
        schema = tool.get_json_schema()
        params = schema["function"]["parameters"]
        assert params["properties"]["queries"]["type"] == "array"
        assert params["properties"]["queries"]["items"] == {"type": "string"}
        assert "queries" in params["required"]

    # ---- execute: input normalization ----

    @pytest.mark.asyncio
    async def test_empty_queries_returns_error(self):
        tool = PAKnowledgeAPITool(_make_config())
        tc = _make_tool_call([])
        result = await tool.execute(tc)
        assert result.is_error is False
        assert "error" in result.content

    @pytest.mark.asyncio
    async def test_single_string_normalized_to_list(self):
        tool = PAKnowledgeAPITool(_make_config())
        tc = _make_tool_call("single query")

        resp = _api_response([_seg_item("Q", "A")])
        mock_response = MagicMock()
        mock_response.json.return_value = resp

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.post = AsyncMock(return_value=mock_response)
            MockClient.return_value = instance

            result = await tool.execute(tc, context={"session_id": "s1"})

        assert result.content["total"] == 1

    # ---- Token: static token ----

    @pytest.mark.asyncio
    async def test_static_token_used_directly(self):
        tool = PAKnowledgeAPITool(_make_config(static_auth_token="my-static"))
        token = await tool._get_token()
        assert token == "my-static"

    @pytest.mark.asyncio
    async def test_static_token_not_refreshed(self):
        """Static token: _get_token() never calls httpx."""
        tool = PAKnowledgeAPITool(_make_config(static_auth_token="tok"))
        with patch("httpx.AsyncClient") as MockClient:
            await tool._get_token()
            await tool._get_token()
            MockClient.assert_not_called()

    # ---- Token: dynamic token with caching ----

    @pytest.mark.asyncio
    async def test_dynamic_token_cached(self):
        cfg = _make_config(
            static_auth_token=None,
            app_secret="secret",
            token_auth_url="https://pa-api.test/auth",
        )
        tool = PAKnowledgeAPITool(cfg)

        token_resp = MagicMock()
        token_resp.json.return_value = {"data": "fresh-token"}

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.post = AsyncMock(return_value=token_resp)
            MockClient.return_value = instance

            t1 = await tool._get_token()
            t2 = await tool._get_token()  # should use cache

        assert t1 == t2 == "fresh-token"
        assert instance.post.call_count == 1  # token API called once

    # ---- Token: missing auth raises ----

    @pytest.mark.asyncio
    async def test_missing_auth_raises(self):
        cfg = _make_config(static_auth_token=None, app_secret=None, token_auth_url=None)
        tool = PAKnowledgeAPITool(cfg)
        with pytest.raises(ValueError, match="Auth not configured"):
            await tool._get_token()

    # ---- execute: partial failure ----

    @pytest.mark.asyncio
    async def test_partial_query_failure_returns_partial(self):
        tool = PAKnowledgeAPITool(_make_config())
        tc = _make_tool_call(["good query", "bad query"])

        good_resp = MagicMock()
        good_resp.json.return_value = _api_response([_seg_item("Q", "A")])

        call_count = 0

        async def _mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return good_resp
            raise ConnectionError("network error")

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.post = _mock_post
            MockClient.return_value = instance

            result = await tool.execute(tc, context={"session_id": "s1"})

        assert result.content["total"] == 1
        assert result.content["results"][0]["hitQuestion"] == "Q"

    # ---- _build_body camelCase mapping ----

    def test_build_body_camelcase(self):
        cfg = _make_config(
            tenant_id="t1",
            kn_ids=["k1", "k2"],
            top_n=3,
            faq_score_limit=0.9,
            rag_strategy=2,
        )
        tool = PAKnowledgeAPITool(cfg)
        body = tool._build_body("query text", "sess-1", "req-1")

        assert body["tenantId"] == "t1"
        assert body["context"]["knIds"] == ["k1", "k2"]
        assert body["context"]["topN"] == 3
        assert body["context"]["faqScoreLimit"] == 0.9
        assert body["context"]["ragStrategy"] == 2
        assert body["sessionId"] == "sess-1"
        assert body["requestId"] == "req-1"
        assert body["content"] == "query text"

    # ---- session_id fallback ----

    @pytest.mark.asyncio
    async def test_session_id_fallback_when_missing(self):
        tool = PAKnowledgeAPITool(_make_config())
        tc = _make_tool_call(["q"])
        captured_bodies = []

        mock_response = MagicMock()
        mock_response.json.return_value = {"code": "200", "data": []}

        async def _mock_post(url, json=None, **kwargs):
            captured_bodies.append(json)
            return mock_response

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.post = _mock_post
            MockClient.return_value = instance

            # context without session_id
            await tool.execute(tc, context={})

        assert captured_bodies[0]["sessionId"] != ""
        assert len(captured_bodies[0]["sessionId"]) > 0

    @pytest.mark.asyncio
    async def test_session_id_from_context_used_in_request(self):
        """Runner 注入的 session_id 应被正确传入 API 请求体."""
        tool = PAKnowledgeAPITool(_make_config())
        tc = _make_tool_call(["q"])
        captured_bodies = []

        mock_response = MagicMock()
        mock_response.json.return_value = {"code": "200", "data": []}

        async def _mock_post(url, json=None, **kwargs):
            captured_bodies.append(json)
            return mock_response

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.post = _mock_post
            MockClient.return_value = instance

            await tool.execute(tc, context={"session_id": "runner-injected-sess-123"})

        assert captured_bodies[0]["sessionId"] == "runner-injected-sess-123"
