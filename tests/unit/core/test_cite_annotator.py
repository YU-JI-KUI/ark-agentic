"""DefaultCiteAnnotator unit tests.

Coverage:
  - claim → span / entry mapping on a simple answer
  - (tool_name, matched_text) deduplication across multiple occurrences
  - no hits → empty spans and entries
  - span start/end offsets are correct
  - span ordering by start offset
"""

from __future__ import annotations

from ark_agentic.core.citation.annotator import DefaultCiteAnnotator


TOOL_SOURCES = {
    "tool_policy_query": "保单号 P001，现金价值 5000 元",
    "tool_customer_info": "客户姓名张三，手机号 13800138000",
}


class TestDefaultCiteAnnotatorBasic:
    def setup_method(self) -> None:
        self.ann = DefaultCiteAnnotator()

    def test_single_claim_hit(self) -> None:
        answer = "您的现金价值为 5000 元。"

        spans, entries = self.ann.annotate(answer, TOOL_SOURCES)

        assert len(entries) >= 1
        matched = [e for e in entries if "5000" in e.matched_text]
        assert matched, "expected a CiteEntry with '5000'"
        assert matched[0].tool_name == "policy_query"

    def test_span_offsets_correct(self) -> None:
        answer = "您的现金价值为 5000 元。"

        spans, _ = self.ann.annotate(answer, TOOL_SOURCES)

        value_spans = [s for s in spans if "5000" in s.matched_text]
        assert value_spans
        s = value_spans[0]
        assert answer[s.start:s.end] == s.matched_text

    def test_no_match_returns_empty(self) -> None:
        answer = "暂无相关数据。"

        spans, entries = self.ann.annotate(answer, TOOL_SOURCES)

        assert spans == []
        assert entries == []

    def test_empty_answer_returns_empty(self) -> None:
        spans, entries = self.ann.annotate("", TOOL_SOURCES)

        assert spans == []
        assert entries == []

    def test_empty_tool_sources_returns_empty(self) -> None:
        spans, entries = self.ann.annotate("有数据", {})

        assert spans == []
        assert entries == []

    def test_span_ordering_by_start(self) -> None:
        answer = "张三的保单号是 P001，现金价值 5000 元。"

        spans, _ = self.ann.annotate(answer, TOOL_SOURCES)

        if len(spans) >= 2:
            for a, b in zip(spans, spans[1:]):
                assert a.start <= b.start

    def test_thousand_separator_number_spans(self) -> None:
        """NUMBER claims 使用规范化面值；answer 中千分位仍应能标出 span。"""
        answer = (
            "当前冻结资金为 **2,000.00元**，现金总额：**50,000.00元**。"
        )
        sources = {
            "tool_cash_assets": "冻结资金 2000 元，现金总额 50000 元",
        }

        spans, entries = self.ann.annotate(answer, sources)

        frozen = [
            s for s in spans
            if "2,000.00" in s.matched_text or s.matched_text == "2000"
        ]
        total = [
            s for s in spans
            if "50,000.00" in s.matched_text or s.matched_text == "50000"
        ]
        assert frozen, "expected span over 2,000.00"
        assert total, "expected span over 50,000.00"
        fs, ts = frozen[0], total[0]
        assert answer[fs.start:fs.end] == fs.matched_text
        assert answer[ts.start:ts.end] == ts.matched_text
        assert {e.matched_text for e in entries} >= {"2000", "50000"}


class TestDefaultCiteAnnotatorDedup:
    def setup_method(self) -> None:
        self.ann = DefaultCiteAnnotator()

    def test_same_value_same_tool_gets_one_cite_id(self) -> None:
        # The same matched value from the same tool appearing twice should
        # produce two spans but only ONE entry (same cite-N).
        answer = "5000 元即现金价值 5000 元。"
        sources = {"tool_policy_query": "现金价值 5000 元"}

        spans, entries = self.ann.annotate(answer, sources)

        cite_ids = {s.source_id for s in spans if "5000" in s.matched_text}
        assert len(cite_ids) == 1, "same (tool, value) should share a cite ID"
        assert len(entries) == 1

    def test_different_tools_same_value_get_different_cite_ids(self) -> None:
        answer = "账号余额 3000 元，基金净值也是 3000 元。"
        sources = {
            "tool_cash_assets": "可用资金 3000 元",
            "tool_fund_holdings": "净值 3000 元",
        }

        spans, entries = self.ann.annotate(answer, sources)

        cash_entries = [e for e in entries if e.tool_name == "cash_assets"]
        fund_entries = [e for e in entries if e.tool_name == "fund_holdings"]
        if cash_entries and fund_entries:
            assert cash_entries[0].source_id != fund_entries[0].source_id

    def test_cite_ids_are_sequential(self) -> None:
        answer = "张三持有保单 P001，现金价值 5000 元。"

        _, entries = self.ann.annotate(answer, TOOL_SOURCES)

        ids = [e.source_id for e in entries]
        for i, sid in enumerate(ids, start=1):
            assert sid == f"cite-{i}"
