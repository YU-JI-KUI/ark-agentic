"""Job 抽象基类

所有主动服务 Job 继承 BaseJob，实现两个方法：
  - should_process_user: 轻量规则过滤（无 LLM，<1ms）
  - process_user: 完整处理（LLM + 工具调用）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..notifications.models import Notification


@dataclass
class JobMeta:
    """Job 元数据配置"""

    job_id: str
    cron: str                         # cron 表达式，如 "0 9 * * *"（每天9点）
    max_concurrent_users: int = 50    # asyncio.Semaphore 并发上限
    batch_size: int = 500             # 每批处理的用户数
    user_timeout_secs: float = 30.0   # 单用户处理超时（秒）
    enabled: bool = True              # 可动态关闭


@dataclass
class JobRunStats:
    """单次 Job 运行统计"""

    scanned: int = 0          # 扫描的用户总数
    skipped: int = 0          # 规则过滤跳过（无意图）
    notified: int = 0         # 成功生成通知的用户数
    errors: int = 0           # 处理异常数
    timed_out: int = 0        # 处理超时数
    pushed: int = 0           # 实时推送成功数
    stored: int = 0           # 仅存储（用户离线）数

    @property
    def processed(self) -> int:
        return self.notified + self.errors + self.timed_out

    def summary(self) -> str:
        return (
            f"scanned={self.scanned} skipped={self.skipped} "
            f"notified={self.notified} pushed={self.pushed} stored={self.stored} "
            f"errors={self.errors} timed_out={self.timed_out}"
        )


class BaseJob(ABC):
    """主动服务 Job 抽象基类"""

    meta: JobMeta

    @abstractmethod
    async def should_process_user(self, user_id: str, memory: str) -> bool:
        """轻量判断：该用户是否有需要主动服务的意图。

        此方法应极快（<1ms），使用纯规则/关键词扫描，不调用 LLM。
        千万用户全量扫描依赖此方法的性能。
        """
        ...

    @abstractmethod
    async def process_user(self, user_id: str, memory: str) -> list["Notification"] | None:
        """完整处理：LLM 意图分析 + 工具调用 + 生成通知。

        Returns:
            list[Notification] — 要发送的通知列表
            None               — 本次无需通知
        """
        ...
