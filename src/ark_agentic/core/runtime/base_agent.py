"""BaseAgent — the agent itself (identity + ReAct execution + state).

Subclassing contract:

    class InsuranceAgent(BaseAgent):
        agent_id          = "insurance"
        agent_name        = "保险智能助手"
        agent_description = "..."

        def build_tools(self):
            return create_insurance_tools(sessions_dir=self.sessions_dir)

The framework discovers ``BaseAgent`` subclasses under the configured
agents root, instantiates each (zero-arg ``__init__``), and registers
them by ``agent_id``. ``__init__`` is ``@final``: do not override.
Customize via ``ClassVar`` attributes and ``build_*`` hooks.
"""

from __future__ import annotations

import inspect
import json
import logging
from abc import ABC
from pathlib import Path
from typing import Any, ClassVar, TYPE_CHECKING, final
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel

from ._runner_helpers import (
    apply_session_effects,
    apply_state_delta,
    augment_user_metadata,
    dispatch_event,
    enrich_skills_with_stage_reference,
    merge_input_context,
    merge_tool_state_deltas,
    user_friendly_error_message,
)
from ._runner_types import _LoopState, _RunParams, RunResult, RunnerConfig
from .callbacks import (
    CallbackContext,
    CallbackResult,
    HookAction,
    RunnerCallbacks,
)
from ..llm import create_chat_model_from_env
from ..llm.caller import LLMCaller
from ..llm.errors import LLMError
from ..llm.sampling import SamplingConfig
from ..memory.manager import build_memory_manager
from ..paths import get_memory_base_dir, prepare_agent_data_dir
from ..prompt.builder import SystemPromptBuilder, PromptConfig
from ..session.compaction import CompactionConfig, LLMSummarizer
from ..session.manager import SessionManager
from ..skills.base import SkillConfig
from ..skills.loader import SkillLoader
from ..skills.matcher import SkillMatcher
from ..skills.router import LLMSkillRouter, RouteContext, SkillRouter
from ..stream.event_bus import AgentEventHandler
from ..tools.base import AgentTool
from ..tools.executor import ToolExecutor
from ..tools.memory import create_memory_tools
from ..tools.registry import ToolRegistry
from ..observability.decorators import (
    add_span_attributes,
    add_span_input,
    add_span_output,
    traced_agent,
    traced_chain,
)
from ..types import (
    AgentMessage,
    MessageRole,
    RunOptions,
    SessionEntry,
    SkillEntry,
    SkillLoadMode,
    ToolLoopAction,
    TurnContext,
)
from ..utils.env import env_flag

if TYPE_CHECKING:
    from ..memory.extractor import MemoryFlusher
    from ..memory.manager import MemoryManager

logger = logging.getLogger(__name__)


# ============ Base Agent ============


class BaseAgent(ABC):
    """The agent: identity + tools/skills + ReAct execution + state.

    Subclass and declare identity at the class level; the framework
    instantiates exactly once per process and serves traffic against
    that instance. ``__init__`` is final — customize via ``ClassVar``
    attributes and ``build_*`` hooks.
    """

    # ── Identity (subclass MUST declare agent_id; others have defaults) ─
    agent_id: ClassVar[str]
    agent_name: ClassVar[str] = ""
    agent_description: ClassVar[str] = ""

    # ── Behavior knobs (subclass may override) ──────────────────────────
    system_protocol: ClassVar[str] = ""
    custom_instructions: ClassVar[str] = ""
    enable_subtasks: ClassVar[bool] = False
    max_turns: ClassVar[int] = 10
    skill_load_mode: ClassVar[SkillLoadMode] = SkillLoadMode.dynamic

    # ── Convention paths ────────────────────────────────────────────────
    @property
    def sessions_dir(self) -> Path:
        return prepare_agent_data_dir(self.agent_id)

    @property
    def memory_dir(self) -> Path:
        return get_memory_base_dir() / self.agent_id

    @property
    def skills_dir(self) -> Path:
        """Convention: ``skills/`` directory next to the subclass module."""
        try:
            module_file = inspect.getfile(type(self))
        except TypeError:
            return Path.cwd() / "skills"
        return Path(module_file).resolve().parent / "skills"

    # ── Process-global toggles (env-driven; subclass may override) ──────
    @property
    def enable_memory(self) -> bool:
        return env_flag("ENABLE_MEMORY")

    @property
    def enable_dream(self) -> bool:
        if "ENABLE_DREAM" in __import__("os").environ:
            return env_flag("ENABLE_DREAM")
        return True

    # ── Build hooks (subclass overrides as needed) ──────────────────────
    def build_tools(self) -> list[AgentTool]:
        """Override to expose agent-specific business tools."""
        return []

    def build_callbacks(self) -> RunnerCallbacks | None:
        """Override to attach business hooks (auth, citations, flow…)."""
        return None

    def build_llm(self) -> BaseChatModel:
        """Override to inject a non-default LLM (default reads env)."""
        return create_chat_model_from_env()

    def build_sampling(self) -> SamplingConfig:
        return SamplingConfig.for_chat()

    def build_compaction(self) -> CompactionConfig:
        return CompactionConfig(context_window=128_000, preserve_recent=4)

    def build_skill_router(self) -> SkillRouter | None:
        """Default: ``LLMSkillRouter`` in dynamic mode, ``None`` in full mode."""
        if self.skill_load_mode == SkillLoadMode.dynamic:
            return LLMSkillRouter(
                llm_factory=lambda: self.llm,
                history_window=6,
                timeout=5.0,
            )
        return None

    # ── Construction ────────────────────────────────────────────────────
    @final
    def __init__(self) -> None:
        self._validate_subclass_declaration()
        self.llm = self.build_llm()
        skill_config = self._init_skill_subsystem()
        self._init_session_manager()
        self._init_tool_registry()
        self._init_memory_manager()
        self._callbacks = self.build_callbacks() or RunnerCallbacks()
        self._skill_router: SkillRouter | None = self.build_skill_router()
        self._init_engine_internals(
            skill_config=skill_config, sampling=self.build_sampling(),
        )
        self._finish_wiring(
            skill_loader=self.skill_loader,
            skill_load_mode=self.skill_load_mode,
            memory_manager=self._memory_manager,
        )
        self._register_subtask_tool_if_enabled()

    # ── __init__ phases (private; @final __init__ orchestrates) ─────────
    def _validate_subclass_declaration(self) -> None:
        """Reject direct ``BaseAgent()`` and malformed identity declarations."""
        cls = type(self)
        if cls is BaseAgent:
            raise TypeError(
                "BaseAgent cannot be instantiated directly; subclass it and "
                "declare agent_id / agent_name / agent_description."
            )
        if "agent_id" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must declare a class-level 'agent_id' "
                "(non-empty string)."
            )
        if not isinstance(cls.agent_id, str) or not cls.agent_id:
            raise TypeError(
                f"{cls.__name__}.agent_id must be a non-empty string; "
                f"got {cls.agent_id!r}."
            )

    def _init_skill_subsystem(self) -> SkillConfig:
        """Build SkillLoader + SkillMatcher; return SkillConfig for RunnerConfig."""
        skill_config = SkillConfig(
            skill_directories=[str(self.skills_dir)],
            agent_id=self.agent_id,
            enable_eligibility_check=True,
            load_mode=self.skill_load_mode,
        )
        self.skill_loader: SkillLoader | None = SkillLoader(skill_config)
        try:
            self.skill_loader.load_from_directories()
            logger.info(
                "Loaded %d skills for agent '%s'",
                len(self.skill_loader.list_skills()),
                self.agent_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load skills for agent '%s': %s", self.agent_id, exc,
            )
        self.skill_matcher: SkillMatcher | None = SkillMatcher(self.skill_loader)
        return skill_config

    def _init_session_manager(self) -> None:
        self.session_manager = SessionManager(
            sessions_dir=self.sessions_dir,
            compaction_config=self.build_compaction(),
            summarizer=LLMSummarizer(self.llm),
            agent_id=self.agent_id,
        )

    def _init_tool_registry(self) -> None:
        self.tool_registry = ToolRegistry()
        self.tool_registry.register_all(self.build_tools())

    def _init_memory_manager(self) -> None:
        """Build MemoryManager when ``enable_memory``; tools/flusher come later
        via ``_finish_wiring`` (shared with the explicit-args ``_construct``)."""
        self._memory_manager: "MemoryManager | None" = None
        if self.enable_memory:
            self._memory_manager = build_memory_manager(
                memory_dir=self.memory_dir,
                agent_id=self.agent_id,
                enable_dream=self.enable_dream,
                session_manager=self.session_manager,
                llm_factory=(lambda: self.llm) if self.enable_dream else None,
            )

    def _init_engine_internals(
        self, *, skill_config: SkillConfig, sampling: SamplingConfig,
    ) -> None:
        """Assemble RunnerConfig + LLMCaller + ToolExecutor; init flusher slot."""
        self.config = RunnerConfig(
            sampling=sampling,
            max_turns=self.max_turns,
            enable_subtasks=self.enable_subtasks,
            prompt_config=PromptConfig(
                agent_name=self.agent_name,
                agent_description=self.agent_description,
                system_protocol=self.system_protocol,
                custom_instructions=self.custom_instructions,
            ),
            skill_config=skill_config,
            skill_router=self._skill_router,
        )
        self._llm_caller = LLMCaller(self.llm, max_retries=self.config.max_retries)
        self._tool_executor = ToolExecutor(
            self.tool_registry,
            timeout=self.config.tool_timeout,
            max_calls_per_turn=self.config.max_tool_calls_per_turn,
        )
        self._flusher: "MemoryFlusher | None" = None

    def _register_subtask_tool_if_enabled(self) -> None:
        """Subtask spawn-tool needs ``self`` (to fork sub-agents) and the
        already-built session manager — must run after both exist."""
        if not self.enable_subtasks:
            return
        from ..subtask import create_subtask_tool
        self.tool_registry.register(
            create_subtask_tool(self, self.session_manager)
        )

    # ── Internal explicit-args constructor ──────────────────────────────
    @classmethod
    def _assign_subagent_identity(
        cls, instance: "BaseAgent", agent_id: str | None,
    ) -> None:
        """Resolve identity for an ephemeral subagent and write it to the
        instance via ``object.__setattr__`` (bypasses the ``ClassVar``
        descriptor so a subagent can have an id distinct from its class
        — needed because subagents are spawned from arbitrary parent
        classes for ephemeral work, not registered as their own type).

        Resolution: explicit ``agent_id`` arg → ``cls.agent_id`` ClassVar
        → literal ``"ephemeral"`` (so observability spans always have a name).
        """
        resolved_id = agent_id or getattr(cls, "agent_id", None) or "ephemeral"
        object.__setattr__(instance, "agent_id", resolved_id)
        object.__setattr__(
            instance, "agent_name",
            getattr(cls, "agent_name", "") or resolved_id,
        )
        object.__setattr__(
            instance, "agent_description",
            getattr(cls, "agent_description", "") or "",
        )

    @classmethod
    def _construct(
        cls,
        *,
        llm: BaseChatModel,
        session_manager: SessionManager,
        tool_registry: ToolRegistry | None = None,
        skill_loader: SkillLoader | None = None,
        config: RunnerConfig | None = None,
        memory_manager: "MemoryManager | None" = None,
        callbacks: RunnerCallbacks | None = None,
        agent_id: str | None = None,
    ) -> "BaseAgent":
        """Internal: build an instance from explicit dependencies.

        Bypasses identity validation and the declarative build hooks —
        used by:
          * the ``spawn_subtasks`` tool to fork ephemeral sub-agents
            from a parent agent;
          * unit tests that need to inject mock components.

        Production code instantiates real agents via ``cls()`` (no args)
        so the framework's ``ClassVar`` + hook-driven wiring stays the
        single source of truth for agent identity / capabilities.
        """
        instance = object.__new__(cls)
        cls._assign_subagent_identity(instance, agent_id)
        instance.llm = llm
        instance.tool_registry = tool_registry or ToolRegistry()
        instance.session_manager = session_manager
        instance.skill_loader = skill_loader
        instance.skill_matcher = SkillMatcher(skill_loader) if skill_loader else None
        cfg = config or RunnerConfig()
        instance.config = cfg
        instance._callbacks = callbacks or RunnerCallbacks()
        instance._memory_manager = memory_manager
        instance._flusher = None
        instance._skill_router = cfg.skill_router
        instance._llm_caller = LLMCaller(llm, max_retries=cfg.max_retries)
        instance._tool_executor = ToolExecutor(
            instance.tool_registry,
            timeout=cfg.tool_timeout,
            max_calls_per_turn=cfg.max_tool_calls_per_turn,
        )
        instance._finish_wiring(
            skill_loader=skill_loader,
            skill_load_mode=cfg.skill_config.load_mode,
            memory_manager=memory_manager,
        )
        return instance

    def _finish_wiring(
        self,
        *,
        skill_loader: SkillLoader | None,
        skill_load_mode: SkillLoadMode,
        memory_manager: "MemoryManager | None",
    ) -> None:
        """Auto-register read_skill (dynamic mode) + memory tools/flusher.

        Idempotent: skips tools whose name is already in the registry.
        Single source of truth for the post-wire step shared between the
        declarative path (``__init__``) and the explicit-args path
        (``_construct``).
        """
        if (
            skill_loader is not None
            and skill_load_mode != SkillLoadMode.full
            and not self.tool_registry.has("read_skill")
        ):
            from ..tools.read_skill import ReadSkillTool
            self.tool_registry.register(ReadSkillTool(skill_loader))

        if memory_manager is not None:
            from ..memory.extractor import MemoryFlusher
            extraction_sampling = SamplingConfig.for_extraction()
            self._flusher = MemoryFlusher(
                lambda: self._llm_caller.get_llm(
                    sampling_override=extraction_sampling
                )
            )
            def _mem_lookup(_uid: str) -> "MemoryManager | None":
                return self._memory_manager
            for tool in create_memory_tools(_mem_lookup):
                if not self.tool_registry.has(tool.name):
                    self.tool_registry.register(tool)

    # ── Public API ──────────────────────────────────────────────────────
    async def close(self) -> None:
        """Release per-agent resources. Called once at lifecycle stop.

        Currently a no-op; kept as a stable shutdown hook so future
        backends (e.g. DB connections) can release without breaking
        the public surface.
        """

    @property
    def memory_manager(self) -> "MemoryManager | None":
        return self._memory_manager

    @traced_agent("agent.run", span_name_template="agent.run:{self.agent_id}")
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
        """Execute the agent.

        Lifecycle: resolve → prepare → execute → finalize
        """
        input_context = input_context or {}
        params = self._resolve_run_params(run_options)
        run_id = uuid4().hex
        run_metadata: dict[str, Any] = {
            "user_id": user_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "model": params.model,
            "stream": stream,
            "skill_load_mode": params.skill_load_mode,
            "correlation_id": input_context.get("temp:trace_id"),
        }
        add_span_attributes({
            "session.id": session_id,
            "user.id": user_id,
            "ark.run_id": run_id,
            "ark.agent_id": self.agent_id,
            "ark.agent_name": self.agent_name,
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
            pass

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
        """Persistence-free ReAct loop, used by ephemeral subtasks.

        Caller owns session creation and cleanup. Skips the persistence /
        hooks / compaction lifecycle of the regular ``run()``.
        """
        user_message = AgentMessage.user(user_input)
        self.session_manager.add_message_in_memory_only(session_id, user_message)
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
        """Lazy init, before_agent hooks, context merge, history merge,
        record user message, auto-compact.

        Returns RunResult on halt (early exit), CallbackContext on success.
        """
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
            merge_input_context(session, input_context)
            user_message = AgentMessage.user(user_input, metadata=input_context)
            augment_user_metadata(user_message, chat_request_meta)
            await self.session_manager.add_message(session_id, user_id, user_message)
            resp = r.response or AgentMessage.assistant("")
            await self.session_manager.add_message(session_id, user_id, resp)
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
        merge_input_context(session, input_context)

        if history and self.config.accept_external_history and use_history:
            from ..session.history_merge import merge_external_history

            ops = merge_external_history(session.messages, history)
            if ops:
                await self.session_manager.inject_messages(session_id, user_id, ops)
                logger.info("Merged %d external history message(s)", len(ops))

        user_message = AgentMessage.user(user_input, metadata=input_context)
        augment_user_metadata(user_message, chat_request_meta)
        await self.session_manager.add_message(session_id, user_id, user_message)

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
            result=result,
            context=cb_ctx.input_context,
            handler=handler,
        )
        if cb_result and cb_result.response is not None:
            result.response = cb_result.response
        cb_ctx.session.strip_temp_state()
        await self.session_manager.sync_session_state(session_id, user_id)
        await self.session_manager.finalize_session(session_id, user_id)

        if self._memory_manager is not None:
            await self._memory_manager.maybe_consolidate(user_id)

    async def _run_hooks(
        self,
        hooks: list,
        cb_ctx: CallbackContext | None,
        *,
        context: dict[str, Any] | None = None,
        handler: AgentEventHandler | None = None,
        **kwargs: Any,
    ) -> CallbackResult | None:
        """Run hooks in order. Apply context_updates/event for each non-None result."""
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
                dispatch_event(handler, r.event)
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
                logger.info(
                    "[RUN_END] session=%s turns=%d tool_calls=%d",
                    session_id[:8], ls.turns, ls.total_tool_calls,
                )
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
        if (
            skill_load_mode == SkillLoadMode.full.value
            and self.skill_loader is not None
        ):
            session.set_active_skill_ids(self.skill_loader.list_skill_ids())
        state = session.state
        messages = await self._build_messages(
            session_id, state,
            skill_load_mode=skill_load_mode,
            session=session,
        )
        tools = [
            t.get_json_schema()
            for t in self._filter_tools(state, session=session)
        ]

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

        turn_context = TurnContext(
            active_skill_id=session.current_active_skill_id,
            tools_mounted=tools_mounted,
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
            turn_context=turn_context,
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
        """before_loop_end → final result. Returns None on RETRY."""
        bc = await self._run_hooks(
            self._callbacks.before_loop_end,
            cb_ctx,
            response=response,
            handler=handler,
        )
        if bc and bc.action == HookAction.RETRY:
            logger.info("[before_loop_end] retry turns=%s", ls.turns)
            if bc.response:
                session = self.session_manager.get_session_required(session_id)
                await self.session_manager.add_message(
                    session_id, session.user_id or "", bc.response,
                )
            return None
        return ls.make_result(response)

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
        turn_context: TurnContext,
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
                user_message = user_friendly_error_message(e)
                error_response = AgentMessage.assistant(content=user_message)
                error_response.metadata["error"] = {
                    "reason": e.reason.value,
                    "message": str(e),
                    "retryable": e.retryable,
                }
                session_for_persist = self.session_manager.get_session_required(session_id)
                await self.session_manager.add_message(
                    session_id, session_for_persist.user_id or "", error_response,
                )
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

        from ..observability import current_trace_id_or_none
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

        session_for_persist = self.session_manager.get_session_required(session_id)
        response.turn_context = turn_context
        await self.session_manager.add_message(
            session_id, session_for_persist.user_id or "", response,
        )

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

        merge_tool_state_deltas(session, tool_results)
        apply_session_effects(session, tool_results)

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
            merge_tool_state_deltas(session, tool_results)
            apply_session_effects(session, tool_results)

        tool_message = AgentMessage.tool(tool_results)
        await self.session_manager.add_message(
            session_id, session.user_id or "", tool_message,
        )

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
            await self.session_manager.add_message(
                session_id, session.user_id or "", stop_response,
            )
            return ls.make_result(stop_response)

        if all(tr.is_error for tr in tool_results):
            logger.warning("[TOOLS_FAIL] turn=%d all_failed=True", ls.turns)

        if handler:
            handler.on_step("信息收集完毕，正在为您总结…")

        return None

    async def _build_messages(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        skill_load_mode: str = "full",
        session: SessionEntry | None = None,
    ) -> list[dict[str, Any]]:
        """Build the LLM message list."""
        if session is None:
            session = self.session_manager.get_session_required(session_id)
        messages: list[dict[str, Any]] = []

        system_prompt = await self._build_system_prompt(
            state,
            session_id=session_id,
            skill_load_mode=skill_load_mode,
            session=session,
        )
        messages.append({"role": "system", "content": system_prompt})

        for msg in session.messages:
            if msg.role == MessageRole.SYSTEM:
                continue

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
        """Dynamic mode: deterministically activate one skill before the loop."""
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
        except Exception as exc:
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
        """Unified skill match entry — single match per loop, multi-use."""
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

    async def _build_system_prompt(
        self,
        state: dict[str, Any],
        session_id: str | None = None,
        *,
        skill_load_mode: str = "full",
        session: SessionEntry | None = None,
    ) -> str:
        """Build the system prompt."""
        tools = self._filter_tools(state, session=session)

        skills = self._match_skills(
            state, session_id, skill_load_mode=skill_load_mode,
        )

        active_skill: SkillEntry | None = None
        if skill_load_mode != SkillLoadMode.full.value and self.skill_loader:
            active_id = session.current_active_skill_id if session else None
            if active_id:
                active_skill = self.skill_loader.get_skill(active_id)

        current_stage_id = state.get("_flow_stage")
        if current_stage_id and current_stage_id != "__completed__" and skills:
            skills = enrich_skills_with_stage_reference(skills, current_stage_id)

        prompt_config = self.config.prompt_config

        user_state = {k: v for k, v in state.items() if k.startswith("user:")}

        profile_content = ""
        if self._memory_manager:
            user_id = state.get("user:id")
            if user_id:
                from ..memory.user_profile import truncate_profile
                try:
                    profile_content = truncate_profile(
                        await self._memory_manager.read_memory(str(user_id))
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
        """Per-skill tool visibility filter (single source of truth)."""
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

    # ============ Session conveniences ============

    async def create_session(
        self,
        user_id: str,
        model: str = "Qwen3-80B-Instruct",
        provider: str = "ark",
        state: dict[str, Any] | None = None,
    ) -> str:
        """Create a new session and return its ID (async, persisted)."""
        session = await self.session_manager.create_session(
            user_id=user_id, model=model, provider=provider, state=state
        )
        return session.session_id

    def register_tool(self, tool: AgentTool) -> None:
        """Register a single tool."""
        self.tool_registry.register(tool)
