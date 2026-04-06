"""
输出验证层 — 单轮闭环 Cite 幻觉检测

架构：LLM 生成 (answer + citations) → validate_citations（确定性校验）→ score + errors

核心原则：
  1. 模型负责生成证据（cite）
  2. 系统负责验证证据（deterministic）
  3. 评分基于工具输出，不由模型决定

框架级扩展：
  - _build_tool_sources: 从 session.state 提取工具文本证据
  - create_citation_validation_hook: 工厂函数，返回 BeforeCompleteCallback
"""

from __future__ import annotations

import csv
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

from flashtext import KeywordProcessor

from .types import AgentToolResult

if TYPE_CHECKING:
    from .callbacks import BeforeCompleteCallback, CallbackContext, CallbackResult
    from .types import AgentMessage

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# 中文日期（从最长到最短，保证 greedy 优先匹配完整形式）：
#   YYYY年M月D日 | YYYY年M月 | YYYY年
_CHINESE_DATE_RE = re.compile(r"\d{4}年\d{1,2}月(?:\d{1,2}日)?|\d{4}年")
# 紧凑型 8 位日期 YYYYMMDD（工具数据常见格式），限定年份范围避免误匹配普通整数
# TODO(perf): _normalize_tool_source_dates 对每条工具文本做全量 re.sub，
#             大数据集场景下可改为 lazy 构建（仅在有 tool_ source 的 citation 时触发）
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


_MIN_BUSINESS_NUMBER = 100.0
# 每个校验错误的扣分（score = max(0, 1.0 - penalty * n_errors)）
_ERROR_PENALTY = 0.2
# 路由阈值（score 0–1 区间）
_SAFE_THRESHOLD = 0.8   # >= 0.8 → safe
_WARN_THRESHOLD = 0.6   # >= 0.6 → warn；< 0.6 → retry


# ============ Cite 数据结构 ============


@dataclass
class Citation:
    """LLM 输出的单条引用。"""

    value: str
    type: str    # "ENTITY" | "TIME" | "NUMBER"
    source: str  # "tool_{tool_key}" | "context"


@dataclass
class CitedResponse:
    """LLM 带 citations 的结构化输出。"""

    answer: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class CitationError:
    """单个校验错误。"""

    type: str    # "CITE_NOT_FOUND" | "UNCITED"
    value: str
    source: str = ""  # 仅 CITE_NOT_FOUND 时填写


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
    """确定性校验：验证 citations 真实性并检测 answer 中未标注的关键元素。

    Args:
        cited_response: LLM 带 citations 的输出（空 citations 代表纯文本回退）
        tool_sources:   {tool_key: text} 工具数据文本；citation.source="tool_{key}" 对应此字典
        context:        用户输入文本；citation.source="context" 对应此值
        entity_trie:    EntityTrie，用于从 answer 中提取未标注实体

    Returns:
        CitationValidationResult（score, errors, passed, route）
    """
    errors: list[CitationError] = []
    answer = cited_response.answer

    # Step1：校验每条 citation 是否真实存在于声明的来源
    for c in cited_response.citations:
        src_text = _resolve_source_text(c.source, tool_sources, context)
        if src_text is None or c.value not in src_text:
            errors.append(
                CitationError(type="CITE_NOT_FOUND", value=c.value, source=c.source)
            )

    cited_values = {c.value for c in cited_response.citations}

    # Step2 + Step4：从 answer 提取关键元素，检测未标注（UNCITED）
    # 时间：ISO 格式 YYYY-MM-DD
    for iso_date in set(_DATE_RE.findall(answer)):
        if not _is_cited(iso_date, cited_values):
            errors.append(CitationError(type="UNCITED", value=iso_date))

    # 时间：中文日期 YYYY年M月D日 / YYYY年M月 / YYYY年
    # 同时检查中文形式本身及其 ISO 等价形式，避免因格式差异误报 UNCITED
    for m in _CHINESE_DATE_RE.finditer(answer):
        chinese_date = m.group()
        iso_equiv = _chinese_date_to_iso(chinese_date)
        candidate_forms = {chinese_date}
        if iso_equiv:
            candidate_forms.add(iso_equiv)
        if not any(_is_cited(f, cited_values) for f in candidate_forms):
            errors.append(CitationError(type="UNCITED", value=chinese_date))

    # 时间：中文相对时间表述（上个月、昨天、本周…）
    # 模型应在 citations.value 中使用绝对日期，所以校验时将相对表述解析为等价绝对形式再比对
    for rel in set(_RELATIVE_TIME_RE.findall(answer)):
        equivalent_forms = _relative_time_to_forms(rel)
        if not any(_is_cited(f, cited_values) for f in equivalent_forms):
            errors.append(CitationError(type="UNCITED", value=rel))

    # 数字：业务量级（abs >= _MIN_BUSINESS_NUMBER）
    for n in extract_numbers_from_text(answer):
        if abs(n) >= _MIN_BUSINESS_NUMBER:
            n_str = str(int(n)) if float(n).is_integer() else str(n)
            if not _is_cited(n_str, cited_values):
                errors.append(CitationError(type="UNCITED", value=n_str))

    # 实体（依赖 EntityTrie，无 Trie 时跳过）
    if entity_trie is not None:
        for e in entity_trie.extract(answer):
            if not _is_cited(e, cited_values):
                errors.append(CitationError(type="UNCITED", value=e))

    # Step5：计算得分与路由
    score = max(0.0, 1.0 - _ERROR_PENALTY * len(errors))
    if score >= _SAFE_THRESHOLD:
        route, passed = "safe", True
    elif score >= _WARN_THRESHOLD:
        route, passed = "warn", True
    else:
        route, passed = "retry", False

    return CitationValidationResult(score=score, errors=errors, passed=passed, route=route)


def _normalize_tool_source_dates(text: str) -> str:
    """将 tool source 文本中 YYYYMMDD 格式日期内联替换为 YYYY-MM-DD。

    工具数据通常是 JSON 序列化文本，直接替换后 citation.value（ISO 格式）
    能在原位命中，无需追加。

    性能说明：对每条工具文本执行全量 re.sub，当工具返回数据量较大时有一定开销。
    优化方向：可改为 lazy 触发（仅当存在 tool_ source 的 citation 时才归一化）。
    """
    return _YYYYMMDD_RE.sub(r"\1-\2-\3", text)


def _normalize_context_dates(text: str) -> str:
    """将 context 文本中所有时间表述展开为等价绝对形式，追加到原文末尾。

    覆盖三类情形：
    1. 中文绝对日期：2026年3月15日 → 2026-03-15
    2. 中文相对表述：上个月 / 上周 / 今天 → 所有等价绝对形式（复用 _relative_time_to_forms）
    3. ISO 日期无需处理，本身已可匹配

    这样 citation.value 填 ISO 日期（如 "2026-03-01"）时，不论用户输入是
    "2026年3月1日" 还是 "上个月" 都能在 src_text 中命中，避免误报 CITE_NOT_FOUND。
    """
    extras: list[str] = []

    # 中文绝对日期 → ISO 等价形式
    for m in _CHINESE_DATE_RE.finditer(text):
        iso = _chinese_date_to_iso(m.group())
        if iso and iso not in text:
            extras.append(iso)

    # 中文相对表述 → 所有等价绝对形式
    for rel in set(_RELATIVE_TIME_RE.findall(text)):
        for form in _relative_time_to_forms(rel):
            if form not in text and form not in extras:
                extras.append(form)

    return text + (" " + " ".join(extras) if extras else "")


def _resolve_source_text(
    source: str,
    tool_sources: dict[str, str],
    context: str,
) -> str | None:
    """根据 citation.source 解析对应的文本内容，并对各类日期格式做归一化。

    - context 源：中文绝对日期 + 相对表述 → 追加 ISO 等价形式
    - tool 源：YYYYMMDD → 内联替换为 YYYY-MM-DD
    """
    if source == "context":
        return _normalize_context_dates(context)
    key = source[5:] if source.startswith("tool_") else source
    raw = tool_sources.get(key)
    return _normalize_tool_source_dates(raw) if raw is not None else None


def _is_cited(value: str, cited_values: set[str]) -> bool:
    """检查 value 是否已被任一 citation 覆盖（精确或子串匹配）。"""
    if value in cited_values:
        return True
    for cv in cited_values:
        if value in cv or cv in value:
            return True
    return False


def _relative_time_to_forms(expr: str) -> set[str]:
    """将中文相对时间表述转换为等价的绝对日期表示集合，用于 citation 匹配。

    模型应在 citations.value 中使用绝对日期（如 "2026-03-01"），
    此函数将 answer 中的相对表述解析为所有可能的等价绝对形式，
    只要任意一种等价形式被 cited，则认为该时间已被正确引用。
    """
    today = date.today()
    forms: set[str] = {expr}

    if expr in ("上个月", "上月"):
        last = (today.replace(day=1) - timedelta(days=1))
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


def extract_numbers_from_text(text: str) -> list[float]:
    """提取文本中的数字（支持千分位、小数、负数、百分号）。"""
    if not text:
        return []
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    pattern = r"(?<!\w)(-?\d+(?:\.\d+)?)(?:\s*%)?(?!\w)"
    results = []
    for m in re.findall(pattern, cleaned):
        if re.fullmatch(r"\d{4}", m) and 1900 <= int(m) <= 2100:
            continue
        try:
            results.append(float(m))
        except ValueError:
            pass
    return results


def _collect_numbers(
    data: Union[str, int, float, dict[str, Any], list[Any], tuple[Any, ...]],
    output: set[float],
) -> None:
    """递归收集数据结构中的所有数字值。"""
    if isinstance(data, (int, float)):
        if data != 0:
            output.add(float(data))
    elif isinstance(data, dict):
        for v in data.values():
            _collect_numbers(v, output)
    elif isinstance(data, (list, tuple)):
        for item in data:
            _collect_numbers(item, output)
    elif isinstance(data, str):
        for n in extract_numbers_from_text(data):
            output.add(n)


# ============ 相对时间转换 ============


_WEEKDAY_MAP: dict[str, int] = {
    "一": 0, "二": 1, "三": 2, "四": 3,
    "五": 4, "六": 5, "日": 6, "天": 6,
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
        "今天": 0, "今日": 0,
        "昨天": -1, "昨日": -1,
        "前天": -2, "大前天": -3,
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

    多轮对话中用户可能引用之前轮次的日期/实体，仅取当前轮会导致跨轮
    context 引用误报 CITE_NOT_FOUND。
    """
    from .types import MessageRole

    user_contents = [
        msg.content
        for msg in session.messages
        if msg.role == MessageRole.USER and msg.content
    ]
    recent = user_contents[-context_turns:] if context_turns > 0 else user_contents
    return "\n".join(recent)


def _build_tool_sources(
    state: dict[str, Any],
    tool_keys: set[str],
) -> dict[str, str]:
    """从 session.state 中提取工具数据快照，转为 {tool_key: text} 供 validate_citations 使用。"""
    sources: dict[str, str] = {}
    for key in tool_keys:
        data = state.get(key)
        if data is None:
            continue
        sources[key] = json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data)
    return sources


# ============ 框架级 Hook 工厂 ============


def create_citation_validation_hook(
    tool_keys: set[str],
    entity_trie: "EntityTrie | None" = None,
    *,
    context_turns: int = 3,
) -> "BeforeCompleteCallback":
    """工厂：返回一个 BeforeCompleteCallback，在最终回答落地前校验 citations。

    Args:
        tool_keys:     session.state 中要扫描的工具 key 集合（agent 自定义）
        entity_trie:   EntityTrie 实体提取器（可选，None 时跳过 ENTITY 校验）
        context_turns: 用于 source="context" 校验的历史用户消息轮数，默认 3

    Returns:
        BeforeCompleteCallback — 注入 RunnerCallbacks.before_complete
    """
    async def _hook(
        ctx: "CallbackContext",
        *,
        response: "AgentMessage",
    ) -> "CallbackResult | None":
        from .callbacks import CallbackResult
        from .types import AgentMessage as _AgentMessage

        content = response.content or ""
        raw: list[Any] = ctx.session.state.get("_pending_citations", [])

        citations = [
            Citation(
                value=str(c["value"]),
                type=str(c.get("type", "")).upper(),
                source=str(c.get("source", "")),
            )
            for c in raw
            if isinstance(c, dict) and "value" in c
        ]
        cited = CitedResponse(answer=content, citations=citations)
        tool_sources = _build_tool_sources(ctx.session.state, tool_keys)
        # 取最近 context_turns 轮用户消息作为 context，覆盖跨轮引用场景
        user_input: str = _build_context_from_session(ctx.session, context_turns)

        result = validate_citations(
            cited,
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
            error_lines = [
                f"- {e.type}: {e.value!r} (source={e.source or 'N/A'})"
                for e in result.errors
            ]
            feedback = "[引用校验失败，请修正回答后重新输出]\n" + "\n".join(error_lines)
            ctx.session.state.pop("_pending_citations", None)
            return CallbackResult(
                halt=True,
                response=_AgentMessage.user(content=feedback),
            )

        return None

    return _hook  # type: ignore[return-value]
