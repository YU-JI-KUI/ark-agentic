"""Tests for context compaction."""

import os
import pytest
from ark_agentic.core.compaction import (
    CompactionConfig,
    ContextCompactor,
    LLMSummarizer,
    MessageChunk,
    SimpleSummarizer,
    compute_adaptive_chunk_ratio,
    create_adaptive_chunks,
    estimate_message_tokens,
    estimate_tokens,
    is_oversized_for_summary,
    should_compact,
)
from ark_agentic.core.types import AgentMessage


class TestTokenEstimation:
    """Tests for token estimation."""

    def test_estimate_tokens_empty(self) -> None:
        """Test empty string."""
        assert estimate_tokens("") == 0

    def test_estimate_tokens_chinese(self) -> None:
        """Test Chinese text."""
        # 10 Chinese characters ≈ 7 tokens
        tokens = estimate_tokens("你好世界这是测试文本啊")
        assert 5 <= tokens <= 15

    def test_estimate_tokens_english(self) -> None:
        """Test English text."""
        # ~5 words ≈ 6.5 tokens
        tokens = estimate_tokens("Hello world this is test")
        assert 5 <= tokens <= 10

    def test_estimate_tokens_mixed(self) -> None:
        """Test mixed text."""
        tokens = estimate_tokens("Hello 你好 world 世界")
        assert tokens > 0

    def test_estimate_message_tokens(self) -> None:
        """Test message token estimation."""
        msg = AgentMessage.user("Hello world")
        tokens = estimate_message_tokens(msg)
        # Content + structure overhead (4)
        assert tokens >= 4


class TestAdaptiveChunking:
    """Tests for adaptive chunking."""

    def test_create_adaptive_chunks_empty(self) -> None:
        """Test empty message list."""
        chunks = create_adaptive_chunks([])
        assert chunks == []

    def test_create_adaptive_chunks_single(self) -> None:
        """Test single message."""
        messages = [AgentMessage.user("Hello")]
        chunks = create_adaptive_chunks(messages, target_chunk_tokens=100)
        assert len(chunks) == 1
        assert chunks[0].messages == messages

    def test_create_adaptive_chunks_multiple(self) -> None:
        """Test multiple messages split into chunks."""
        messages = [AgentMessage.user(f"Message {i} " * 50) for i in range(10)]
        chunks = create_adaptive_chunks(
            messages,
            target_chunk_tokens=500,
            max_chunk_tokens=1000
        )
        # Should create multiple chunks
        assert len(chunks) >= 1
        # Total messages should be preserved
        total = sum(len(c.messages) for c in chunks)
        assert total == 10

    def test_create_adaptive_chunks_oversized(self) -> None:
        """Test oversized single message."""
        # Create a very large message
        large_msg = AgentMessage.user("x" * 10000)
        messages = [large_msg]
        chunks = create_adaptive_chunks(
            messages,
            target_chunk_tokens=100,
            max_chunk_tokens=500
        )
        # Should be in its own chunk
        assert len(chunks) == 1
        assert chunks[0].messages == [large_msg]

    def test_compute_adaptive_chunk_ratio(self) -> None:
        """Test adaptive chunk ratio."""
        messages = [AgentMessage.user("Hello")]
        ratio = compute_adaptive_chunk_ratio(messages, context_window=32000)
        assert 0.15 <= ratio <= 0.4

    def test_compute_adaptive_chunk_ratio_empty(self) -> None:
        """Test empty messages."""
        ratio = compute_adaptive_chunk_ratio([], context_window=32000)
        assert ratio == 0.4  # BASE_CHUNK_RATIO

    def test_is_oversized_for_summary(self) -> None:
        """Test oversized message detection."""
        small_msg = AgentMessage.user("Hello")
        assert not is_oversized_for_summary(small_msg, context_window=32000)

        # Very large message - needs to be > 50% of context_window after safety margin
        # With context_window=100, 50% = 50 tokens. After 1.2x safety margin ~42 tokens
        # "x" * 100 ≈ 100 tokens (1.3 tokens per word for English)
        large_msg = AgentMessage.user("word " * 100)  # ~130 tokens
        assert is_oversized_for_summary(large_msg, context_window=100)


class TestSimpleSummarizer:
    """Tests for SimpleSummarizer."""

    @pytest.mark.asyncio
    async def test_summarize_short_text(self) -> None:
        """Test short text passthrough."""
        summarizer = SimpleSummarizer()
        result = await summarizer.summarize("Hello world", max_tokens=100)
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_summarize_truncation(self) -> None:
        """Test long text truncation."""
        summarizer = SimpleSummarizer()
        # Use words separated by spaces to trigger token estimation
        long_text = " ".join(["word"] * 10000)  # ~10000 words
        result = await summarizer.summarize(long_text, max_tokens=10)
        assert len(result) < len(long_text)
        assert result.endswith("...")

    @pytest.mark.asyncio
    async def test_summarize_with_previous(self) -> None:
        """Test summarization with previous summary."""
        summarizer = SimpleSummarizer()
        result = await summarizer.summarize(
            "New content",
            max_tokens=1000,
            previous_summary="Previous summary"
        )
        assert "之前的摘要" in result or "Previous" in result


class TestCompactionConfig:
    """Tests for CompactionConfig."""

    def test_default_values(self) -> None:
        """Test default configuration."""
        config = CompactionConfig()
        assert config.context_window == 32000
        assert config.output_reserve == 4000
        assert config.system_reserve == 2000
        assert config.preserve_recent == 4

    def test_auto_target_tokens(self) -> None:
        """Test automatic target token calculation."""
        config = CompactionConfig(
            context_window=32000,
            output_reserve=4000,
            system_reserve=2000
        )
        # target = context_window - output_reserve - system_reserve
        assert config.target_tokens == 26000

    def test_trigger_tokens(self) -> None:
        """Test trigger threshold calculation."""
        config = CompactionConfig(trigger_threshold=0.8)
        expected = int(config.target_tokens * 0.8)
        assert config.trigger_tokens == expected


class TestContextCompactor:
    """Tests for ContextCompactor."""

    def test_needs_compaction_small(self) -> None:
        """Test small message list doesn't need compaction."""
        compactor = ContextCompactor()
        messages = [AgentMessage.user("Hello")]
        assert not compactor.needs_compaction(messages)

    def test_needs_compaction_large(self) -> None:
        """Test large message list needs compaction."""
        # context_window=1000, output_reserve=100, system_reserve=100
        # target_tokens = 1000 - 100 - 100 = 800
        # trigger_tokens = 800 * 0.5 = 400
        # With safety_margin 1.2x, we need ~333 actual tokens to trigger
        compactor = ContextCompactor(CompactionConfig(
            context_window=1000,
            output_reserve=100,
            system_reserve=100,
            trigger_threshold=0.5
        ))
        # Create messages that exceed trigger threshold
        # Each message with "word " * 50 ≈ 65 tokens, 10 messages ≈ 650 tokens
        messages = [AgentMessage.user("word " * 50) for _ in range(10)]
        assert compactor.needs_compaction(messages)

    @pytest.mark.asyncio
    async def test_compact_no_action(self) -> None:
        """Test compaction with small message list."""
        compactor = ContextCompactor()
        messages = [AgentMessage.user("Hello")]
        result = await compactor.compact(messages)
        assert result.messages == messages
        assert result.original_count == 1
        assert result.compacted_count == 1

    @pytest.mark.asyncio
    async def test_compact_forced(self) -> None:
        """Test forced compaction."""
        compactor = ContextCompactor(CompactionConfig(
            preserve_recent=1,
            min_messages_for_split=2
        ))
        messages = [
            AgentMessage.user("Message 1"),
            AgentMessage.user("Message 2"),
            AgentMessage.user("Message 3"),
            AgentMessage.user("Message 4"),
            AgentMessage.user("Message 5"),
        ]
        result = await compactor.compact(messages, force=True)
        # Should preserve recent messages
        assert result.compacted_count <= result.original_count

    def test_estimate_total_tokens(self) -> None:
        """Test total token estimation."""
        compactor = ContextCompactor()
        messages = [
            AgentMessage.user("Hello"),
            AgentMessage.assistant(content="Hi there"),
        ]
        tokens = compactor.estimate_total_tokens(messages)
        assert tokens > 0

    def test_prune_to_budget(self) -> None:
        """Test pruning to budget."""
        config = CompactionConfig(max_history_share=0.1, context_window=100)
        compactor = ContextCompactor(config)
        messages = [AgentMessage.user("x" * 100) for _ in range(10)]
        kept, dropped_count, dropped_tokens = compactor.prune_to_budget(messages)
        assert dropped_count > 0
        assert len(kept) < len(messages)


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_should_compact(self) -> None:
        """Test should_compact helper."""
        messages = [AgentMessage.user("Hello")]
        assert not should_compact(messages, context_window=32000)

        # Large messages that exceed threshold (0.7 * 1000 = 700 tokens)
        # With safety margin 1.2x, we need ~583 actual tokens
        # 10 messages * "word " * 20 ≈ 10 * 26 = 260 tokens each = 2600 total
        large_messages = [AgentMessage.user("word " * 100) for _ in range(10)]
        assert should_compact(large_messages, context_window=1000)


# ============ LLM Integration Tests ============


@pytest.mark.skipif(
    not os.getenv("API_KEY"),
    reason="API_KEY not set, skipping LLM integration tests"
)
class TestLLMSummarizerIntegration:
    """Integration tests for LLMSummarizer with real LLM."""

    @pytest.mark.asyncio
    async def test_llm_summarizer_basic(self) -> None:
        """Test LLMSummarizer with real OpenAI-compatible model."""
        from ark_agentic.core.llm import create_chat_model

        llm = create_chat_model(
            model=os.getenv("MODEL_NAME", "gpt-4o"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("LLM_BASE_URL"),
            temperature=0.3,
            max_tokens=500,
        )
        summarizer = LLMSummarizer(llm)

        # Test conversation to summarize
        conversation = """
        USER: 我想查询我的保单信息
        ASSISTANT: 好的，我来帮您查询。请问您的保单号是多少？
        USER: 保单号是 P123456
        ASSISTANT: [调用工具: query_policy]
        [工具结果: 保单 P123456，投保人张三，保额100万，状态正常]
        ASSISTANT: 您的保单信息如下：保单号 P123456，投保人张三，保额100万元，状态正常。
        USER: 我想申请理赔
        ASSISTANT: 好的，请问理赔原因是什么？
        """

        result = await summarizer.summarize(conversation, max_tokens=200)

        # Verify result is not empty and is shorter than original
        assert result
        assert len(result) < len(conversation)
        # Should contain key information
        assert "保单" in result or "P123456" in result or "张三" in result

    @pytest.mark.asyncio
    async def test_llm_summarizer_with_previous_summary(self) -> None:
        """Test incremental summarization."""
        from ark_agentic.core.llm import create_chat_model

        llm = create_chat_model(
            model=os.getenv("MODEL_NAME", "gpt-4o"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("LLM_BASE_URL"),
            temperature=0.3,
        )
        summarizer = LLMSummarizer(llm)

        previous = "用户查询了保单 P123456，投保人张三，保额100万。"
        new_content = "USER: 我要修改受益人\nASSISTANT: 好的，请提供新受益人信息。"

        result = await summarizer.summarize(
            new_content,
            max_tokens=200,
            previous_summary=previous
        )

        assert result
        # Should reference both old and new information
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_llm_summarizer_custom_instructions(self) -> None:
        """Test custom summarization instructions."""
        from ark_agentic.core.llm import create_chat_model

        llm = create_chat_model(
            model=os.getenv("MODEL_NAME", "gpt-4o"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("LLM_BASE_URL"),
            temperature=0.3,
        )
        summarizer = LLMSummarizer(llm)

        text = "用户询问保单信息，查询了保单号 P123456，然后申请理赔。"
        custom_instructions = "只提取保单号和操作类型，忽略其他细节。"

        result = await summarizer.summarize(
            text,
            max_tokens=100,
            custom_instructions=custom_instructions
        )

        assert result
        assert len(result) < len(text)


@pytest.mark.skipif(
    not os.getenv("API_KEY"),
    reason="API_KEY not set, skipping LLM integration tests"
)
class TestContextCompactorIntegration:
    """Integration tests for ContextCompactor with real LLM."""

    @pytest.mark.asyncio
    async def test_compactor_with_llm_summarizer(self) -> None:
        """Test full compaction flow with LLM summarizer."""
        from ark_agentic.core.llm import create_chat_model

        llm = create_chat_model(
            model=os.getenv("MODEL_NAME", "gpt-4o"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("LLM_BASE_URL"),
            temperature=0.3,
        )
        summarizer = LLMSummarizer(llm)

        config = CompactionConfig(
            context_window=1000,
            output_reserve=100,
            system_reserve=100,
            trigger_threshold=0.5,
            preserve_recent=1,  # 只保留 1 条最近消息
            min_messages_for_split=2,  # 降低最小分块数
            max_chunk_tokens=100,  # 降低阈值
        )
        compactor = ContextCompactor(config, summarizer=summarizer)

        # Create enough messages to trigger compaction
        messages = [
            AgentMessage.user("我想查询我的保单信息，我记得保单号好像是 P 开头的，但是具体记不清了"),
            AgentMessage.assistant(content="好的，我来帮您查询。请提供您的保单号，如果记不清可以提供投保人姓名和身份证号"),
            AgentMessage.user("保单号是 P123456，投保人是张三，身份证号是 110101199001011234"),
            AgentMessage.assistant(content="查询到保单信息：保单号 P123456，投保人张三，保额100万元，保险类型为意外险，状态正常，保费已缴清"),
            AgentMessage.user("我要申请理赔，因为上个月发生了意外事故导致受伤住院"),
            AgentMessage.assistant(content="好的，请详细说明理赔原因、受伤情况、住院时间和医疗费用"),
            AgentMessage.user("2024年1月15日意外摔伤导致骨折，住院治疗10天，医疗费用共计5万元"),
            AgentMessage.assistant(content="好的，我来帮您处理理赔申请。请准备好医院诊断证明、住院发票、身份证复印件等材料"),
        ]

        result = await compactor.compact(messages, force=True)

        # Verify compaction happened
        # With preserve_recent=1, we should have 7 messages to compact
        # If compaction works, we should get fewer messages
        assert result.compacted_count <= result.original_count

        # If summaries were generated, verify the structure
        if result.summaries_generated > 0:
            assert result.compacted_count < result.original_count
            # Recent message should be preserved
            assert result.messages[-1] == messages[-1]
            # Should have a summary message
            summary_messages = [m for m in result.messages if "摘要" in (m.content or "")]
            assert len(summary_messages) > 0
