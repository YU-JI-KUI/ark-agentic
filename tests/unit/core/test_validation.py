"""单轮闭环后置 grounding 校验 — 校验层单元测试

覆盖：
  - parse_cited_response：兼容旧 JSON 解析与回退
  - validate_citations / validate_answer_grounding：后置 grounding 校验与得分路由
  - extract_claims_from_answer：实体/数字/日期提取
  - EntityTrie：CSV 白名单提取
  - resolve_relative_time：相对时间转换
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from ark_agentic.core.validation import (
    CitedResponse,
    EntityTrie,
    extract_claims_from_answer,
    extract_numbers_from_text,
    parse_cited_response,
    resolve_relative_time,
    validate_answer_grounding,
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


# ============ 后置 grounding 校验 ============


class TestPostHocGrounding:
    def test_entity_and_number_grounded_by_tool(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "banks.csv"
        csv_file.write_text(
            "code,name,exchange\n000001,平安银行,SZ\n", encoding="utf-8"
        )
        trie = EntityTrie()
        trie.load_from_csv(csv_file)

        result = validate_answer_grounding(
            "平安银行市值 150000 元",
            {"security_detail": '{"stock_name": "平安银行", "market_value": 150000}'},
            entity_trie=trie,
        )
        assert result.route == "safe"
        assert result.errors == []

    def test_context_can_ground_entity(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "banks.csv"
        csv_file.write_text(
            "code,name,exchange\n600036,招商银行,SH\n", encoding="utf-8"
        )
        trie = EntityTrie()
        trie.load_from_csv(csv_file)

        result = validate_answer_grounding(
            "您查询的是招商银行",
            {},
            context="帮我看看招商银行",
            entity_trie=trie,
        )
        assert result.route == "safe"
        assert result.errors == []

    def test_number_not_found_triggers_ungrounded(self) -> None:
        result = validate_answer_grounding(
            "总资产 200000 元",
            {"account_overview": '{"total_assets": 150000}'},
        )
        assert any(
            e.type == "UNGROUNDED" and e.value == "200000" for e in result.errors
        )

    def test_date_not_found_triggers_ungrounded(self) -> None:
        result = validate_answer_grounding(
            "截至 2026-04-01 收益 300 元",
            {"account_overview": '{"business_date": "2026-04-02", "profit": 300}'},
        )
        assert any(
            e.type == "UNGROUNDED" and e.value == "2026-04-01" for e in result.errors
        )

    def test_chinese_date_range_in_tool_grounds_iso_in_answer(self) -> None:
        """工具串「2026年03月08日-至今」经归一化后应能支撑 answer 中的 ISO 日期。"""
        result = validate_answer_grounding(
            "统计区间自 2026-03-08 起至当前",
            {"profit": '{"period_text": "2026年03月08日-至今", "profit": 100}'},
        )
        assert result.route == "safe"
        assert result.errors == []

    def test_ymd_in_context_grounds_iso_in_answer(self) -> None:
        """用户上下文中 YYYYMMDD 归一化后应能与 answer 中 ISO 对齐。"""
        result = validate_answer_grounding(
            "从 2026-03-08 开始统计",
            {},
            context='查询区间 start_date=20260308',
        )
        assert result.route == "safe"
        assert result.errors == []

    def test_relative_time_grounded_by_context(self) -> None:
        today_str = date.today().isoformat()
        result = validate_answer_grounding(
            "今天成交量 200000",
            {"overview": "200000"},
            context=today_str,
        )
        assert result.errors == []

    def test_small_number_not_flagged(self) -> None:
        result = validate_answer_grounding(
            "持有 3 支股票",
            {"account_overview": '{"count": 3}'},
        )
        assert result.errors == []

    def test_multiple_missing_claims_trigger_retry(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "banks.csv"
        csv_file.write_text(
            "code,name,exchange\n000001,平安银行,SZ\n", encoding="utf-8"
        )
        trie = EntityTrie()
        trie.load_from_csv(csv_file)

        result = validate_answer_grounding(
            "招商银行总资产 200000 元，截至 2026-04-01 收益 300000 元",
            {"account_overview": '{"total_assets": 150000, "profit": 100000}'},
            entity_trie=trie,
        )
        assert result.route == "retry"
        assert result.passed is False

    def test_validate_citations_delegates_to_grounding(self) -> None:
        cited = CitedResponse(answer="总资产 150000 元", citations=[])
        result = validate_citations(
            cited, {"account_overview": '{"total_assets": 150000}'}
        )
        assert result.route == "safe"
        assert result.errors == []

    def test_percent_in_answer_matches_decimal_ratio_in_tool(self) -> None:
        """9.21% 归一化含 0.0921，与 JSON 中小数字段对齐。"""
        result = validate_answer_grounding(
            "累计收益率 9.21%",
            {"profit": json.dumps({"yield_rate": 0.0921}, ensure_ascii=False)},
        )
        assert result.route == "safe"
        assert result.errors == []

    def test_percent_92_1_matches_decimal_921_in_tool(self) -> None:
        result = validate_answer_grounding(
            "同期涨幅 92.1%",
            {"market": '{"chg": 0.921}'},
        )
        assert result.route == "safe"
        assert result.errors == []


# ============ claim 提取 ============


class TestExtractClaimsFromAnswer:
    def test_small_percent_not_filtered_by_min_business_number(self) -> None:
        claims = extract_claims_from_answer("累计收益率 9.21%，同期基准 2.5％")
        numbers = {c.value for c in claims if c.type == "NUMBER"}
        assert "9.21" in numbers
        assert "2.5" in numbers

    def test_small_plain_number_still_filtered(self) -> None:
        claims = extract_claims_from_answer("持有 3 支股票")
        assert not any(c.type == "NUMBER" for c in claims)

    def test_extract_entity_number_and_date(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "banks.csv"
        csv_file.write_text(
            "code,name,exchange\n000001,平安银行,SZ\n", encoding="utf-8"
        )
        trie = EntityTrie()
        trie.load_from_csv(csv_file)

        claims = extract_claims_from_answer(
            "平安银行在 2026-04-01 的市值为 150,000 元",
            entity_trie=trie,
        )
        pairs = {(claim.type, claim.value) for claim in claims}
        assert ("ENTITY", "平安银行") in pairs
        assert ("TIME", "2026-04-01") in pairs
        assert ("NUMBER", "150000") in pairs

    def test_extract_relative_time(self) -> None:
        claims = extract_claims_from_answer("上个月收益 5000 元")
        pairs = {(claim.type, claim.value) for claim in claims}
        assert ("TIME", "上个月") in pairs
        assert ("NUMBER", "5000") in pairs

    def test_same_value_deduped_by_priority(self) -> None:
        """同一字面值被多个 extractor 命中时，仅保留优先级最高的 type（TIME > NUMBER）。"""
        # "2026" 同时被 DateClaimExtractor（YYYYMMDD → 年份过滤）和 NumberClaimExtractor 处理；
        # 含完整 ISO 日期 2026-04-01 的字符串：DATE_RE 和 NUMBER 都会抽取 "2026-04-01" 中的年份部分；
        # 最直接的场景：YYYYMMDD "20260401" 同时被 DATE extractor(TIME) 和 NUMBER extractor 命中。
        claims = extract_claims_from_answer("起息日 20260401 金额 150000")
        values = [c.value for c in claims]
        # 20260401 应只出现一次（TIME 优先于 NUMBER）
        assert values.count("20260401") <= 1
        # 若存在，其 type 应为 TIME
        for c in claims:
            if c.value == "20260401":
                assert c.type == "TIME"


# ============ 相对时间辅助 ============


class TestRelativeTimeToForms:
    def test_last_month_contains_year_month(self) -> None:
        forms = _relative_time_to_forms("上个月")
        last = date.today().replace(day=1) - timedelta(days=1)
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

    def test_filter_compact_ymd_not_number(self) -> None:
        """合法 YYYYMMDD 不作为业务数值提取，避免与 TIME claim 重复。"""
        result = extract_numbers_from_text("起息日 20260308 金额 150000")
        assert 20260308.0 not in result
        assert 150000.0 in result

    def test_empty_string(self) -> None:
        assert extract_numbers_from_text("") == []

    def test_multiple_numbers(self) -> None:
        result = extract_numbers_from_text("市值 150,000 元，收益 3,200 元")
        assert 150000.0 in result
        assert 3200.0 in result


# ============ 相对时间转换 ============


def _expected_relative_weekday(weeks_ago: int, target_weekday: int) -> str:
    today = date.today()
    days_since_monday = today.weekday()
    this_week_target = today - timedelta(days=days_since_monday - target_weekday)
    return (this_week_target - timedelta(weeks=weeks_ago)).isoformat()


class TestRelativeTime:
    def test_today(self) -> None:
        assert resolve_relative_time("今天") == date.today().isoformat()

    def test_yesterday(self) -> None:
        assert (
            resolve_relative_time("昨天")
            == (date.today() - timedelta(days=1)).isoformat()
        )

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
        csv_file.write_text(
            "code,name,exchange\n000001,平安银行,SZ\n000002,万科A,SZ\n",
            encoding="utf-8",
        )
        trie = EntityTrie()
        trie.load_from_csv(csv_file)
        assert "平安银行" in trie.extract("您持有的平安银行市值上涨了")

    def test_extract_multiple_entities(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "code,name,exchange\n000001,平安银行,SZ\n600036,招商银行,SH\n",
            encoding="utf-8",
        )
        trie = EntityTrie()
        trie.load_from_csv(csv_file)
        entities = trie.extract("平安银行和招商银行都涨了")
        assert "平安银行" in entities
        assert "招商银行" in entities

    def test_csv_with_irregular_spacing(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            'code,name,exchange\n000002,"万  科Ａ",SZ\n',
            encoding="utf-8",
        )
        trie = EntityTrie()
        trie.load_from_csv(csv_file)
        assert len(trie.extract("万科A今天涨了")) >= 1

    def test_returns_empty_for_no_match(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "code,name,exchange\n000001,平安银行,SZ\n",
            encoding="utf-8",
        )
        trie = EntityTrie()
        trie.load_from_csv(csv_file)
        assert trie.extract("今天天气不错") == []

    def test_extract_stock_code(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "code,name,exchange\n000001,平安银行,SZ\n",
            encoding="utf-8",
        )
        trie = EntityTrie()
        trie.load_from_csv(csv_file)
        assert "000001" in trie.extract("000001 表现不错")
