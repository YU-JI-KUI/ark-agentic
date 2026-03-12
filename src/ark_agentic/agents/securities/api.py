"""
证券智能体 API 支持模块

提供证券智能体的构建与配置，供统一 FastAPI 服务调用。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .agent import create_securities_agent
from ark_agentic.core.llm import create_chat_model_from_env
from ark_agentic.core.runner import AgentRunner

logger = logging.getLogger(__name__)


def create_securities_agent_from_env(
    sessions_dir: str | Path | None = None,
    enable_persistence: bool = True,
) -> AgentRunner:
    """从环境变量创建证券智能体

    环境变量:
        LLM_PROVIDER: pa | openai 等，默认 pa
        MODEL_NAME: 必填，PA 时为 PA-SX-80B / PA-JT-80B 等，OpenAI 兼容时为模型 id
        API_KEY: OpenAI 兼容端点必填；PA-SX 鉴权用
        LLM_BASE_URL: PA 时必填；OpenAI 兼容时可选
        PA-JT 签名专用: PA_JT_OPEN_API_CODE / PA_JT_RSA_PRIVATE_KEY 等
        PA-SX trace 专用: PA_SX_80B_APP_ID / PA_SX_235B_APP_ID
        SESSIONS_DIR: 会话持久化目录
    """
    llm = create_chat_model_from_env()

    # 从环境变量或参数获取会话目录
    if sessions_dir is None:
        sessions_dir = os.getenv("SESSIONS_DIR")

    if enable_persistence and sessions_dir is None:
        sessions_dir = Path("data") / "ark_sessions"

    if sessions_dir:
        sessions_dir = Path(sessions_dir)
        sessions_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Session persistence enabled: {sessions_dir}")

    # Memory 目录
    memory_dir = os.getenv("MEMORY_DIR")
    if memory_dir is None:
        memory_dir = Path("data") / "ark_securities_memory"
    else:
        memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)

    enable_memory = os.getenv("ENABLE_MEMORY", "").lower() in ("true", "1")

    runner = create_securities_agent(
        llm=llm,
        sessions_dir=sessions_dir,
        enable_persistence=enable_persistence,
        memory_dir=memory_dir,
        enable_memory=enable_memory,
    )

    # 记录配置信息
    mock_mode = os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1")
    account_type = os.getenv("SECURITIES_ACCOUNT_TYPE", "normal")
    logger.info(
        f"Securities Agent created: mock={mock_mode}, account_type={account_type}"
    )

    return runner
