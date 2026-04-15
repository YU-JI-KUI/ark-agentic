"""Agent Runner - ReAct 执行器

使用 langchain ChatOpenAI 作为 LLM 后端。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, NamedTuple, TYPE_CHECKING

from langchain_core.language_models.chat_models import BaseChatModel

from .callbacks import (
    CallbackContext,
    CallbackEvent,
    CallbackResult,
    HookAction,
    RunnerCallbacks,
)
from .llm.caller import LLMCaller
from .llm.errors import LLMError, LLMErrorReason
from .prompt.builder import SystemPromptBuilder, PromptConfig
from .session import SessionManager
from .skills.base import SkillConfig
from .skills.loader import SkillLoader
from .skills.matcher import SkillMatcher
from .stream.event_bus import AgentEventHandler
from .tools.base import AgentTool
from .tools.executor import ToolExecutor
from .tools.registry import ToolRegistry
from .tools.memory import create_memory_tools
from .guardrails.channels import resolve_llm_visible_content
from .observability import create_tracing_callbacks, phoenix_callbacks_enabled
from .types import (
    AgentMessage,
    AgentToolResult,
    MessageRole,
    RunOptions,
    SessionEntry,
    SkillLoadMode,
    ToolCall,
    ToolLoopAction,
    ToolResultType,
)
if TYPE_CHECKING:
    from .memory.manager import MemoryManager
    from .jobs.proactive_service import ProactiveServiceJob

logger = logging.getLogger(__name__)


def _compose_runner_callbacks(
    internal: RunnerCallbacks,
    external: RunnerCallbacks | None,
) -> RunnerCallbacks:
    external = external or RunnerCallbacks()
    return RunnerCallbacks(
        before_agent=[*internal.before_agent, *external.before_agent],
        after_agent=[*external.after_agent, *internal.after_agent],
        before_model=[*internal.before_model, *external.before_model],
        after_model=[*external.after_model, *internal.after_model],
        before_tool=[*internal.before_tool, *external.before_tool],
        after_tool=[*external.after_tool, *internal.after_tool],
        before_loop_end=[*external.before_loop_end, *internal.before_loop_end],
    )


def _build_runner_callbacks(
    *,
    config: RunnerConfig,
    callbacks: RunnerCallbacks | None,
) -> RunnerCallbacks:
    if not phoenix_callbacks_enabled():
        return callbacks or RunnerCallbacks()
    return _compose_runner_callbacks(
        create_tracing_callbacks(
            agent_id=config.skill_config.agent_id,
            agent_name=config.prompt_config.agent_name,
        ),
        callbacks,
    )


# ============ Runner Config ============


@dataclass
class RunnerConfig:
    """Runner 配置"""

    # LLM 参数
    model: str | None = None
    temperature: float = float(os.getenv("DEFAULT_TEMPERATURE", "0.7"))
    max_tokens: int = 4096

    # 执行控制
    max_turns: int = 10  # 最大对话轮数（防止无限循环）
    max_tool_calls_per_turn: int = 5  # 单轮最大工具调用数
    tool_timeout: float = 30.0  # 单个工具执行超时（秒）

    # 思考标签：启用后 system prompt 注入 <think>/<final> 指引，流式解析器按标签路由
    enable_thinking_tags: bool = False

    # 自动压缩
    auto_compact: bool = True

    # 提示配置
    prompt_config: PromptConfig = field(default_factory=PromptConfig)

    # 技能配置
    skill_config: SkillConfig = field(default_factory=SkillConfig)

    # 子任务（启用后自动注册 spawn_subtasks 工具）
    enable_subtasks: bool = False

    # 外部历史合并（agent 级开关）
    accept_external_history: bool = True


@dataclass
class RunResult:
    """执行结果"""

    # 最终响应
    response: AgentMessage

    # 执行统计
    turns: int = 0
    tool_calls_count: int = 0

    # 所有工具调用（用于返回给客户端）
    tool_calls: list[ToolCall] = field(default_factory=list)

    # 所有工具结果（用于提取结构化数据，如模板卡片）
    tool_results: list[AgentToolResult] = field(default_factory=list)

    # Token 使用
    prompt_tokens: int = 0
    completion_tokens: int = 0

    # 是否因达到限制而停止
    stopped_by_limit: bool = False


# ============ Run Params / Loop State ============


class _RunParams(NamedTuple):
    """Resolved per-run parameters (pure computation result)."""

    model: str | None
    temperature: float
    skill_load_mode: str


@dataclass
class _LoopState:
    """ReAct loop 累积状态（私有）。"""

    turns: int = 0
    total_tool_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    all_tool_calls: list[ToolCall] = field(default_factory=list)
    all_tool_results: list[AgentToolResult] = field(default_factory=list)

    def make_result(self, response: AgentMessage, **overrides: Any) -> RunResult:
        return RunResult(
            response=response,
            turns=self.turns,
            tool_calls_count=self.total_tool_calls,
            tool_calls=self.all_tool_calls,
            tool_results=self.all_tool_results,
            prompt_tokens=self.total_prompt_tokens,
            completion_tokens=self.total_completion_tokens,
            **overrides,
        )


# ============ Agent Runner ============


class AgentRunner:
    """智能体执行器

    核心执行循环：
    1. 构建系统提示（含工具和技能）
    2. 调用 LLM 获取响应
    3. 如果有工具调用，执行工具并继续
    4. 返回最终响应
    """

    def __init__(
        self,
        llm: BaseChatModel,
        *,
        session_manager: SessionManager,
        tool_registry: ToolRegistry | None = None,
        skill_loader: SkillLoader | None = None,
        config: RunnerConfig | None = None,
        memory_manager: MemoryManager | None = None,
        callbacks: RunnerCallbacks | None = None,
        proactive_job: ProactiveServiceJob | None = None,
    ) -> None:
        self.llm = llm
        self.tool_registry = tool_registry or ToolRegistry()
        self.session_manager = session_manager
        self.skill_loader = skill_loader
        self.config = config or RunnerConfig()

        self._callbacks = _build_runner_callbacks(
            config=self.config,
            callbacks=callbacks,
        )

        self._memory_manager = memory_manager
        self._proactive_job = proactive_job
        self._flusher = None
        self._dreamer = None
        self._dream_tasks: dict[str, asyncio.Task[Any]] = {}

        # LLMCaller / ToolExecutor (SRP)
        self._llm_caller = LLMCaller(
            llm,
            enable_thinking_tags=self.config.enable_thinking_tags,
        )
        self._tool_executor = ToolExecutor(
            self.tool_registry,
            timeout=self.config.tool_timeout,
            max_calls_per_turn=self.config.max_tool_calls_per_turn,
        )

        if memory_manager is not None:
            from .memory.dream import MemoryDreamer
            from .memory.extractor import MemoryFlusher

            self._flusher = MemoryFlusher(self._llm_caller.get_llm)
            self._dreamer = MemoryDreamer(self._llm_caller.get_llm)
            memory_tools = create_memory_tools(self._get_memory_for_user)
            for tool in memory_tools:
                self.tool_registry.register(tool)
            logger.info("Registered %d memory tools", len(memory_tools))

        if skill_loader is not None:
            if self.config.skill_config.load_mode != SkillLoadMode.full:
                from .tools.read_skill import ReadSkillTool

                self.tool_registry.register(ReadSkillTool(skill_loader))
                logger.info("Registered read_skill tool for dynamic skill loading")

        self.skill_matcher = (
            SkillMatcher(skill_loader) if skill_loader else None
        )

        if self.config.enable_subtasks:
            from .subtask import create_subtask_tool
            self.tool_registry.register(
                create_subtask_tool(self, self.session_manager)
            )
            logger.info("Registered spawn_subtasks tool")

    def _get_memory_for_user(self, user_id: str) -> "MemoryManager | None":
        """返回共享 MemoryManager（所有用户共用一个实例）。"""
        return self._memory_manager

    async def warmup(self) -> None:
        """Warmup：若配置了 proactive_job，自动向全局 JobManager 注册。

        宿主应用（app.py / lifespan）在 JobManager 启动前调用此方法，
        框架负责把 job 注册进调度器，无需宿主感知 job 细节。
        """
        if self._proactive_job is None:
            return  # 未配置主动服务 Job，跳过

        from .jobs.manager import get_job_manager
        job_manager = get_job_manager()
        if job_manager is None:
            return  # JobManager 尚未初始化（ENABLE_JOB_MANAGER=false）

        job_manager.register(self._proactive_job)
        logger.info("Registered proactive job '%s'", self._proactive_job.meta.job_id)

    def mark_memory_dirty(self) -> None:
        """保留接口兼容 — 无 SQLite 索引，无需刷新标记。"""

    async def close_memory(self) -> None:
        """保留接口兼容 — 无需释放资源。"""

    async def run(
        self,
        session_id: str,
        user_input: str,
        user_id: str,
        input_context: dict[str, Any] | None = None,
        *,
        run_options: RunOptions | None = None,
        stream: bool = True,
        handler: AgentEventHandler | None = None,
        history: list[dict[str, Any]] | None = None,
        use_history: bool = True,
    ) -> RunResult:
        """执行智能体

        Lifecycle: resolve → prepare → execute → finalize
        """
        input_context = input_context or {}
        params = self._resolve_run_params(run_options)
        prepared = await self._prepare_session(
            session_id,
            user_id,
            user_input,
            input_context,
            handler=handler,
            history=history,
            use_history=use_history,
            runtime={
                "run": {
                "user_id": user_id,
                "stream": stream,
                "model": params.model,
                "skill_load_mode": params.skill_load_mode,
                "agent_id": self.config.skill_config.agent_id,
                "agent_name": self.config.prompt_config.agent_name,
            }
        },
        )
        if isinstance(prepared, RunResult):
            return prepared

        cb_ctx = prepared
        try:
            result = await self._run_loop(
                session_id,
                use_streaming=stream,
                model_override=params.model,
                temperature_override=params.temperature,
                skill_load_mode=params.skill_load_mode,
                handler=handler,
                cb_ctx=cb_ctx,
            )
        finally:
            await self.session_manager.sync_pending_messages(session_id, user_id)

        cb_ctx.runtime["run_result"] = result
        await self._finalize_run(session_id, user_id, result, cb_ctx, handler)
        return result

    async def run_ephemeral(self, session_id: str, user_input: str) -> RunResult:
        """无持久化的 ReAct 循环，用于 ephemeral 子任务。

        调用方负责 session 创建和清理。跳过 _prepare_session / _finalize_run
        的持久化、hooks、compaction 生命周期。
        """
        user_message = AgentMessage.user(user_input)
        self.session_manager.add_message_sync(session_id, user_message)
        params = self._resolve_run_params(None)
        return await self._run_loop(
            session_id,
            use_streaming=False,
            model_override=params.model,
            temperature_override=params.temperature,
            skill_load_mode=params.skill_load_mode,
        )

    # ---- run() lifecycle phases ----

    def _resolve_run_params(self, run_options: RunOptions | None) -> _RunParams:
        """Pure parameter resolution from run_options + config defaults."""
        model = (run_options.model if run_options else None) or self.config.model
        temperature = self.config.temperature
        if run_options and run_options.temperature is not None:
            temperature = run_options.temperature
        skill_load_mode = self.config.skill_config.load_mode.value
        return _RunParams(model=model, temperature=temperature, skill_load_mode=skill_load_mode)

    async def _prepare_session(
        self,
        session_id: str,
        user_id: str,
        user_input: str,
        input_context: dict[str, Any],
        *,
        handler: AgentEventHandler | None,
        history: list[dict[str, Any]] | None,
        use_history: bool,
        runtime: dict[str, Any] | None = None,
    ) -> RunResult | CallbackContext:
        """Lazy init, before_agent hooks, context merge, history merge, record user message, auto-compact.

        Returns RunResult on halt (early exit), CallbackContext on success.
        """
        session = self.session_manager.get_session_required(session_id)
        session.user_id = user_id
        cb_ctx = CallbackContext(
            user_input=user_input,
            input_context=input_context,
            session=session,
            runtime=runtime or {},
        )

        r = await self._run_hooks(
            self._callbacks.before_agent,
            cb_ctx,
            context=input_context,
            handler=handler,
        )
        if r and r.action == HookAction.ABORT:
            self._merge_input_context(session, input_context)
            user_message = AgentMessage.user(user_input, metadata=input_context)
            self.session_manager.add_message_sync(session_id, user_message)
            resp = r.response or AgentMessage.assistant("")
            self.session_manager.add_message_sync(session_id, resp)
            await self.session_manager.sync_pending_messages(session_id, user_id)
            result = RunResult(response=resp)
            cb_ctx.runtime["run_result"] = result
            cb_result = await self._run_hooks(
                self._callbacks.after_agent,
                cb_ctx,
                response=result.response,
                context=cb_ctx.input_context,
                handler=handler,
            )
            if cb_result and cb_result.response is not None:
                result.response = cb_result.response
            return result

        input_context = cb_ctx.input_context
        self._merge_input_context(session, input_context)

        if history and self.config.accept_external_history and use_history:
            from .history_merge import merge_external_history

            ops = merge_external_history(session.messages, history)
            if ops:
                self.session_manager.inject_messages(session_id, ops)
                logger.info("Merged %d external history message(s)", len(ops))

        user_message = AgentMessage.user(user_input, metadata=input_context)
        self.session_manager.add_message_sync(session_id, user_message)

        if self.config.auto_compact:
            flush_cb = (
                self._flusher.make_pre_compact_callback(
                    user_id,
                    self.config.prompt_config,
                    self._memory_manager,
                )
                if self._flusher and self._memory_manager
                else None
            )
            await self.session_manager.auto_compact_if_needed(
                session_id,
                user_id,
                pre_compact_callback=flush_cb,
            )

        # 供工具在执行时通过 session.state["temp:user_input"] 访问当前用户输入；
        # strip_temp_state() 在 _finalize_run 中自动清理。
        session.state["temp:user_input"] = user_input

        return cb_ctx

    async def _finalize_run(
        self,
        session_id: str,
        user_id: str,
        result: RunResult,
        cb_ctx: CallbackContext,
        handler: AgentEventHandler | None,
    ) -> None:
        """after_agent hooks + session state cleanup."""
        cb_result = await self._run_hooks(
            self._callbacks.after_agent,
            cb_ctx,
            response=result.response,
            context=cb_ctx.input_context,
            handler=handler,
        )
        # 支持 after_agent 回调替换最终 response
        if cb_result and cb_result.response is not None:
            result.response = cb_result.response
        cb_ctx.session.strip_temp_state()
        await self.session_manager.sync_session_state(session_id, user_id)

        self._maybe_trigger_dream(user_id)

    def _maybe_trigger_dream(self, user_id: str) -> None:
        """Check dream gate and launch background task if thresholds met."""
        if not self._dreamer or not self._memory_manager:
            return

        task = self._dream_tasks.get(user_id)
        if task is not None and not task.done():
            return

        from .memory.dream import should_dream

        workspace = Path(self._memory_manager.config.workspace_dir)
        sessions_dir = Path(self.session_manager._transcript_manager.sessions_dir)

        try:
            if not should_dream(user_id, workspace, sessions_dir):
                return
        except Exception:
            logger.debug("Dream gate check failed for user %s", user_id, exc_info=True)
            return

        memory_path = self._memory_manager.memory_path(user_id)
        self._dream_tasks[user_id] = asyncio.create_task(
            self._run_dream(user_id, memory_path, sessions_dir)
        )
        logger.info("Dream triggered for user %s", user_id)

    async def _run_dream(
        self, user_id: str, memory_path: Path, sessions_dir: Path,
    ) -> None:
        """Background dream cycle with error handling."""
        try:
            result = await self._dreamer.run(memory_path, sessions_dir, user_id)
            logger.info("Dream completed for user %s: %s", user_id, result.changes)
        except Exception:
            logger.warning("Dream failed for user %s", user_id, exc_info=True)

    @staticmethod
    def _merge_tool_state_deltas(
        session: SessionEntry,
        tool_results: list[AgentToolResult],
    ) -> None:
        # guardrails 可能在 after_tool 阶段重写 tool_results，因此前后都需要合并一次 state_delta。
        for tr in tool_results:
            state_delta = tr.metadata.get("state_delta")
            if state_delta and isinstance(state_delta, dict):
                session.update_state(state_delta)

    @staticmethod
    def _merge_input_context(
        session: SessionEntry, input_context: dict[str, Any]
    ) -> None:
        """将 input_context 合并到 session.state，所有键始终覆盖已有值。"""
        for k, v in input_context.items():
            session.state[k] = v

    def _get_user_friendly_error_message(self, error: LLMError) -> str:
        if error.reason == LLMErrorReason.AUTH:
            return "抱歉，模型认证失败，请检查 API 配置。如需帮助，请联系技术支持。"
        elif error.reason == LLMErrorReason.QUOTA:
            return "抱歉，当前 API 账户余额不足，服务暂时不可用，请联系技术支持充值后重试。"
        elif error.reason == LLMErrorReason.RATE_LIMIT:
            return "抱歉，当前请求较多，请稍后再试。"
        elif error.reason == LLMErrorReason.TIMEOUT:
            return "抱歉，请求超时，请检查网络连接后重试。"
        elif error.reason == LLMErrorReason.CONTEXT_OVERFLOW:
            return "抱歉，对话内容过长，系统将自动压缩历史消息后重试。如问题持续，请新建会话。"
        elif error.reason == LLMErrorReason.CONTENT_FILTER:
            return "抱歉，您的输入包含不适当内容，请修改后重试。"
        elif error.reason == LLMErrorReason.SERVER_ERROR:
            return "抱歉，服务暂时不可用，请稍后重试。"
        elif error.reason == LLMErrorReason.NETWORK:
            return "抱歉，网络连接出现问题，请检查网络后重试。"
        else:
            return "抱歉，处理您的请求时出现了问题，请稍后重试。"

    @staticmethod
    def _dispatch_event(handler: AgentEventHandler, event: CallbackEvent) -> None:
        """Route CallbackEvent to the appropriate handler method."""
        if event.type == "step":
            handler.on_step(event.data.get("text", ""))
        elif event.type == "ui_component":
            handler.on_ui_component(event.data)
        else:
            handler.on_custom_event(event.type, event.data)

    async def _run_hooks(
        self,
        hooks: list,
        cb_ctx: CallbackContext | None,
        *,
        context: dict[str, Any] | None = None,
        handler: AgentEventHandler | None = None,
        **kwargs: Any,
    ) -> CallbackResult | None:
        """Run hooks in order. Apply context_updates/event for each non-None result.

        Returns first result with action != PASS (remaining hooks skipped),
        or last non-None result, or None.
        """
        if not hooks or cb_ctx is None:
            return None
        last: CallbackResult | None = None
        for cb in hooks:
            r = await cb(cb_ctx, **kwargs)
            if r is None:
                continue
            if r.context_updates and context is not None:
                context.update(r.context_updates)
            if r.event and handler:
                self._dispatch_event(handler, r.event)
            last = r
            if r.action != HookAction.PASS:
                return r
        return last

    async def _run_loop(
        self,
        session_id: str,
        *,
        use_streaming: bool = True,
        model_override: str | None = None,
        temperature_override: float | None = None,
        skill_load_mode: str = "full",
        handler: AgentEventHandler | None = None,
        cb_ctx: CallbackContext | None = None,
    ) -> RunResult:
        """ReAct loop: LLM → Tool → LLM → ... → Response"""
        ls = _LoopState()
        session = self.session_manager.get_session_required(session_id)
        logger.info("[RUN] session=%s streaming=%s", session_id[:8], use_streaming)

        while ls.turns < self.config.max_turns:
            ls.turns += 1
            state = session.state
            messages = self._build_messages(
                session_id, state, skill_load_mode=skill_load_mode
            )
            tools = self._build_tools()
            logger.info(
                "Turn %d | messages=%d tools=%d model=%s",
                ls.turns,
                len(messages),
                len(tools),
                model_override or self.config.model,
            )

            model_result = await self._model_phase(
                session_id,
                ls,
                messages,
                tools,
                state,
                use_streaming=use_streaming,
                model_override=model_override,
                temperature_override=temperature_override,
                handler=handler,
                cb_ctx=cb_ctx,
            )
            if isinstance(model_result, RunResult):
                return model_result

            response = model_result
            if response.tool_calls:
                stop = await self._tool_phase(
                    session_id,
                    ls,
                    response,
                    session,
                    state,
                    handler=handler,
                    cb_ctx=cb_ctx,
                )
                if stop is not None:
                    return stop
                continue

            result = await self._complete_phase(
                session_id, ls, response, state,
                handler=handler, cb_ctx=cb_ctx,
            )
            if result is None:
                continue
            return result

        logger.warning(
            "[RUN_LIMIT] session=%s max_turns=%d", session_id[:8], self.config.max_turns
        )
        session = self.session_manager.get_session_required(session_id)
        last_assistant = next(
            (m for m in reversed(session.messages) if m.role == MessageRole.ASSISTANT),
            AgentMessage.assistant(content="抱歉，处理过程中出现了问题，请稍后重试。"),
        )
        return ls.make_result(last_assistant, stopped_by_limit=True)

    # ---- Phase methods (SRP: each handles one phase of a ReAct turn) ----

    async def _complete_phase(
        self,
        session_id: str,
        ls: _LoopState,
        response: AgentMessage,
        state: dict[str, Any],
        *,
        handler: AgentEventHandler | None,
        cb_ctx: CallbackContext | None,
    ) -> RunResult | None:
        """before_loop_end → finalize.  Returns None on RETRY."""
        bc = await self._run_hooks(
            self._callbacks.before_loop_end,
            cb_ctx,
            response=response,
            handler=handler,
        )
        if bc and bc.action == HookAction.RETRY:
            logger.info("[before_loop_end] retry turns=%s", ls.turns)
            if bc.response:
                self.session_manager.add_message_sync(session_id, bc.response)
            return None
        return await self._finalize_response(
            ls, response, session_id=session_id, handler=handler,
        )

    async def _model_phase(
        self,
        session_id: str,
        ls: _LoopState,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        state: dict[str, Any],
        *,
        use_streaming: bool,
        model_override: str | None,
        temperature_override: float | None,
        handler: AgentEventHandler | None,
        cb_ctx: CallbackContext | None,
    ) -> AgentMessage | RunResult:
        """before_model → LLM call → after_model → persist → tokens → finish_reason."""
        if cb_ctx is not None:
            cb_ctx.runtime["model_phase"] = {
                "streaming": use_streaming,
                "tool_schema_count": len(tools),
                "model_override": model_override or self.config.model,
            }
        bm = await self._run_hooks(
            self._callbacks.before_model,
            cb_ctx,
            turn=ls.turns,
            messages=messages,
            context=state,
            handler=handler,
        )
        if bm and bm.action == HookAction.OVERRIDE and bm.response:
            response = bm.response
        else:
            turn = ls.turns

            def _on_content(text: str, _t: int = turn) -> None:
                if handler:
                    handler.on_content_delta(text, _t)

            def _on_thinking(text: str, _t: int = turn) -> None:
                if handler:
                    handler.on_thinking_delta(text, _t)

            try:
                if use_streaming:
                    response = await self._llm_caller.call_streaming(
                        messages,
                        tools,
                        model_override=model_override,
                        temperature_override=temperature_override,
                        content_callback=_on_content,
                        thinking_callback=_on_thinking,
                    )
                else:
                    response = await self._llm_caller.call(
                        messages,
                        tools,
                        model_override=model_override,
                        temperature_override=temperature_override,
                    )
            except LLMError as e:
                if cb_ctx is not None:
                    cb_ctx.runtime["model_error"] = e
                logger.error(
                    "[LLM_ERROR] turn=%d reason=%s retryable=%s",
                    ls.turns,
                    e.reason.value,
                    e.retryable,
                )
                user_message = self._get_user_friendly_error_message(e)
                error_response = AgentMessage.assistant(content=user_message)
                error_response.metadata["error"] = {
                    "reason": e.reason.value,
                    "message": str(e),
                    "retryable": e.retryable,
                }
                self.session_manager.add_message_sync(session_id, error_response)
                if handler:
                    handler.on_content_delta(user_message, ls.turns)
                return ls.make_result(error_response, stopped_by_limit=False)

        am = await self._run_hooks(
            self._callbacks.after_model,
            cb_ctx,
            turn=ls.turns,
            response=response,
            context=state,
            handler=handler,
        )
        if am and am.response:
            response = am.response

        usage = response.metadata.get("usage", {})
        turn_prompt = usage.get("prompt_tokens", 0)
        turn_completion = usage.get("completion_tokens", 0)
        ls.total_prompt_tokens += turn_prompt
        ls.total_completion_tokens += turn_completion
        finish_reason = response.metadata.get("finish_reason")
        logger.info(
            "Turn %d | finish_reason=%s content_len=%d tool_calls=%d tokens=+%d/%d",
            ls.turns,
            finish_reason,
            len(response.content or ""),
            len(response.tool_calls or []),
            turn_prompt,
            turn_completion,
        )

        self.session_manager.update_token_usage(
            session_id,
            prompt_tokens=turn_prompt,
            completion_tokens=turn_completion,
        )
        self.session_manager.add_message_sync(session_id, response)

        if finish_reason == "length":
            logger.warning("Response truncated (max_tokens) in session %s", session_id)
            return ls.make_result(response, stopped_by_limit=True)

        return response

    async def _tool_phase(
        self,
        session_id: str,
        ls: _LoopState,
        response: AgentMessage,
        session: SessionEntry,
        state: dict[str, Any],
        *,
        handler: AgentEventHandler | None,
        cb_ctx: CallbackContext | None,
    ) -> RunResult | None:
        """before_tool → execute → state_delta → after_tool → persist → STOP check."""
        tool_calls = response.tool_calls or []
        logger.info(
            "[TOOLS] turn=%d count=%d names=%s",
            ls.turns,
            len(tool_calls),
            [tc.name for tc in tool_calls],
        )
        ls.all_tool_calls.extend(tool_calls)

        bt = await self._run_hooks(
            self._callbacks.before_tool,
            cb_ctx,
            turn=ls.turns,
            tool_calls=tool_calls,
            context=state,
            handler=handler,
        )
        if bt and bt.action == HookAction.OVERRIDE and bt.tool_results is not None:
            tool_results = bt.tool_results
        else:
            tool_results = await self._tool_executor.execute(
                tool_calls,
                {**state, "session_id": session_id},
                handler=handler,
            )

        ls.total_tool_calls += len(tool_calls)
        ls.all_tool_results.extend(tool_results)

        self._merge_tool_state_deltas(session, tool_results)

        at = await self._run_hooks(
            self._callbacks.after_tool,
            cb_ctx,
            turn=ls.turns,
            results=tool_results,
            context=state,
            handler=handler,
        )
        if at and at.tool_results is not None:
            tool_results = at.tool_results
            self._merge_tool_state_deltas(session, tool_results)

        tool_message = AgentMessage.tool(tool_results)
        self.session_manager.add_message_sync(session_id, tool_message)

        stop_results = [
            tr for tr in tool_results if tr.loop_action == ToolLoopAction.STOP
        ]
        if stop_results:
            stop_content_parts = [
                str(tr.content) for tr in stop_results if tr.content and not tr.is_error
            ]
            stop_content = "\n".join(stop_content_parts)
            if stop_content and handler:
                handler.on_content_delta(stop_content, ls.turns)
            if not stop_content and not any(tr.events for tr in stop_results):
                logger.warning(
                    "[TOOL_STOP] tool signaled STOP but both content and events are empty"
                )
            stop_response = AgentMessage.assistant(content=stop_content or "")
            self.session_manager.add_message_sync(session_id, stop_response)
            return ls.make_result(stop_response)

        if all(tr.is_error for tr in tool_results):
            logger.warning("[TOOLS_FAIL] turn=%d all_failed=True", ls.turns)

        if handler:
            handler.on_step("信息收集完毕，正在为您总结…")

        return None

    async def _finalize_response(
        self,
        ls: _LoopState,
        response: AgentMessage,
        *,
        session_id: str,
        handler: AgentEventHandler | None,
    ) -> RunResult:
        """Final turn: thinking-tags fallback."""
        logger.info(
            "[RUN_END] session=%s turns=%d tool_calls=%d tokens=%d/%d",
            session_id[:8],
            ls.turns,
            ls.total_tool_calls,
            ls.total_prompt_tokens,
            ls.total_completion_tokens,
        )

        if self.config.enable_thinking_tags and handler:
            fallback = response.metadata.get("thinking_fallback_content")
            if fallback:
                handler.on_content_delta(fallback, ls.turns)

        return ls.make_result(response)

    def _build_messages(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        skill_load_mode: str = "full",
    ) -> list[dict[str, Any]]:
        """构建 LLM 消息列表"""
        import json

        session = self.session_manager.get_session_required(session_id)
        messages: list[dict[str, Any]] = []

        # 系统提示
        system_prompt = self._build_system_prompt(
            state,
            session_id=session_id,
            skill_load_mode=skill_load_mode,
        )
        messages.append({"role": "system", "content": system_prompt})

        # A2UI tool result 遮蔽：将大体积组件 payload 替换为极简标记，节省 token。
        # arguments 保留原值，作为模型后续调用的 few-shot 示例。
        _A2UI_TOOL = "render_a2ui"
        a2ui_tc_ids: set[str] = set()
        for msg in session.messages:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.name == _A2UI_TOOL:
                        a2ui_tc_ids.add(tc.id)
            if msg.tool_results:
                for tr in msg.tool_results:
                    if tr.result_type == ToolResultType.A2UI:
                        a2ui_tc_ids.add(tr.tool_call_id)

        # 历史消息
        for msg in session.messages:
            if msg.role == MessageRole.SYSTEM:
                continue  # 已添加

            if msg.role == MessageRole.USER:
                messages.append({"role": "user", "content": msg.content})

            elif msg.role == MessageRole.ASSISTANT:
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or "",
                }
                if msg.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(
                                    tc.arguments, ensure_ascii=False
                                ),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                messages.append(assistant_msg)

            elif msg.role == MessageRole.TOOL:
                if msg.tool_results:
                    for tr in msg.tool_results:
                        llm_visible = resolve_llm_visible_content(
                            tr.content, tr.metadata,
                        )
                        if llm_visible is not tr.content:
                            # 若 guardrails 已提供模型可见副本，则优先把脱敏后的内容送入上下文。
                            content = llm_visible
                            if isinstance(content, (dict, list)):
                                content = json.dumps(content, ensure_ascii=False)
                            else:
                                content = str(content)
                        elif tr.tool_call_id in a2ui_tc_ids:
                            digest = (
                                tr.metadata.get("llm_digest") if tr.metadata else None
                            )
                            if digest:
                                content = f"[已向用户展示卡片] {digest}"
                            else:
                                raw = tr.content
                                n = len(raw) if isinstance(raw, list) else 1
                                content = f"[已向用户展示卡片，共{n}个组件]"
                        else:
                            content = tr.content
                            if isinstance(content, (dict, list)):
                                content = json.dumps(content, ensure_ascii=False)
                            else:
                                content = str(content)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tr.tool_call_id,
                                "content": content,
                            }
                        )

        return messages

    def _build_system_prompt(
        self,
        state: dict[str, Any],
        session_id: str | None = None,
        *,
        skill_load_mode: str = "full",
    ) -> str:
        """构建系统提示"""
        tools = self.tool_registry.list_all()

        # 将已注册的工具名注入，供 skill 资格检查使用
        skill_context = {**state, "available_tools": {t.name for t in tools}}

        # 提取最近的用户查询（供 skill matcher 做相关性判断）
        user_query: str | None = None
        if session_id:
            session = self.session_manager.get_session(session_id)
            if session:
                for msg in reversed(session.messages):
                    if msg.role == MessageRole.USER and msg.content:
                        user_query = msg.content
                        break

        # 获取匹配的技能
        skills = []
        if self.skill_matcher:
            match_result = self.skill_matcher.match(
                query=user_query, context=skill_context,
                skill_load_mode=skill_load_mode,
            )
            skills = match_result.matched_skills

        prompt_config = self.config.prompt_config

        # 当 enable_thinking_tags=True 且 prompt_config 未自定义指令时，自动填充默认模板
        if (
            self.config.enable_thinking_tags
            and not prompt_config.thinking_tag_instructions
        ):
            from .stream.thinking_tag_parser import DEFAULT_THINKING_TAG_INSTRUCTIONS

            prompt_config = replace(
                prompt_config,
                thinking_tag_instructions=DEFAULT_THINKING_TAG_INSTRUCTIONS,
            )

        # 默认只注入 user: 前缀的状态到提示词，减少噪声
        user_state = {k: v for k, v in state.items() if k.startswith("user:")}

        profile_content = ""
        if self._memory_manager:
            user_id = state.get("user:id")
            if user_id:
                from .memory.user_profile import truncate_profile
                try:
                    profile_content = truncate_profile(
                        self._memory_manager.read_memory(str(user_id))
                    )
                except Exception:
                    pass

        return SystemPromptBuilder.quick_build(
            tools=tools,
            skills=skills,
            context=user_state,
            config=prompt_config,
            user_profile_content=profile_content,
            skill_config=self.config.skill_config,
        )

    def _build_tools(self) -> list[dict[str, Any]]:
        """构建工具定义"""
        return [tool.get_json_schema() for tool in self.tool_registry.list_all()]

    def _get_llm(
        self,
        model_override: str | None = None,
        temperature_override: float | None = None,
    ) -> BaseChatModel:
        """向后兼容 — 委托给 LLMCaller.get_llm。"""
        return self._llm_caller.get_llm(model_override, temperature_override)

    # ============ 便捷方法 ============

    async def create_session(
        self,
        user_id: str,
        model: str = "Qwen3-80B-Instruct",
        provider: str = "ark",
        state: dict[str, Any] | None = None,
    ) -> str:
        """创建新会话并返回 ID（异步，支持持久化）"""
        session = await self.session_manager.create_session(
            user_id=user_id, model=model, provider=provider, state=state
        )
        return session.session_id

    def create_session_sync(
        self,
        model: str = "Qwen3-80B-Instruct",
        provider: str = "ark",
        state: dict[str, Any] | None = None,
    ) -> str:
        """创建新会话并返回 ID（同步，无持久化）"""
        session = self.session_manager.create_session_sync(
            model=model, provider=provider, state=state
        )
        return session.session_id

    def register_tool(self, tool: AgentTool) -> None:
        """注册工具"""
        self.tool_registry.register(tool)

    def register_tools(self, tools: list[AgentTool]) -> None:
        """批量注册工具"""
        self.tool_registry.register_all(tools)
