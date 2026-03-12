"""
流式 <think>/<final> 标签解析器

在 ReAct 循环中实时区分思考态和最终生成态。
跨 chunk 维护状态，支持标签断裂、缺失闭合、嵌套等边界情况。
严格模式 (strict)：只有 <final> 标签内的内容才输出为 final；
未包裹的文本静默丢弃。Runner 层通过 ever_in_final 标志实现最终轮 fallback。

参考: openclaw-main/src/agents/pi-embedded-subscribe.ts — stripBlockTags()
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_THINK_TAG_RE = re.compile(
    r"<\s*(/?)\s*(?:think(?:ing)?)\s*>", re.IGNORECASE
)
_FINAL_TAG_RE = re.compile(
    r"<\s*(/?)\s*final\s*>", re.IGNORECASE
)
_TRAILING_LT_RE = re.compile(r"<[^>]{0,20}$")
_ALL_TAGS_RE = re.compile(
    r"<\s*/?\s*(?:think(?:ing)?|final)\s*>", re.IGNORECASE
)


DEFAULT_THINKING_TAG_INSTRUCTIONS = """\
## 回答格式要求

请使用以下标签结构化你的回复：

- 当你需要分析问题或决定下一步操作时，用 <think> 标签包裹你的思考过程：
  <think>用户想查询保单信息，我需要调用 policy_query 工具。</think>

- 当你给出最终回答时，用 <final> 标签包裹你的回答：
  <final>根据查询结果，您的保单信息如下：…</final>

规则：
1. 思考内容必须在 <think> 内
2. 最终回答必须在 <final> 内
3. 不要在标签外输出内容
4. 每个标签必须正确闭合"""


@dataclass
class ThinkingTagParser:
    """流式 <think>/<final> 标签状态机。

    每个 ReAct turn 创建或 reset 一次。
    process_chunk 逐 chunk 调用，返回 (thinking_content, final_content)。
    流结束时调用 flush 清空 pending buffer。
    """

    in_think: bool = False
    in_final: bool = False
    ever_in_final: bool = False
    _pending: str = field(default="", repr=False)

    # ---- 核心 API ----

    def process_chunk(self, text: str) -> tuple[str, str]:
        """处理一个 streaming chunk。

        Returns:
            (thinking_content, final_content) — 两者都可能为空字符串。
        """
        if not text and not self._pending:
            return ("", "")

        text = self._pending + text
        self._pending = ""

        text = self._buffer_trailing_partial_tag(text)

        non_think, thinking = self._extract_think(text)

        final = self._extract_final(non_think)

        return (thinking, final)

    def flush(self) -> tuple[str, str]:
        """流结束时调用，清空 _pending buffer。"""
        remaining = self._pending
        self._pending = ""
        if not remaining:
            return ("", "")
        if self.in_think:
            return (remaining, "")
        if self.in_final:
            return ("", remaining)
        return ("", "")

    def reset(self) -> None:
        """每个 ReAct turn 开始前 reset。"""
        self.in_think = False
        self.in_final = False
        self.ever_in_final = False
        self._pending = ""

    # ---- 静态工具 ----

    @staticmethod
    def strip_tags(text: str) -> str:
        """移除所有 <think>/<final> 标签，保留标签内的文本内容。

        用于清洗 AgentMessage.content 再写入对话历史。
        """
        if not text:
            return text
        return _ALL_TAGS_RE.sub("", text)

    @staticmethod
    def extract_non_think(text: str) -> str:
        """提取所有不在 <think>/<thinking> 标签内的内容，并去掉 <final> 标签本身。

        用于 runner-level fallback：当整轮未出现 <final> 时，
        从 full_content 中提取可展示给用户的非思考内容。
        """
        if not text:
            return text
        parts: list[str] = []
        last_idx = 0
        in_think = False
        for m in _THINK_TAG_RE.finditer(text):
            if not in_think:
                parts.append(text[last_idx : m.start()])
            in_think = m.group(1) != "/"
            last_idx = m.end()
        if not in_think:
            parts.append(text[last_idx:])
        result = "".join(parts)
        return _ALL_TAGS_RE.sub("", result)

    # ---- 内部实现 ----

    def _buffer_trailing_partial_tag(self, text: str) -> str:
        """检测 chunk 末尾未闭合的 '<...'，缓冲到下一 chunk。"""
        m = _TRAILING_LT_RE.search(text)
        if not m:
            return text
        candidate = m.group()
        stripped = re.sub(r"^<\s*/?", "", candidate).lstrip()
        if not stripped or stripped[0].lower() in ("t", "f"):
            self._pending = candidate
            return text[: m.start()]
        return text

    def _extract_think(self, text: str) -> tuple[str, str]:
        """扫描 <think>/<thinking> 标签。

        Returns:
            (non_think_text, thinking_text) — 分离后的两部分。
        """
        thinking_parts: list[str] = []
        non_think_parts: list[str] = []

        last_idx = 0
        in_think = self.in_think

        for m in _THINK_TAG_RE.finditer(text):
            segment = text[last_idx : m.start()]
            if in_think:
                thinking_parts.append(segment)
            else:
                non_think_parts.append(segment)

            is_close = m.group(1) == "/"
            in_think = not is_close
            last_idx = m.end()

        tail = text[last_idx:]
        if in_think:
            thinking_parts.append(tail)
        else:
            non_think_parts.append(tail)

        self.in_think = in_think
        return ("".join(non_think_parts), "".join(thinking_parts))

    def _extract_final(self, text: str) -> str:
        """扫描 <final> 标签，仅提取 <final> 内的内容（strict 模式）。"""
        if not text:
            return ""

        final_parts: list[str] = []
        last_idx = 0
        in_final = self.in_final

        for m in _FINAL_TAG_RE.finditer(text):
            segment = text[last_idx : m.start()]
            if in_final:
                final_parts.append(segment)

            is_close = m.group(1) == "/"
            if not is_close:
                in_final = True
                self.ever_in_final = True
            else:
                in_final = False
            last_idx = m.end()

        tail = text[last_idx:]
        if in_final:
            final_parts.append(tail)

        self.in_final = in_final
        return "".join(final_parts)
