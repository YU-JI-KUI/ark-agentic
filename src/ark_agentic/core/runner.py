"""
Agent Runner - 智能体执行器

参考: openclaw-main/src/agents/pi-embedded-runner/run.ts

核心执行循环，编排消息处理、工具调用和响应生成。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from .llm.base import LLMClientProtocol
from .llm.errors import LLMError, classify_error
from .prompt.builder import SystemPromptBuilder, PromptConfig
from .session import SessionManager
from .skills.base import SkillConfig
from .skills.loader import SkillLoader
from .skills.matcher import SkillMatcher
from .stream.assembler import StreamAssembler, StreamEvent
from .tools.base import AgentTool
from .tools.registry import ToolRegistry
from .tools.memory import create_memory_tools
from .types import AgentMessage, AgentToolResult, MessageRole, ToolCall
from .validation import validate_response_against_tools

# Type hint for MemoryManager (avoid circular import)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .memory.manager import MemoryManager

logger = logging.getLogger(__name__)


# ============ Runner Config ============


@dataclass
class RunnerConfig:
    """Runner 配置"""

    # LLM 参数
    model: str = "Qwen3-80B-Instruct"
    temperature: float = 0.7
    max_tokens: int = 4096

    # 执行控制
    max_turns: int = 10  # 最大对话轮数（防止无限循环）
    max_tool_calls_per_turn: int = 5  # 单轮最大工具调用数
    tool_timeout: float = 30.0  # 单个工具执行超时（秒）

    # 流式输出
    enable_streaming: bool = True

    # 自动压缩
    auto_compact: bool = True

    # 输出验证（检查 LLM 输出数值与工具结果的一致性）
    enable_output_validation: bool = True

    # 提示配置
    prompt_config: PromptConfig = field(default_factory=PromptConfig)

    # 技能配置
    skill_config: SkillConfig = field(default_factory=SkillConfig)


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

    # Token 使用
    input_tokens: int = 0
    output_tokens: int = 0

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
        llm_client: LLMClientProtocol,
        tool_registry: ToolRegistry | None = None,
        session_manager: SessionManager | None = None,
        skill_loader: SkillLoader | None = None,
        config: RunnerConfig | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry or ToolRegistry()
        self.session_manager = session_manager or SessionManager()
        self.skill_loader = skill_loader
        self.config = config or RunnerConfig()
        self._memory_manager = memory_manager

        # 自动注册 memory 工具（如果提供了 memory_manager）
        if memory_manager is not None:
            memory_tools = create_memory_tools(memory_manager)
            for tool in memory_tools:
                self.tool_registry.register(tool)
            logger.info(f"Registered {len(memory_tools)} memory tools")

        # 技能匹配器
        self.skill_matcher = (
            SkillMatcher(skill_loader) if skill_loader else None
        )

        # 流式组装器
        self._stream_assembler: StreamAssembler | None = None

        # Callbacks — 2 only
        self._on_step: Callable[[str], None] | None = None
        self._on_content: Callable[[str, int], None] | None = None

    def set_callbacks(
        self,
        on_step: Callable[[str], None] | None = None,
        on_content: Callable[[str, int], None] | None = None,
    ) -> None:
        """设置回调函数

        Args:
            on_step: 生命周期步骤回调 (str) → response.step
            on_content: LLM 文本增量回调 (delta, output_index) → response.content.delta
        """
        self._on_step = on_step
        self._on_content = on_content

    async def run(
        self,
        session_id: str,
        user_input: str,
        context: dict[str, Any] | None = None,
        *,
        stream_override: bool | None = None,
        model_override: str | None = None,
    ) -> RunResult:
        """执行智能体

        Args:
            session_id: 会话 ID
            user_input: 用户输入
            context: 额外上下文
            stream_override: 覆盖 config.enable_streaming（线程安全，不修改共享状态）
            model_override: 覆盖默认模型名称，传递给 LLM client

        Returns:
            执行结果
        """
        context = context or {}

        # 惰性初始化 Memory（首次 run 时触发）
        if self._memory_manager and not self._memory_manager._initialized:
            await self._memory_manager.initialize()

        # 添加用户消息（使用同步方法避免额外的异步开销）
        user_message = AgentMessage.user(user_input, metadata=context)
        self.session_manager.add_message_sync(session_id, user_message)

        # 自动压缩（如果需要），传入 pre-compact 回调将即将丢弃的上下文写入 memory
        if self.config.auto_compact:
            callback = self._make_pre_compact_callback() if self._memory_manager else None
            await self.session_manager.auto_compact_if_needed(
                session_id, pre_compact_callback=callback,
            )

        # 确定本次执行是否启用流式
        use_streaming = stream_override if stream_override is not None else self.config.enable_streaming

        # 执行主循环
        try:
            result = await self._run_loop(
                session_id, context,
                use_streaming=use_streaming,
                model_override=model_override,
            )
        finally:
            # 无论成功或失败，同步待写入消息到持久化存储
            await self.session_manager.sync_pending_messages(session_id)

        # 同步元数据到持久化存储
        await self.session_manager.sync_session_metadata(session_id)

        return result

    def _make_pre_compact_callback(self) -> Callable:
        """创建压缩前回调：将即将丢弃的消息摘要写入 MEMORY.md"""
        memory_mgr = self._memory_manager

        async def _flush_to_memory(
            session_id: str, messages: list[AgentMessage]
        ) -> None:
            if not memory_mgr or not memory_mgr._initialized:
                return

            # 拼接即将被压缩的消息的关键内容（排除 system）
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

            # 写入 MEMORY.md 作为一条压缩快照
            from pathlib import Path
            from datetime import datetime

            workspace_dir = Path(memory_mgr.config.workspace_dir)
            memory_file = workspace_dir / "MEMORY.md"
            memory_file.parent.mkdir(parents=True, exist_ok=True)

            snapshot = (
                f"\n\n## Session Snapshot ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
                + "\n".join(parts[:20])  # 最多保留 20 条摘要行
                + "\n"
            )
            with open(memory_file, "a", encoding="utf-8") as f:
                f.write(snapshot)

            # 增量同步索引
            try:
                await memory_mgr.sync()
            except Exception as e:
                logger.warning(f"Memory sync after pre-compact flush failed: {e}")

        return _flush_to_memory

    async def _run_loop(
        self,
        session_id: str,
        context: dict[str, Any],
        *,
        use_streaming: bool = True,
        model_override: str | None = None,
    ) -> RunResult:
        """执行主循环（ReAct 模式）

        ReAct 循环：
        1. 调用 LLM 获取响应
        2. 如果有工具调用，执行工具并将结果发回 LLM
        3. 重复直到 LLM 返回最终响应（无工具调用）
        """
        turns = 0
        total_tool_calls = 0
        total_input_tokens = 0
        total_output_tokens = 0
        all_tool_calls: list[ToolCall] = []  # 记录所有工具调用
        all_tool_results: list[AgentToolResult] = []  # 记录所有工具结果（用于输出验证）
        output_index = 0  # 当前输出块索引，每轮工具调用后递增

        while turns < self.config.max_turns:
            turns += 1

            # 构建请求
            messages = self._build_messages(session_id, context)
            tools = self._build_tools(context)
            logger.info(f"Turn {turns} | messages={len(messages)} tools={len(tools)} model={model_override or self.config.model}")

            # 绑定当前 output_index 的 content 回调（闭包捕获当前值）
            _current_idx = output_index
            def _scoped_content(text: str, _idx: int = _current_idx) -> None:
                if self._on_content:
                    self._on_content(text, _idx)

            if use_streaming:
                response = await self._call_llm_streaming(
                    messages, tools,
                    model_override=model_override,
                    content_callback=_scoped_content,
                )
            else:
                response = await self._call_llm(messages, tools, model_override=model_override)

            # 更新 token 统计
            usage = response.metadata.get("usage", {})
            turn_input = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
            turn_output = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
            total_input_tokens += turn_input
            total_output_tokens += turn_output
            finish_reason = response.metadata.get("finish_reason")
            logger.info(
                f"Turn {turns} | finish_reason={finish_reason} "
                f"content_len={len(response.content or '')} "
                f"tool_calls={len(response.tool_calls or [])} "
                f"tokens=+{turn_input}/{turn_output}"
            )

            # 同步 token 统计到 session
            self.session_manager.update_token_usage(
                session_id,
                input_tokens=turn_input,
                output_tokens=turn_output,
            )

            # 添加助手响应到会话（使用同步方法，持久化在 run 结束后批量处理）
            self.session_manager.add_message_sync(session_id, response)

            # 检查 finish_reason
            if finish_reason == "length":
                logger.warning(f"Response truncated (max_tokens) in session {session_id}")
                # 可以选择继续或返回，这里选择返回截断的响应
                return RunResult(
                    response=response,
                    turns=turns,
                    tool_calls_count=total_tool_calls,
                    tool_calls=all_tool_calls,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    stopped_by_limit=True,
                )

            # ---- 工具调用轮（中间轮） ----
            if response.tool_calls:
                all_tool_calls.extend(response.tool_calls)

                tool_results = await self._execute_tools(
                    response.tool_calls, context
                )
                total_tool_calls += len(response.tool_calls)
                all_tool_results.extend(tool_results)

                # 添加工具结果到会话
                tool_message = AgentMessage.tool(tool_results)
                self.session_manager.add_message_sync(session_id, tool_message)

                # 检查是否所有工具都失败了
                all_errors = all(tr.is_error for tr in tool_results)
                if all_errors:
                    logger.warning(f"All tool calls failed in turn {turns}")

                # 递增 output_index，进入下一轮
                output_index += 1
                if self._on_step:
                    self._on_step("信息收集完毕，正在为您总结…")

                continue

            # ---- 最终轮：无 tool_calls —— 内容已通过 on_content 实时流式输出 ----
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

            return RunResult(
                response=response,
                turns=turns,
                tool_calls_count=total_tool_calls,
                tool_calls=all_tool_calls,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )

        # 达到最大轮数
        logger.warning(f"Reached max turns ({self.config.max_turns}) for session {session_id}")
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
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            stopped_by_limit=True,
        )

    def _build_messages(
        self, session_id: str, context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """构建 LLM 消息列表"""
        import json

        session = self.session_manager.get_session_required(session_id)
        messages: list[dict[str, Any]] = []

        # 系统提示
        system_prompt = self._build_system_prompt(context, session_id=session_id)
        messages.append({"role": "system", "content": system_prompt})

        # 历史消息
        for msg in session.messages:
            if msg.role == MessageRole.SYSTEM:
                continue  # 已添加

            if msg.role == MessageRole.USER:
                messages.append({"role": "user", "content": msg.content})

            elif msg.role == MessageRole.ASSISTANT:
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if msg.content:
                    assistant_msg["content"] = msg.content
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
                        # 确保 content 是正确的 JSON 字符串
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
        self, context: dict[str, Any], session_id: str | None = None
    ) -> str:
        """构建系统提示"""
        tools = self.tool_registry.list_all()

        # 将已注册的工具名注入 context，供 skill 资格检查使用
        skill_context = {**context, "available_tools": {t.name for t in tools}}

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

        # 如果启用了 memory，添加 memory 使用指令
        include_memory = self._memory_manager is not None

        return SystemPromptBuilder.quick_build(
            tools=tools,
            skills=skills,
            context=context,
            config=self.config.prompt_config,
            include_memory_instructions=include_memory,
        )

    def _build_tools(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """构建工具定义"""
        tools = self.tool_registry.list_all()
        return [tool.get_json_schema() for tool in tools]

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model_override: str | None = None,
    ) -> AgentMessage:
        """非流式调用 LLM"""
        llm_kwargs: dict[str, Any] = {
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if model_override:
            llm_kwargs["model"] = model_override

        try:
            response = await self.llm_client.chat(
                messages=messages,
                tools=tools if tools else None,
                stream=False,
                **llm_kwargs,
            )
        except LLMError:
            raise
        except Exception as exc:
            raise classify_error(exc, model=model_override or self.config.model) from exc

        return self._parse_llm_response(response)

    async def _call_llm_streaming(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model_override: str | None = None,
        content_callback: Callable[[str], None] | None = None,
    ) -> AgentMessage:
        """流式调用 LLM

        content_callback 由 _run_loop 传入，已绑定当前轮的 output_index。
        所有 LLM 内容实时转发给前端（打字机效果）。
        """
        model = model_override or self.config.model
        logger.info(f"LLM stream start | model={model}")

        assembler = StreamAssembler(
            on_content=content_callback,
            on_thinking=self._on_step,
        )

        llm_kwargs: dict[str, Any] = {
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if model_override:
            llm_kwargs["model"] = model_override

        try:
            stream = await self.llm_client.chat(
                messages=messages,
                tools=tools if tools else None,
                stream=True,
                **llm_kwargs,
            )
        except LLMError:
            raise
        except Exception as exc:
            raise classify_error(exc, model=model) from exc

        # 处理流
        async for chunk in stream:
            event = self._parse_stream_chunk(chunk)
            if event:
                assembler.process_event(event)

        logger.info(
            f"LLM stream done | content_len={len(assembler.state.content)} "
            f"tool_calls={len(assembler.state.tool_calls)}"
        )
        return assembler.build_message()

    def _parse_llm_response(self, response: dict[str, Any]) -> AgentMessage:
        """解析 LLM 响应

        支持 OpenAI 和兼容格式，处理 finish_reason。
        """
        import json

        # OpenAI 格式
        choices = response.get("choices", [])
        if not choices:
            return AgentMessage.assistant(content="")

        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content")
        finish_reason = choice.get("finish_reason")

        # 处理特殊的 finish_reason
        if finish_reason == "length":
            logger.warning("Response truncated due to max_tokens limit")
            # 可以在 content 末尾添加标记，或者在 metadata 中记录
        elif finish_reason == "content_filter":
            logger.warning("Response filtered due to content policy")
            content = content or "[内容已被过滤]"

        # 解析工具调用
        tool_calls = None
        raw_tool_calls = message.get("tool_calls", [])
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                func = tc.get("function", {})
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool arguments: {func.get('arguments')}")
                    args = {"_raw": func.get("arguments", "")}

                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args,
                ))

        # 构建消息，保存 finish_reason 到 metadata
        msg = AgentMessage.assistant(content=content, tool_calls=tool_calls)
        msg.metadata["finish_reason"] = finish_reason

        # 保存 usage 信息
        usage = response.get("usage")
        if usage:
            msg.metadata["usage"] = usage

        return msg

    def _parse_stream_chunk(self, chunk: dict[str, Any]) -> StreamEvent | None:
        """解析流式块"""
        from .stream.assembler import parse_openai_sse
        return parse_openai_sse(chunk)

    # 工具名 → 用户可见状态描述
    _TOOL_STATUS: dict[str, str] = {
        "policy_query": "正在查询您的保单信息，请稍等…",
        "customer_info": "正在查询您的客户信息…",
        "user_profile": "正在获取用户画像信息…",
        "rule_engine": "正在为您计算取款方案…",
        "verify_identity": "正在进行身份验证…",
        "memory_search": "正在检索相关信息…",
        "memory_get": "正在读取相关资料…",
        "memory_set": "正在保存关键信息…",
    }

    async def _execute_tools(
        self,
        tool_calls: list[ToolCall],
        context: dict[str, Any],
    ) -> list[AgentToolResult]:
        """执行工具调用（支持并行执行、超时保护）"""
        timeout = self.config.tool_timeout

        async def execute_single(tc: ToolCall) -> AgentToolResult:
            """执行单个工具（带超时保护）"""
            logger.info(f"Tool {tc.name} | args={tc.arguments}")
            if self._on_step:
                status = self._TOOL_STATUS.get(tc.name, f"正在处理 {tc.name}…")
                self._on_step(status)

            tool = self.tool_registry.get(tc.name)
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
                    logger.error(f"Tool execution error: {tc.name} - {e}")
                    result = AgentToolResult.error_result(tc.id, str(e))

            logger.info(f"Tool {tc.name} | error={result.is_error} result_len={len(result.content or '')}")
            if result.is_error and self._on_step:
                self._on_step("工具调用遇到问题，正在尝试其他方式…")

            return result

        # 限制工具调用数量
        limited_calls = tool_calls[: self.config.max_tool_calls_per_turn]

        # 并行执行所有工具
        results = await asyncio.gather(
            *[execute_single(tc) for tc in limited_calls],
            return_exceptions=False,
        )

        return list(results)

    # ============ 便捷方法 ============

    async def create_session(self, **kwargs: Any) -> str:
        """创建新会话并返回 ID（异步，支持持久化）"""
        session = await self.session_manager.create_session(**kwargs)
        return session.session_id

    def create_session_sync(self, **kwargs: Any) -> str:
        """创建新会话并返回 ID（同步，无持久化）"""
        session = self.session_manager.create_session_sync(**kwargs)
        return session.session_id

    def register_tool(self, tool: AgentTool) -> None:
        """注册工具"""
        self.tool_registry.register(tool)

    def register_tools(self, tools: list[AgentTool]) -> None:
        """批量注册工具"""
        self.tool_registry.register_all(tools)
