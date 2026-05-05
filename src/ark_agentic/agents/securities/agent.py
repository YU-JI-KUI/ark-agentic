"""
证券资产管理 Agent

创建并配置证券 AgentRunner。路径完全由环境变量控制。

环境变量:
    SESSIONS_DIR: 会话持久化基础目录（默认 data/ark_sessions）
    MEMORY_DIR:   Memory 数据基础目录（默认 data/ark_memory）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from ark_agentic.core.runtime.factory import AgentDef, build_standard_agent
from ark_agentic.core.runtime.callbacks import (
    CallbackContext,
    CallbackEvent,
    CallbackResult,
    HookAction,
    RunnerCallbacks,
)
from ark_agentic.core.runtime.runner import AgentRunner
from ark_agentic.core.types import AgentMessage
from ark_agentic.core.runtime.validation import EntityTrie, create_citation_validation_hook

from .tools import create_securities_tools
from .tools.service.param_mapping import enrich_securities_context, _get_context_value
from .validation import VALIDATION_SYSTEM_INSTRUCTION

logger = logging.getLogger(__name__)

_AGENT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _AGENT_DIR / "skills"
_STOCKS_CSV = _AGENT_DIR / "mock_data" / "stocks" / "a_shares_seed.csv"

_DEF = AgentDef(
    agent_id="securities",
    agent_name="证券资产管理助手",
    agent_description="专业的证券资产查询与分析助手",
    custom_instructions=VALIDATION_SYSTEM_INSTRUCTION,
)


async def _enrich_context(ctx: CallbackContext, **kwargs: Any) -> CallbackResult | None:
    return CallbackResult(context_updates=enrich_securities_context(ctx.input_context))


async def _auth_check(ctx: CallbackContext, **kwargs: Any) -> CallbackResult | None:
    login_flag = _get_context_value(ctx.input_context, "loginflag")
    if str(login_flag) != "1":
        return None
    account_type = _get_context_value(ctx.input_context, "account_type", "normal")
    type_code = "1" if account_type == "margin" else "2"
    return CallbackResult(
        action=HookAction.ABORT,
        response=AgentMessage.assistant("需要进行证券账户登录才能访问该服务。"),
        event=CallbackEvent(
            type="ui_component",
            data={
                "template": "common_login",
                "body": {"actionAuth": "Z", "type": type_code},
            },
        ),
    )


def create_securities_agent(
    llm: BaseChatModel | None = None,
    *,
    enable_memory: bool = False,
    enable_dream: bool = True,
) -> AgentRunner:
    """创建证券资产管理 Agent

    Args:
        llm: LLM 实例；None 时从环境变量初始化
        enable_memory: 是否启用 Memory 系统；路径由 MEMORY_DIR 环境变量控制
        enable_dream: 是否启用 Dream 后台蒸馏（需 enable_memory=True 才有效）
    """
    trie = EntityTrie()
    trie.load_from_csv(_STOCKS_CSV)
    callbacks = RunnerCallbacks(
        before_agent=[_enrich_context, _auth_check],
        before_loop_end=[create_citation_validation_hook(entity_trie=trie)],
    )
    return build_standard_agent(
        _DEF,
        skills_dir=_SKILLS_DIR,
        tools=create_securities_tools(),
        llm=llm,
        enable_memory=enable_memory,
        enable_dream=enable_dream,
        callbacks=callbacks,
    )
