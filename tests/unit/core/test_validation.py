"""单轮闭环 Cite 幻觉检测 — 校验层单元测试

覆盖：
  - parse_cited_response：JSON 解析与回退
  - validate_citations：citation 真实性校验 + 未标注检测 + 得分路由
  - EntityTrie：CSV 白名单提取
  - resolve_relative_time：相对时间转换
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datetime import date, timedelta

from ark_agentic.core.validation import (
    Citation,
    CitedResponse,
    CitationError,
    EntityTrie,
    extract_numbers_from_text,
    parse_cited_response,
    resolve_relative_time,
    validate_citations,
    _relative_time_to_forms,
)


# ============ parse_cited_response ============


class TestParseCitedResponse:
    def test_valid_json(self) -> None:
        text = '{"answer": "平安银行市值 150000 元", "citations": [{"value": "平安银行", "type": "ENTITY", "source": "tool_security_detail"}, {"value": "150000", "type": "NUMBER", "source": "tool_security_detail"}]}'
        result = parse_cited_response(text)
        assert result is not None
        assert result.answer == "平安银行市值 150000 元"
        assert len(result.citations) == 2
        assert result.citations[0].value == "平安银行"
        assert result.citations[0].type == "ENTITY"

    def test_empty_citations(self) -> None:
        text = '{"answer": "无数据", "citations": []}'
        result = parse_cited_response(text)
        assert result is not None
        assert result.citations == []

    def test_markdown_code_block(self) -> None:
        text = '```json\n{"answer": "收益 300 元", "citations": [{"value": "300", "type": "NUMBER", "source": "tool_x"}]}\n```'
        result = parse_cited_response(text)
        assert result is not None
        assert result.answer == "收益 300 元"

    def test_plain_text_returns_none(self) -> None:
        assert parse_cited_response("今日平安银行市值上涨") is None

    def test_invalid_json_returns_none(self) -> None:
        assert parse_cited_response("{invalid json}") is None

    def test_missing_answer_returns_none(self) -> None:
        assert parse_cited_response('{"citations": []}') is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_cited_response("") is None

    def test_type_uppercased(self) -> None:
        text = '{"answer": "ok", "citations": [{"value": "v", "type": "entity", "source": "context"}]}'
        result = parse_cited_response(text)
        assert result is not None
        assert result.citations[0].type == "ENTITY"


# ============ validate_citations：citation 真实性校验 ============


class TestCiteNotFound:
    def test_cite_found_in_tool(self) -> None:
        cited = CitedResponse(
            answer="平安银行市值 150000 元",
            citations=[
                Citation(value="平安银行", type="ENTITY", source="tool_security_detail"),
                Citation(value="150000", type="NUMBER", source="tool_security_detail"),
            ],
        )
        tool_sources = {"security_detail": '{"stock_name": "平安银行", "market_value": 150000}'}
        result = validate_citations(cited, tool_sources)
        assert not any(e.type == "CITE_NOT_FOUND" for e in result.errors)

    def test_cite_not_found_triggers_error(self) -> None:
        cited = CitedResponse(
            answer="招商银行市值 200000 元",
            citations=[
                Citation(value="招商银行", type="ENTITY", source="tool_security_detail"),
            ],
        )
        # 工具数据中只有平安银行
        tool_sources = {"security_detail": '{"stock_name": "平安银行", "market_value": 150000}'}
        result = validate_citations(cited, tool_sources)
        assert any(e.type == "CITE_NOT_FOUND" and e.value == "招商银行" for e in result.errors)

    def test_context_source_checks_user_input(self) -> None:
        cited = CitedResponse(
            answer="您查询的招商银行",
            citations=[
                Citation(value="招商银行", type="ENTITY", source="context"),
            ],
        )
        result = validate_citations(cited, {}, context="帮我看看招商银行")
        assert not any(e.type == "CITE_NOT_FOUND" for e in result.errors)

    def test_context_source_not_found(self) -> None:
        cited = CitedResponse(
            answer="招商银行价格",
            citations=[
                Citation(value="招商银行", type="ENTITY", source="context"),
            ],
        )
        result = validate_citations(cited, {}, context="看看平安银行")
        assert any(e.type == "CITE_NOT_FOUND" for e in result.errors)

    def test_tool_key_without_prefix_also_resolves(self) -> None:
        cited = CitedResponse(
            answer="总资产 150000",
            citations=[Citation(value="150000", type="NUMBER", source="account_overview")],
        )
        tool_sources = {"account_overview": '{"total_assets": 150000}'}
        result = validate_citations(cited, tool_sources)
        assert not any(e.type == "CITE_NOT_FOUND" for e in result.errors)


# ============ validate_citations：未标注检测（UNCITED）============


class TestUncited:
    def test_uncited_number_triggers_error(self) -> None:
        cited = CitedResponse(
            answer="总资产 150000 元",
            citations=[],
        )
        tool_sources = {"account_overview": '{"total_assets": 150000}'}
        result = validate_citations(cited, tool_sources)
        assert any(e.type == "UNCITED" and "150000" in e.value for e in result.errors)

    def test_cited_number_no_uncited_error(self) -> None:
        cited = CitedResponse(
            answer="总资产 150000 元",
            citations=[Citation(value="150000", type="NUMBER", source="tool_account_overview")],
        )
        tool_sources = {"account_overview": '{"total_assets": 150000}'}
        result = validate_citations(cited, tool_sources)
        assert not any(e.type == "UNCITED" for e in result.errors)

    def test_small_number_not_flagged(self) -> None:
        cited = CitedResponse(answer="持有 3 支股票", citations=[])
        tool_sources = {"account_overview": '{"count": 3}'}
        result = validate_citations(cited, tool_sources)
        assert not any(e.type == "UNCITED" for e in result.errors)

    def test_uncited_date_triggers_error(self) -> None:
        cited = CitedResponse(
            answer="截至 2026-04-01 收益 300 元",
            citations=[Citation(value="300", type="NUMBER", source="tool_account_overview")],
        )
        tool_sources = {"account_overview": '{"business_date": "2026-04-01", "profit": 300}'}
        result = validate_citations(cited, tool_sources)
        assert any(e.type == "UNCITED" and "2026-04-01" in e.value for e in result.errors)

    def test_uncited_entity_via_trie(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "banks.csv"
        csv_file.write_text("code,name,exchange\n000001,平安银行,SZ\n", encoding="utf-8")
        trie = EntityTrie()
        trie.load_from_csv(csv_file)

        cited = CitedResponse(answer="平安银行市值上涨", citations=[])
        tool_sources = {"security_detail": '{"stock_name": "平安银行"}'}
        result = validate_citations(cited, tool_sources, entity_trie=trie)
        assert any(e.type == "UNCITED" and e.value == "平安银行" for e in result.errors)

    def test_cited_entity_no_uncited_error(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "banks.csv"
        csv_file.write_text("code,name,exchange\n000001,平安银行,SZ\n", encoding="utf-8")
        trie = EntityTrie()
        trie.load_from_csv(csv_file)

        cited = CitedResponse(
            answer="平安银行市值上涨",
            citations=[Citation(value="平安银行", type="ENTITY", source="tool_security_detail")],
        )
        tool_sources = {"security_detail": '{"stock_name": "平安银行"}'}
        result = validate_citations(cited, tool_sources, entity_trie=trie)
        assert not any(e.type == "UNCITED" for e in result.errors)


# ============ 相对时间检测 ============


class TestRelativeTimeInAnswer:
    """answer 中含中文相对时间表述时，validate_citations 应检测 UNCITED 或正确匹配引用。"""

    def test_relative_month_uncited(self) -> None:
        """上个月未被引用 → UNCITED 错误"""
        cited = CitedResponse(answer="上个月净收益为 5000 元", citations=[])
        result = validate_citations(cited, {"account_overview": "5000"})
        assert any(e.type == "UNCITED" and e.value == "上个月" for e in result.errors)

    def test_relative_month_cited_with_absolute_date(self) -> None:
        """citation 使用绝对日期（上个月的月份字符串）→ 不报 UNCITED"""
        last_month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        cited = CitedResponse(
            answer="上个月净收益为 5000 元",
            citations=[
                Citation(value=last_month, type="TIME", source="tool_account_overview"),
                Citation(value="5000", type="NUMBER", source="tool_account_overview"),
            ],
        )
        result = validate_citations(cited, {"account_overview": f"{last_month} 5000"})
        assert not any(e.type == "UNCITED" and e.value == "上个月" for e in result.errors)

    def test_today_uncited(self) -> None:
        """答案中含"今天"但无引用 → UNCITED"""
        cited = CitedResponse(answer="今天市场表现良好，成交量 200000", citations=[])
        result = validate_citations(cited, {"overview": "200000"})
        assert any(e.type == "UNCITED" and e.value == "今天" for e in result.errors)

    def test_today_cited_with_isoformat(self) -> None:
        """citation.value 为今天的 ISO 日期 → 今天被视为已引用"""
        today_str = date.today().isoformat()
        cited = CitedResponse(
            answer="今天成交量 200000",
            citations=[
                Citation(value=today_str, type="TIME", source="context"),
                Citation(value="200000", type="NUMBER", source="tool_overview"),
            ],
        )
        result = validate_citations(
            cited,
            {"overview": "200000"},
            context=today_str,
        )
        assert not any(e.type == "UNCITED" and e.value == "今天" for e in result.errors)

    def test_last_year_cited_with_year_string(self) -> None:
        """citation.value 为去年年份字符串 → 去年被视为已引用"""
        last_year = str(date.today().year - 1)
        cited = CitedResponse(
            answer=f"去年全年收益 {last_year}",
            citations=[Citation(value=last_year, type="TIME", source="tool_profit")],
        )
        result = validate_citations(cited, {"profit": last_year})
        assert not any(e.type == "UNCITED" and e.value == "去年" for e in result.errors)


class TestRelativeTimeToForms:
    """_relative_time_to_forms 的单元测试。"""

    def test_last_month_contains_year_month(self) -> None:
        forms = _relative_time_to_forms("上个月")
        last = (date.today().replace(day=1) - timedelta(days=1))
        assert last.strftime("%Y-%m") in forms

    def test_today_contains_isoformat(self) -> None:
        forms = _relative_time_to_forms("今天")
        assert date.today().isoformat() in forms

    def test_last_year_contains_year_string(self) -> None:
        forms = _relative_time_to_forms("去年")
        assert str(date.today().year - 1) in forms

    def test_this_week_contains_monday(self) -> None:
        forms = _relative_time_to_forms("本周")
        monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        assert monday in forms


# ============ 得分与路由 ============


class TestScoreAndRouting:
    """score = max(0, 1.0 - 0.2 * n_errors)"""

    def test_zero_errors_is_safe(self) -> None:
        cited = CitedResponse(
            answer="总资产 150000 元",
            citations=[Citation(value="150000", type="NUMBER", source="tool_account_overview")],
        )
        result = validate_citations(cited, {"account_overview": "150000"})
        assert result.route == "safe"
        assert result.score == 1.0
        assert result.passed is True

    def test_one_error_is_safe(self) -> None:
        # 1 error → score = 0.8 → safe
        cited = CitedResponse(
            answer="总资产 150000 元，收益 3000 元",
            citations=[Citation(value="150000", type="NUMBER", source="tool_account_overview")],
        )
        result = validate_citations(cited, {"account_overview": "150000"})
        errors = [e for e in result.errors if e.type == "UNCITED"]
        # 3000 未标注 → 1 UNCITED
        assert result.score >= 0.8
        assert result.route == "safe"

    def test_two_errors_is_warn(self) -> None:
        # 2 errors → score = 0.6 → warn
        cited = CitedResponse(
            answer="总资产 150000 元，收益 3000 元",
            citations=[],
        )
        result = validate_citations(cited, {"account_overview": "150000, 3000"})
        assert result.score == pytest.approx(0.6)
        assert result.route == "warn"

    def test_three_or_more_errors_is_retry(self) -> None:
        # 3 errors → score = 0.4 → retry
        cited = CitedResponse(
            answer="总资产 150000 元，收益 3000 元，市值 200000 元",
            citations=[],
        )
        result = validate_citations(cited, {"account_overview": "150000, 3000, 200000"})
        assert result.score <= 0.4
        assert result.route == "retry"
        assert result.passed is False

    def test_no_tool_sources_does_not_fail_cite_check(self) -> None:
        # 无工具来源，citations 无法被验证（CITE_NOT_FOUND），
        # 未标注数字仍会被检测
        cited = CitedResponse(
            answer="市值 200000 元",
            citations=[Citation(value="200000", type="NUMBER", source="tool_x")],
        )
        result = validate_citations(cited, {})
        assert any(e.type == "CITE_NOT_FOUND" for e in result.errors)


# ============ 数字提取 ============


class TestExtractNumbersFromText:
    def test_basic_integer(self) -> None:
        assert extract_numbers_from_text("总资产 150000 元") == [150000.0]

    def test_thousands_separator(self) -> None:
        assert extract_numbers_from_text("总资产 150,000 元") == [150000.0]

    def test_decimal(self) -> None:
        assert 12.5 in extract_numbers_from_text("收益 12.5%")

    def test_negative_number(self) -> None:
        assert -300.0 in extract_numbers_from_text("亏损 -300 元")

    def test_filter_year(self) -> None:
        result = extract_numbers_from_text("2024 年收益 5000 元")
        assert 2024.0 not in result
        assert 5000.0 in result

    def test_empty_string(self) -> None:
        assert extract_numbers_from_text("") == []

    def test_multiple_numbers(self) -> None:
        result = extract_numbers_from_text("市值 150,000 元，收益 3,200 元")
        assert 150000.0 in result
        assert 3200.0 in result


# ============ 相对时间转换 ============


def _expected_relative_weekday(weeks_ago: int, target_weekday: int) -> str:
    from datetime import date, timedelta

    today = date.today()
    days_since_monday = today.weekday()
    this_week_target = today - timedelta(days=days_since_monday - target_weekday)
    return (this_week_target - timedelta(weeks=weeks_ago)).isoformat()


class TestRelativeTime:
    def test_today(self) -> None:
        from datetime import date

        assert resolve_relative_time("今天") == date.today().isoformat()

    def test_yesterday(self) -> None:
        from datetime import date, timedelta

        assert resolve_relative_time("昨天") == (date.today() - timedelta(days=1)).isoformat()

    def test_last_friday(self) -> None:
        assert resolve_relative_time("上周五") == _expected_relative_weekday(1, 4)

    def test_this_monday(self) -> None:
        assert resolve_relative_time("本周一") == _expected_relative_weekday(0, 0)

    def test_unsupported_returns_none(self) -> None:
        assert resolve_relative_time("某一天") is None

    def test_already_absolute(self) -> None:
        assert resolve_relative_time("2026-04-01") == "2026-04-01"


# ============ EntityTrie ============


class TestEntityTrie:
    def test_extract_from_csv_whitelist(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("code,name,exchange\n000001,平安银行,SZ\n000002,万科A,SZ\n")
        trie = EntityTrie()
        trie.load_from_csv(csv_file)
        assert "平安银行" in trie.extract("您持有的平安银行市值上涨了")

    def test_extract_multiple_entities(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("code,name,exchange\n000001,平安银行,SZ\n600036,招商银行,SH\n")
        trie = EntityTrie()
        trie.load_from_csv(csv_file)
        entities = trie.extract("平安银行和招商银行都涨了")
        assert "平安银行" in entities
        assert "招商银行" in entities

    def test_csv_with_irregular_spacing(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text('code,name,exchange\n000002,"万  科Ａ",SZ\n')
        trie = EntityTrie()
        trie.load_from_csv(csv_file)
        assert len(trie.extract("万科A今天涨了")) >= 1

    def test_returns_empty_for_no_match(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("code,name,exchange\n000001,平安银行,SZ\n")
        trie = EntityTrie()
        trie.load_from_csv(csv_file)
        assert trie.extract("今天天气不错") == []

    def test_extract_stock_code(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("code,name,exchange\n000001,平安银行,SZ\n")
        trie = EntityTrie()
        trie.load_from_csv(csv_file)
        assert "000001" in trie.extract("000001 表现不错")
