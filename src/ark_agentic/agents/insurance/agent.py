"""
保险取款智能体示例

演示如何使用 Agent 框架实现一个保险取款场景。

功能特点：
- 多轮对话支持
- 工具调用（用户画像、保单查询、规则引擎）
- 会话持久化（JSONL 格式）
- 技能系统集成
- 支持多种 LLM 提供商（OpenAI 兼容、PA 等）

使用方法：
    # 使用 OpenAI 兼容端点（需 API_KEY、可选 LLM_BASE_URL）
    export API_KEY=sk-xxx
    python -m ark_agentic.agents.insurance.agent

    # 交互模式
    python -m ark_agentic.agents.insurance.agent -i
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from ark_agentic.agents.insurance.tools import create_insurance_tools
from ark_agentic.core.compaction import CompactionConfig
from ark_agentic.core.llm import create_chat_model
from ark_agentic.core.memory.manager import MemoryManager, MemoryConfig
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.skills.loader import SkillLoader
from ark_agentic.core.tools.demo_a2ui import DemoA2UITool
from ark_agentic.core.tools.demo_state import SetStateDemoTool, GetStateDemoTool
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import SkillLoadMode

logger = logging.getLogger(__name__)

# 模块路径常量
_AGENT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _AGENT_DIR / "skills"


# ============ 创建 LLM 客户端 ============


def get_llm_client(args: argparse.Namespace) -> Any:
    """透传 CLI 参数给 factory；校验逻辑由 factory 统一处理。"""
    return create_chat_model(
        model=args.model,
        api_key=args.api_key or None,
        base_url=args.base_url or None,
    )


# ============ 创建 Agent ============


def create_insurance_agent(
    llm: BaseChatModel,
    sessions_dir: str | Path | None = None,
    enable_persistence: bool = False,
    memory_dir: str | Path | None = None,
    enable_memory: bool = False,
) -> AgentRunner:
    """创建保险取款智能体

    Args:
        llm: LLM instance (BaseChatModel, e.g. ChatOpenAI)
        sessions_dir: 会话持久化目录（None 则使用临时目录）
        enable_persistence: 是否启用持久化
        memory_dir: Memory 数据目录（用于向量存储等）
        enable_memory: 是否启用 Memory 系统

    Returns:
        配置好的 AgentRunner
    """
    # 1. 创建工具注册器并注册保险工具 + Demo A2UI 工具
    tool_registry = ToolRegistry()
    tool_registry.register_all(create_insurance_tools())

    # 2. 创建会话管理器（支持持久化，使用 LLM 摘要器进行上下文压缩）
    if enable_persistence:
        if sessions_dir is None:
            sessions_dir = Path("data") / "sessions"
        logger.info(f"Session persistence enabled: {sessions_dir}")

    from ark_agentic.core.compaction import LLMSummarizer
    summarizer = LLMSummarizer(llm)

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
        agent_id="insurance",
        enable_eligibility_check=True,
        default_load_mode=SkillLoadMode.dynamic,  # 保险 Agent 默认全量加载（最可靠）
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
        temperature=float(os.getenv("DEFAULT_TEMPERATURE", "0.7")),
        max_tokens=4096,
        max_turns=10,
        enable_streaming=False,
        prompt_config=PromptConfig(
            agent_name="保险智能助手",
            agent_description="专业的保险咨询和业务处理助手，帮助您管理保单和解决保险相关问题。",
        ),
        skill_config=skill_config,
    )

    # 6. 创建 Runner
    runner = AgentRunner(
        llm=llm,
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
        state={
            "user:id": "U001",
            "user:channel": "app",
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
            input_context={"user:id": "U001"},
        )

        print(f"[助手] {result.response.content}")
        print()
        print(f"[统计] 轮数: {result.turns}, 工具调用: {result.tool_calls_count}")
        print(f"[Token] 输入: {result.prompt_tokens}, 输出: {result.completion_tokens}")
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
    session_id = await agent.create_session(state={"user:id": "U001"})
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
                print("\n[会话统计]")
                print(f"  消息数: {stats['message_count']}")
                print(f"  估算 Token: {stats['estimated_tokens']}")
                print()
                continue

            if user_input.lower() == "new":
                session_id = await agent.create_session(state={"user:id": "U001"})
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
                input_context={"user:id": "U001"},
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
  # 使用 OpenAI 兼容端点（需要设置 API_KEY 环境变量）
  python examples/insurance_withdrawal_agent.py

  # 交互模式
  python examples/insurance_withdrawal_agent.py -i
""",
    )

    # LLM 配置（provider 由 LLM_PROVIDER 环境变量控制）
    parser.add_argument(
        "--api-key",
        help="API Key（也可通过 API_KEY 环境变量设置）",
    )
    parser.add_argument(
        "--base-url",
        help="API Base URL（用于自定义端点）",
    )
    parser.add_argument(
        "--model",
        help="模型名称",
    )

    # 运行模式
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
        return

    # 创建 Agent
    agent = create_insurance_agent(
        llm=llm_client,
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
