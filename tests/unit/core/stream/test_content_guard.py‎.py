"""
TextLeakGuard 单元测试

测试不依赖任何 runner / LLM / formatter 实现，
只使用 AgentStreamEvent 和一个最简 fmt 函数。
"""

from __future__ import annotations

import pytest

from ark_agentic.core.stream.content_guard import TextLeakGuard
from ark_agentic.core.stream.events import AgentStreamEvent


# ── 辅助工具 ─────────────────────────────────────────────────────────────────


def _evt(type: str, **kwargs) -> AgentStreamEvent:
    """构造测试用事件，seq/run_id/session_id 填固定值。"""
    return AgentStreamEvent(
        type=type, seq=0, run_id="run-test", session_id="sess-test", **kwargs
    )


def _fmt(event: AgentStreamEvent) -> str | None:
    """最简 formatter：直接返回 event.type 字符串，方便断言顺序。"""
    return event.type


async def _collect(guard: TextLeakGuard, events: list[AgentStreamEvent]) -> list[str]:
    """把一组事件依次送入 guard，收集所有 yield 出来的行。"""
    lines: list[str] = []
    for evt in events:
        async for line in guard.process(evt, _fmt):
            lines.append(line)
    return lines


# ── 场景 1：无工具调用（纯文字回答）────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_tool_call_flushes_text_on_run_finished() -> None:
    """无工具调用时，text 事件在 run_finished 时按原始顺序 flush。"""
    guard = TextLeakGuard()
    events = [
        _evt("run_started"),
        _evt("text_message_start", message_id="m1"),
        _evt("text_message_content", message_id="m1", delta="你好"),
        _evt("text_message_content", message_id="m1", delta="！"),
        _evt("text_message_end", message_id="m1"),
        _evt("run_finished", message="你好！"),
    ]
    lines = await _collect(guard, events)

    assert lines == [
        "run_started",
        "text_message_start",
        "text_message_content",
        "text_message_content",
        "text_message_end",
        "run_finished",
    ]


# ── 场景 2：有工具调用——text 被丢弃 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_call_discards_buffered_text() -> None:
    """出现 tool_call_start 时，之前缓冲的 text 事件被丢弃。"""
    guard = TextLeakGuard()
    events = [
        _evt("run_started"),
        _evt("text_message_start", message_id="m1"),
        _evt("text_message_content", message_id="m1", delta="我来查一下"),
        _evt("text_message_end", message_id="m1"),
        _evt("tool_call_start", tool_call_id="tc1", tool_name="query_policy"),
        _evt("tool_call_args", tool_call_id="tc1", tool_name="query_policy", tool_args={}),
        _evt("tool_call_end", tool_call_id="tc1", tool_name="query_policy"),
        _evt("tool_call_result", tool_call_id="tc1", tool_name="query_policy", tool_result="ok"),
        _evt("run_finished", message="查询完毕"),
    ]
    lines = await _collect(guard, events)

    # text_message_* 三条全部丢弃，tool_* 和其他正常透传
    assert "text_message_start" not in lines
    assert "text_message_content" not in lines
    assert "text_message_end" not in lines
    assert lines == [
        "run_started",
        "tool_call_start",
        "tool_call_args",
        "tool_call_end",
        "tool_call_result",
        "run_finished",
    ]


# ── 场景 3：多轮（工具调用轮 + 最终回答轮）───────────────────────────────────


@pytest.mark.asyncio
async def test_multi_turn_tool_then_final_answer() -> None:
    """
    Turn 1：有工具调用，text 被丢弃
    Turn 2：无工具调用（最终回答），text 被 flush

    注意：AG-UI 协议里一次 run 只有一个 run_finished，
    两轮的文字事件属于同一个 run；本测试模拟 guard 跨轮的状态管理。
    """
    guard = TextLeakGuard()

    # Turn 1：推理文字 + 工具调用
    turn1 = [
        _evt("text_message_start", message_id="m1"),
        _evt("text_message_content", message_id="m1", delta="让我查一下"),
        _evt("text_message_end", message_id="m1"),
        _evt("tool_call_start", tool_call_id="tc1", tool_name="query_policy"),
        _evt("tool_call_end", tool_call_id="tc1", tool_name="query_policy"),
        _evt("tool_call_result", tool_call_id="tc1", tool_name="query_policy", tool_result="数据"),
    ]
    # Turn 2：最终回答
    turn2 = [
        _evt("text_message_start", message_id="m2"),
        _evt("text_message_content", message_id="m2", delta="您的保单"),
        _evt("text_message_content", message_id="m2", delta="有效期至明年"),
        _evt("text_message_end", message_id="m2"),
        _evt("run_finished", message="您的保单有效期至明年"),
    ]

    lines = await _collect(guard, turn1 + turn2)

    # Turn 1 的 text_message_* 被丢弃
    # Turn 2 的 text_message_* 被 flush（因为 turn2 中没有 tool_call_start）
    assert lines.count("tool_call_start") == 1
    assert lines.count("tool_call_end") == 1
    assert lines.count("tool_call_result") == 1

    # 最终回答的三个 text 事件都出现
    text_content_count = lines.count("text_message_content")
    assert text_content_count == 2  # Turn 2 的两条

    assert lines[-1] == "run_finished"


# ── 场景 4：其他事件直接透传 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_passthrough_events_not_buffered() -> None:
    """step_*、thinking_*、custom 等事件直接透传，不受缓冲影响。"""
    guard = TextLeakGuard()
    events = [
        _evt("run_started"),
        _evt("step_started", step_name="正在思考"),
        _evt("thinking_message_start", message_id="t1"),
        _evt("thinking_message_content", message_id="t1", delta="内部推理"),
        _evt("thinking_message_end", message_id="t1"),
        _evt("step_finished", step_name="正在思考"),
        _evt("text_message_start", message_id="m1"),
        _evt("text_message_content", message_id="m1", delta="结论"),
        _evt("text_message_end", message_id="m1"),
        _evt("run_finished", message="结论"),
    ]
    lines = await _collect(guard, events)

    # step_* 和 thinking_* 在 text 之前，应该已经发出
    assert lines[0] == "run_started"
    assert lines[1] == "step_started"
    assert lines[2] == "thinking_message_start"
    assert lines[3] == "thinking_message_content"
    assert lines[4] == "thinking_message_end"
    assert lines[5] == "step_finished"
    # text_message_* 在 run_finished 之前 flush
    assert "text_message_start" in lines
    assert lines[-1] == "run_finished"


# ── 场景 5：fmt 返回 None 时不 yield ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_none_fmt_result_not_yielded() -> None:
    """formatter 返回 None 的事件（如某些格式器跳过特定事件）不应被 yield。"""
    guard = TextLeakGuard()

    def _null_fmt(event: AgentStreamEvent) -> str | None:
        # 只对 run_finished 返回非 None
        return "done" if event.type == "run_finished" else None

    events = [
        _evt("text_message_start", message_id="m1"),
        _evt("text_message_content", message_id="m1", delta="hello"),
        _evt("text_message_end", message_id="m1"),
        _evt("run_finished", message="hello"),
    ]
    lines: list[str] = []
    for evt in events:
        async for line in guard.process(evt, _null_fmt):
            lines.append(line)

    assert lines == ["done"]


# ── 场景 6：STREAM_CHUNK_DELAY_MS=0 无延迟（加速测试）───────────────────────


@pytest.mark.asyncio
async def test_zero_delay_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """STREAM_CHUNK_DELAY_MS=0 时，flush 不产生实质延迟，测试快速完成。"""
    import ark_agentic.core.stream.content_guard as mod
    monkeypatch.setattr(mod, "_CHUNK_DELAY", 0.0)

    guard = TextLeakGuard()
    events = [
        _evt("text_message_start", message_id="m1"),
        _evt("text_message_content", message_id="m1", delta="快"),
        _evt("text_message_end", message_id="m1"),
        _evt("run_finished", message="快"),
    ]
    lines = await _collect(guard, events)
    assert "text_message_content" in lines
    assert lines[-1] == "run_finished"


# ── 场景 7：A2UI 卡片直接透传，不受缓冲/过滤影响 ─────────────────────────────


@pytest.mark.asyncio
async def test_a2ui_content_kind_always_passthrough() -> None:
    """content_kind="a2ui" 的 text_message_content（卡片组件）必须直接透传。

    A2UI 卡片是工具执行结果的 UI 渲染，不是 LLM 的推理文字，
    即使本轮有工具调用也不应被丢弃。
    """
    guard = TextLeakGuard()
    events = [
        _evt("run_started"),
        # 推理文字（会被丢弃）
        _evt("text_message_start", message_id="m1"),
        _evt("text_message_content", message_id="m1", delta="让我查一下"),
        _evt("text_message_end", message_id="m1"),
        # 工具调用
        _evt("tool_call_start", tool_call_id="tc1", tool_name="render_a2ui"),
        _evt("tool_call_end", tool_call_id="tc1", tool_name="render_a2ui"),
        # A2UI 卡片（来自 on_ui_component，content_kind="a2ui"，必须透传）
        _evt("text_message_content", content_kind="a2ui", custom_data={"event": "beginRendering"}),
        _evt("run_finished", message=""),
    ]
    lines = await _collect(guard, events)

    # 推理文字被丢弃
    assert lines.count("text_message_start") == 0
    # 但 a2ui 卡片正常出现
    assert "text_message_content" in lines
    # 工具事件和结束事件正常
    assert "tool_call_start" in lines
    assert lines[-1] == "run_finished"