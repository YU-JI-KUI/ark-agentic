"""
Memory System - 端到端测试
========================================

包含三个测试场景，使用 pytest-asyncio 运行：
  1. test_phase1_react_loop_memory: React Loop 主动记忆
     - LLM 自己决定调用 memory_set
  2. test_phase2_compact_flush: 上下文压缩记忆写入
     - 强制触发 compact -> MEMORY.md 自动追加 Session Snapshot
  3. test_phase3_cross_session_recall: 跨会话记忆生效
     - 新会话里验证 memory_search 能找回历史

运行命令（须在仓库根目录执行，确保 ark_agentic 可导入）:
    uv run pytest tests/test_memory_e2e.py -v -s
"""

import asyncio
import logging
import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv

# 确保加载根目录的 .env 文件
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from ark_agentic.core.compaction import CompactionConfig, LLMSummarizer
from ark_agentic.core.llm import create_chat_model_from_env
from ark_agentic.core.memory.manager import MemoryConfig, MemoryManager
from ark_agentic.core.prompt.builder import PromptConfig
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.skills.base import SkillConfig
from ark_agentic.core.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session", autouse=True)
def setup_logging():
    """配置测试日志"""
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("ark_agentic").setLevel(logging.INFO)


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    """提供干净的独立 Memory 数据目录"""
    d = tmp_path / "test_memory"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def base_sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest_asyncio.fixture
async def base_agent(memory_dir: Path, base_sessions_dir: Path):
    """
    提供一个干净解耦的 AgentRunner，不加载任何特定领域（如Insurance）的 Skills 和 Tools。
    仅具备原生的 Memory Tools。
    """
    llm = create_chat_model_from_env()

    # 1. 独立构建 Memory Manager（index_dir 省略，默认 workspace_dir/.memory）
    memory_config = MemoryConfig(workspace_dir=str(memory_dir))
    memory_manager = MemoryManager(memory_config)

    # 2. 独立构建 Session Manager
    summarizer = LLMSummarizer(llm)
    session_manager = SessionManager(
        compaction_config=CompactionConfig(
            context_window=128000,
            preserve_recent=4,
        ),
        sessions_dir=base_sessions_dir,
        summarizer=summarizer,
    )

    # 3. Runner 配置（最小引导 prompt）
    runner_config = RunnerConfig(
        max_tokens=4096,
        max_turns=10,
        enable_streaming=False,
        prompt_config=PromptConfig(
            agent_name="记忆测试助手",
            agent_description="一个专门用于测试长期记忆能力的助手。你需要积极地记住用户的偏好、关键信息，并在后续对话中主动利用这些记忆。",
        ),
        skill_config=SkillConfig(),  # 空
    )

    # 4. 创建 Runner (内部会自动注册 memory_tools)
    runner = AgentRunner(
        llm=llm,
        tool_registry=ToolRegistry(),  # 空
        session_manager=session_manager,
        config=runner_config,
        memory_manager=memory_manager,
    )
    return runner


@pytest.mark.skip(reason="memory_set 已移除，记忆写入由 MemoryWriteTool / MemoryFlusher 完成")
@pytest.mark.asyncio
async def test_phase1_react_loop_memory(base_agent: AgentRunner, memory_dir: Path):
    """
    Phase 1: 原测试 LLM 主动调用 memory_set；现设计改为仅由 compact/extractor 写入，此用例保留作历史参考。
    """
    user_id = "testuser_p1"
    session_id = await base_agent.create_session(
        user_id=user_id,
        state={"user:id": user_id, "user:name": "张三"},
    )

    # Turn 1: 声明偏好
    turn1 = "我叫张三，我的保单号是 PL-2024-888888。以后跟我说话请尽量用简洁的语言，我更喜欢简短的回复。"
    r1 = await base_agent.run(
        session_id=session_id, user_input=turn1, user_id=user_id, input_context={"user:id": user_id}
    )
    logger.info(f"[Phase1 T1] Agent: {r1.response.content}")

    # Turn 2: 强制保存记忆
    turn2 = "请帮我把刚才的偏好和保单号记录到你的记忆里，一定要调用保存记忆的工具。"
    r2 = await base_agent.run(
        session_id=session_id, user_input=turn2, user_id=user_id, input_context={"user:id": user_id}
    )
    logger.info(f"[Phase1 T2] Agent: {r2.response.content}")

    # 验证 MEMORY.md 写入状态
    mem_file = memory_dir / user_id / "MEMORY.md"
    if not mem_file.exists():
        mem_file = memory_dir / "MEMORY.md"

    assert mem_file.exists(), f"MEMORY.md 应当被创建: {mem_file}"
    content = mem_file.read_text(encoding="utf-8")
    
    # 断言
    has_pref = "简洁" in content or "简单" in content or "偏好" in content
    has_policy = "PL-2024-888888" in content or "888888" in content
    
    # 如果断言失败，打印内容便于调试
    if not (has_pref or has_policy):
        logger.error(f"当前 MEMORY.md: \n{content}")
        
    assert has_pref, "MEMORY.md 应当包含语言偏好记录"
    assert has_policy, "MEMORY.md 应当包含保单号"


@pytest.mark.asyncio
async def test_phase2_compact_flush(
    base_agent: AgentRunner, memory_dir: Path, base_sessions_dir: Path
):
    """
    Phase 2: 测试上下文压缩触发后，_flush_to_memory 将会话摘要写入 MEMORY.md 的行为。
    """
    # SessionManager 的 _compactor 在构造时固定 config，赋值 compaction_config 无效。
    # 使用带极小窗口的新 SessionManager，才能触发 compact。
    tiny_compaction_config = CompactionConfig(
        context_window=200,
        preserve_recent=2,
    )
    summarizer = base_agent.session_manager._compactor.summarizer
    base_agent.session_manager = SessionManager(
        compaction_config=tiny_compaction_config,
        sessions_dir=str(base_sessions_dir),
        summarizer=summarizer,
    )

    user_id = "compacttest"
    session_id = await base_agent.create_session(
        user_id=user_id,
        state={"user:id": user_id},
    )

    # 播种初始 MEMORY.md
    seed_file = memory_dir / user_id / "MEMORY.md"
    seed_file.parent.mkdir(parents=True, exist_ok=True)
    seed_file.write_text("# Agent Memory\n\n", encoding="utf-8")
    content_before = seed_file.read_text(encoding="utf-8")

    turns = [
        "你好，我想了解一下理赔流程。",
        "好的，车祸的话怎么理赔？",
        "对方逃逸怎么处理？非常急。",
    ]

    for turn in turns:
        await base_agent.run(session_id=session_id, user_input=turn, user_id=user_id, input_context={"user:id": user_id})

    # 验证 snapshot 是否写入
    assert seed_file.exists()
    content_after = seed_file.read_text(encoding="utf-8")
    new_content = content_after[len(content_before):]
    
    if not ("Session Snapshot" in new_content or len(new_content.strip()) > 50):
        logger.error(f"Snapshot未写入。全量内容: \n{content_after}")
        
    assert "Session Snapshot" in new_content or len(new_content.strip()) > 50, "Session Snapshot 应写入"


@pytest.mark.asyncio
async def test_phase3_cross_session_recall(base_agent: AgentRunner, memory_dir: Path):
    """
    Phase 3: 跨会话记忆检索，模拟内存提前有历史，新会话中让Agent自发检索
    """
    user_id = "recalltest"
    user_mem_dir = memory_dir / user_id
    user_mem_dir.mkdir(parents=True, exist_ok=True)
    mem_file = user_mem_dir / "MEMORY.md"
    
    preset_content = """# Agent Memory

此文件用于存储跨会话的长期记忆。

## User Preferences

- 用户姓名：李四
- 偏好简洁语言，不喜欢过长的解释
- 重要保单号：PL-2024-999999（万能险）
- 已选择取款方案A（部分退保）
"""
    mem_file.write_text(preset_content, encoding="utf-8")
    
    session_id = await base_agent.create_session(
        user_id=user_id,
        state={"user:id": user_id},
    )
    
    # 等待索引初始化完毕 (防止查询过快)
    memory_mgr = base_agent._get_memory_for_user(user_id)
    if memory_mgr:
        if not memory_mgr._initialized:
            await memory_mgr.initialize()

    # Turn
    turn = "你还记得我吗？上次我好像聊过一个保单的事情，你能帮我回忆一下吗？"
    r = await base_agent.run(session_id=session_id, user_input=turn, user_id=user_id, input_context={"user:id": user_id})
    logger.info(f"[Phase3] Agent: {r.response.content}")
    
    # 断言
    used_memory = any(tc.name in ("memory_search", "memory_get") for tc in r.tool_calls)
    assert used_memory, f"Agent 理应调用 memory_search 或 memory_get, 但是只调用了: {[tc.name for tc in r.tool_calls]}"
    
    content_lower = r.response.content.lower()
    has_policy = "999999" in r.response.content or "pl-2024" in content_lower
    has_name = "李四" in r.response.content
    assert has_policy or has_name, "回复应当包含上次的记忆内容"
