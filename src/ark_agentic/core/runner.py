"""Agent Runner - ReAct 执行器

使用 langchain ChatOpenAI 作为 LLM 后端。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field, replace
from typing import Any, TYPE_CHECKING, Callable, Awaitable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from .llm.errors import LLMError, LLMErrorReason, classify_error
from .prompt.builder import SystemPromptBuilder, PromptConfig
from .session import SessionManager
from .skills.base import SkillConfig
from .skills.loader import SkillLoader
from .skills.matcher import SkillMatcher
from .stream.event_bus import AgentEventHandler
from .tools.base import AgentTool
from .tools.registry import ToolRegistry
from .tools.memory import create_memory_tools
from .types import (
    AgentMessage,
    AgentToolResult,
    MessageRole,
    RunOptions,
    SessionEntry,
    ToolCall,
    ToolResultType,
)
from .validation import validate_response_against_tools

if TYPE_CHECKING:
    from .memory.manager import MemoryManager

logger = logging.getLogger(__name__)


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

    # 流式输出
    enable_streaming: bool = True

    # 思考标签：启用后 system prompt 注入 <think>/<final> 指引，流式解析器按标签路由
    enable_thinking_tags: bool = False

    # 自动压缩
    auto_compact: bool = True

    # 输出验证（检查 LLM 输出数值与工具结果的一致性）
    enable_output_validation: bool = True

    # 提示配置
    prompt_config: PromptConfig = field(default_factory=PromptConfig)

    # 技能配置
    skill_config: SkillConfig = field(default_factory=SkillConfig)

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
        tool_registry: ToolRegistry | None = None,
        session_manager: SessionManager | None = None,
        skill_loader: SkillLoader | None = None,
        config: RunnerConfig | None = None,
        memory_manager: MemoryManager | None = None,
        context_preprocessor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.llm = llm  # LLM following LangChain protocol
        self.tool_registry = tool_registry or ToolRegistry()
        self.session_manager = session_manager or SessionManager()
        self.skill_loader = skill_loader
        self.config = config or RunnerConfig()
        self._context_preprocessor = context_preprocessor

        # memory: base manager config for cloning per-user managers
        self._memory_base_manager = memory_manager
        self._memory_managers: dict[str, MemoryManager] = {}

        if memory_manager is not None:
            memory_tools = create_memory_tools(self._get_memory_for_user)
            for tool in memory_tools:
                self.tool_registry.register(tool)
            logger.info(f"Registered {len(memory_tools)} memory tools")

        if skill_loader is not None:
            from .tools.read_skill import ReadSkillTool
            self.tool_registry.register(ReadSkillTool(skill_loader))
            logger.info("Registered read_skill tool for dynamic skill loading")

        self.skill_matcher = (
            SkillMatcher(skill_loader) if skill_loader else None
        )

    def _get_memory_for_user(self, user_id: str) -> MemoryManager | None:
        """Get or create a user-scoped MemoryManager."""
        if self._memory_base_manager is None:
            return None
        if user_id in self._memory_managers:
            return self._memory_managers[user_id]

        from .memory.manager import MemoryConfig, MemoryManager as MM
        from pathlib import Path
        import copy

        base_cfg = self._memory_base_manager.config
        user_workspace = str(Path(base_cfg.workspace_dir) / user_id)
        user_config = copy.copy(base_cfg)
        user_config.workspace_dir = user_workspace

        mgr = MM(user_config)
        self._memory_managers[user_id] = mgr
        return mgr

    async def run(
        self,
        session_id: str,
        user_input: str,
        user_id: str,
        input_context: dict[str, Any] | None = None,
        *,
        run_options: RunOptions | None = None,
        stream_override: bool | None = None,
        handler: AgentEventHandler | None = None,
        history: list[dict[str, Any]] | None = None,
        use_history: bool = True,
    ) -> RunResult:
        """执行智能体

        Args:
            session_id: 会话 ID
            user_input: 用户输入
            user_id: 用户 ID（必须）
            input_context: 每次请求的调用方上下文，合并进 session.state
            run_options: 本次运行选项（model/temperature），优先于 config 默认值
            stream_override: 覆盖 config.enable_streaming
            handler: AgentEventHandler 实例（用于接收流式事件）
            history: 外部系统聊天历史 [{role, content}]
            use_history: 请求级开关，False 则忽略 history

        Returns:
            执行结果
        """
        input_context = input_context or {}

        effective_model = (
            (run_options.model if run_options else None)
            or self.config.model
        )
        effective_temperature = (
            (run_options.temperature if run_options else None)
            if (run_options and run_options.temperature is not None)
            else self.config.temperature
        )
        raw = self.config.skill_config.default_load_mode
        resolved_skill_load_mode: str = raw.value

        # 惰性初始化 user-scoped Memory
        memory_mgr = self._get_memory_for_user(user_id) if self._memory_base_manager else None
        if memory_mgr and not memory_mgr._initialized:
            await memory_mgr.initialize()

        if self._context_preprocessor:
            input_context = self._context_preprocessor(input_context)

        session = self.session_manager.get_session_required(session_id)
        self._merge_input_context(session, input_context)

        # 外部历史合并（在添加当前用户消息之前）
        if history and self.config.accept_external_history and use_history:
            from .history_merge import merge_external_history

            ops = merge_external_history(session.messages, history)
            if ops:
                self.session_manager.inject_messages(session_id, ops)
                logger.info(f"Merged {len(ops)} external history message(s)")

        user_message = AgentMessage.user(user_input, metadata=input_context)
        self.session_manager.add_message_sync(session_id, user_message)

        if self.config.auto_compact:
            callback = self._make_pre_compact_callback(user_id) if memory_mgr else None
            await self.session_manager.auto_compact_if_needed(
                session_id, user_id, pre_compact_callback=callback,
            )

        use_streaming = stream_override if stream_override is not None else self.config.enable_streaming

        try:
            result = await self._run_loop(
                session_id,
                use_streaming=use_streaming,
                model_override=effective_model,
                temperature_override=effective_temperature,
                skill_load_mode=resolved_skill_load_mode,
                handler=handler,
            )
        finally:
            await self.session_manager.sync_pending_messages(session_id, user_id)

        session.strip_temp_state()
        await self.session_manager.sync_session_state(session_id, user_id)

        return result

    @staticmethod
    def _merge_input_context(session: SessionEntry, input_context: dict[str, Any]) -> None:
        """将 input_context 合并到 session.state，所有键始终覆盖已有值。"""
        for k, v in input_context.items():
            session.state[k] = v

    def _make_pre_compact_callback(self, user_id: str) -> Callable[[str, list[AgentMessage]], Awaitable[None]]:
        """创建压缩前回调：将即将丢弃的消息写入记忆（file 或 mem0）"""

        def _get_mgr() -> MemoryManager | None:
            return self._memory_managers.get(user_id)

        async def _flush_to_memory(
            session_id: str, messages: list[AgentMessage]
        ) -> None:
            memory_mgr = _get_mgr()
            if not memory_mgr or not memory_mgr._initialized:
                return
            parts: list[str] = []
            for msg in messages:
                if msg.role == MessageRole.SYSTEM:
                    continue
                label = msg.role.value.upper()
                text = msg.content or ""
                if msg.tool_calls:
                    tool_names = ", ".join(tc.name for tc in msg.tool_calls)
                    text += f" [tools: {tool_names}]"
                if text.strip():
                    parts.append(f"{label}: {text[:300]}")

            if not parts:
                return

            from pathlib import Path
            from datetime import datetime

            workspace_dir = Path(memory_mgr.config.workspace_dir)
            memory_file = workspace_dir / "MEMORY.md"
            memory_file.parent.mkdir(parents=True, exist_ok=True)

            snapshot = (
                f"\n\n## Session Snapshot ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
                + "\n".join(parts[:20])
                + "\n"
            )
            with open(memory_file, "a", encoding="utf-8") as f:
                f.write(snapshot)

            try:
                await memory_mgr.sync()
            except Exception as e:
                logger.warning(f"Memory sync after pre-compact flush failed: {e}")

        return _flush_to_memory

    def _get_user_friendly_error_message(self, error: LLMError) -> str:
        if error.reason == LLMErrorReason.AUTH:
            return "抱歉，模型认证失败，请检查 API 配置。如需帮助，请联系技术支持。"
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

    async def _run_loop(
        self,
        session_id: str,
        *,
        use_streaming: bool = True,
        model_override: str | None = None,
        temperature_override: float | None = None,
        skill_load_mode: str = "full",
        handler: AgentEventHandler | None = None,
    ) -> RunResult:
        """ReAct 循环: LLM → Tool → LLM → ... → Response"""
        logger.info(f"[RUN] session={session_id[:8]} streaming={use_streaming}")
                
        turns = 0
        total_tool_calls = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        all_tool_calls: list[ToolCall] = []
        all_tool_results: list[AgentToolResult] = []

        session = self.session_manager.get_session_required(session_id)

        while turns < self.config.max_turns:
            turns += 1

            state = session.state
            messages = self._build_messages(session_id, state, skill_load_mode=skill_load_mode)
            tools = self._build_tools()
            logger.info(
                f"Turn {turns} | messages={len(messages)} tools={len(tools)} "
                f"model={model_override or self.config.model}"
            )

            # 绑定当前 ReAct 轮次到 content / thinking 回调（1-based）
            _current_turn = turns

            def _scoped_content(text: str, _turn: int = _current_turn) -> None:
                if handler:
                    handler.on_content_delta(text, _turn)

            def _scoped_thinking(text: str, _turn: int = _current_turn) -> None:
                if handler:
                    handler.on_thinking_delta(text, _turn)

            try:
                if use_streaming:
                    response = await self._call_llm_streaming(
                        messages, tools,
                        model_override=model_override,
                        temperature_override=temperature_override,
                        content_callback=_scoped_content,
                        thinking_callback=_scoped_thinking,
                        handler=handler,
                    )
                else:
                    response = await self._call_llm(
                        messages, tools,
                        model_override=model_override,
                        temperature_override=temperature_override,
                    )
            except LLMError as e:
                logger.error(f"[LLM_ERROR] turn={turns} reason={e.reason.value} retryable={e.retryable}")
                user_message = self._get_user_friendly_error_message(e)
                error_response = AgentMessage.assistant(content=user_message)
                error_response.metadata["error"] = {
                    "reason": e.reason.value,
                    "message": str(e),
                    "retryable": e.retryable,
                }
                self.session_manager.add_message_sync(session_id, error_response)
                return RunResult(
                    response=error_response,
                    turns=turns,
                    tool_calls_count=total_tool_calls,
                    tool_calls=all_tool_calls,
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    stopped_by_limit=False,
                )

            usage = response.metadata.get("usage", {})
            turn_prompt = usage.get("prompt_tokens", 0)
            turn_completion = usage.get("completion_tokens", 0)
            total_prompt_tokens += turn_prompt
            total_completion_tokens += turn_completion
            finish_reason = response.metadata.get("finish_reason")
            logger.info(
                f"Turn {turns} | finish_reason={finish_reason} "
                f"content_len={len(response.content or '')} "
                f"tool_calls={len(response.tool_calls or [])} "
                f"tokens=+{turn_prompt}/{turn_completion}"
            )

            self.session_manager.update_token_usage(
                session_id,
                prompt_tokens=turn_prompt,
                completion_tokens=turn_completion,
            )

            self.session_manager.add_message_sync(session_id, response)

            if finish_reason == "length":
                logger.warning(f"Response truncated (max_tokens) in session {session_id}")
                return RunResult(
                    response=response,
                    turns=turns,
                    tool_calls_count=total_tool_calls,
                    tool_calls=all_tool_calls,
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    stopped_by_limit=True,
                )

            # 工具调用轮
            if response.tool_calls:
                logger.info(
                    f"[TOOLS] turn={turns} count={len(response.tool_calls)} "
                    f"names={[tc.name for tc in response.tool_calls]}"
                )
                all_tool_calls.extend(response.tool_calls)

                tool_results = await self._execute_tools(
                    response.tool_calls, {**state, "session_id": session_id}, handler=handler,
                )
                total_tool_calls += len(response.tool_calls)
                all_tool_results.extend(tool_results)

                # 合并工具返回的 state_delta 到 session.state
                for tr in tool_results:
                    state_delta = tr.metadata.get("state_delta")
                    if state_delta and isinstance(state_delta, dict):
                        session.update_state(state_delta)

                tool_message = AgentMessage.tool(tool_results)
                self.session_manager.add_message_sync(session_id, tool_message)

                if all(tr.is_error for tr in tool_results):
                    logger.warning(f"[TOOLS_FAIL] turn={turns} all_failed=True")

                if handler:
                    handler.on_step("信息收集完毕，正在为您总结…")

                continue

            # 最终轮：无工具调用
            logger.info(
                f"[RUN_END] session={session_id[:8]} turns={turns} "
                f"tool_calls={total_tool_calls} tokens={total_prompt_tokens}/{total_completion_tokens}"
            )
            # 输出验证
            if self.config.enable_output_validation and all_tool_results and response.content:
                validation = validate_response_against_tools(
                    response.content, all_tool_results
                )
                if validation.issues:
                    logger.warning(
                        f"Output validation: {len(validation.issues)} issue(s) detected"
                    )
                    response.metadata["validation_issues"] = [
                        {
                            "severity": i.severity,
                            "field": i.field,
                            "llm_value": i.llm_value,
                            "tool_value": i.tool_value,
                            "message": i.message,
                        }
                        for i in validation.issues
                    ]

            # strict thinking-tags fallback: 整轮未出现 <final> 时补发非 think 内容
            if self.config.enable_thinking_tags and handler:
                fallback = response.metadata.get("thinking_fallback_content")
                if fallback:
                    handler.on_content_delta(fallback, turns)

            return RunResult(
                response=response,
                turns=turns,
                tool_calls_count=total_tool_calls,
                tool_calls=all_tool_calls,
                tool_results=all_tool_results,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
            )

        logger.warning(f"[RUN_LIMIT] session={session_id[:8]} max_turns={self.config.max_turns}")
        session = self.session_manager.get_session_required(session_id)
        last_assistant = next(
            (m for m in reversed(session.messages) if m.role == MessageRole.ASSISTANT),
            AgentMessage.assistant(content="抱歉，处理过程中出现了问题，请稍后重试。"),
        )

        return RunResult(
            response=last_assistant,
            turns=turns,
            tool_calls_count=total_tool_calls,
            tool_calls=all_tool_calls,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            stopped_by_limit=True,
        )

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
            state, session_id=session_id, skill_load_mode=skill_load_mode
        )
        messages.append({"role": "system", "content": system_prompt})

        # 历史消息
        for msg in session.messages:
            if msg.role == MessageRole.SYSTEM:
                continue  # 已添加

            if msg.role == MessageRole.USER:
                messages.append({"role": "user", "content": msg.content})

            elif msg.role == MessageRole.ASSISTANT:
                assistant_msg: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
                if msg.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                messages.append(assistant_msg)

            elif msg.role == MessageRole.TOOL:
                if msg.tool_results:
                    for tr in msg.tool_results:
                        if tr.result_type == ToolResultType.A2UI:
                            # A2UI payload 通过 on_ui_component 走独立 UI 通道推送给前端。
                            # 写回 LLM history 仅保留极简哑标记：无展示语义、无卡片内容，
                            # 避免 LLM 将"已渲染"解读为"业务已完成，无需再次生成"。
                            raw = tr.content
                            component_count = len(raw) if isinstance(raw, list) else 1
                            content = json.dumps(
                                {"kind": "ui_event", "event": "a2ui_emitted", "component_count": component_count},
                                ensure_ascii=False,
                            )
                        else:
                            content = tr.content
                            if isinstance(content, (dict, list)):
                                content = json.dumps(content, ensure_ascii=False)
                            else:
                                content = str(content)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tr.tool_call_id,
                            "content": content,
                        })

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
                query=user_query, context=skill_context
            )
            skills = match_result.matched_skills

        include_memory = self._memory_base_manager is not None

        # 技能注入模式
        base_config = self.config.prompt_config
        if skill_load_mode == "full":
            use_skill_metadata_only = False
        elif skill_load_mode == "dynamic":
            use_skill_metadata_only = True
        elif skill_load_mode == "semantic":
            # 占位: 未来通过 SemanticSkillMatcher 预匹配后，
            # 高置信 skill 全文注入，低置信 skill 走 metadata
            logger.warning(
                "Semantic skill loading not yet implemented, falling back to 'dynamic'"
            )
            use_skill_metadata_only = True
        else:
            use_skill_metadata_only = False
        prompt_config = replace(base_config, use_skill_metadata_only=use_skill_metadata_only)

        # 当 enable_thinking_tags=True 且 prompt_config 未自定义指令时，自动填充默认模板
        if self.config.enable_thinking_tags and not prompt_config.thinking_tag_instructions:
            from .stream.thinking_tag_parser import DEFAULT_THINKING_TAG_INSTRUCTIONS
            prompt_config = replace(
                prompt_config,
                thinking_tag_instructions=DEFAULT_THINKING_TAG_INSTRUCTIONS,
            )

        # 默认只注入 user: 前缀的状态到提示词，减少噪声
        user_state = {k: v for k, v in state.items() if k.startswith("user:")}

        return SystemPromptBuilder.quick_build(
            tools=tools,
            skills=skills,
            context=user_state,
            config=prompt_config,
            include_memory_instructions=include_memory,
        )

    def _build_tools(self) -> list[dict[str, Any]]:
        """构建工具定义"""
        tools = self.tool_registry.list_all()
        return [tool.get_json_schema() for tool in tools]

    def _get_llm(self, model_override: str | None = None, temperature_override: float | None = None) -> BaseChatModel:
        """获取 LLM 实例，支持 per-call model/temperature 覆盖。"""
        updates: dict[str, Any] = {}
        if model_override:
            updates["model"] = model_override
        if temperature_override is not None:
            updates["temperature"] = temperature_override
        if updates:
            if hasattr(self.llm, "model_copy"):
                return self.llm.model_copy(update=updates)
            if hasattr(self.llm, "copy"):
                return self.llm.copy(update=updates)
            logger.debug(f"LLM backend lacks model_copy/copy methods; ignoring overrides: {updates}")
        return self.llm

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model_override: str | None = None,
        temperature_override: float | None = None,
    ) -> AgentMessage:
        """非流式 LLM 调用（ChatOpenAI.ainvoke）"""
        llm = self._get_llm(model_override, temperature_override)
        if tools:
            llm = llm.bind_tools(tools)

        try:
            ai_msg = await llm.ainvoke(messages)
        except LLMError:
            raise
        except Exception as exc:
            error = classify_error(exc, model=model_override or self.config.model)
            raise error from exc

        return self._ai_message_to_agent_message(ai_msg)

    async def _call_llm_streaming(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model_override: str | None = None,
        temperature_override: float | None = None,
        content_callback: Callable[[str], None] | None = None,
        thinking_callback: Callable[[str], None] | None = None,
        handler: AgentEventHandler | None = None,
    ) -> AgentMessage:
        """流式 LLM 调用（ChatOpenAI.astream）

        当 enable_thinking_tags=True 时，通过 ThinkingTagParser 实时解析
        <think>/<final> 标签，将 thinking 内容路由到 thinking_callback，
        final 内容路由到 content_callback。
        """
        from .stream.thinking_tag_parser import ThinkingTagParser

        llm = self._get_llm(model_override, temperature_override)
        if tools:
            llm = llm.bind_tools(tools)

        model = model_override or self.config.model
        logger.info(f"LLM stream start | model={model}")

        parser = ThinkingTagParser() if self.config.enable_thinking_tags else None

        full_content = ""
        tool_calls_data: dict[int, dict[str, str]] = {}  # index → {id, name, args}
        finish_reason = "stop"
        usage: dict[str, int] = {}

        try:
            async for chunk in llm.astream(messages):
                # Content delta
                if chunk.content:
                    full_content += chunk.content
                    if parser:
                        thinking, final = parser.process_chunk(chunk.content)
                        if thinking and thinking_callback:
                            thinking_callback(thinking)
                        if final and content_callback:
                            content_callback(final)
                    elif content_callback:
                        content_callback(chunk.content)

                # Tool call chunks (dict or ToolCallChunk-like; index may be int or str)
                if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                    for tc_chunk in chunk.tool_call_chunks:
                        raw = tc_chunk if isinstance(tc_chunk, dict) else dict(tc_chunk)
                        idx = int(raw.get("index") or 0)
                        if idx not in tool_calls_data:
                            tool_calls_data[idx] = {"id": "", "name": "", "args": ""}
                        if raw.get("id"):
                            tool_calls_data[idx]["id"] = str(raw["id"])
                        if raw.get("name"):
                            tool_calls_data[idx]["name"] = str(raw["name"])
                        args_delta = raw.get("args")
                        if args_delta is not None and args_delta != "":
                            tool_calls_data[idx]["args"] += (
                                args_delta if isinstance(args_delta, str) else str(args_delta)
                            )

                # Response metadata (last chunk)
                if hasattr(chunk, "response_metadata") and chunk.response_metadata:
                    finish_reason = chunk.response_metadata.get("finish_reason", finish_reason)
                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                    usage = {
                        "prompt_tokens": chunk.usage_metadata.get("input_tokens", 0),
                        "completion_tokens": chunk.usage_metadata.get("output_tokens", 0),
                    }

        except LLMError:
            raise
        except Exception as exc:
            error = classify_error(exc, model=model)
            raise error from exc

        # flush parser pending buffer
        if parser:
            thinking, final = parser.flush()
            if thinking and thinking_callback:
                thinking_callback(thinking)
            if final and content_callback:
                content_callback(final)

        # 组装工具调用
        parsed_tool_calls = None
        if tool_calls_data:
            parsed_tool_calls = []
            for idx in sorted(tool_calls_data):
                tc = tool_calls_data[idx]
                try:
                    args = json.loads(tc["args"]) if tc["args"] else {}
                except json.JSONDecodeError:
                    args = {"_raw": tc["args"]}
                parsed_tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))

        # strip 标签后存入 content，防止污染对话历史
        clean_content = ThinkingTagParser.strip_tags(full_content) if parser else full_content
        msg = AgentMessage.assistant(content=clean_content, tool_calls=parsed_tool_calls)
        msg.metadata["finish_reason"] = finish_reason
        if usage:
            msg.metadata["usage"] = usage

        # strict 模式：整轮未出现 <final> 时，预计算 fallback 供 _run_loop 最终轮补发
        if parser and not parser.ever_in_final and full_content:
            fallback = ThinkingTagParser.extract_non_think(full_content)
            if fallback:
                msg.metadata["thinking_fallback_content"] = fallback

        logger.debug(f"[LLM_STREAM_DONE] content={len(full_content)}B tools={len(tool_calls_data)}")
        return msg

    def _ai_message_to_agent_message(self, ai_msg: AIMessage) -> AgentMessage:
        """将 LangChain AIMessage 转为 AgentMessage。"""
        content = ai_msg.content if isinstance(ai_msg.content, str) else ""

        tool_calls = None
        if ai_msg.tool_calls:
            tool_calls = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("args", {}))
                for tc in ai_msg.tool_calls
            ]

        msg = AgentMessage.assistant(content=content, tool_calls=tool_calls)

        # finish_reason
        rm = getattr(ai_msg, "response_metadata", {}) or {}
        msg.metadata["finish_reason"] = rm.get("finish_reason", "stop")

        # usage
        um = getattr(ai_msg, "usage_metadata", None)
        if um:
            msg.metadata["usage"] = {
                "prompt_tokens": um.get("input_tokens", 0),
                "completion_tokens": um.get("output_tokens", 0),
            }

        return msg

    async def _execute_tools(
        self,
        tool_calls: list[ToolCall],
        context: dict[str, Any],
        handler: AgentEventHandler | None = None,
    ) -> list[AgentToolResult]:
        timeout = self.config.tool_timeout

        async def execute_single(tc: ToolCall) -> AgentToolResult:
            logger.debug(f"[TOOL_START] {tc.name} args={tc.arguments}")

            tool = self.tool_registry.get(tc.name)
            if handler:
                handler.on_tool_call_start(tc.id, tc.name, tc.arguments)
                status = (tool.thinking_hint if tool and tool.thinking_hint else f"正在处理 {tc.name}…")
                handler.on_step(status)
            if tool is None:
                result = AgentToolResult.error_result(
                    tc.id, f"Tool not found: {tc.name}"
                )
            else:
                try:
                    result = await asyncio.wait_for(
                        tool.execute(tc, context),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    logger.error(f"Tool execution timeout: {tc.name} ({timeout}s)")
                    result = AgentToolResult.error_result(
                        tc.id, f"Tool '{tc.name}' timed out after {timeout}s"
                    )
                except Exception as e:
                    logger.error(f"[TOOL_ERROR] {tc.name}: {e}")
                    result = AgentToolResult.error_result(tc.id, str(e))

            if handler:
                handler.on_tool_call_result(tc.id, tc.name, result.content)
                if result.result_type == ToolResultType.A2UI:
                    components = (
                        [result.content]
                        if isinstance(result.content, dict)
                        else result.content
                    )
                    for component in components:
                        handler.on_ui_component(component)

            logger.debug(f"[TOOL_DONE] {tc.name} error={result.is_error} size={len(str(result.content))}B")
            if result.is_error and handler:
                handler.on_step("工具调用遇到问题，正在尝试其他方式…")

            return result

        limited_calls = tool_calls[: self.config.max_tool_calls_per_turn]
        if len(tool_calls) > len(limited_calls):
            logger.warning(f"[TOOLS_LIMIT] requested={len(tool_calls)} limited={len(limited_calls)}")

        results = await asyncio.gather(
            *[execute_single(tc) for tc in limited_calls],
            return_exceptions=False,
        )

        return list(results)

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
