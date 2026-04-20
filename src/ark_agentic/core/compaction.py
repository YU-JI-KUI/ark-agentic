"""上下文压缩: Token 估算、自适应分块、LLM 摘要"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, TYPE_CHECKING

from .llm.sampling import SamplingConfig
from .types import AgentMessage, MessageRole, ToolResultType

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


# ============ 常量 ============

# 安全边界：token 估算可能不准确，留 20% 余量
SAFETY_MARGIN = 1.2

# 基础分块比例（历史占上下文的比例）
BASE_CHUNK_RATIO = 0.4
MIN_CHUNK_RATIO = 0.15

# 默认摘要回退文本
DEFAULT_SUMMARY_FALLBACK = "暂无历史记录。"


# ============ Token 估算 ============


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量

    简化实现：按字符数估算
    - 中文：约 0.7 token/字
    - 英文：约 1.3 token/词
    - 结构开销：每条消息 +4 token

    生产环境应使用 tiktoken 或模型 tokenizer。
    """
    if not text:
        return 0

    # 统计中文字符
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")

    # 非中文按词估算
    non_chinese = text
    for c in text:
        if "\u4e00" <= c <= "\u9fff":
            non_chinese = non_chinese.replace(c, " ")

    words = len(non_chinese.split())

    # 中文约 0.7 token/字，英文约 1.3 token/词
    return int(chinese_chars * 0.7 + words * 1.3)


def estimate_message_tokens(message: AgentMessage) -> int:
    """估算单条消息的 token 数量"""
    tokens = 0

    if message.content:
        tokens += estimate_tokens(message.content)

    if message.thinking:
        tokens += estimate_tokens(message.thinking)

    if message.tool_calls:
        for tc in message.tool_calls:
            tokens += estimate_tokens(tc.name)
            tokens += estimate_tokens(str(tc.arguments))

    if message.tool_results:
        for tr in message.tool_results:
            tokens += estimate_tokens(str(tr.content))

    # 消息结构开销
    tokens += 4

    return tokens


# ============ 消息分块 ============


@dataclass
class MessageChunk:
    """消息分块"""

    messages: list[AgentMessage]
    token_count: int = 0
    is_summarized: bool = False
    summary: str | None = None

    @property
    def message_count(self) -> int:
        return len(self.messages)


def create_adaptive_chunks(
    messages: list[AgentMessage],
    target_chunk_tokens: int = 2000,
    max_chunk_tokens: int = 4000,
) -> list[MessageChunk]:
    """自适应消息分块

    参考: openclaw-main/src/agents/compaction.ts - createAdaptiveChunks

    将消息列表分成多个块，每块大小在 target_chunk_tokens 附近，
    不超过 max_chunk_tokens。

    Args:
        messages: 消息列表
        target_chunk_tokens: 目标块大小
        max_chunk_tokens: 最大块大小

    Returns:
        消息块列表
    """
    if not messages:
        return []

    chunks: list[MessageChunk] = []
    current_chunk: list[AgentMessage] = []
    current_tokens = 0

    for msg in messages:
        msg_tokens = estimate_message_tokens(msg)

        # 如果单条消息超过最大块大小，单独成块
        if msg_tokens >= max_chunk_tokens:
            # 先保存当前块
            if current_chunk:
                chunks.append(MessageChunk(messages=current_chunk, token_count=current_tokens))
                current_chunk = []
                current_tokens = 0
            # 单独成块
            chunks.append(MessageChunk(messages=[msg], token_count=msg_tokens))
            continue

        # 如果添加后超过目标大小且当前块非空，开始新块
        if current_tokens + msg_tokens > target_chunk_tokens and current_chunk:
            chunks.append(MessageChunk(messages=current_chunk, token_count=current_tokens))
            current_chunk = []
            current_tokens = 0

        current_chunk.append(msg)
        current_tokens += msg_tokens

    # 保存最后一块
    if current_chunk:
        chunks.append(MessageChunk(messages=current_chunk, token_count=current_tokens))

    return chunks


# ============ 自适应分块 ============


def compute_adaptive_chunk_ratio(
    messages: list[AgentMessage], context_window: int
) -> float:
    """计算自适应分块比例

    当消息较大时，使用更小的分块以避免超出模型限制。

    参考: openclaw-main/src/agents/compaction.ts - computeAdaptiveChunkRatio
    """
    if not messages:
        return BASE_CHUNK_RATIO

    total_tokens = sum(estimate_message_tokens(msg) for msg in messages)
    avg_tokens = total_tokens / len(messages)

    # 应用安全边界
    safe_avg_tokens = avg_tokens * SAFETY_MARGIN
    avg_ratio = safe_avg_tokens / context_window

    # 如果平均消息 > 10% 上下文，减少分块比例
    if avg_ratio > 0.1:
        reduction = min(avg_ratio * 2, BASE_CHUNK_RATIO - MIN_CHUNK_RATIO)
        return max(MIN_CHUNK_RATIO, BASE_CHUNK_RATIO - reduction)

    return BASE_CHUNK_RATIO


def is_oversized_for_summary(msg: AgentMessage, context_window: int) -> bool:
    """检查消息是否太大无法摘要

    如果单条消息 > 50% 上下文，无法安全地摘要。
    """
    tokens = estimate_message_tokens(msg) * SAFETY_MARGIN
    return tokens > context_window * 0.5


# ============ 摘要生成协议 ============


class SummarizerProtocol(Protocol):
    """摘要生成器协议"""

    async def summarize(
        self,
        text: str,
        max_tokens: int = 500,
        custom_instructions: str | None = None,
        previous_summary: str | None = None,
    ) -> str:
        """生成摘要

        Args:
            text: 要摘要的文本
            max_tokens: 摘要最大 token 数
            custom_instructions: 自定义摘要指令
            previous_summary: 之前的摘要（用于增量摘要）

        Returns:
            摘要文本
        """
        ...


class SimpleSummarizer:
    """简单摘要生成器（截断实现）

    这是一个基础实现，生产环境应使用 LLMSummarizer。
    """

    async def summarize(
        self,
        text: str,
        max_tokens: int = 500,
        custom_instructions: str | None = None,
        previous_summary: str | None = None,
    ) -> str:
        """简单截断摘要"""
        # 如果有之前的摘要，拼接
        if previous_summary:
            text = f"[之前的摘要]\n{previous_summary}\n\n[新内容]\n{text}"

        estimated = estimate_tokens(text)
        if estimated <= max_tokens:
            return text

        # 简单截断，保留约 max_tokens 对应的字符
        max_chars = int(max_tokens * 1.5)
        if len(text) <= max_chars:
            return text

        return text[: max_chars - 3] + "..."


class LLMSummarizer:
    """基于 LLM 的摘要生成器

    支持 ChatOpenAI 或任何实现了 ainvoke() 的 LLM 实例。
    """

    DEFAULT_INSTRUCTIONS = """生成对话摘要，保留以下关键信息：
1. 用户的核心需求和问题
2. 已做出的决策和选择
3. 待办事项和未解决的问题
4. 重要的约束条件
5. 已查询的数据要点

摘要应简洁但完整，便于后续对话继续。"""

    MERGE_INSTRUCTIONS = """合并以下多个部分摘要为一个统一的摘要。
保留所有重要的决策、待办事项、问题和约束条件。"""

    def __init__(
        self,
        llm: BaseChatModel,
        *,
        sampling: SamplingConfig | None = None,
    ) -> None:
        """
        Args:
            llm: ChatOpenAI 实例（或任何实现了 ainvoke 的 LangChain chat model）
            sampling: 摘要任务采样参数，默认 SamplingConfig.for_summarization()
                （低温 + 防重复，专为摘要场景调优）
        """
        self.llm = self._apply_sampling(
            llm, sampling or SamplingConfig.for_summarization()
        )

    @staticmethod
    def _apply_sampling(
        llm: BaseChatModel, sampling: SamplingConfig
    ) -> BaseChatModel:
        """基于 sampling 覆盖 llm 的采样参数（走 model_copy）。"""
        updates: dict[str, Any] = {**sampling.to_chat_openai_kwargs()}
        current_body = getattr(llm, "extra_body", None) or {}
        updates["extra_body"] = {**current_body, **sampling.to_extra_body()}
        if hasattr(llm, "model_copy"):
            return llm.model_copy(update=updates)
        if hasattr(llm, "copy"):
            return llm.copy(update=updates)
        logger.debug("Summarizer llm lacks model_copy; sampling override ignored")
        return llm

    async def summarize(
        self,
        text: str,
        max_tokens: int = 500,
        custom_instructions: str | None = None,
        previous_summary: str | None = None,
    ) -> str:
        """使用 LLM 生成摘要"""
        from langchain_core.messages import HumanMessage

        instructions = custom_instructions or self.DEFAULT_INSTRUCTIONS

        prompt_parts = [f"## 摘要指令\n{instructions}"]

        if previous_summary:
            prompt_parts.append(f"## 之前的摘要\n{previous_summary}")

        prompt_parts.append(f"## 需要摘要的内容\n{text}")
        prompt_parts.append(f"\n请生成不超过 {max_tokens} token 的摘要：")

        prompt = "\n\n".join(prompt_parts)

        try:
            ai_msg = await self.llm.ainvoke(
                [HumanMessage(content=prompt)]
            )
            # Handle different content types from LangChain
            if hasattr(ai_msg, "content"):
                content = ai_msg.content
                # If content is a list, join it into a string
                if isinstance(content, list):
                    content = " ".join(str(item) for item in content)
                elif not isinstance(content, str):
                    content = str(content)
            else:
                content = str(ai_msg)

            return content or DEFAULT_SUMMARY_FALLBACK

        except Exception as e:
            logger.warning(f"LLM summarization failed: {e}")
            simple = SimpleSummarizer()
            return await simple.summarize(text, max_tokens, custom_instructions, previous_summary)


# ============ 上下文压缩器 ============


@dataclass
class CompactionConfig:
    """压缩配置"""

    # 上下文窗口大小（token）
    context_window: int = 128000

    # 保留给输出的 token 数
    output_reserve: int = 4000

    # 系统提示预留
    system_reserve: int = 2000

    # 目标压缩后 token 数
    target_tokens: int = 0  # 0 表示自动计算

    # 触发压缩的阈值比例（超过目标的这个比例时触发）
    trigger_threshold: float = 0.8

    # 分块参数
    target_chunk_tokens: int = 2000
    max_chunk_tokens: int = 4000

    # 摘要参数
    summary_max_tokens: int = 500

    # 保留最近 N 条消息不压缩
    preserve_recent: int = 4

    # 最小分块消息数（少于此数不分块）
    min_messages_for_split: int = 4

    # 分块数量（用于分阶段摘要）
    summary_parts: int = 2

    # 历史占上下文的最大比例
    max_history_share: float = 0.5

    def __post_init__(self) -> None:
        if self.target_tokens == 0:
            self.target_tokens = (
                self.context_window - self.output_reserve - self.system_reserve
            )

    @property
    def trigger_tokens(self) -> int:
        """触发压缩的 token 阈值"""
        return int(self.target_tokens * self.trigger_threshold)

    @property
    def history_budget_tokens(self) -> int:
        """历史消息的 token 预算"""
        return int(self.target_tokens * self.max_history_share)


@dataclass
class CompactionResult:
    """压缩结果"""

    messages: list[AgentMessage]
    original_count: int
    compacted_count: int
    original_tokens: int
    compacted_tokens: int
    summaries_generated: int = 0


class ContextCompactor:
    """上下文压缩器

    参考: openclaw-main/src/agents/compaction.ts

    执行多阶段压缩:
    1. 估算当前 token 使用（带安全边界）
    2. 如果超过阈值，进行自适应分块
    3. 对历史块生成摘要（处理超大消息）
    4. 分阶段摘要后合并
    5. 聚合摘要和最近消息
    """

    def __init__(
        self,
        config: CompactionConfig | None = None,
        summarizer: SummarizerProtocol | None = None,
    ) -> None:
        self.config = config or CompactionConfig()
        self.summarizer = summarizer or SimpleSummarizer()

    def estimate_total_tokens(self, messages: list[AgentMessage]) -> int:
        """估算消息列表的总 token 数"""
        return sum(estimate_message_tokens(msg) for msg in messages)

    def estimate_safe_tokens(self, messages: list[AgentMessage]) -> int:
        """估算消息列表的安全 token 数（含安全边界）"""
        return int(self.estimate_total_tokens(messages) * SAFETY_MARGIN)

    def needs_compaction(self, messages: list[AgentMessage]) -> bool:
        """检查是否需要压缩

        使用带安全边界的估算，并与触发阈值比较。
        """
        total = self.estimate_safe_tokens(messages)
        return total > self.config.trigger_tokens

    async def compact(
        self,
        messages: list[AgentMessage],
        force: bool = False,
    ) -> CompactionResult:
        """执行压缩

        Args:
            messages: 消息列表
            force: 是否强制压缩（即使未超过阈值）

        Returns:
            压缩结果
        """
        original_count = len(messages)
        original_tokens = self.estimate_total_tokens(messages)

        # 检查是否需要压缩
        if not force and not self.needs_compaction(messages):
            return CompactionResult(
                messages=messages,
                original_count=original_count,
                compacted_count=original_count,
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
            )

        logger.info(
            f"Starting compaction: {original_count} messages, {original_tokens} tokens"
        )

        # 分离系统消息和对话消息
        system_messages = [m for m in messages if m.role == MessageRole.SYSTEM]
        conversation = [m for m in messages if m.role != MessageRole.SYSTEM]

        # 保留最近的消息
        preserve_count = min(self.config.preserve_recent, len(conversation))
        history = conversation[:-preserve_count] if preserve_count > 0 else conversation
        recent = conversation[-preserve_count:] if preserve_count > 0 else []

        # 对历史进行分阶段压缩
        compacted_history, summaries_count = await self._compact_history_staged(history)

        # 组合结果
        result_messages = system_messages + compacted_history + recent
        compacted_tokens = self.estimate_total_tokens(result_messages)

        logger.info(
            f"Compaction complete: {len(result_messages)} messages, "
            f"{compacted_tokens} tokens, {summaries_count} summaries"
        )

        return CompactionResult(
            messages=result_messages,
            original_count=original_count,
            compacted_count=len(result_messages),
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            summaries_generated=summaries_count,
        )

    async def _compact_history_staged(
        self, history: list[AgentMessage]
    ) -> tuple[list[AgentMessage], int]:
        """分阶段压缩历史消息

        1. 分离超大消息
        2. 对正常消息分块
        3. 每块生成摘要
        4. 合并所有摘要

        Returns:
            (压缩后的消息列表, 生成的摘要数)
        """
        if not history:
            return [], 0

        total_tokens = self.estimate_total_tokens(history)

        # 如果历史很小，不需要压缩
        if (
            len(history) < self.config.min_messages_for_split
            or total_tokens <= self.config.max_chunk_tokens
        ):
            return history, 0

        # 分离超大消息和正常消息
        normal_messages: list[AgentMessage] = []
        oversized_notes: list[str] = []

        for msg in history:
            if is_oversized_for_summary(msg, self.config.context_window):
                tokens = estimate_message_tokens(msg)
                oversized_notes.append(
                    f"[大型 {msg.role.value} 消息 (~{tokens // 1000}K tokens) 已省略]"
                )
                logger.warning(f"Oversized message ({tokens} tokens) omitted from summary")
            else:
                normal_messages.append(msg)

        # 计算自适应分块比例
        chunk_ratio = compute_adaptive_chunk_ratio(
            normal_messages, self.config.context_window
        )
        max_chunk_tokens = int(self.config.context_window * chunk_ratio)

        # 分块
        chunks = create_adaptive_chunks(
            normal_messages,
            target_chunk_tokens=self.config.target_chunk_tokens,
            max_chunk_tokens=max_chunk_tokens,
        )

        if len(chunks) <= 1 and not oversized_notes:
            # 只有一个块且无超大消息
            return history, 0

        # 对每个块生成摘要
        partial_summaries: list[str] = []
        for i, chunk in enumerate(chunks):
            chunk_text = self._chunk_to_text(chunk)
            try:
                summary = await self.summarizer.summarize(
                    chunk_text, self.config.summary_max_tokens
                )
                partial_summaries.append(summary)
            except Exception as e:
                logger.warning(f"Failed to summarize chunk {i}: {e}")
                # 回退：简单截断
                partial_summaries.append(chunk_text[: self.config.summary_max_tokens * 2])

        # 合并摘要
        if len(partial_summaries) > 1:
            # 分阶段摘要：先合并部分摘要
            combined = "\n\n---\n\n".join(
                f"[部分摘要 {i + 1}]\n{s}" for i, s in enumerate(partial_summaries)
            )
            try:
                final_summary = await self.summarizer.summarize(
                    combined,
                    self.config.summary_max_tokens,
                    custom_instructions="合并这些部分摘要为一个统一的摘要，保留所有重要信息。",
                )
            except Exception as e:
                logger.warning(f"Failed to merge summaries: {e}")
                final_summary = combined
        elif partial_summaries:
            final_summary = partial_summaries[0]
        else:
            final_summary = DEFAULT_SUMMARY_FALLBACK

        # 添加超大消息说明
        if oversized_notes:
            final_summary += "\n\n" + "\n".join(oversized_notes)

        # 创建摘要消息
        summary_message = AgentMessage.assistant(
            content=f"[以下是之前对话的摘要]\n\n{final_summary}"
        )

        return [summary_message], len(partial_summaries)

    async def _compact_history(
        self, history: list[AgentMessage]
    ) -> tuple[list[AgentMessage], int]:
        """压缩历史消息（简化版，委托 _compact_history_staged）"""
        return await self._compact_history_staged(history)

    def _chunk_to_text(self, chunk: MessageChunk) -> str:
        """将消息块转换为文本"""
        parts: list[str] = []
        for msg in chunk.messages:
            role = msg.role.value.upper()
            content = msg.content or ""
            if msg.tool_calls:
                tool_names = ", ".join(tc.name for tc in msg.tool_calls)
                content += f"\n[调用工具: {tool_names}]"
            if msg.tool_results:
                for tr in msg.tool_results:
                    if tr.result_type == ToolResultType.A2UI:
                        result_preview = "[A2UI 卡片已渲染]"
                    else:
                        result_preview = str(tr.content)[:200]
                        if len(str(tr.content)) > 200:
                            result_preview += "..."
                    content += f"\n[工具结果: {result_preview}]"
            parts.append(f"{role}: {content}")
        return "\n\n".join(parts)

    def prune_to_budget(
        self, messages: list[AgentMessage]
    ) -> tuple[list[AgentMessage], int, int]:
        """裁剪消息以适应预算

        参考: openclaw-main/src/agents/compaction.ts - pruneHistoryForContextShare

        Returns:
            (保留的消息, 丢弃的消息数, 丢弃的 token 数)
        """
        budget = self.config.history_budget_tokens
        kept = list(messages)
        dropped_count = 0
        dropped_tokens = 0

        while kept and self.estimate_total_tokens(kept) > budget:
            # 丢弃最早的消息
            dropped = kept.pop(0)
            dropped_count += 1
            dropped_tokens += estimate_message_tokens(dropped)

        return kept, dropped_count, dropped_tokens


# ============ 便捷函数 ============


async def compact_messages(
    messages: list[AgentMessage],
    config: CompactionConfig | None = None,
    summarizer: SummarizerProtocol | None = None,
) -> CompactionResult:
    """便捷函数：压缩消息列表"""
    compactor = ContextCompactor(config, summarizer)
    return await compactor.compact(messages)


def should_compact(
    messages: list[AgentMessage],
    context_window: int = 32000,
    threshold_ratio: float = 0.7,
) -> bool:
    """便捷函数：检查是否应该压缩

    Args:
        messages: 消息列表
        context_window: 上下文窗口大小
        threshold_ratio: 触发压缩的阈值比例

    Returns:
        是否应该压缩
    """
    # 使用安全边界估算
    total = int(sum(estimate_message_tokens(msg) for msg in messages) * SAFETY_MARGIN)
    threshold = int(context_window * threshold_ratio)
    return total > threshold


def estimate_context_usage(
    messages: list[AgentMessage],
    context_window: int = 32000,
) -> dict[str, Any]:
    """估算上下文使用情况

    Returns:
        包含使用情况的字典
    """
    total_tokens = sum(estimate_message_tokens(msg) for msg in messages)
    safe_tokens = int(total_tokens * SAFETY_MARGIN)

    return {
        "message_count": len(messages),
        "estimated_tokens": total_tokens,
        "safe_tokens": safe_tokens,
        "context_window": context_window,
        "usage_ratio": safe_tokens / context_window if context_window > 0 else 0,
        "remaining_tokens": max(0, context_window - safe_tokens),
    }


def create_compactor_with_llm(
    llm_client: BaseChatModel,
    config: CompactionConfig | None = None,
) -> ContextCompactor:
    """创建使用 LLM 摘要的压缩器

    Args:
        llm_client: LLM 客户端（LangChain BaseChatModel 实例）
        config: 压缩配置

    Returns:
        配置好的压缩器
    """
    summarizer = LLMSummarizer(llm_client)
    return ContextCompactor(config, summarizer)
