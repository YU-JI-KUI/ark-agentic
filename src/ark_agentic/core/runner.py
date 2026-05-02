"""Agent Runner - ReAct 执行器

使用 langchain ChatOpenAI 作为 LLM 后端。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, NamedTuple, TYPE_CHECKING
from uuid import uuid4

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
from .llm.sampling import SamplingConfig
from .prompt.builder import SystemPromptBuilder, PromptConfig
from .session import SessionManager
from .skills.base import SkillConfig
from .skills.loader import SkillLoader
from .skills.matcher import SkillMatcher
from .skills.router import RouteContext, SkillRouter
from .stream.event_bus import AgentEventHandler
from .tools.base import AgentTool
from .tools.executor import ToolExecutor
from .tools.registry import ToolRegistry
from .tools.memory import create_memory_tools
from .observability.decorators import (
    add_span_attributes,
    add_span_input,
    add_span_output,
    traced_agent,
    traced_chain,
)
from .types import (
    AgentMessage,
    AgentToolResult,
    MessageRole,
    RunOptions,
    SessionEntry,
    SkillEntry,
    SkillLoadMode,
    ToolCall,
    ToolLoopAction,
    ToolResultType,
    TurnContext,
)
if TYPE_CHECKING:
    from .memory.manager import MemoryManager

logger = logging.getLogger(__name__)


def _build_runner_callbacks(
    *,
    config: RunnerConfig,
    callbacks: RunnerCallbacks | None,
) -> RunnerCallbacks:
    """Business hooks only — observability is handled by OTel decorators."""
    return callbacks or RunnerCallbacks()


# ============ Runner Config ============


@dataclass
class RunnerConfig:
    """Runner 配置"""

    # LLM 参数
    model: str | None = None
    sampling: SamplingConfig = field(default_factory=SamplingConfig.for_chat)

    # LLM 调用重试（指数退避 + 抖动，仅对 retryable 错误生效）
    max_retries: int = 3

    # 执行控制
    max_turns: int = 10  # 最大对话轮数（防止无限循环）
    max_tool_calls_per_turn: int = 5  # 单轮最大工具调用数
    tool_timeout: float = 30.0  # 单个工具执行超时（秒）

    # 自动压缩
    auto_compact: bool = True

    # 提示配置
    prompt_config: PromptConfig = field(default_factory=PromptConfig)

    # 技能配置
    skill_config: SkillConfig = field(default_factory=SkillConfig)

    # 子任务（启用后自动注册 spawn_subtasks 工具）
    enable_subtasks: bool = False

    # Dream 开关：False 时不创建 MemoryDreamer，即使 memory 系统已启用也不会执行后台蒸馏
    enable_dream: bool = True

    # Dream 触发：最少 session 数（OR 语义：时间够 或 session 数够）
    dream_min_sessions: int = 5

    # 外部历史合并（agent 级开关）
    accept_external_history: bool = True

    # Skill 路由器（dynamic 模式专用）。
    # 实例：在 ReAct 循环开始前确定性写入 session.active_skill_ids（SSOT）。
    # None：runner 不会 route；通常由 build_standard_agent 在 dynamic 模式下
    # 自动注入 LLMSkillRouter。直接构造 AgentRunner 时由调用方自负其责。
    skill_router: SkillRouter | None = None


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

    # 是否因达到限制而停止
    stopped_by_limit: bool = False


# ============ Run Params / Loop State ============


class _RunParams(NamedTuple):
    """Resolved per-run parameters (pure computation result)."""

    model: str | None
    sampling_override: SamplingConfig | None
    skill_load_mode: str


@dataclass
class _LoopState:
    """ReAct loop 累积状态（私有）。"""

    turns: int = 0
    total_tool_calls: int = 0
    all_tool_calls: list[ToolCall] = field(default_factory=list)
    all_tool_results: list[AgentToolResult] = field(default_factory=list)

    def make_result(self, response: AgentMessage, **overrides: Any) -> RunResult:
        return RunResult(
            response=response,
            turns=self.turns,
            tool_calls_count=self.total_tool_calls,
            tool_calls=self.all_tool_calls,
            tool_results=self.all_tool_results,
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
        self._flusher = None
        self._dreamer = None
        self._dream_tasks: dict[str, asyncio.Task[Any]] = {}
        self._dream_failures: dict[str, int] = {}

        # LLMCaller / ToolExecutor (SRP)
        self._llm_caller = LLMCaller(
            llm,
            max_retries=self.config.max_retries,
        )
        self._tool_executor = ToolExecutor(
            self.tool_registry,
            timeout=self.config.tool_timeout,
            max_calls_per_turn=self.config.max_tool_calls_per_turn,
        )

        if memory_manager is not None:
            from .memory.extractor import MemoryFlusher

            # Memory flush 是结构化 JSON 抽取任务，需要低温度 + 可复现 seed
            extraction_sampling = SamplingConfig.for_extraction()
            self._flusher = MemoryFlusher(
                lambda: self._llm_caller.get_llm(sampling_override=extraction_sampling)
            )

            if self.config.enable_dream:
                from .memory.dream import MemoryDreamer

                summarization_sampling = SamplingConfig.for_summarization()
                self._dreamer = MemoryDreamer(
                    lambda: self._llm_caller.get_llm(
                        sampling_override=summarization_sampling
                    )
                )
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

        # Skill router: caller is the source of truth. Wiring concerns
        # (default selection, mode validation) live in build_standard_agent.
        # Direct AgentRunner construction trusts whatever RunnerConfig provides.
        self._skill_router: SkillRouter | None = self.config.skill_router

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
        """Warmup hook — 执行 services 模块附加的 _warmup_tasks。

        runner 本身不感知具体任务(job 注册、资源预热等);services 层通过
        apply_*_bindings() 在构造后追加任务,此处仅负责依次触发。
        """
        tasks = getattr(self, "_warmup_tasks", None)
        if not tasks:
            return
        for task in tasks:
            await task()

    @property
    def memory_manager(self) -> "MemoryManager | None":
        return self._memory_manager

    def mark_memory_dirty(self) -> None:
        """保留接口兼容 — 无 SQLite 索引，无需刷新标记。"""

    async def close_memory(self) -> None:
        """保留接口兼容 — 无需释放资源。"""

    @traced_agent("agent.run", span_name_template="agent.run:{self.config.skill_config.agent_id}")
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
        run_id = uuid4().hex
        run_metadata: dict[str, Any] = {
            "user_id": user_id,
            "agent_id": self.config.skill_config.agent_id,
            "agent_name": self.config.prompt_config.agent_name,
            "model": params.model,
            "stream": stream,
            "skill_load_mode": params.skill_load_mode,
            "correlation_id": input_context.get("temp:trace_id"),
        }
        add_span_attributes({
            "session.id": session_id,
            "user.id": user_id,
            "ark.run_id": run_id,
            "ark.agent_id": self.config.skill_config.agent_id,
            "ark.agent_name": self.config.prompt_config.agent_name,
            "ark.model": params.model,
            "ark.stream": stream,
            "ark.skill_load_mode": params.skill_load_mode,
            "ark.correlation_id": input_context.get("temp:trace_id"),
        })
        add_span_input({"user_input": user_input, "input_context": input_context})
        prepared = await self._prepare_session(
            session_id,
            user_id,
            user_input,
            input_context,
            handler=handler,
            history=history,
            use_history=use_history,
            run_id=run_id,
            run_metadata=run_metadata,
        )
        if isinstance(prepared, RunResult):
            add_span_attributes({
                "ark.aborted": True,
                "ark.turns": 0,
            })
            add_span_output({"response": prepared.response.content})
            return prepared

        cb_ctx = prepared
        # Phase: deterministic skill routing (dynamic mode only).
        # Writes session.active_skill_ids (SSOT); first ReAct turn picks it up
        # via _build_system_prompt + _filter_tools. No-op in full mode.
        await self._route_skill_phase(session_id, cb_ctx)

        try:
            result = await self._run_loop(
                session_id,
                use_streaming=stream,
                model_override=params.model,
                sampling_override=params.sampling_override,
                skill_load_mode=params.skill_load_mode,
                handler=handler,
                cb_ctx=cb_ctx,
            )
        finally:
            await self.session_manager.sync_pending_messages(session_id, user_id)

        await self._finalize_run(session_id, user_id, result, cb_ctx, handler)
        add_span_attributes({
            "ark.turns": result.turns,
            "ark.tool_calls_count": result.tool_calls_count,
            "ark.stopped_by_limit": result.stopped_by_limit,
        })
        add_span_output({
            "content": result.response.content,
            "has_tool_calls": bool(result.response.tool_calls),
        })
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
            sampling_override=params.sampling_override,
            skill_load_mode=params.skill_load_mode,
        )

    # ---- run() lifecycle phases ----

    def _resolve_run_params(self, run_options: RunOptions | None) -> _RunParams:
        """Pure parameter resolution from run_options + config defaults."""
        model = (run_options.model if run_options else None) or self.config.model
        sampling_override: SamplingConfig | None = None
        if run_options and run_options.temperature is not None:
            sampling_override = self.config.sampling.model_copy(
                update={"temperature": run_options.temperature}
            )
        skill_load_mode = self.config.skill_config.load_mode.value
        return _RunParams(
            model=model,
            sampling_override=sampling_override,
            skill_load_mode=skill_load_mode,
        )

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
        run_id: str,
        run_metadata: dict[str, Any],
    ) -> RunResult | CallbackContext:
        """Lazy init, before_agent hooks, context merge, history merge, record user message, auto-compact.

        Returns RunResult on halt (early exit), CallbackContext on success.
        """
        # Pop display-only meta:* keys before they reach AgentMessage.metadata via
        # input_context. They re-enter under their proper top-level key names below.
        chat_request_meta = input_context.pop("meta:chat_request", None)

        session = self.session_manager.get_session_required(session_id)
        session.user_id = user_id
        cb_ctx = CallbackContext(
            run_id=run_id,
            user_input=user_input,
            input_context=input_context,
            session=session,
            metadata=run_metadata,
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
            self._augment_user_metadata(user_message, chat_request_meta)
            self.session_manager.add_message_sync(session_id, user_message)
            resp = r.response or AgentMessage.assistant("")
            self.session_manager.add_message_sync(session_id, resp)
            await self.session_manager.sync_pending_messages(session_id, user_id)
            result = RunResult(response=resp)
            cb_result = await self._run_hooks(
                self._callbacks.after_agent,
                cb_ctx,
                response=result.response,
                result=result,
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
        self._augment_user_metadata(user_message, chat_request_meta)
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

    @staticmethod
    def _augment_user_metadata(
        msg: AgentMessage,
        chat_request: dict[str, Any] | None,
    ) -> None:
        """Display-only metadata for the Studio user-message panel.

        Only `chat_request` lives here; trace correlation is observability
        cross-cut surfaced via the assistant message's trace.trace_id link.
        """
        if chat_request:
            msg.metadata["chat_request"] = chat_request

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
            result=result,
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
            if not should_dream(user_id, workspace, sessions_dir,
                               min_sessions=self.config.dream_min_sessions):
                return
        except Exception:
            logger.debug("Dream gate check failed for user %s", user_id, exc_info=True)
            return

        memory_path = self._memory_manager.memory_path(user_id)
        self._dream_tasks[user_id] = asyncio.create_task(
            self._run_dream(user_id, memory_path, sessions_dir)
        )
        logger.info("Dream triggered for user %s", user_id)

    _DREAM_FAILURE_THRESHOLD = 3

    async def _run_dream(
        self, user_id: str, memory_path: Path, sessions_dir: Path,
    ) -> None:
        """Background dream cycle with error handling and retry protection."""
        assert self._dreamer is not None
        assert self._memory_manager is not None
        try:
            result = await self._dreamer.run(memory_path, sessions_dir, user_id)
            self._dream_failures.pop(user_id, None)
            logger.info("Dream completed for user %s: %s", user_id, result.changes)
        except Exception:
            logger.warning("Dream failed for user %s", user_id, exc_info=True)
            failures = self._dream_failures.get(user_id, 0) + 1
            self._dream_failures[user_id] = failures
            if failures >= self._DREAM_FAILURE_THRESHOLD:
                from .memory.dream import touch_last_dream
                workspace = Path(self._memory_manager.config.workspace_dir)
                touch_last_dream(user_id, workspace)
                self._dream_failures.pop(user_id, None)
                logger.warning(
                    "Dream failed %d consecutive times for %s, advancing .last_dream",
                    failures, user_id,
                )

    @staticmethod
    def _merge_tool_state_deltas(
        session: SessionEntry,
        tool_results: list[AgentToolResult],
    ) -> None:
        for tr in tool_results:
            state_delta = tr.state_delta if tr.state_delta is not None else tr.metadata.get("state_delta")
            if state_delta and isinstance(state_delta, dict):
                AgentRunner._apply_state_delta(session.state, state_delta)
                session.updated_at = __import__("datetime").datetime.now()

    @staticmethod
    def _apply_session_effects(
        session: SessionEntry,
        tool_results: list[AgentToolResult],
    ) -> None:
        """Dispatch typed `session_effects` from tool results to SessionEntry mutations.

        与 `_merge_tool_state_deltas` 并列：state_delta 通道只处理 `session.state`
        通用 dict 变更，session_effects 通道处理 SessionEntry 上的 typed 字段
        变更（如 active_skill_ids），两者完全解耦。

        畸形 effect 记录 warning 并 skip，不抛异常（防御工具路径，避免一条坏
        effect 阻断整轮）。
        """
        from pydantic import ValidationError
        from .types import SessionEffect

        for tr in tool_results:
            effects = tr.session_effects if tr.session_effects is not None else tr.metadata.get("session_effects", [])
            if not isinstance(effects, list):
                continue
            for raw in effects:
                try:
                    effect = SessionEffect.model_validate(raw)
                except ValidationError as exc:
                    logger.warning("invalid session_effect %r: %s", raw, exc)
                    continue
                if effect.op == "activate_skill":
                    session.set_active_skill_ids(effect.skill_ids)

    @staticmethod
    def _apply_state_delta(state: dict[str, Any], delta: dict[str, Any]) -> None:
        """支持点路径（dot-path）的深度合并。

        普通 key → state[key] = value（浅覆盖）
        点路径 key（如 "_flow_context.stage_identity_verify"）→ 逐层 setdefault({}) 后赋值，
        不整体替换父对象，避免清空同级其他 key。
        """
        for key, value in delta.items():
            if "." in key:
                parts = key.split(".")
                obj = state
                for part in parts[:-1]:
                    if not isinstance(obj.get(part), dict):
                        obj[part] = {}
                    obj = obj[part]
                obj[parts[-1]] = value
            else:
                state[key] = value

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
        sampling_override: SamplingConfig | None = None,
        skill_load_mode: str = "full",
        handler: AgentEventHandler | None = None,
        cb_ctx: CallbackContext | None = None,
    ) -> RunResult:
        """ReAct loop: LLM → Tool → LLM → ... → Response"""
        ls = _LoopState()
        logger.info("[RUN] session=%s streaming=%s", session_id[:8], use_streaming)

        while ls.turns < self.config.max_turns:
            ls.turns += 1
            result = await self._run_turn(
                session_id,
                ls,
                use_streaming=use_streaming,
                model_override=model_override,
                sampling_override=sampling_override,
                skill_load_mode=skill_load_mode,
                handler=handler,
                cb_ctx=cb_ctx,
            )
            if result is not None:
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

    @traced_chain("agent.turn", span_name_template="agent.turn-{ls.turns}")
    async def _run_turn(
        self,
        session_id: str,
        ls: _LoopState,
        *,
        use_streaming: bool,
        model_override: str | None,
        sampling_override: SamplingConfig | None,
        skill_load_mode: str,
        handler: AgentEventHandler | None,
        cb_ctx: CallbackContext | None,
    ) -> RunResult | None:
        """One ReAct turn. Returns RunResult to terminate, or None to continue."""
        add_span_attributes({"ark.turn": ls.turns})
        session = self.session_manager.get_session_required(session_id)
        # full 模式不变量：每轮以"全部已加载 skill"覆盖 active_skill_ids（SSOT）。
        # 外部 API 写入 full 模式 session 的 active_skill_ids 在下轮被 clobber。
        if (
            skill_load_mode == SkillLoadMode.full.value
            and self.skill_loader is not None
        ):
            session.set_active_skill_ids(self.skill_loader.list_skill_ids())
        state = session.state
        messages = self._build_messages(
            session_id, state,
            skill_load_mode=skill_load_mode,
            session=session,
        )
        tools = self._build_tools(state=state, session=session)

        tools_mounted = [
            (t.get("function", {}).get("name") or t.get("name") or "")
            for t in tools
        ]
        tools_mounted = [n for n in tools_mounted if n]

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
            sampling_override=sampling_override,
            handler=handler,
            cb_ctx=cb_ctx,
        )
        if isinstance(model_result, RunResult):
            return model_result

        response = model_result
        ctx_session = self.session_manager.get_session(session_id)
        response.turn_context = TurnContext(
            active_skill_id=ctx_session.current_active_skill_id if ctx_session else None,
            tools_mounted=tools_mounted,
        )
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
            return None

        return await self._complete_phase(
            session_id, ls, response, state,
            handler=handler, cb_ctx=cb_ctx,
        )

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

    @traced_chain("agent.model_phase")
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
        sampling_override: SamplingConfig | None,
        handler: AgentEventHandler | None,
        cb_ctx: CallbackContext | None,
    ) -> AgentMessage | RunResult:
        """before_model → LLM call → after_model → persist → tokens → finish_reason."""
        add_span_attributes({
            "ark.turn": ls.turns,
            "ark.streaming": use_streaming,
            "ark.message_count": len(messages),
            "ark.tool_count": len(tools),
            "ark.model": model_override or self.config.model,
        })
        add_span_input({"messages": messages})
        bm = await self._run_hooks(
            self._callbacks.before_model,
            cb_ctx,
            turn=ls.turns,
            messages=messages,
            streaming=use_streaming,
            model=model_override or self.config.model,
            tool_count=len(tools),
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

            try:
                if use_streaming:
                    response = await self._llm_caller.call_streaming(
                        messages,
                        tools,
                        model_override=model_override,
                        sampling_override=sampling_override,
                        content_callback=_on_content,
                    )
                else:
                    response = await self._llm_caller.call(
                        messages,
                        tools,
                        model_override=model_override,
                        sampling_override=sampling_override,
                    )
            except LLMError as e:
                await self._run_hooks(
                    self._callbacks.on_model_error,
                    cb_ctx,
                    turn=ls.turns,
                    error=e,
                    handler=handler,
                )
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

        from .observability import current_trace_id_or_none
        trace_id = current_trace_id_or_none()
        if trace_id:
            response.metadata.setdefault("trace", {})["trace_id"] = trace_id

        finish_reason = response.finish_reason
        logger.info(
            "Turn %d | finish_reason=%s content_len=%d tool_calls=%d",
            ls.turns,
            finish_reason,
            len(response.content or ""),
            len(response.tool_calls or []),
        )

        self.session_manager.add_message_sync(session_id, response)

        add_span_attributes({
            "ark.finish_reason": finish_reason,
            "ark.response_content_length": len(response.content or ""),
            "ark.tool_call_count": len(response.tool_calls or []),
        })
        add_span_output({
            "content": response.content,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in (response.tool_calls or [])
            ],
            "finish_reason": finish_reason,
        })

        if finish_reason == "length":
            logger.warning("Response truncated (max_tokens) in session %s", session_id)
            return ls.make_result(response, stopped_by_limit=True)

        return response

    @traced_chain("agent.tool_phase")
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
        add_span_attributes({
            "ark.turn": ls.turns,
            "ark.tool_count": len(tool_calls),
            "ark.tool_names": ",".join(tc.name for tc in tool_calls),
        })
        add_span_input([
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in tool_calls
        ])

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
                {
                    **state,
                    "session_id": session_id,
                    "_active_skill_id": session.current_active_skill_id,
                },
                handler=handler,
            )

        ls.total_tool_calls += len(tool_calls)
        ls.all_tool_results.extend(tool_results)

        self._merge_tool_state_deltas(session, tool_results)
        self._apply_session_effects(session, tool_results)

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
            self._apply_session_effects(session, tool_results)

        tool_message = AgentMessage.tool(tool_results)
        self.session_manager.add_message_sync(session_id, tool_message)

        add_span_attributes({
            "ark.result_count": len(tool_results),
            "ark.error_count": sum(1 for r in tool_results if r.is_error),
            "ark.stop_result_count": sum(
                1 for r in tool_results if r.loop_action == ToolLoopAction.STOP
            ),
        })
        add_span_output([
            {
                "tool_call_id": r.tool_call_id,
                "is_error": r.is_error,
                "result_type": getattr(r.result_type, "value", r.result_type),
                "loop_action": getattr(r.loop_action, "value", r.loop_action),
            }
            for r in tool_results
        ])

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
        """Final turn summary."""
        logger.info(
            "[RUN_END] session=%s turns=%d tool_calls=%d",
            session_id[:8],
            ls.turns,
            ls.total_tool_calls,
        )
        return ls.make_result(response)

    def _build_messages(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        skill_load_mode: str = "full",
        session: SessionEntry | None = None,
    ) -> list[dict[str, Any]]:
        """构建 LLM 消息列表。"""
        import json

        if session is None:
            session = self.session_manager.get_session_required(session_id)
        messages: list[dict[str, Any]] = []

        # 系统提示
        system_prompt = self._build_system_prompt(
            state,
            session_id=session_id,
            skill_load_mode=skill_load_mode,
            session=session,
        )
        messages.append({"role": "system", "content": system_prompt})

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
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tr.tool_call_id,
                                "content": tr.llm_digest,
                            }
                        )

        return messages

    @traced_chain("agent.skill_route")
    async def _route_skill_phase(
        self,
        session_id: str,
        cb_ctx: CallbackContext,
    ) -> None:
        """Dynamic 模式下，在 ReAct 循环前确定性激活一个 skill。

        写入 session.active_skill_ids（SSOT），newest-wins 语义。
        Router 出错或决定为 None 时，保留原值不变。
        """
        if self._skill_router is None or self.skill_loader is None:
            return

        session = cb_ctx.session
        candidates = self._match_skills(
            session.state, session_id, skill_load_mode="dynamic",
        )
        if not candidates:
            return

        history_window = self._skill_router.history_window
        history = (
            session.messages[-history_window:] if history_window else []
        )

        ctx = RouteContext(
            user_input=cb_ctx.user_input,
            history=history,
            current_active_skill_id=session.current_active_skill_id,
            candidate_skills=candidates,
        )

        try:
            decision = await self._skill_router.route(ctx)
        except Exception as exc:  # Protocol violation defense
            logger.warning(
                "Skill router raised (Protocol violation): %s", exc, exc_info=True,
            )
            return

        current = session.current_active_skill_id
        if decision.skill_id and decision.skill_id != current:
            self.session_manager.set_active_skill_ids(
                session.session_id, [decision.skill_id]
            )
            logger.info(
                "Skill routed: %s → %s (reason=%s)",
                current or "<none>", decision.skill_id, decision.reason,
            )

        add_span_attributes({
            "ark.router.candidate_count": len(candidates),
            "ark.router.decision": decision.skill_id or "none",
            "ark.router.reason": decision.reason,
        })

    def _match_skills(
        self,
        state: dict[str, Any],
        session_id: str | None = None,
        *,
        skill_load_mode: str = "full",
    ) -> list[SkillEntry]:
        """统一技能匹配入口，供 _run_loop 一次匹配、多处复用。"""
        if not self.skill_matcher:
            return []

        tools = self.tool_registry.list_all()
        skill_context = {**state, "available_tools": {t.name for t in tools}}

        user_query: str | None = None
        if session_id:
            session = self.session_manager.get_session(session_id)
            if session:
                for msg in reversed(session.messages):
                    if msg.role == MessageRole.USER and msg.content:
                        user_query = msg.content
                        break

        match_result = self.skill_matcher.match(
            query=user_query, context=skill_context,
            skill_load_mode=skill_load_mode,
        )
        return match_result.matched_skills

    def _build_system_prompt(
        self,
        state: dict[str, Any],
        session_id: str | None = None,
        *,
        skill_load_mode: str = "full",
        session: SessionEntry | None = None,
    ) -> str:
        """构建系统提示。

        dynamic 模式下，若 session.active_skill_ids 非空，则将其末元素
        （newest-wins）对应 skill 正文注入 <active_skill> 段；此时传入 builder
        的 tools 与 `_build_tools` 同源（经 `_filter_tools` 筛选），保证 system
        prompt 描述的工具集与 API tools schema 一致。
        """
        tools = self._filter_tools(state, session=session)

        skills = self._match_skills(
            state, session_id, skill_load_mode=skill_load_mode,
        )

        active_skill: SkillEntry | None = None
        if skill_load_mode != SkillLoadMode.full.value and self.skill_loader:
            active_id = session.current_active_skill_id if session else None
            if active_id:
                active_skill = self.skill_loader.get_skill(active_id)

        # Dynamic reference 注入: 有 _flow_stage 时按阶段按需追加 reference 内容
        current_stage_id = state.get("_flow_stage")
        if current_stage_id and current_stage_id != "__completed__" and skills:
            skills = self._enrich_skills_with_stage_reference(skills, current_stage_id)

        prompt_config = self.config.prompt_config

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

        flow_hint = state.get("_flow_hint", "")

        return SystemPromptBuilder.quick_build(
            tools=tools,
            skills=skills,
            active_skill=active_skill,
            context=user_state,
            config=prompt_config,
            user_profile_content=profile_content,
            skill_config=self.config.skill_config,
            enable_memory=self._memory_manager is not None,
            flow_hint=flow_hint,
        )

    def _filter_tools(
        self,
        state: dict[str, Any] | None = None,
        *,
        session: SessionEntry | None = None,
    ) -> list[AgentTool]:
        """按 skill_load_mode 与 session.active_skill_ids 筛选可见工具（单一事实源）。

        full 模式: 全部返回。
        dynamic 模式: always 工具始终可见；auto 工具仅在 session.active_skill_ids
            末元素（newest-wins）对应的技能被激活后才暴露给 LLM。

        `_build_tools` 与 `_build_system_prompt` 都以此为准，保证 API tools
        schema 与 system prompt 中的工具描述（若开启）同源。
        """
        all_tools = self.tool_registry.list_all()

        if (
            not self.skill_loader
            or self.config.skill_config.load_mode == SkillLoadMode.full
        ):
            return all_tools

        always = [t for t in all_tools if getattr(t, "visibility", "auto") == "always"]

        active_skill_id = session.current_active_skill_id if session else None
        if not active_skill_id:
            return always

        skill = self.skill_loader.get_skill(active_skill_id)
        allowed = set(skill.metadata.required_tools or []) if skill else set()
        seen = {t.name for t in always}
        skill_tools = [t for t in all_tools if t.name in allowed and t.name not in seen]
        return always + skill_tools

    def _build_tools(
        self,
        state: dict[str, Any] | None = None,
        *,
        session: SessionEntry | None = None,
    ) -> list[dict[str, Any]]:
        """构建 API tools schema（`_filter_tools` 的薄包装）。"""
        return [t.get_json_schema() for t in self._filter_tools(state, session=session)]

    @staticmethod
    def _enrich_skills_with_stage_reference(
        skills: list, current_stage_id: str
    ) -> list:
        """根据 _flow_stage，将当前阶段 reference 文件内容追加到对应 SkillEntry.content。

        通过 FlowEvaluatorRegistry 反查 evaluator，使用 StageDefinition.reference_file
        （而非直接拼接 stage.id），避免文件名与 stage.id 不一致导致静默失败。
        """
        from .flow.base_evaluator import FlowEvaluatorRegistry

        enriched = []
        for skill in skills:
            # 尝试用完整 id 和短 id（去掉 agent 前缀）查找 evaluator
            skill_short = skill.id.split(".")[-1]
            evaluator = FlowEvaluatorRegistry.get(skill.id) or FlowEvaluatorRegistry.get(skill_short)

            ref_filename: str | None = None
            if evaluator:
                stage_def = next(
                    (s for s in evaluator.stages if s.id == current_stage_id), None
                )
                ref_filename = stage_def.reference_file if stage_def else None

            if ref_filename:
                from pathlib import Path
                ref_path = Path(skill.path) / "references" / ref_filename
                if ref_path.exists():
                    ref_content = ref_path.read_text(encoding="utf-8")
                    enriched.append(replace(
                        skill,
                        content=(
                            skill.content
                            + f"\n\n---\n### 当前阶段参考: {current_stage_id}\n\n"
                            + ref_content
                        ),
                    ))
                    continue
                else:
                    import warnings
                    warnings.warn(
                        f"[FlowEvaluator] reference file not found: {ref_path}",
                        stacklevel=4,
                    )
            enriched.append(skill)
        return enriched

    def _get_llm(
        self,
        model_override: str | None = None,
        sampling_override: SamplingConfig | None = None,
    ) -> BaseChatModel:
        """委托给 LLMCaller.get_llm（支持模型 / 采样参数覆盖）。"""
        return self._llm_caller.get_llm(
            model_override=model_override,
            sampling_override=sampling_override,
        )

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
