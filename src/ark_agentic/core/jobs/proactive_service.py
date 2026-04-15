"""ProactiveServiceJob — 主动服务 Job 基类

通用执行流程（所有 Agent 共享）：
  1. should_process_user  — 关键词快速过滤（子类覆盖 intent_keywords）
  2. process_user         — 完整处理：LLM 提取意图 → 工具调用 → 生成通知
     ├── get_intent_prompt()   ← 子类覆盖：领域专属的意图提取 Prompt
     ├── fetch_data()          ← 子类覆盖：调用哪个工具、怎么取数据
     └── get_notify_prompt()   ← 子类覆盖（可选）：通知文本生成 Prompt

各 Agent 子类只需覆盖上述三个钩子，无需重写整个执行流程。
"""

from __future__ import annotations

import json
import logging
import uuid
from abc import abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from .base import BaseJob, JobMeta
from ..notifications.models import Notification

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from ..tools.registry import ToolRegistry
    from ..memory.manager import MemoryManager
    from ..notifications.store import NotificationStore

logger = logging.getLogger(__name__)

# ── 通用 Prompt：通知文本生成（各 Agent 可覆盖）─────────────────────────────
_DEFAULT_NOTIFY_PROMPT = """\
根据以下信息，生成一条简洁友好的主动服务通知（不超过100字）：

用户关注：{description}
最新数据：{data_summary}
今天日期：{today}

要求：
- 用中文
- 直接给出数据结论
- 如数据获取失败，如实说明
- 不要客套语
"""


class ProactiveServiceJob(BaseJob):
    """主动服务 Job 通用基类。

    子类只需覆盖三个钩子方法即可实现领域专属逻辑：
      - intent_keywords   : 快速过滤用的关键词列表
      - get_intent_prompt : 意图提取 Prompt（告诉 LLM 识别哪些意图）
      - fetch_data        : 根据意图调用工具获取实时数据

    示例（证券 Agent）：
        class SecuritiesProactiveJob(ProactiveServiceJob):
            intent_keywords = ["股价", "涨到", "跌到", "关注", "目标价"]

            def get_intent_prompt(self, memory, today):
                return f"识别股票/基金价格提醒意图...{memory}"

            async def fetch_data(self, intent):
                tool = self._tool_registry.get("security_info_search")
                ...
    """

    # ── 子类覆盖这三个钩子 ────────────────────────────────────────────────

    # 关键词列表，用于阶段1快速过滤（无 LLM，<1ms）
    intent_keywords: list[str] = ["关注", "提醒", "通知我"]

    @abstractmethod
    def get_intent_prompt(self, memory: str, today: str) -> str:
        """返回意图提取的 LLM Prompt。子类必须实现，提供领域专属意图识别指令。"""
        ...

    async def fetch_data(self, intent: dict[str, Any], user_id: str) -> str:
        """根据单个意图调用工具获取实时数据，返回文本摘要。子类覆盖。

        Args:
            intent:  LLM 提取出的单条意图字典
            user_id: 当前处理的用户 ID（部分工具如 policy_query 需要此参数）
        """
        return f"关注内容：{intent.get('description', '未知')}"

    def get_notify_prompt(self, description: str, data_summary: str, today: str) -> str:
        """返回通知文本生成的 LLM Prompt。子类可覆盖以定制风格。"""
        return _DEFAULT_NOTIFY_PROMPT.format(
            description=description,
            data_summary=data_summary,
            today=today,
        )

    # ── 构造与属性 ────────────────────────────────────────────────────────

    def __init__(
        self,
        llm_factory: Callable[[], "BaseChatModel"],
        tool_registry: "ToolRegistry",
        memory_manager: "MemoryManager",
        job_id: str = "proactive_service",
        cron: str = "0 9 * * *",
    ) -> None:
        from pathlib import Path
        from ..notifications.store import NotificationStore
        from ..paths import get_notifications_base_dir

        self._get_llm = llm_factory
        self._tool_registry = tool_registry
        self._memory_manager = memory_manager
        self.meta = JobMeta(
            job_id=job_id,
            cron=cron,
            max_concurrent_users=50,
            batch_size=500,
            user_timeout_secs=45.0,
        )

        # 按 agent_id 隔离通知目录：ark_notifications/{agent_id}/
        # agent_id 从 memory workspace_dir 最后一段推导（如 "insurance"、"securities"）
        self._agent_id = Path(memory_manager.config.workspace_dir).name
        self._notification_store = NotificationStore(
            base_dir=get_notifications_base_dir() / self._agent_id
        )

    @property
    def memory_manager(self) -> "MemoryManager":
        return self._memory_manager

    @property
    def notification_store(self) -> "NotificationStore":
        return self._notification_store

    # ── 框架流程（子类一般不需要覆盖）───────────────────────────────────────

    async def should_process_user(self, user_id: str, memory: str) -> bool:
        """关键词快速过滤，使用子类定义的 intent_keywords，<1ms。"""
        return any(kw in memory for kw in self.intent_keywords)

    async def process_user(self, user_id: str, memory: str) -> list[Notification] | None:
        today = datetime.now().strftime("%Y-%m-%d")

        intents = await self._extract_intents(memory, today)
        if not intents:
            return None

        notifications: list[Notification] = []
        for intent in intents:
            notification = await self._process_intent(user_id, intent, today)
            if notification:
                notifications.append(notification)

        return notifications if notifications else None

    # ── 内部流程方法 ──────────────────────────────────────────────────────

    async def _extract_intents(self, memory: str, today: str) -> list[dict[str, Any]]:
        prompt = self.get_intent_prompt(memory, today)
        try:
            llm = self._get_llm()
            response = await llm.ainvoke(prompt)
            raw = response.content
            if isinstance(raw, list):
                raw = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in raw)
            data = self._parse_json(str(raw))
            return data.get("intents", []) if data else []
        except Exception as e:
            logger.warning("Intent extraction failed: %s", e)
            return []

    async def _process_intent(
        self, user_id: str, intent: dict[str, Any], today: str
    ) -> Notification | None:
        description = intent.get("description", intent.get("symbol", ""))
        data_summary = await self.fetch_data(intent, user_id)
        body = await self._generate_notification_text(description, data_summary, today)
        if not body:
            return None

        return Notification(
            user_id=user_id,
            agent_id=self._agent_id,
            job_id=self.meta.job_id,
            title=intent.get("title", "主动服务通知"),
            body=body,
            data={"intent": intent, "raw_data": data_summary, "date": today},
        )

    async def _generate_notification_text(
        self, description: str, data_summary: str, today: str
    ) -> str | None:
        prompt = self.get_notify_prompt(description, data_summary, today)
        try:
            llm = self._get_llm()
            response = await llm.ainvoke(prompt)
            raw = response.content
            if isinstance(raw, list):
                raw = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in raw)
            return str(raw).strip() or None
        except Exception as e:
            logger.warning("Notification text generation failed: %s", e)
            return None

    def _parse_json(self, raw: str) -> dict | None:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return None
