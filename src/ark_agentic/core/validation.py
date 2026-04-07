"""
输出验证层 — 单轮后置 grounding（纯文本 answer）

架构：从 answer 提取实体/日期/数字 claim → 与扁平化 tool_sources + 用户 context 做子串命中 → score + route

核心原则：
  1. 模型仅输出自然语言；不由模型声明 citation JSON
  2. 校验为确定性逆向匹配（EntityTrie + 正则）
  3. 评分由未 grounding 的 claim 数量决定

兼容：`validate_citations(CitedResponse, ...)` 仅读取 `.answer`，委托 `validate_answer_grounding`；`parse_cited_response` 供旧格式解析。

框架级扩展：
  - create_citation_validation_hook: BeforeCompleteCallback 工厂，
    从 session.messages 中最后一条 USER 之后的 TOOL 消息提取工具事实语料
"""

from __future__ import annotations

import csv
import json
import logging
import re
from decimal import Decimal, InvalidOperation
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from flashtext import KeywordProcessor

if TYPE_CHECKING:
    from .callbacks import BeforeCompleteCallback, CallbackContext, CallbackResult
    from .types import AgentMessage

logger = logging.getLogger(__name__)

# answer 中 ISO 日期；事实语料侧另经 _normalize_compact_ymd_in_text 将 YYYYMMDD 转为同形
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# 中文日期（从最长到最短，保证 greedy 优先匹配完整形式）：
#   YYYY年M月D日 | YYYY年M月 | YYYY年
_CHINESE_DATE_RE = re.compile(r"\d{4}年\d{1,2}月(?:\d{1,2}日)?|\d{4}年")
# 紧凑型 8 位日期 YYYYMMDD（工具/用户上下文常见），限定年份范围避免误匹配普通整数
# TODO(perf): 对每条事实文本做全量 re.sub，大数据集场景可 lazy 触发
_YYYYMMDD_RE = re.compile(r"\b((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b")
# 中文相对时间表述（顺序从长到短避免子串截断）
_RELATIVE_TIME_RE = re.compile(
    r"上上个?月|上个?月|上月|本月|这个?月|下个?月|下月"
    r"|今天|今日|昨天|昨日|前天|大前天"
    r"|本周|上周|这周|下周"
    r"|上季度|本季度|上个季度|这个季度"
    r"|去年|今年|明年|前年"
)


def _chinese_date_to_iso(text: str) -> str | None:
    """将中文日期转为 ISO 等价形式，用于 citation 匹配时的跨格式比对。

    2026年3月15日 → 2026-03-15
    2026年3月    → 2026-03
    2026年       → 2026
    """
    m = re.fullmatch(r"(\d{4})年(?:(\d{1,2})月(?:(\d{1,2})日)?)?", text)
    if not m:
        return None
    year, month, day = m.group(1), m.group(2), m.group(3)
    if month and day:
        return f"{year}-{int(month):02d}-{int(day):02d}"
    if month:
        return f"{year}-{int(month):02d}"
    return year


# 低于此绝对值的普通数字视为噪声（如「3 支」）；带 % 的收益率等始终参与校验
_MIN_BUSINESS_NUMBER = 100.0
# 每个校验错误的扣分（score = max(0, 1.0 - penalty * n_errors)）
_ERROR_PENALTY = 0.2
# 路由阈值（score 0–1 区间）
_SAFE_THRESHOLD = 0.8  # >= 0.8 → safe
_WARN_THRESHOLD = 0.6  # >= 0.6 → warn；< 0.6 → retry


# ============ Cite 数据结构 ============


@dataclass
class Citation:
    """LLM 输出的单条引用。"""

    value: str
    type: str  # "ENTITY" | "TIME" | "NUMBER"
    source: str  # "tool_{tool_key}" | "context"


@dataclass
class CitedResponse:
    """LLM 带 citations 的结构化输出。"""

    answer: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class CitationError:
    """单个校验错误。"""

    type: str  # "CITE_NOT_FOUND" | "UNCITED" | "UNGROUNDED"
    value: str
    source: str = ""  # 未命中时可填写期望/定位来源


@dataclass
class ExtractedClaim:
    """从最终回答中提取出的待 grounding claim。"""

    value: str
    type: str
    normalized_values: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class CitationValidationResult:
    """Cite 校验结果。"""

    score: float = 1.0
    errors: list[CitationError] = field(default_factory=list)
    passed: bool = True
    route: str = "safe"  # "safe" | "warn" | "retry"


# ============ 解析 LLM 结构化输出 ============


def parse_cited_response(text: str) -> CitedResponse | None:
    """尝试将 LLM 输出解析为 CitedResponse JSON。

    支持两种格式：
      - 裸 JSON：`{"answer": "...", "citations": [...]}`
      - Markdown 代码块：` ```json {...} ``` `

    若解析失败（纯文本回复）返回 None。
    """
    if not text:
        return None

    stripped = text.strip()

    def _parse_dict(data: Any) -> CitedResponse | None:
        if not isinstance(data, dict):
            return None
        answer = data.get("answer")
        if not isinstance(answer, str) or not answer:
            return None
        citations = [
            Citation(
                value=str(c["value"]),
                type=str(c["type"]).upper(),
                source=str(c["source"]),
            )
            for c in data.get("citations", [])
            if isinstance(c, dict) and all(k in c for k in ("value", "type", "source"))
        ]
        return CitedResponse(answer=answer, citations=citations)

    if stripped.startswith("{"):
        try:
            return _parse_dict(json.loads(stripped))
        except json.JSONDecodeError:
            pass

    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if m:
        try:
            return _parse_dict(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass

    return None


# ============ 确定性校验 ============


def validate_citations(
    cited_response: CitedResponse,
    tool_sources: dict[str, str],
    context: str = "",
    *,
    entity_trie: EntityTrie | None = None,
) -> CitationValidationResult:
    """兼容旧接口：基于最终 answer 执行后置 grounding 校验。"""
    return validate_answer_grounding(
        cited_response.answer,
        tool_sources,
        context=context,
        entity_trie=entity_trie,
    )


def validate_answer_grounding(
    answer: str,
    tool_sources: dict[str, str],
    context: str = "",
    *,
    entity_trie: EntityTrie | None = None,
) -> CitationValidationResult:
    """对最终 answer 做后置 grounding 校验。

    校验逻辑：
    1. 从 answer 中提取实体、日期、数字 claim
    2. 将工具输出与上下文扁平化为事实来源
    3. 对每个 claim 做逆向匹配，判断是否有来源支撑
    """
    errors: list[CitationError] = []
    fact_sources = _build_fact_sources(tool_sources, context)

    for claim in extract_claims_from_answer(answer, entity_trie=entity_trie):
        matched_sources = _match_claim_sources(claim, fact_sources)
        if matched_sources:
            claim.sources = matched_sources
            continue
        errors.append(
            CitationError(
                type="UNGROUNDED",
                value=claim.value,
                source="fact_corpus",
            )
        )

    score = max(0.0, 1.0 - _ERROR_PENALTY * len(errors))
    if score >= _SAFE_THRESHOLD:
        route, passed = "safe", True
    elif score >= _WARN_THRESHOLD:
        route, passed = "warn", True
    else:
        route, passed = "retry", False

    return CitationValidationResult(
        score=score,
        errors=errors,
        passed=passed,
        route=route,
    )


def _normalize_compact_ymd_in_text(text: str) -> str:
    """将文中合法 YYYYMMDD 内联替换为 YYYY-MM-DD（与 answer 中 _DATE_RE 对齐）。"""
    return _YYYYMMDD_RE.sub(r"\1-\2-\3", text)


def _append_chinese_date_iso_aliases(text: str) -> str:
    """将文中出现的「YYYY年M月D日」等片段对应的 ISO（及年月）追加到末尾。

    工具/上下文中常见「2026年03月08日-至今」、JSON 内中文日期等，answer 侧常为
    ``2026-03-08`` 子串匹配；若不展开，无法与仅含中文日期的工具串对齐。
    """
    extras: list[str] = []
    seen: set[str] = set()
    for m in _CHINESE_DATE_RE.finditer(text):
        iso = _chinese_date_to_iso(m.group())
        if not iso:
            continue
        if iso in text or iso in seen:
            continue
        seen.add(iso)
        extras.append(iso)
    return text + (" " + " ".join(extras) if extras else "")


def _normalize_tool_source_dates(text: str) -> str:
    """规范化 tool source 文本中的日期表达，便于与 answer 中 ISO/中文日期对齐。

    1. YYYYMMDD → YYYY-MM-DD（内联替换）
    2. 中文绝对日期 → 在文末追加对应 ISO/年月别名（见 _append_chinese_date_iso_aliases）

    性能说明：对每条工具文本执行全量扫描；大数据集场景可改为 lazy 触发。
    """
    text = _normalize_compact_ymd_in_text(text)
    return _append_chinese_date_iso_aliases(text)


def _normalize_context_dates(text: str) -> str:
    """将 context 文本中所有时间表述展开为等价绝对形式，追加到原文末尾。

    覆盖：
    1. YYYYMMDD → YYYY-MM-DD（与工具侧共用 _normalize_compact_ymd_in_text）
    2. 中文绝对日期 → ISO 别名（_append_chinese_date_iso_aliases）
    3. 中文相对表述：上个月 / 上周 / 今天 → _relative_time_to_forms
    """
    text = _normalize_compact_ymd_in_text(text)
    text = _append_chinese_date_iso_aliases(text)
    extras: list[str] = []
    for rel in set(_RELATIVE_TIME_RE.findall(text)):
        for form in _relative_time_to_forms(rel):
            if form not in text and form not in extras:
                extras.append(form)
    return text + (" " + " ".join(extras) if extras else "")



def _build_fact_sources(
    tool_sources: dict[str, str],
    context: str,
) -> dict[str, str]:
    """构建扁平化事实来源文本。"""
    sources: dict[str, str] = {}
    if context:
        sources["context"] = _normalize_context_dates(context)
    for key, value in tool_sources.items():
        sources[f"tool_{key}"] = _normalize_tool_source_dates(value)
    return sources


def _decimal_str_no_noise(d: Decimal) -> str:
    """Decimal → 普通十进制字符串，供 JSON 子串匹配。"""
    s = format(d, "f").rstrip("0").rstrip(".")
    if s in ("-0", "-0.0"):
        return "0"
    return s


def _ratio_str_from_percent_points(compact: str) -> str | None:
    """百分数读数 → 小数比例（9.21% → 0.0921，92.1% → 0.921）。用 Decimal 避免 float 噪音。"""
    try:
        d = Decimal(compact) / Decimal(100)
    except (InvalidOperation, ValueError):
        return None
    return _decimal_str_no_noise(d)


def _normalize_number_forms(value: str, *, percent: bool = False) -> list[str]:
    """将数字文本归一化为可匹配的候选形式。

    percent=True 时追加「÷100」比例串，便于工具返回 0.0921、JSON 字段为小数等场景。
    """
    compact = value.replace(",", "").strip()
    if not compact:
        return []
    forms: list[str] = [value]
    if compact not in forms:
        forms.append(compact)
    try:
        numeric = float(compact)
    except ValueError:
        return _dedupe_forms(forms)
    if numeric.is_integer():
        integer_form = str(int(numeric))
        if integer_form not in forms:
            forms.append(integer_form)
    else:
        decimal_form = str(numeric)
        if decimal_form not in forms:
            forms.append(decimal_form)

    if percent:
        ratio = _ratio_str_from_percent_points(compact)
        if ratio and ratio not in forms:
            forms.append(ratio)

    return _dedupe_forms(forms)


def _dedupe_forms(forms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in forms:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def extract_claims_from_answer(
    answer: str,
    *,
    entity_trie: EntityTrie | None = None,
) -> list[ExtractedClaim]:
    """从回答中提取需要做 grounding 的 claim。"""
    claims: list[ExtractedClaim] = []
    seen: set[tuple[str, str]] = set()

    def _append(claim: ExtractedClaim) -> None:
        key = (claim.type, claim.value)
        if key in seen:
            return
        seen.add(key)
        claims.append(claim)

    if entity_trie is not None:
        for entity in entity_trie.extract(answer):
            _append(
                ExtractedClaim(value=entity, type="ENTITY", normalized_values=[entity])
            )

    for iso_date in set(_DATE_RE.findall(answer)):
        _append(
            ExtractedClaim(value=iso_date, type="TIME", normalized_values=[iso_date])
        )

    for m in _YYYYMMDD_RE.finditer(answer):
        compact = m.group(0)
        iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        _append(
            ExtractedClaim(
                value=compact,
                type="TIME",
                normalized_values=[compact, iso],
            )
        )

    for m in _CHINESE_DATE_RE.finditer(answer):
        chinese_date = m.group()
        normalized_values = [chinese_date]
        iso_equiv = _chinese_date_to_iso(chinese_date)
        if iso_equiv and iso_equiv not in normalized_values:
            normalized_values.append(iso_equiv)
        _append(
            ExtractedClaim(
                value=chinese_date,
                type="TIME",
                normalized_values=normalized_values,
            )
        )

    for rel in set(_RELATIVE_TIME_RE.findall(answer)):
        _append(
            ExtractedClaim(
                value=rel,
                type="TIME",
                normalized_values=list(_relative_time_to_forms(rel)),
            )
        )

    for number, is_percent in _extract_number_tokens(answer):
        if abs(number) < _MIN_BUSINESS_NUMBER and not is_percent:
            continue
        value = str(int(number)) if float(number).is_integer() else str(number)
        _append(
            ExtractedClaim(
                value=value,
                type="NUMBER",
                normalized_values=_normalize_number_forms(value, percent=is_percent),
            )
        )

    return claims


def _match_claim_sources(
    claim: ExtractedClaim,
    fact_sources: dict[str, str],
) -> list[str]:
    """在扁平化事实来源中查找 claim 的支撑来源。"""
    matched: list[str] = []
    candidates = claim.normalized_values or [claim.value]
    for source, text in fact_sources.items():
        if any(candidate and candidate in text for candidate in candidates):
            matched.append(source)
    return matched



def _relative_time_to_forms(expr: str) -> set[str]:
    """将中文相对时间表述转换为等价的绝对日期表示集合，用于 citation 匹配。

    将 answer 中的相对表述展开为若干绝对日期/年月等形式，
    任一等价形式出现在事实语料中即视为该 TIME claim 可 grounding。
    """
    today = date.today()
    forms: set[str] = {expr}

    if expr in ("上个月", "上月"):
        last = today.replace(day=1) - timedelta(days=1)
        forms |= {
            last.strftime("%Y-%m"),
            last.strftime("%Y年%m月"),
            f"{last.year}年{last.month}月",
            last.replace(day=1).isoformat(),
        }
    elif expr in ("上上个月", "上上月"):
        first_of_last = today.replace(day=1) - timedelta(days=1)
        two_months_ago = first_of_last.replace(day=1) - timedelta(days=1)
        forms |= {
            two_months_ago.strftime("%Y-%m"),
            two_months_ago.replace(day=1).isoformat(),
        }
    elif expr in ("本月", "这个月", "这月"):
        forms |= {
            today.strftime("%Y-%m"),
            f"{today.year}年{today.month}月",
            today.replace(day=1).isoformat(),
        }
    elif expr in ("下个月", "下月"):
        if today.month == 12:
            nxt = today.replace(year=today.year + 1, month=1, day=1)
        else:
            nxt = today.replace(month=today.month + 1, day=1)
        forms |= {nxt.strftime("%Y-%m"), nxt.isoformat()}
    elif expr in ("今天", "今日"):
        forms.add(today.isoformat())
    elif expr in ("昨天", "昨日"):
        forms.add((today - timedelta(days=1)).isoformat())
    elif expr == "前天":
        forms.add((today - timedelta(days=2)).isoformat())
    elif expr == "大前天":
        forms.add((today - timedelta(days=3)).isoformat())
    elif expr in ("本周", "这周"):
        monday = today - timedelta(days=today.weekday())
        for i in range(7):
            forms.add((monday + timedelta(days=i)).isoformat())
    elif expr == "上周":
        monday = today - timedelta(days=today.weekday() + 7)
        for i in range(7):
            forms.add((monday + timedelta(days=i)).isoformat())
    elif expr == "下周":
        monday = today - timedelta(days=today.weekday() - 7)
        for i in range(7):
            forms.add((monday + timedelta(days=i)).isoformat())
    elif expr in ("上季度", "上个季度"):
        q = (today.month - 1) // 3
        year = today.year if q > 0 else today.year - 1
        q = q if q > 0 else 4
        start_month = (q - 1) * 3 + 1
        forms |= {f"{year}-{start_month:02d}", f"{year}年Q{q}"}
    elif expr in ("本季度", "这个季度"):
        q = (today.month - 1) // 3 + 1
        forms.add(f"{today.year}年Q{q}")
    elif expr == "去年":
        forms |= {str(today.year - 1), f"{today.year - 1}年"}
    elif expr == "今年":
        forms |= {str(today.year), f"{today.year}年"}
    elif expr == "明年":
        forms |= {str(today.year + 1), f"{today.year + 1}年"}
    elif expr == "前年":
        forms |= {str(today.year - 2), f"{today.year - 2}年"}

    return forms


# ============ 数字提取工具函数 ============


def _extract_number_tokens(text: str) -> list[tuple[float, bool]]:
    """提取数值 token：(值, 是否为百分数写法，如 9.21%)。

    与 extract_numbers_from_text 共用过滤规则（年份、YYYYMMDD）。"""
    if not text:
        return []
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    pattern = re.compile(r"(?<!\w)(-?\d+(?:\.\d+)?)(\s*[%％])?(?!\w)")
    results: list[tuple[float, bool]] = []
    for m in pattern.finditer(cleaned):
        raw, pct = m.group(1), m.group(2)
        if re.fullmatch(r"\d{4}", raw) and 1900 <= int(raw) <= 2100:
            continue
        if _YYYYMMDD_RE.fullmatch(raw):
            continue
        try:
            results.append((float(raw), pct is not None))
        except ValueError:
            pass
    return results


def extract_numbers_from_text(text: str) -> list[float]:
    """提取文本中的数字（支持千分位、小数、负数、百分号）。"""
    return [n for n, _ in _extract_number_tokens(text)]



# ============ 相对时间转换 ============


_WEEKDAY_MAP: dict[str, int] = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}
_RELATIVE_WEEK_RE = re.compile(r"^(本周|上周|下周)([一二三四五六日天])$")


def resolve_relative_time(text: str) -> str | None:
    """将中文相对时间表述转换为绝对日期（YYYY-MM-DD 格式）。

    支持：今天/今日、昨天/昨日、前天、大前天、本/上/下周X。
    不支持的表述返回 None。
    """
    text = text.strip()
    today = date.today()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text

    _DAY_OFFSET: dict[str, int] = {
        "今天": 0,
        "今日": 0,
        "昨天": -1,
        "昨日": -1,
        "前天": -2,
        "大前天": -3,
    }
    if text in _DAY_OFFSET:
        return (today + timedelta(days=_DAY_OFFSET[text])).isoformat()

    m = _RELATIVE_WEEK_RE.match(text)
    if m:
        prefix, weekday_char = m.group(1), m.group(2)
        target_weekday = _WEEKDAY_MAP[weekday_char]
        this_monday = today - timedelta(days=today.weekday())
        target = this_monday + timedelta(days=target_weekday)
        if prefix == "上周":
            target -= timedelta(weeks=1)
        elif prefix == "下周":
            target += timedelta(weeks=1)
        return target.isoformat()

    return None


# ============ Trie 实体提取器 ============


class EntityTrie:
    """基于 flashtext 的实体提取器，支持 CSV 白名单加载。

    使用两个 KeywordProcessor：
    - 名称处理器（case_insensitive）：匹配归一化后的实体名称
    - 代码处理器（case_sensitive）：匹配股票代码等精确标识符
    """

    def __init__(self) -> None:
        self._processor = KeywordProcessor(case_sensitive=False)
        self._code_processor = KeywordProcessor(case_sensitive=True)

    @staticmethod
    def _normalize_name(name: str) -> str:
        """归一化实体名称：全角→半角，去除空格。"""
        result = unicodedata.normalize("NFKC", name)
        return "".join(result.split())

    def load_from_csv(
        self,
        csv_path: Path,
        *,
        name_column: str = "name",
        code_column: str = "code",
    ) -> None:
        """从 CSV 文件加载实体白名单（需包含 name 和 code 列）。"""
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_name = row.get(name_column, "").strip()
                code = row.get(code_column, "").strip()
                if raw_name:
                    normalized = self._normalize_name(raw_name)
                    self._processor.add_keyword(normalized, normalized)
                if code:
                    self._code_processor.add_keyword(code, code)

    def add_keywords(self, keywords: list[str]) -> None:
        """手动添加关键词。"""
        for kw in keywords:
            normalized = self._normalize_name(kw)
            self._processor.add_keyword(normalized, normalized)

    def extract(self, text: str) -> list[str]:
        """从文本中提取所有匹配的实体，返回去重有序列表。"""
        if not text:
            return []
        normalized_text = self._normalize_name(text)
        names = self._processor.extract_keywords(normalized_text)
        codes = self._code_processor.extract_keywords(text)
        seen: set[str] = set()
        result: list[str] = []
        for entity in names + codes:
            if entity not in seen:
                seen.add(entity)
                result.append(entity)
        return result


# ============ 框架级辅助：session.state → 工具文本证据 ============


def _build_context_from_session(
    session: Any,
    context_turns: int = 3,
) -> str:
    """从 session.messages 提取最近 N 轮用户消息，拼接为 context 字符串。

    多轮对话中用户可能引用之前轮次的日期/实体，仅取当前轮会误报未 grounding。
    """
    from .types import MessageRole

    user_contents = [
        msg.content
        for msg in session.messages
        if msg.role == MessageRole.USER and msg.content
    ]
    recent = user_contents[-context_turns:] if context_turns > 0 else user_contents
    return "\n".join(recent)


def _build_tool_sources_from_session(session: Any) -> dict[str, str]:
    """从 session.messages 中最后一条 USER 之后的 ASSISTANT（tool_calls）+ TOOL 消息构建事实语料。

    按 tool_call_id 将 ASSISTANT.tool_calls 的 name 与 TOOL.tool_results 的 content 配对，
    同名工具多次调用用 ``\\n---\\n`` 拼接。返回 ``{tool_<name>: normalized_text}``。
    """
    from .types import MessageRole

    last_user_idx = -1
    for i, msg in enumerate(session.messages):
        if msg.role == MessageRole.USER:
            last_user_idx = i

    if last_user_idx < 0:
        return {}

    tc_name_by_id: dict[str, str] = {}
    merged: dict[str, list[str]] = {}

    for msg in session.messages[last_user_idx + 1:]:
        if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_name_by_id[tc.id] = tc.name
        elif msg.role == MessageRole.TOOL and msg.tool_results:
            for tr in msg.tool_results:
                name = tc_name_by_id.get(tr.tool_call_id, "unknown")
                c = tr.content
                text = json.dumps(c, ensure_ascii=False) if isinstance(c, (dict, list)) else str(c)
                merged.setdefault(name, []).append(_normalize_tool_source_dates(text))

    return {
        f"tool_{name}": "\n---\n".join(chunks) for name, chunks in merged.items()
    }


# ============ 框架级 Hook 工厂 ============


def create_citation_validation_hook(
    entity_trie: "EntityTrie | None" = None,
    *,
    context_turns: int = 3,
) -> "BeforeCompleteCallback":
    """工厂：返回 BeforeCompleteCallback，在最终回答落地前做后置 grounding 校验。

    事实语料中的工具侧数据从 ``session.messages`` 中最后一条 USER 之后的 TOOL 消息提取，
    无需 Runner 额外注入或 agent 侧枚举 state key。

    每轮用户输入内最多触发 **一次** 校验失败→注入反馈→重试：首次失败会写入
    ``session.state['temp:grounding_reflect_used']``（随 ``strip_temp_state`` 在 run 结束时清理）。
    下一轮 ``before_complete`` 若该标记已存在则 **跳过校验** 且不再 ``halt``，避免校验反馈进入
    ``context`` 后干扰子串比对；第二次模型输出直接落地。Runner 对每次 ``halt`` 均会注入反馈并
    ``continue``，故重复注入须由本 hook 通过上述标记自行约束（每用户轮至多一次反思）。

    Args:
        entity_trie:   EntityTrie 实体提取器（可选，None 时跳过 ENTITY 校验）
        context_turns: 参与校验的最近用户消息轮数（与用户 context 拼接）

    Returns:
        BeforeCompleteCallback — 注入 RunnerCallbacks.before_complete
    """
    _REFLECT_FLAG = "temp:grounding_reflect_used"

    async def _hook(
        ctx: "CallbackContext",
        *,
        response: "AgentMessage",
    ) -> "CallbackResult | None":
        from .callbacks import CallbackResult
        from .types import AgentMessage as _AgentMessage

        if ctx.session.state.get(_REFLECT_FLAG):
            logger.info(
                "[CITATION_HOOK] skip validation (already reflected once this user turn)"
            )
            return None

        content = response.content or ""
        tool_sources = _build_tool_sources_from_session(ctx.session)
        # 取最近 context_turns 轮用户消息作为 context，覆盖跨轮引用场景
        user_input: str = _build_context_from_session(ctx.session, context_turns)

        result = validate_answer_grounding(
            content,
            tool_sources,
            context=user_input,
            entity_trie=entity_trie,
        )

        if result.errors:
            for e in result.errors:
                logger.warning(
                    "[CITATION_HOOK] %s value=%r source=%s",
                    e.type,
                    e.value,
                    e.source or "N/A",
                )
        logger.info(
            "[CITATION_HOOK] route=%s score=%.2f errors=%d",
            result.route,
            result.score,
            len(result.errors),
        )

        if result.route == "retry":
            ctx.session.state[_REFLECT_FLAG] = True
            error_lines = [
                f"- {e.type}: {e.value!r} (source={e.source or 'N/A'})"
                for e in result.errors
            ]
            feedback = "[回答事实出现偏差，请检查回答内容与工具信息是否一致]\n" + "\n".join(
                error_lines
            )
            return CallbackResult(
                halt=True,
                response=_AgentMessage.user(content=feedback),
            )

        return None

    return _hook  # type: ignore[return-value]
