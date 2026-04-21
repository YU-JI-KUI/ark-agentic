"""SecurityInfoSearchTool 单元测试"""

from __future__ import annotations

import pytest

from ark_agentic.agents.securities.tools.service.stock_search.index import StockIndex, _infer_exchange
from ark_agentic.agents.securities.tools.service.stock_search.loader import StockLoader
from ark_agentic.agents.securities.tools.service.stock_search.matcher import MultiPathMatcher
from ark_agentic.agents.securities.tools.service.stock_search_service import StockSearchService
from ark_agentic.agents.securities.tools.agent.security_info_search import SecurityInfoSearchTool
from ark_agentic.core.types import ToolCall, ToolResultType

# 拼音可用标志（拼音相关测试类依赖此条件）
_pypinyin_available = pytest.importorskip  # 在各测试类上用 skipif 标记


def _has_pypinyin() -> bool:
    try:
        import pypinyin  # noqa: F401
        return True
    except ImportError:
        return False


# ── 测试数据 ──────────────────────────────────────────────────────────────────

_SAMPLE_ROWS = [
    {"code": "600519", "name": "贵州茅台", "exchange": "SH"},
    {"code": "000858", "name": "五粮液", "exchange": "SZ"},
    {"code": "300750", "name": "宁德时代", "exchange": "SZ"},
    {"code": "600036", "name": "招商银行", "exchange": "SH"},
    {"code": "000001", "name": "平安银行", "exchange": "SZ"},
    {"code": "601318", "name": "中国平安", "exchange": "SH"},
    {"code": "000333", "name": "美的集团", "exchange": "SZ"},
    {"code": "688041", "name": "海光信息", "exchange": "SH"},
    {"code": "837183", "name": "好想你", "exchange": "BJ"},
]


@pytest.fixture()
def index() -> StockIndex:
    return StockIndex(_SAMPLE_ROWS)


@pytest.fixture()
def matcher(index: StockIndex) -> MultiPathMatcher:
    return MultiPathMatcher(index)


@pytest.fixture()
def mock_loader() -> StockLoader:
    loader = StockLoader(mock_mode=True)
    return loader


# ── _infer_exchange 测试 ────────────────────────────────────────────────────


class TestInferExchange:
    def test_6_prefix_is_sh(self):
        assert _infer_exchange("600519") == "SH"

    def test_0_prefix_is_sz(self):
        assert _infer_exchange("000001") == "SZ"

    def test_3_prefix_is_sz(self):
        assert _infer_exchange("300750") == "SZ"

    def test_8_prefix_is_bj(self):
        assert _infer_exchange("830946") == "BJ"

    def test_688_is_sh(self):
        assert _infer_exchange("688041") == "SH"


# ── StockIndex 测试 ────────────────────────────────────────────────────────


@pytest.mark.skipif(not _has_pypinyin(), reason="需要 pypinyin")
class TestStockIndex:
    def test_find_by_code_exact(self, index: StockIndex):
        entity = index.find_by_code("600519")
        assert entity is not None
        assert entity.name == "贵州茅台"
        assert entity.exchange == "SH"
        assert entity.full_code == "600519.SH"

    def test_find_by_code_without_zero_padding(self, index: StockIndex):
        # 传入 "600519" 和 "0600519" 效果一样（zfill(6)）
        entity = index.find_by_code("600519")
        assert entity is not None

    def test_find_by_name_exact(self, index: StockIndex):
        entity = index.find_by_name("贵州茅台")
        assert entity is not None
        assert entity.code == "600519"

    def test_find_by_code_not_found(self, index: StockIndex):
        assert index.find_by_code("999999") is None

    def test_len(self, index: StockIndex):
        assert len(index) == len(_SAMPLE_ROWS)

    def test_pinyin_generated(self, index: StockIndex):
        entity = index.find_by_code("600519")
        assert entity is not None
        assert "maotai" in entity.pinyin

    def test_initials_generated(self, index: StockIndex):
        entity = index.find_by_code("300750")
        assert entity is not None
        assert entity.initials  # 不为空


# ── MultiPathMatcher 测试 ─────────────────────────────────────────────────


@pytest.mark.skipif(not _has_pypinyin(), reason="需要 pypinyin")
class TestMultiPathMatcher:
    def test_exact_code_match(self, matcher: MultiPathMatcher):
        result = matcher.search("600519")
        assert result.matched is True
        assert result.confidence == "exact"
        assert result.score == 1.0
        assert result.stock is not None
        assert result.stock.name == "贵州茅台"

    def test_exact_name_match(self, matcher: MultiPathMatcher):
        result = matcher.search("贵州茅台")
        assert result.matched is True
        assert result.confidence in ("exact", "high")
        assert result.stock is not None
        assert result.stock.code == "600519"

    def test_partial_name_match(self, matcher: MultiPathMatcher):
        result = matcher.search("茅台")
        # 部分名称应该能匹配到候选
        assert result.confidence in ("exact", "high", "ambiguous")

    def test_pinyin_match(self, matcher: MultiPathMatcher):
        result = matcher.search("maotai")
        # 拼音输入应能匹配
        assert result.confidence != "none"

    def test_initials_ascii_exact(self, matcher: MultiPathMatcher):
        # 纯字母首字母缩写（与全拼 WRatio 无关，走 initials_map）
        result = matcher.search("gzmt")
        assert result.matched is True
        assert result.confidence == "exact"
        assert result.stock is not None
        assert result.stock.code == "600519"

    def test_fuzzy_asr_error(self, matcher: MultiPathMatcher):
        # 模拟 ASR 识别偏差："宁德实代" → 宁德时代
        result = matcher.search("宁德实代")
        assert result.confidence in ("exact", "high", "ambiguous")
        if result.confidence in ("exact", "high"):
            assert result.stock is not None
            assert result.stock.code == "300750"
        elif result.confidence == "ambiguous":
            codes = [c["code"] for c in result.candidates]
            assert "300750" in codes

    def test_empty_query(self, matcher: MultiPathMatcher):
        result = matcher.search("")
        assert result.matched is False
        assert result.confidence == "none"

    def test_no_match_returns_none(self, matcher: MultiPathMatcher):
        result = matcher.search("XXXXXXXXXXX不存在股票")
        assert result.confidence in ("none", "ambiguous")

    def test_result_has_raw_query(self, matcher: MultiPathMatcher):
        result = matcher.search("茅台")
        assert result.raw_query == "茅台"

    def test_ambiguous_has_candidates(self, matcher: MultiPathMatcher):
        result = matcher.search("银行")
        if result.confidence == "ambiguous":
            assert len(result.candidates) > 0
            for c in result.candidates:
                assert "code" in c
                assert "name" in c
                assert "score" in c


# ── StockLoader 测试 ──────────────────────────────────────────────────────


class TestStockLoader:
    def test_default_loader_loads_seed(self):
        loader = StockLoader()
        assert len(loader.index) > 0

    def test_mock_mode_dividend(self):
        loader = StockLoader(mock_mode=True)
        # mock_data/dividends/default.json 当前仅含 601318
        div = loader.get_dividend_info("601318")
        assert div is not None
        assert div.stock_code == "601318"
        assert len(div.dividend_list) >= 1
        first = div.dividend_list[0]
        assert first.plan is not None
        assert first.cash_amount is not None

    def test_mock_mode_unknown_code_returns_empty_dividend(self):
        loader = StockLoader(mock_mode=True)
        div = loader.get_dividend_info("999999")
        assert div is not None  # 返回空 DividendInfo 对象

    def test_non_mock_mode_returns_none(self):
        loader = StockLoader(mock_mode=False)
        div = loader.get_dividend_info("600519")
        assert div is None

    def test_env_mock_mode(self, monkeypatch):
        monkeypatch.setenv("SECURITIES_SERVICE_MOCK", "true")
        loader = StockLoader()
        assert loader._mock_mode is True


# ── SecurityInfoSearchTool 集成测试 ───────────────────────────────────────


@pytest.mark.skipif(not _has_pypinyin(), reason="需要 pypinyin")
class TestSecurityInfoSearchTool:
    @pytest.fixture()
    def tool(self) -> SecurityInfoSearchTool:
        loader = StockLoader(mock_mode=True)
        return SecurityInfoSearchTool(service=StockSearchService(loader=loader))

    def _make_call(self, query: str, include_dividend: bool = True) -> ToolCall:
        return ToolCall(
            id="test_001",
            name="security_info_search",
            arguments={"query": query, "include_dividend": include_dividend},
        )

    @pytest.mark.asyncio
    async def test_exact_code_returns_json(self, tool: SecurityInfoSearchTool):
        call = self._make_call("600519")
        result = await tool.execute(call)
        assert result.result_type == ToolResultType.JSON
        data = result.content
        assert data["matched"] is True
        assert data["confidence"] == "exact"
        assert data["stock"]["code"] == "600519"
        assert data["stock"]["exchange"] == "SH"

    @pytest.mark.asyncio
    async def test_dividend_included(self, tool: SecurityInfoSearchTool):
        call = self._make_call("601318", include_dividend=True)
        result = await tool.execute(call)
        data = result.content
        assert data["matched"] is True
        div = data.get("dividend_info")
        assert div is not None
        assert div.get("dividend_list")

    @pytest.mark.asyncio
    async def test_dividend_excluded(self, tool: SecurityInfoSearchTool):
        call = self._make_call("600519", include_dividend=False)
        result = await tool.execute(call)
        data = result.content
        assert data["dividend_info"] is None

    @pytest.mark.asyncio
    async def test_name_match(self, tool: SecurityInfoSearchTool):
        call = self._make_call("招商银行")
        result = await tool.execute(call)
        data = result.content
        assert data["confidence"] in ("exact", "high")

    @pytest.mark.asyncio
    async def test_tool_name_and_description(self, tool: SecurityInfoSearchTool):
        assert tool.name == "security_info_search"
        assert "股票" in tool.description

    @pytest.mark.asyncio
    async def test_json_schema_has_query_param(self, tool: SecurityInfoSearchTool):
        schema = tool.get_json_schema()
        params = schema["function"]["parameters"]["properties"]
        assert "query" in params
        assert "include_dividend" in params
