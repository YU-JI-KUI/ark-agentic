"""SpawnSubtasksTool — batched 并行子任务工具

设计原则：
- 接收任务列表，工具内部 asyncio.gather 并行执行，不依赖 executor 并行
- 每个子任务创建独立 AgentRunner + ephemeral session，真正上下文隔离
- 防嵌套：子任务 session_id 含 ":sub:"，检测到则拒绝再次 spawn
- state_delta / token_usage / transcript 回传父 runner
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..tools.base import AgentTool, ToolParameter
from ..tools.registry import ToolRegistry
from ..types import AgentMessage, AgentToolResult, ToolCall

if TYPE_CHECKING:
    from ..agent.runner import AgentRunner
    from ..session import SessionManager

logger = logging.getLogger(__name__)

_SUBTASK_SESSION_MARKER = ":sub:"


@dataclass
class SubtaskConfig:
    """子任务并发与生命周期配置"""

    max_concurrent: int = 4
    timeout_seconds: float = 300.0
    tools_deny: set[str] = field(default_factory=lambda: {"memory_write"})
    keep_session: bool = False
    max_turns: int | None = None
    persist_transcript: bool = True


def _serialize_transcript(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    transcript: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {"role": msg.role.value, "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {"name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls
            ]
        if msg.tool_results:
            entry["tool_results"] = [
                {"name": tr.tool_call_id, "content": tr.content, "is_error": tr.is_error}
                for tr in msg.tool_results
            ]
        transcript.append(entry)
    return transcript


class SpawnSubtasksTool(AgentTool):
    """并行执行多个独立子任务并汇总结果。

    适用于用户一句话包含多个独立意图时（如"我要理赔，同时查查能领多少钱"），
    每个子任务在隔离会话中独立推理。不要用于有先后依赖的任务。
    """

    visibility = "always"

    name = "spawn_subtasks"
    description = (
        "并行执行多个独立子任务并汇总结果。适用于用户一句话包含多个独立意图时"
        "（如'我要理赔，同时查查能领多少钱'），每个子任务在隔离会话中独立推理。"
        "不要用于有先后依赖的任务。"
    )
    parameters = [
        ToolParameter(
            "tasks", "array", "子任务列表", required=True,
            items={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "子任务完整描述"},
                    "label": {"type": "string", "description": "标识标签（用于日志和结果标识）"},
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选：工具白名单。省略则继承父级全部。不需要包含 read_skill。",
                    },
                },
                "required": ["task"],
            },
        ),
    ]

    def __init__(
        self,
        runner: AgentRunner,
        session_manager: SessionManager,
        config: SubtaskConfig | None = None,
    ) -> None:
        self._runner = runner
        self._session_manager = session_manager
        self._config = config or SubtaskConfig()
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent)

    async def execute(self, tool_call: ToolCall, context: dict[str, Any] | None = None) -> AgentToolResult:
        context = context or {}
        tasks: list[dict[str, Any]] = tool_call.arguments.get("tasks", [])

        parent_session_id: str = context.get("session_id", "")
        if _SUBTASK_SESSION_MARKER in parent_session_id:
            return AgentToolResult.json_result(
                tool_call.id,
                {"status": "error", "error": "subtask nesting is not allowed"},
            )

        if not tasks:
            return AgentToolResult.json_result(
                tool_call.id,
                {"status": "error", "error": "tasks list is empty"},
            )

        results = await asyncio.gather(
            *[self._run_single(parent_session_id, t, context) for t in tasks]
        )

        merged_state_delta: dict[str, Any] = {}
        total_prompt = 0
        total_completion = 0
        subtask_results: list[dict[str, Any]] = []

        for r in results:
            subtask_results.append(r["payload"])
            delta = r.get("state_delta", {})
            if delta:
                for k, v in delta.items():
                    if k in merged_state_delta and merged_state_delta[k] != v:
                        logger.warning(
                            "[SUBTASK_DELTA_CONFLICT] key=%s old=%r new=%r (last-write-wins)",
                            k, merged_state_delta[k], v,
                        )
                    merged_state_delta[k] = v
            total_prompt += r.get("prompt_tokens", 0)
            total_completion += r.get("completion_tokens", 0)

        if parent_session_id:
            self._session_manager.update_token_usage(
                parent_session_id,
                prompt_tokens=total_prompt,
                completion_tokens=total_completion,
            )

        metadata: dict[str, Any] = {}
        if merged_state_delta:
            metadata["state_delta"] = merged_state_delta

        transcripts = {r["label"]: r.get("transcript") for r in results if r.get("transcript")}
        if transcripts:
            metadata["transcripts"] = transcripts

        return AgentToolResult.json_result(
            tool_call.id,
            {"subtasks": subtask_results},
            metadata=metadata or None,
        )

    async def _run_single(
        self,
        parent_session_id: str,
        task_spec: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        task: str = task_spec.get("task", "")
        label: str = task_spec.get("label", "")
        tools_allow: list[str] | None = task_spec.get("tools") or None

        if not task.strip():
            return {"payload": {"status": "error", "label": label, "error": "empty task"}, "label": label}

        sub_session_id = f"{parent_session_id}{_SUBTASK_SESSION_MARKER}{uuid4().hex[:8]}"
        log_prefix = f"label={label!r} sub={sub_session_id[-12:]}"

        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    self._execute_subtask(
                        parent_session_id, sub_session_id, task, label, log_prefix, context,
                        tools_allow=tools_allow,
                    ),
                    timeout=self._config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning("[SUBTASK_TIMEOUT] %s timeout=%.0fs", log_prefix, self._config.timeout_seconds)
                self._session_manager.delete_session_sync(sub_session_id)
                return {
                    "payload": {"status": "timed_out", "label": label, "error": f"timed out after {self._config.timeout_seconds}s"},
                    "label": label,
                }

    async def _execute_subtask(
        self,
        parent_session_id: str,
        sub_session_id: str,
        task: str,
        label: str,
        log_prefix: str,
        context: dict[str, Any],
        tools_allow: list[str] | None = None,
    ) -> dict[str, Any]:
        from ..agent.runner import AgentRunner

        parent_session = self._session_manager.get_session(parent_session_id)
        initial_state: dict[str, Any] = {}
        user_id: str = ""
        if parent_session:
            initial_state = {k: v for k, v in parent_session.state.items() if k.startswith("user:")}
            user_id = parent_session.user_id

        self._session_manager.create_session_sync(
            model=self._runner.config.model or "Qwen3-80B-Instruct",
            provider="ark",
            state=dict(initial_state),
            session_id=sub_session_id,
            user_id=user_id,
        )

        deny = {self.name, *self._config.tools_deny}
        if tools_allow:
            allow_set = {t for t in tools_allow if t not in deny}
            allowed_tools = self._runner.tool_registry.filter(allow=list(allow_set))
        else:
            allowed_tools = self._runner.tool_registry.filter(deny=list(deny))
        sub_registry = ToolRegistry()
        sub_registry.register_all(allowed_tools)

        sub_config = replace(
            self._runner.config,
            auto_compact=False,
            enable_subtasks=False,
        )
        if self._config.max_turns is not None:
            sub_config = replace(sub_config, max_turns=self._config.max_turns)

        sub_runner = AgentRunner(
            llm=self._runner.llm,
            tool_registry=sub_registry,
            session_manager=self._session_manager,
            skill_loader=self._runner.skill_loader,
            config=sub_config,
            memory_manager=None,
        )

        start = time.monotonic()
        logger.info("[SUBTASK_START] %s task=%r", log_prefix, task[:80])

        try:
            result = await sub_runner.run_ephemeral(sub_session_id, task)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            answer = result.response.content or ""

            sub_session_obj = self._session_manager.get_session(sub_session_id)
            state_delta: dict[str, Any] = {}
            if sub_session_obj:
                state_delta = {
                    k: v for k, v in sub_session_obj.state.items()
                    if not k.startswith("temp:") and initial_state.get(k) != v
                }

            tools_called = list({tc.name for tc in (result.tool_calls or [])})

            execution_summary = {
                "turns": result.turns,
                "tools_called": tools_called,
                "tool_calls_count": result.tool_calls_count,
                "token_usage": {"prompt": result.prompt_tokens, "completion": result.completion_tokens},
                "duration_ms": elapsed_ms,
            }

            payload: dict[str, Any] = {
                "status": "completed",
                "label": label,
                "result": answer,
                "execution": execution_summary,
            }

            transcript = None
            if self._config.persist_transcript and sub_session_obj:
                transcript = _serialize_transcript(sub_session_obj.messages)

            logger.info("[SUBTASK_DONE] %s turns=%d elapsed=%dms", log_prefix, result.turns, elapsed_ms)

            return {
                "payload": payload,
                "state_delta": state_delta,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "label": label,
                "transcript": transcript,
            }
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.error("[SUBTASK_ERROR] %s error=%s elapsed=%dms", log_prefix, exc, elapsed_ms)
            return {
                "payload": {"status": "error", "label": label, "error": str(exc)},
                "label": label,
            }
        finally:
            if not self._config.keep_session:
                self._session_manager.delete_session_sync(sub_session_id)


def create_subtask_tool(
    runner: AgentRunner,
    session_manager: SessionManager,
    config: SubtaskConfig | None = None,
) -> SpawnSubtasksTool:
    """工厂函数：创建绑定了父 Runner 上下文的 spawn_subtasks 工具。"""
    return SpawnSubtasksTool(runner, session_manager, config)
