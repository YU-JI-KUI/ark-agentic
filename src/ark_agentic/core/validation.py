"""
输出验证层

校验 LLM 最终输出与工具返回值之间的数值一致性，检测幻觉。

参考场景: 保险取款中 LLM 声称"可取 70,000 元"但工具只返回了 65,000。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Union

from .types import AgentMessage, AgentToolResult, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """验证问题"""

    severity: str  # "warning" | "error"
    field: str
    llm_value: str
    tool_value: str
    message: str


@dataclass
class ValidationResult:
    """验证结果"""

    passed: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)

    def add_issue(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)
        if issue.severity == "error":
            self.passed = False


def extract_numbers_from_text(text: str) -> list[float]:
    """从文本中提取所有数字（包括千分位格式）。

    支持: 65000, 65,000, 65000.5, ￥65,000, 5.5% 等。
    """
    if not text:
        return []

    # 移除千分位逗号再匹配
    cleaned = re.sub(r"(\d),(\d{3})", r"\1\2", text)
    # 匹配所有数字（整数和小数）
    pattern = r"(?<!\w)(\d+(?:\.\d+)?)(?:\s*%)?(?!\w)"
    matches = re.findall(pattern, cleaned)

    results = []
    for m in matches:
        try:
            val = float(m)
            # 过滤掉明显不是金额/费率的数字（如年份、日期片段）
            if val > 1900 and val < 2100:
                continue  # 可能是年份
            results.append(val)
        except ValueError:
            continue

    return results


def extract_numbers_from_tool_results(
    tool_results: list[AgentToolResult],
) -> dict[str, set[float]]:
    """从工具结果中提取数值，按工具名分组。

    递归扫描 dict/list 结构中所有数值。
    """
    numbers: dict[str, set[float]] = {}

    for tr in tool_results:
        tool_name = tr.metadata.get("tool_name", "unknown")
        if tool_name not in numbers:
            numbers[tool_name] = set()

        _collect_numbers(tr.content, numbers[tool_name])

    return numbers


def _collect_numbers(data: Union[str, int, float, dict[str, Any], list[Any], tuple[Any, ...]], output: set[float]) -> None:
    """递归收集数据结构中的所有数字值。"""
    if isinstance(data, (int, float)):
        if data != 0:  # 忽略 0
            output.add(float(data))
    elif isinstance(data, dict):
        for v in data.values():
            _collect_numbers(v, output)
    elif isinstance(data, (list, tuple)):
        for item in data:
            _collect_numbers(item, output)
    elif isinstance(data, str):
        for n in extract_numbers_from_text(data):
            output.add(n)


def validate_response_against_tools(
    response_text: str,
    tool_results: list[AgentToolResult],
    tolerance: float = 0.01,
) -> ValidationResult:
    """验证 LLM 响应中的数值是否与工具返回一致。

    Args:
        response_text: LLM 最终输出文本
        tool_results: 本次执行中所有工具的返回结果
        tolerance: 允许的相对误差（默认 1%）

    Returns:
        验证结果
    """
    result = ValidationResult()

    if not response_text or not tool_results:
        return result

    # 提取 LLM 输出中的数字
    llm_numbers = extract_numbers_from_text(response_text)
    if not llm_numbers:
        return result

    # 提取工具结果中的所有数字
    all_tool_numbers: set[float] = set()
    for tr in tool_results:
        _collect_numbers(tr.content, all_tool_numbers)

    if not all_tool_numbers:
        return result

    # 检查 LLM 输出中的每个数字是否能在工具结果中找到匹配
    for llm_num in llm_numbers:
        # 跳过小数字（可能是序号、百分比等）
        if llm_num < 100:
            continue

        # 检查是否有匹配的工具数字
        matched = any(
            abs(llm_num - tool_num) / max(abs(tool_num), 1) <= tolerance
            for tool_num in all_tool_numbers
        )

        if not matched:
            # LLM 输出了一个工具结果中不存在的大数字 → 可能是幻觉
            issue = ValidationIssue(
                severity="warning",
                field="amount",
                llm_value=str(llm_num),
                tool_value=str(sorted(all_tool_numbers)),
                message=f"LLM 输出数值 {llm_num} 未在工具结果中找到匹配",
            )
            result.add_issue(issue)
            logger.warning(f"Validation: {issue.message}")

    return result
