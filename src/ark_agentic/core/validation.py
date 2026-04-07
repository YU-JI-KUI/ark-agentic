"""
输出验证层 — 单轮后置 grounding（纯文本 answer）

架构：从 answer 提取实体/日期/数字 claim → 与扁平化 tool_sources + 用户 context 做子串命中 → score + route

核心原则：
  1. 模型仅输出自然语言；不由模型声明 citation JSON
  2. 校验为确定性逆向匹配（ClaimExtractor 协议）
  3. 评分：各类 claim 带权（实体 20 / 日期 5 / 数字 10），
     ``score = 100 × (1 - 未 grounding 加权 / 全部 claim 加权)``，阈值 80/60 划分 safe/warn/retry

兼容：`validate_citations(CitedResponse, ...)` 仅读取 `.answer`，委托 `validate_answer_grounding`；`parse_cited_response` 供旧格式解析。

框架级扩展：
  - create_citation_validation_hook: BeforeCompleteCallback 工厂，
    从 session.messages 中最后一条 USER 之后的 TOOL 消息提取工具事实语料
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .callbacks import BeforeCompleteCallback, CallbackContext, CallbackResult
    from .types import AgentMessage

# 向后兼容 re-export：外部 import 路径保持 from ark_agentic.core.validation import ...
from .utils.entities import EntityTrie, EntityClaimExtractor  # noqa: F401
from .utils.dates import (  # noqa: F401
    DateClaimExtractor,
    resolve_relative_time,
    relative_time_to_forms as _relative_time_to_forms,
)
from .utils.numbers import (  # noqa: F401
    NumberClaimExtractor,
    extract_numbers_from_text,
)

logger = logging.getLogger(__name__)

# grounding 评分：NUMBER=10, TIME=5, ENTITY=20；总分 0–100
_GROUNDING_WEIGHT_ENTITY = 20
_GROUNDING_WEIGHT_TIME = 5
_GROUNDING_WEIGHT_NUMBER = 10
_SAFE_THRESHOLD = 80.0
_WARN_THRESHOLD = 60.0


def _grounding_weight_for_claim_type(claim_type: str) -> int:
    if claim_type == "ENTITY":
        return _GROUNDING_WEIGHT_ENTITY
    if claim_type == "TIME":
        return _GROUNDING_WEIGHT_TIME
    if claim_type == "NUMBER":
        return _GROUNDING_WEIGHT_NUMBER
    return _GROUNDING_WEIGHT_NUMBER


# ============ ClaimExtractor 协议 ============


@runtime_checkable
class ClaimExtractor(Protocol):
    """从 answer 中提取特定类型的 claim，并对事实来源文本做格式归一化。"""

    def extract_claims(self, text: str) -> list[ExtractedClaim]: ...
    def normalize_source(self, text: str, *, is_context: bool = False) -> str: ...


# ============ 数据结构 ============


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
    source: str = ""


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

    score: float = 100.0  # 0–100，见 validate_answer_grounding 加权公式
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


def _default_extractors(
    entity_trie: EntityTrie | None = None,
) -> list[ClaimExtractor]:
    """返回 grounding 用的默认 ``ClaimExtractor`` 链。为将来幻觉相关检测提供统一抽取入口。

    顺序：若提供 ``entity_trie`` 则最前为 ``EntityClaimExtractor``（ENTITY），
    其后固定为 ``DateClaimExtractor``（TIME）与 ``NumberClaimExtractor``（NUMBER）。
    ``entity_trie`` 为 ``None`` 时不做实体 claim 提取，仅日期与数字。

    Args:
        entity_trie: 可选白名单实体提取器；为 ``None`` 时列表不含实体提取器。

    Returns:
        供 ``validate_answer_grounding`` / ``extract_claims_from_answer`` / hook 使用的提取器列表。
    """
    extractors: list[ClaimExtractor] = [DateClaimExtractor(), NumberClaimExtractor()]
    if entity_trie is not None:
        extractors.insert(0, EntityClaimExtractor(entity_trie))
    return extractors


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
    extractors: list[ClaimExtractor] | None = None,
) -> CitationValidationResult:
    """对最终 answer 做后置 grounding 校验。

    校验逻辑：
    1. 从 answer 中通过各 ClaimExtractor 提取实体、日期、数字 claim
    2. 将工具输出与上下文通过各 extractor 归一化后扁平化为事实来源
    3. 对每个 claim 做逆向匹配，判断是否有来源支撑
    """
    if extractors is None:
        extractors = _default_extractors(entity_trie)

    errors: list[CitationError] = []
    fact_sources = _build_fact_sources(tool_sources, context, extractors)
    claims = extract_claims_from_answer(answer, extractors=extractors)

    total_weight = sum(_grounding_weight_for_claim_type(c.type) for c in claims)
    ungrounded_weight = 0.0
    for claim in claims:
        matched_sources = _match_claim_sources(claim, fact_sources)
        if matched_sources:
            claim.sources = matched_sources
            continue
        w = _grounding_weight_for_claim_type(claim.type)
        ungrounded_weight += w
        errors.append(
            CitationError(
                type="UNGROUNDED",
                value=claim.value,
                source="fact_corpus",
            )
        )

    # score = 100 - Σ(分类未 grounding 个数×该分类权重) / 总个数
    # 其中「总个数」取为全部 claim 的加权和（与分子同量纲），使全错时 score→0
    if total_weight <= 0:
        score = 100.0
    else:
        score = max(0.0, min(100.0, 100.0 * (1.0 - ungrounded_weight / total_weight)))

    if score >= _SAFE_THRESHOLD:
        route, passed = "safe", True
    elif score >= _WARN_THRESHOLD:
        route, passed = "warn", True
    else:
        route, passed = "retry", False

    if errors and total_weight > 0:
        for claim in claims:
            if claim.sources:
                continue
            w = _grounding_weight_for_claim_type(claim.type)
            delta = 100.0 * w / total_weight
            logger.warning(
                "[GROUNDING] 丢分 type=%s value=%r weight=%d score_delta=%.2f",
                claim.type,
                claim.value,
                w,
                delta,
            )
        logger.warning(
            "[GROUNDING] 汇总 total_weight=%.0f ungrounded_weight=%.0f score=%.2f route=%s",
            total_weight,
            ungrounded_weight,
            score,
            route,
        )

    return CitationValidationResult(
        score=score,
        errors=errors,
        passed=passed,
        route=route,
    )


def extract_claims_from_answer(
    answer: str,
    *,
    entity_trie: EntityTrie | None = None,
    extractors: list[ClaimExtractor] | None = None,
) -> list[ExtractedClaim]:
    """从回答中提取需要做 grounding 的 claim。"""
    if extractors is None:
        extractors = _default_extractors(entity_trie)

    claims: list[ExtractedClaim] = []
    seen: set[tuple[str, str]] = set()
    for ext in extractors:
        for claim in ext.extract_claims(answer):
            key = (claim.type, claim.value)
            if key not in seen:
                seen.add(key)
                claims.append(claim)
    return claims


def _build_fact_sources(
    tool_sources: dict[str, str],
    context: str,
    extractors: list[ClaimExtractor],
) -> dict[str, str]:
    """构建扁平化事实来源文本（各 extractor 依次归一化）。"""
    sources: dict[str, str] = {}
    if context:
        normalized = context
        for ext in extractors:
            normalized = ext.normalize_source(normalized, is_context=True)
        sources["context"] = normalized
    for key, value in tool_sources.items():
        normalized = value
        for ext in extractors:
            normalized = ext.normalize_source(normalized, is_context=False)
        sources[f"tool_{key}"] = normalized
    return sources


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


# ============ 框架级辅助：session → 工具文本证据 ============


def _build_context_from_session(
    session: Any,
    context_turns: int = 3,
) -> str:
    """从 session.messages 提取最近 N 轮用户消息，拼接为 context 字符串。"""
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
    from .utils.dates import normalize_tool_source

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
                merged.setdefault(name, []).append(normalize_tool_source(text))

    return {
        f"tool_{name}": "\n---\n".join(chunks) for name, chunks in merged.items()
    }


# ============ 框架级 Hook 工厂 ============


def create_citation_validation_hook(
    entity_trie: "EntityTrie | None" = None,
    *,
    extractors: "list[ClaimExtractor] | None" = None,
    context_turns: int = 3,
) -> "BeforeCompleteCallback":
    """工厂：返回 BeforeCompleteCallback，在最终回答落地前做后置 grounding 校验。

    事实语料中的工具侧数据从 ``session.messages`` 中最后一条 USER 之后的 TOOL 消息提取，
    无需 Runner 额外注入或 agent 侧枚举 state key。

    每轮用户输入内最多触发 **一次** 校验失败→注入反馈→重试。

    Args:
        entity_trie:   EntityTrie 实体提取器（可选，None 时跳过 ENTITY 校验）
        extractors:    自定义 ClaimExtractor 列表（优先于 entity_trie 构建默认列表）
        context_turns: 参与校验的最近用户消息轮数

    Returns:
        BeforeCompleteCallback — 注入 RunnerCallbacks.before_complete
    """
    _extractors = extractors if extractors is not None else _default_extractors(entity_trie)
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
        user_input: str = _build_context_from_session(ctx.session, context_turns)

        result = validate_answer_grounding(
            content,
            tool_sources,
            context=user_input,
            extractors=_extractors,
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
