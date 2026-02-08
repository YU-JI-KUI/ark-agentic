"""
保险取款智能体示例

演示如何使用 Agent 框架实现一个保险取款场景。

功能特点：
- 多轮对话支持
- 工具调用（用户画像、保单查询、规则引擎）
- 会话持久化（JSONL 格式）
- 技能系统集成
- 支持多种 LLM 提供商（DeepSeek, OpenAI, 内部 API）

使用方法：
    # 使用 DeepSeek（默认，需要设置 DEEPSEEK_API_KEY 环境变量）
    python examples/insurance_withdrawal_agent.py

    # 使用内部 API
    python examples/insurance_withdrawal_agent.py --provider internal --base-url http://api.example.com/chat

    # 使用 Mock 客户端（演示/测试）
    python examples/insurance_withdrawal_agent.py --mock

    # 交互模式
    python examples/insurance_withdrawal_agent.py -i

    # 运行预设对话示例
    python examples/insurance_withdrawal_agent.py --demo
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# 导入 Agent 框架组件
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.compaction import CompactionConfig
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.llm import create_llm_client, LLMClientProtocol
from ark_agentic.core.memory.manager import MemoryManager, MemoryConfig
from ark_agentic.agents.insurance.tools import create_insurance_tools

# 模块路径常量
_AGENT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _AGENT_DIR / "skills"


# ============ Mock LLM Client ============


class MockLLMClient:
    """模拟 LLM 客户端

    用于演示和测试，不依赖真实 API。
    """

    def __init__(self) -> None:
        self._call_count = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        """模拟聊天响应"""
        self._call_count += 1

        # 获取用户最后一条消息
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        # 检查是否有工具结果
        has_tool_results = any(msg.get("role") == "tool" for msg in messages)

        # 根据对话阶段返回不同响应
        if self._call_count == 1 and not has_tool_results:
            return self._response_with_tools()
        elif has_tool_results and self._call_count <= 2:
            return self._response_with_plans()
        else:
            return self._response_followup(user_message)

    def _response_with_tools(self) -> dict[str, Any]:
        """返回带工具调用的响应"""
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_001",
                                "type": "function",
                                "function": {
                                    "name": "user_profile",
                                    "arguments": '{"user_id": "U001"}',
                                },
                            },
                            {
                                "id": "call_002",
                                "type": "function",
                                "function": {
                                    "name": "policy_query",
                                    "arguments": '{"user_id": "U001", "query_type": "withdrawal_limit"}',
                                },
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }

    def _response_with_plans(self) -> dict[str, Any]:
        """返回推荐方案"""
        content = """好的，张先生，我已经查询了您的保单信息。根据您的情况，我为您推荐以下取款方案：

## 推荐方案

### 方案一：部分领取 ⭐ 推荐

从您的「金瑞人生年金险」中部分领取：

- 💰 **可领取金额**：65,000元
- ⏱️ **到账时间**：3-5个工作日
- 💵 **费用**：无手续费
- 💡 **特点**：不影响保单其他权益

**推荐理由**：无利息成本，操作简单，适合短期资金需求。

---

### 方案二：保单贷款

从您的「平安福终身寿险」中申请贷款：

- 💰 **可贷金额**：33,600元
- ⏱️ **到账时间**：1-2个工作日
- 💵 **年利息**：约1,848元（年利率5.5%）
- 💡 **特点**：保障不变，可随时还款

**推荐理由**：到账最快，保障完全不受影响，适合短期周转。

---

### 方案三：组合方案

同时使用以上两种方式：

- 💰 **合计可取**：98,600元
- 💡 **特点**：获取最大资金额度

---

请问您倾向于哪个方案？或者您需要的金额是多少，我可以帮您做更精确的计算。"""

        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ]
        }

    def _response_followup(self, user_message: str) -> dict[str, Any]:
        """返回后续对话响应"""
        if "方案一" in user_message or "部分领取" in user_message:
            content = """好的，您选择了**部分领取**方案。

我来为您确认一下操作细节：

📋 **操作确认**
- 保单：金瑞人生年金险（POL002）
- 操作：部分领取
- 金额：65,000元
- 到账：3-5个工作日

⚠️ **温馨提示**
- 领取后账户价值将相应减少
- 未来年金领取金额会略有调整

如果确认无误，您可以通过以下方式办理：
1. APP自助办理（推荐）
2. 拨打客服热线 95511
3. 前往就近营业网点

请问还有其他问题吗？"""
        else:
            content = """好的，我明白了。还有什么我可以帮您的吗？

如果您想了解更多方案细节，或者有其他保险问题，随时告诉我。"""

        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ]
        }


# ============ 创建 LLM 客户端 ============


def get_llm_client(args: argparse.Namespace) -> LLMClientProtocol:
    """根据命令行参数创建 LLM 客户端"""
    if args.mock:
        logger.info("Using Mock LLM client")
        return MockLLMClient()

    provider = args.provider

    if provider == "internal":
        # 内部 API
        authorization = args.authorization or os.environ.get("INTERNAL_API_AUTH", "")
        trace_appid = args.trace_appid or os.environ.get("INTERNAL_API_APPID", "ark-nav")

        if not args.base_url:
            raise ValueError("--base-url is required for internal provider")
        if not authorization:
            raise ValueError("--authorization or INTERNAL_API_AUTH env var is required for internal provider")

        logger.info(f"Using Internal API client: {args.base_url}")
        return create_llm_client(
            provider="internal",
            base_url=args.base_url,
            authorization=authorization,
            trace_appid=trace_appid,
        )

    else:
        # OpenAI 兼容 API (deepseek, openai)
        api_key = args.api_key

        # 尝试从环境变量获取
        if not api_key:
            env_keys = {
                "deepseek": "DEEPSEEK_API_KEY",
                "openai": "OPENAI_API_KEY",
            }
            env_key = env_keys.get(provider, "")
            if env_key:
                api_key = os.environ.get(env_key, "")

        if not api_key:
            raise ValueError(
                f"API key is required. Set --api-key or {env_keys.get(provider, 'API_KEY')} environment variable."
            )

        logger.info(f"Using {provider.upper()} client (model: {args.model or 'default'})")

        kwargs = {}
        if args.base_url:
            kwargs["base_url"] = args.base_url
        if args.model:
            kwargs["model"] = args.model

        return create_llm_client(
            provider=provider,
            api_key=api_key,
            **kwargs,
        )


# ============ 创建 Agent ============


def create_insurance_agent(
    llm_client: LLMClientProtocol,
    sessions_dir: str | Path | None = None,
    enable_persistence: bool = False,
    memory_dir: str | Path | None = None,
    enable_memory: bool = False,
) -> AgentRunner:
    """创建保险取款智能体

    Args:
        llm_client: LLM 客户端实例
        sessions_dir: 会话持久化目录（None 则使用临时目录）
        enable_persistence: 是否启用持久化
        memory_dir: Memory 数据目录（用于向量存储等）
        enable_memory: 是否启用 Memory 系统

    Returns:
        配置好的 AgentRunner
    """
    # 1. 创建工具注册器并注册保险工具
    tool_registry = ToolRegistry()
    tool_registry.register_all(create_insurance_tools())

    # 2. 创建会话管理器（支持持久化，使用 LLM 摘要器进行上下文压缩）
    if enable_persistence:
        if sessions_dir is None:
            sessions_dir = Path("data") / "sessions"
        logger.info(f"Session persistence enabled: {sessions_dir}")

    from ark_agentic.core.compaction import LLMSummarizer
    summarizer = LLMSummarizer(llm_client)

    session_manager = SessionManager(
        compaction_config=CompactionConfig(
            context_window=32000,
            preserve_recent=4,
        ),
        sessions_dir=sessions_dir if enable_persistence else None,
        enable_persistence=enable_persistence,
        summarizer=summarizer,
    )

    # 3. 创建技能加载器（使用绝对路径）
    skill_config = SkillConfig(
        skill_directories=[str(_SKILLS_DIR)],
        enable_eligibility_check=True,
    )
    skill_loader = SkillLoader(skill_config)

    # 尝试加载技能（如果目录存在）
    try:
        skill_loader.load_from_directories()
        logger.info(f"Loaded {len(skill_loader.list_skills())} skills")
    except Exception as e:
        logger.warning(f"Failed to load skills: {e}")

    # 4. 可选：创建 MemoryManager
    memory_manager = None
    if enable_memory:
        if memory_dir is None:
            memory_dir = Path(tempfile.gettempdir()) / "ark_memory"
        memory_dir = Path(memory_dir)
        memory_dir.mkdir(parents=True, exist_ok=True)

        # workspace_dir 和 index_dir 都指向 memory_dir，
        # 使得 memory 内容文件（MEMORY.md 等）和 FAISS 索引共存于数据目录
        index_sub = memory_dir / ".index"
        index_sub.mkdir(parents=True, exist_ok=True)

        # 初始化 MEMORY.md（如不存在）
        seed_file = memory_dir / "MEMORY.md"
        if not seed_file.exists():
            seed_file.write_text(
                "# Agent Memory\n\n此文件用于存储跨会话的长期记忆。\n",
                encoding="utf-8",
            )

        memory_config = MemoryConfig(
            workspace_dir=str(memory_dir),
            index_dir=str(index_sub),
        )
        memory_manager = MemoryManager(memory_config)
        logger.info(f"Memory enabled: workspace={memory_dir}, index={index_sub}")

    # 5. 配置 Runner
    runner_config = RunnerConfig(
        model="deepseek-chat",
        temperature=0.7,
        max_tokens=4096,
        max_turns=10,
        enable_streaming=False,
        prompt_config=PromptConfig(
            agent_name="保险智能助手",
            agent_description="专业的保险咨询和业务处理助手，帮助您管理保单和解决保险相关问题。",
        ),
    )

    # 6. 创建 Runner
    runner = AgentRunner(
        llm_client=llm_client,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        config=runner_config,
        memory_manager=memory_manager,
    )

    return runner


# ============ 运行示例 ============


async def run_demo(agent: AgentRunner):
    """运行预设对话示例"""
    print("=" * 60)
    print("保险取款智能体 - 演示模式")
    print("=" * 60)
    print()

    # 创建会话
    session_id = await agent.create_session(
        metadata={
            "user_id": "U001",
            "channel": "app",
        }
    )
    print(f"[系统] 会话已创建: {session_id[:8]}...")
    print()

    # 预设对话
    conversations = [
        "我想取点钱",
        "我选方案一",
    ]

    for user_input in conversations:
        print(f"[用户] {user_input}")
        print()

        result = await agent.run(
            session_id=session_id,
            user_input=user_input,
            context={"user_id": "U001"},
        )

        print(f"[助手] {result.response.content}")
        print()
        print(f"[统计] 轮数: {result.turns}, 工具调用: {result.tool_calls_count}")
        print(f"[Token] 输入: {result.input_tokens}, 输出: {result.output_tokens}")
        print("-" * 60)
        print()

    # 显示会话统计
    stats = agent.session_manager.get_session_stats(session_id)
    print("\n[会话统计]")
    print(f"  消息数: {stats['message_count']}")
    print(f"  估算 Token: {stats['estimated_tokens']}")


async def interactive_mode(agent: AgentRunner):
    """交互模式"""
    print("=" * 60)
    print("保险取款智能体 - 交互模式")
    print("输入 'quit' 退出, 'stats' 查看统计, 'new' 新建会话")
    print("=" * 60)
    print()

    # 创建会话
    session_id = await agent.create_session(metadata={"user_id": "U001"})
    print(f"[系统] 会话已创建: {session_id[:8]}...")
    print()

    while True:
        try:
            user_input = input("[用户] ").strip()

            if user_input.lower() in ("quit", "exit", "q"):
                print("再见！")
                break

            if user_input.lower() == "stats":
                stats = agent.session_manager.get_session_stats(session_id)
                print(f"\n[会话统计]")
                print(f"  消息数: {stats['message_count']}")
                print(f"  估算 Token: {stats['estimated_tokens']}")
                print()
                continue

            if user_input.lower() == "new":
                session_id = await agent.create_session(metadata={"user_id": "U001"})
                print(f"[系统] 新会话已创建: {session_id[:8]}...")
                print()
                continue

            if not user_input:
                continue

            print()
            print("[助手] 思考中...")

            result = await agent.run(
                session_id=session_id,
                user_input=user_input,
                context={"user_id": "U001"},
            )

            # 清除 "思考中..." 并输出结果
            print("\033[F\033[K", end="")  # 移动光标上一行并清除
            print(f"[助手] {result.response.content}")
            print()

        except KeyboardInterrupt:
            print("\n再见！")
            break
        except Exception as e:
            logger.exception("Error during conversation")
            print(f"[错误] {e}")


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="保险取款智能体",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 使用 DeepSeek（需要设置 DEEPSEEK_API_KEY 环境变量）
  python examples/insurance_withdrawal_agent.py

  # 使用 Mock 客户端（演示模式）
  python examples/insurance_withdrawal_agent.py --mock --demo

  # 交互模式
  python examples/insurance_withdrawal_agent.py -i
""",
    )

    # LLM 配置
    parser.add_argument(
        "--provider",
        choices=["deepseek", "openai", "internal"],
        default="deepseek",
        help="LLM 提供商 (default: deepseek)",
    )
    parser.add_argument(
        "--api-key",
        help="API Key（也可通过环境变量设置）",
    )
    parser.add_argument(
        "--base-url",
        help="API Base URL（用于自定义端点）",
    )
    parser.add_argument(
        "--model",
        help="模型名称",
    )

    # 内部 API 专用
    parser.add_argument(
        "--authorization",
        help="内部 API 的 Authorization header",
    )
    parser.add_argument(
        "--trace-appid",
        help="内部 API 的 trace-appid",
    )

    # 运行模式
    parser.add_argument(
        "--mock",
        action="store_true",
        help="使用 Mock LLM 客户端（不需要真实 API）",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="交互模式",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="运行预设对话演示",
    )

    # 其他选项
    parser.add_argument(
        "--persistence",
        action="store_true",
        help="启用会话持久化",
    )
    parser.add_argument(
        "--sessions-dir",
        help="会话持久化目录",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="启用 Memory 系统（语义搜索）",
    )
    parser.add_argument(
        "--memory-dir",
        help="Memory 数据目录",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细日志输出",
    )

    return parser.parse_args()


async def main():
    """主函数"""
    from dotenv import load_dotenv
    load_dotenv()
    args = parse_args()

    # 配置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 创建 LLM 客户端
    try:
        llm_client = get_llm_client(args)
    except ValueError as e:
        print(f"[错误] {e}")
        print("\n提示：")
        print("  - 使用 --mock 可以在没有 API Key 的情况下运行演示")
        print("  - 设置 DEEPSEEK_API_KEY 环境变量使用 DeepSeek")
        return

    # 创建 Agent
    agent = create_insurance_agent(
        llm_client=llm_client,
        sessions_dir=args.sessions_dir,
        enable_persistence=args.persistence,
        memory_dir=args.memory_dir,
        enable_memory=args.memory,
    )

    # 运行
    if args.demo:
        await run_demo(agent)
    elif args.interactive:
        await interactive_mode(agent)
    else:
        # 默认：交互模式
        await interactive_mode(agent)


def main_sync():
    """同步入口点（供 pyproject.toml scripts 使用）"""
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
