"""GroundingCache 与二阶段补校验单元测试。

覆盖：
  - GroundingCache.put / get_recent / evict_expired：TTL 过期、多 session 隔离、同名工具合并
  - _recompute_result：重新计算 score/route
  - _fallback_match_ungrounded：历史补匹配
  - create_citation_validation_hook：二阶段降级（当前轮无工具命中 → 历史缓存中找到 → warn 不 retry）
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from ark_agentic.core.types import AgentMessage, AgentToolResult, SessionEntry, ToolCall
from ark_agentic.core.callbacks import CallbackContext, HookAction
from ark_agentic.core.utils.grounding_cache import FactSnapshot, GroundingCache
from ark_agentic.core.validation import (
    ExtractedClaim,
    _fallback_match_ungrounded,
    _recompute_result,
    create_citation_validation_hook,
)
from ark_agentic.core.utils.entities import EntityTrie


# ============ GroundingCache ============


class TestGroundingCache:
    def test_put_and_get_returns_merged_sources(self) -> None:
        cache = GroundingCache()
        cache.put("s1", FactSnapshot({"tool_a": "150000"}))
        cache.put("s1", FactSnapshot({"tool_a": "200000", "tool_b": "平安银行"}))
        merged = cache.get_recent("s1")
        assert "150000" in merged["tool_a"]
        assert "200000" in merged["tool_a"]
        assert merged["tool_b"] == "平安银行"

    def test_get_empty_session_returns_empty(self) -> None:
        cache = GroundingCache()
        assert cache.get_recent("no_such_session") == {}

    def test_ttl_expired_entries_evicted(self) -> None:
        cache = GroundingCache(ttl_sec=0.01)
        cache.put("s1", FactSnapshot({"tool_x": "abc"}))
        time.sleep(0.05)
        assert cache.get_recent("s1") == {}
        assert "s1" not in list(cache)

    def test_expired_entries_do_not_mix_with_live(self) -> None:
        cache = GroundingCache(ttl_sec=60)
        old_snap = FactSnapshot({"tool_old": "stale"}, created_at=time.monotonic() - 61)
        cache._store["s1"] = [old_snap]
        cache.put("s1", FactSnapshot({"tool_new": "fresh"}))
        merged = cache.get_recent("s1")
        assert "tool_old" not in merged
        assert merged.get("tool_new") == "fresh"

    def test_sessions_are_isolated(self) -> None:
        cache = GroundingCache()
        cache.put("a", FactSnapshot({"tool_x": "aaa"}))
        cache.put("b", FactSnapshot({"tool_x": "bbb"}))
        assert cache.get_recent("a") == {"tool_x": "aaa"}
        assert cache.get_recent("b") == {"tool_x": "bbb"}

    def test_empty_tool_sources_snapshot_not_included_in_merge(self) -> None:
        cache = GroundingCache()
        cache.put("s1", FactSnapshot({}))
        cache.put("s1", FactSnapshot({"tool_a": "hello"}))
        merged = cache.get_recent("s1")
        assert merged == {"tool_a": "hello"}


# ============ _recompute_result ============


class TestRecomputeResult:
    def _make_claim(self, value: str, claim_type: str) -> ExtractedClaim:
        return ExtractedClaim(value=value, type=claim_type, normalized_values=[value])

    def test_all_grounded_gives_safe(self) -> None:
        claims = [self._make_claim("150000", "NUMBER")]
        result = _recompute_result(claims, [])
        assert result.route == "safe"
        assert result.score == 100.0
        assert result.errors == []

    def test_all_ungrounded_gives_retry(self) -> None:
        c = self._make_claim("150000", "NUMBER")
        result = _recompute_result([c], [c])
        assert result.route == "retry"
        assert result.score == 0.0

    def test_partial_ungrounded_entity_triggers_retry(self) -> None:
        entity = self._make_claim("招商银行", "ENTITY")   # weight=20
        number = self._make_claim("150000", "NUMBER")     # weight=10; grounded
        number.sources = ["tool_a"]
        # total=30, ungrounded=20 → score = 100*(1-20/30)=33.3 < 60
        result = _recompute_result([entity, number], [entity])
        assert result.route == "retry"

    def test_empty_claims_gives_safe(self) -> None:
        result = _recompute_result([], [])
        assert result.route == "safe"
        assert result.score == 100.0


# ============ _fallback_match_ungrounded ============


class TestFallbackMatchUngrounded:
    def test_history_match_removes_from_ungrounded(self) -> None:
        claim = ExtractedClaim(value="150000", type="NUMBER", normalized_values=["150000"])
        still = _fallback_match_ungrounded([claim], {"tool_prev": "150000"}, [])
        assert still == []
        assert claim.sources == ["history_cache"]

    def test_no_history_match_keeps_ungrounded(self) -> None:
        claim = ExtractedClaim(value="999999", type="NUMBER", normalized_values=["999999"])
        still = _fallback_match_ungrounded([claim], {"tool_prev": "150000"}, [])
        assert still == [claim]
        assert not claim.sources


# ============ create_citation_validation_hook 二阶段降级 ============


def _inject_tool_turn(
    session: SessionEntry,
    tool_call_id: str,
    tool_name: str,
    result_content: dict | list | str,
) -> None:
    tc = ToolCall(id=tool_call_id, name=tool_name, arguments={})
    session.add_message(AgentMessage.assistant(tool_calls=[tc]))
    tr = (
        AgentToolResult.json_result(tool_call_id, result_content)
        if isinstance(result_content, (dict, list))
        else AgentToolResult(tool_call_id=tool_call_id, content=result_content)
    )
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
    t = EntityTrie()
    t.load_from_csv(csv_path)
    return t


@pytest.mark.asyncio
async def test_no_current_tool_fallback_to_history_downgrades_to_not_retry(
    trie: EntityTrie,
) -> None:
    """当前轮无工具调用，但历史缓存含事实语料 → 二阶段后 score 升至 warn/safe，不 retry。"""
    from ark_agentic.core.utils import grounding_cache as _gc_module

    isolated_cache = GroundingCache()
    # 历史轮次写入缓存：包含 150000
    isolated_cache.put("sess1", FactSnapshot({"tool_account": "总资产 150000"}))

    with patch.object(_gc_module, "_CACHE", isolated_cache):
        session = SessionEntry(session_id="sess1", messages=[], state={})
        session.add_message(AgentMessage.user("看看账户"))
        # 当前轮：无工具调用消息
        cb = create_citation_validation_hook(entity_trie=trie)
        ctx = CallbackContext(user_input="看看账户", input_context={}, session=session)
        # answer 只含 150000，来自历史缓存
        response = AgentMessage.assistant(content="您的总资产为 150000 元")
        result = await cb(ctx, response=response)
        assert result is None  # 历史补匹配后 score>=WARN，不 retry


@pytest.mark.asyncio
async def test_phase2_does_not_trigger_when_phase1_passes() -> None:
    """阶段1已通过（score>=WARN）时不进入阶段2，缓存中内容不影响结果。"""
    from ark_agentic.core.utils import grounding_cache as _gc_module

    isolated_cache = GroundingCache()
    with patch.object(_gc_module, "_CACHE", isolated_cache):
        session = SessionEntry(session_id="s_pass", messages=[], state={})
        session.add_message(AgentMessage.user("查资产"))
        _inject_tool_turn(session, "c1", "account", {"total_assets": 150000})
        cb = create_citation_validation_hook()
        ctx = CallbackContext(user_input="查资产", input_context={}, session=session)
        response = AgentMessage.assistant(content="总资产 150000 元")
        result = await cb(ctx, response=response)
        assert result is None


@pytest.mark.asyncio
async def test_phase2_still_retries_when_history_also_misses() -> None:
    """当前轮和历史缓存均无法 grounding → 仍 action=RETRY。"""
    from ark_agentic.core.utils import grounding_cache as _gc_module

    isolated_cache = GroundingCache()
    isolated_cache.put("s_bad", FactSnapshot({"tool_prev": "无关数据"}))
    with patch.object(_gc_module, "_CACHE", isolated_cache):
        session = SessionEntry(session_id="s_bad", messages=[], state={})
        session.add_message(AgentMessage.user("查资产"))
        # 当前轮无工具
        cb = create_citation_validation_hook()
        ctx = CallbackContext(user_input="查资产", input_context={}, session=session)
        # answer 含大量无来源数据
        response = AgentMessage.assistant(
            content="总资产 999999 元，收益 888888 元，市值 777777 元"
        )
        result = await cb(ctx, response=response)
        assert result is not None
        assert result.action == HookAction.RETRY
