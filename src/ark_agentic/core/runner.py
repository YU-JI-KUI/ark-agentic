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
from .prompt.builder import SystemPromptBuilder, PromptConfig
from .session import SessionManager
from .skills.base import SkillConfig
from .skills.loader import SkillLoader
from .skills.matcher import SkillMatcher
from .stream.assembler import StreamAssembler, StreamEvent
from .tools.base import AgentTool
from .tools.registry import ToolRegistry
from .types import AgentMessage, AgentToolResult, MessageRole, ToolCall

logger = logging.getLogger(__name__)


# ============ Runner Config ============


@dataclass
class RunnerConfig:
    """Runner 配置"""

    # LLM 参数
    model: str = "doubao-1.5-pro-32k"
    temperature: float = 0.7
    max_tokens: int = 4096

    # 执行控制
    max_turns: int = 10  # 最大对话轮数（防止无限循环）
    max_tool_calls_per_turn: int = 5  # 单轮最大工具调用数

    # 流式输出
    enable_streaming: bool = True

    # 自动压缩
    auto_compact: bool = True

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
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry or ToolRegistry()
        self.session_manager = session_manager or SessionManager()
        self.skill_loader = skill_loader
        self.config = config or RunnerConfig()

        # 技能匹配器
        self.skill_matcher = (
            SkillMatcher(skill_loader) if skill_loader else None
        )

        # 流式组装器
        self._stream_assembler: StreamAssembler | None = None

        # 回调
        self._on_thinking: Callable[[str], None] | None = None
        self._on_content: Callable[[str], None] | None = None
        self._on_tool_start: Callable[[ToolCall], None] | None = None
        self._on_tool_end: Callable[[AgentToolResult], None] | None = None

    def set_callbacks(
        self,
        on_thinking: Callable[[str], None] | None = None,
        on_content: Callable[[str], None] | None = None,
        on_tool_start: Callable[[ToolCall], None] | None = None,
        on_tool_end: Callable[[AgentToolResult], None] | None = None,
    ) -> None:
        """设置回调函数"""
        self._on_thinking = on_thinking
        self._on_content = on_content
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end

    async def run(
        self,
        session_id: str,
        user_input: str,
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        """执行智能体

        Args:
            session_id: 会话 ID
            user_input: 用户输入
            context: 额外上下文

        Returns:
            执行结果
        """
        context = context or {}

        # 添加用户消息（使用同步方法避免额外的异步开销）
        user_message = AgentMessage.user(user_input, metadata=context)
        self.session_manager.add_message_sync(session_id, user_message)

        # 自动压缩（如果需要）
        if self.config.auto_compact:
            await self.session_manager.auto_compact_if_needed(session_id)

        # 执行主循环
        result = await self._run_loop(session_id, context)

        # 同步元数据到持久化存储
        await self.session_manager.sync_session_metadata(session_id)

        return result

    async def _run_loop(
        self,
        session_id: str,
        context: dict[str, Any],
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

        while turns < self.config.max_turns:
            turns += 1

            # 构建请求
            messages = self._build_messages(session_id, context)
            tools = self._build_tools(context)

            # 调用 LLM
            if self.config.enable_streaming:
                response = await self._call_llm_streaming(messages, tools)
            else:
                response = await self._call_llm(messages, tools)

            # 更新 token 统计
            usage = response.metadata.get("usage", {})
            total_input_tokens += usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
            total_output_tokens += usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)

            # 添加助手响应到会话（使用同步方法，持久化在 run 结束后批量处理）
            self.session_manager.add_message_sync(session_id, response)

            # 检查 finish_reason
            finish_reason = response.metadata.get("finish_reason")
            if finish_reason == "length":
                logger.warning(f"Response truncated (max_tokens) in session {session_id}")
                # 可以选择继续或返回，这里选择返回截断的响应
                return RunResult(
                    response=response,
                    turns=turns,
                    tool_calls_count=total_tool_calls,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    stopped_by_limit=True,
                )

            # 检查是否有工具调用
            if response.tool_calls:
                # 执行工具（并行）
                tool_results = await self._execute_tools(
                    response.tool_calls, context
                )
                total_tool_calls += len(response.tool_calls)

                # 添加工具结果到会话
                tool_message = AgentMessage.tool(tool_results)
                self.session_manager.add_message_sync(session_id, tool_message)

                # 检查是否所有工具都失败了
                all_errors = all(tr.is_error for tr in tool_results)
                if all_errors:
                    logger.warning(f"All tool calls failed in turn {turns}")
                    # 继续循环，让 LLM 看到错误并决定下一步

                # 继续循环（ReAct 的 Act 完成，回到 Reason）
                continue

            # 无工具调用，返回最终结果
            return RunResult(
                response=response,
                turns=turns,
                tool_calls_count=total_tool_calls,
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
        system_prompt = self._build_system_prompt(context)
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

    def _build_system_prompt(self, context: dict[str, Any]) -> str:
        """构建系统提示"""
        tools = self.tool_registry.list_all()

        # 获取匹配的技能
        skills = []
        if self.skill_matcher:
            match_result = self.skill_matcher.match(context=context)
            skills = match_result.matched_skills

        return SystemPromptBuilder.quick_build(
            tools=tools,
            skills=skills,
            context=context,
            config=self.config.prompt_config,
        )

    def _build_tools(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """构建工具定义"""
        tools = self.tool_registry.list_all()
        return [tool.get_json_schema() for tool in tools]

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AgentMessage:
        """非流式调用 LLM"""
        response = await self.llm_client.chat(
            messages=messages,
            tools=tools if tools else None,
            stream=False,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        return self._parse_llm_response(response)

    async def _call_llm_streaming(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AgentMessage:
        """流式调用 LLM"""
        # 创建流式组装器
        assembler = StreamAssembler(
            on_content=self._on_content,
            on_thinking=self._on_thinking,
        )

        stream = await self.llm_client.chat(
            messages=messages,
            tools=tools if tools else None,
            stream=True,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        # 处理流
        async for chunk in stream:
            event = self._parse_stream_chunk(chunk)
            if event:
                assembler.process_event(event)

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

    async def _execute_tools(
        self,
        tool_calls: list[ToolCall],
        context: dict[str, Any],
    ) -> list[AgentToolResult]:
        """执行工具调用（支持并行执行）"""

        async def execute_single(tc: ToolCall) -> AgentToolResult:
            """执行单个工具"""
            if self._on_tool_start:
                self._on_tool_start(tc)

            tool = self.tool_registry.get(tc.name)
            if tool is None:
                result = AgentToolResult.error_result(
                    tc.id, f"Tool not found: {tc.name}"
                )
            else:
                try:
                    result = await tool.execute(tc, context)
                except Exception as e:
                    logger.error(f"Tool execution error: {tc.name} - {e}")
                    result = AgentToolResult.error_result(tc.id, str(e))

            if self._on_tool_end:
                self._on_tool_end(result)

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
