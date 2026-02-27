"""
证券智能体 API 支持模块

提供证券智能体的构建与配置，供统一 FastAPI 服务调用。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .agent import create_securities_agent
from ark_agentic.core.llm import create_chat_model, PAModel
from ark_agentic.core.runner import AgentRunner

logger = logging.getLogger(__name__)


def create_securities_agent_from_env(
    sessions_dir: str | Path | None = None,
    enable_persistence: bool = True,
) -> AgentRunner:
    """从环境变量创建保险智能体

    环境变量:
        LLM_PROVIDER: LLM 提供商 (pa/deepseek/openai)，默认 pa
        PA_MODEL: PA 模型选择 (PA-JT-80B/PA-SX-80B/PA-SX-235B)，默认 PA-SX-80B
        PA_SX_BASE_URL: PA SX 系列 API 地址
        PA_JT_BASE_URL: PA JT 系列 API 地址
        DEEPSEEK_API_KEY: DeepSeek API Key（当 provider=deepseek 时使用）
        LLM_BASE_URL: 自定义 LLM API 地址
        SESSIONS_DIR: 会话持久化目录
    """

    provider = os.getenv("LLM_PROVIDER", "pa")
    pa_model_str = os.getenv("PA_MODEL", "PA-SX-80B")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")

    if provider == "pa":
        try:
            pa_model = PAModel(pa_model_str)
        except ValueError:
            pa_model = PAModel.PA_SX_80B
            logger.warning(f"Invalid PA_MODEL: {pa_model_str}, using PA-SX-80B")

        llm = create_chat_model(model=pa_model)
        logger.info(f"Using PA Internal LLM: {pa_model.value}")
    elif api_key:
        llm = create_chat_model(
            model="deepseek-chat" if provider == "deepseek" else provider,
            api_key=api_key,
            base_url=base_url,
        )
        logger.info(f"Using {provider} LLM client")
    else:
        raise ValueError(
            "LLM_PROVIDER is not 'pa' and no API key found. "
            "Set DEEPSEEK_API_KEY or use LLM_PROVIDER=pa with PA_* env."
        )

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
        memory_dir = Path("data") / "ark_insurance_memory"
    else:
        memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)

    runner = create_securities_agent(
        llm=llm,
        sessions_dir=sessions_dir,
        enable_persistence=enable_persistence,
        memory_dir=memory_dir,
        enable_memory=False,
    )
    
    # 记录配置信息
    mock_mode = os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1")
    account_type = os.getenv("SECURITIES_ACCOUNT_TYPE", "normal")
    logger.info(f"Securities Agent created: mock={mock_mode}, account_type={account_type}")
    
    return runner
