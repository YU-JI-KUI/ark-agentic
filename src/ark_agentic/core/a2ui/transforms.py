"""
Transform DSL Engine for Dynamic A2UI

Executes declarative data transformation instructions to derive UI-ready data
from raw business data. All numeric operations are deterministic — no LLM involvement.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class TransformError(Exception):
    """Transform DSL execution error with context for LLM retry."""

    def __init__(self, message: str, operator: str = "", field: str = ""):
        self.operator = operator
        self.field = field
        super().__init__(message)


def _fmt_currency(value: float | int) -> str:
    return f"¥ {value:,.2f}"


def _fmt_percent(value: float | int) -> str:
    if isinstance(value, float) and value < 1:
        return f"{value * 100:.0f}%"
    return f"{value}%"


def _fmt_int(value: float | int) -> str:
    return str(int(value))


_FORMATTERS: dict[str, Any] = {
    "currency": _fmt_currency,
    "percent": _fmt_percent,
    "int": _fmt_int,
    "raw": str,
}


def _apply_format(value: Any, fmt: str | None) -> Any:
    if fmt is None or fmt == "raw":
        return value
    if value is None or value == "":
        return ""
    formatter = _FORMATTERS.get(fmt)
    if formatter is None:
        return value
    try:
        return formatter(value)
    except (TypeError, ValueError):
        return str(value)


def _resolve_path(data: dict[str, Any], path: str) -> Any:
    """Resolve dot-separated path: 'a.b.c' -> data['a']['b']['c'].

    Supports:
    - Array index: 'policyAssertList[0].field' -> data['policyAssertList'][0]['field']
    - Array wildcard: 'options.field' -> [item['field'] for item in data['options']]
    """
    parts = path.split(".")
    current: Any = data
    for i, part in enumerate(parts):
        if isinstance(current, dict):
            # Support key[index] for array element access
            key, index = part, None
            bracket = re.match(r"^(\w+)\[(\d+)\]$", part)
            if bracket:
                key, index = bracket.group(1), int(bracket.group(2))
            if key not in current:
                available = list(current.keys())
                raise TransformError(
                    f"字段 '{path}' 不存在于数据中 (在 '{part}' 处失败, 可用字段: {available})",
                    field=path,
                )
            current = current[key]
            if index is not None:
                if not isinstance(current, list):
                    raise TransformError(
                        f"字段 '{path}' 中 '{key}' 不是数组 (在 '{part}' 处失败)",
                        field=path,
                    )
                if index < 0 or index >= len(current):
                    raise TransformError(
                        f"字段 '{path}' 数组下标越界 '{part}' (长度 {len(current)})",
                        field=path,
                    )
                current = current[index]
        elif isinstance(current, list):
            if part.isdigit():
                idx = int(part)
                if idx < 0 or idx >= len(current):
                    raise TransformError(
                        f"字段 '{path}' 数组下标越界 (在 '{part}' 处失败)",
                        field=path,
                    )
                current = current[idx]
            else:
                # Array wildcard: collect field from each item
                try:
                    return [item[part] for item in current if isinstance(item, dict) and part in item]
                except (KeyError, TypeError) as e:
                    raise TransformError(f"数组字段 '{part}' 访问失败: {e}", field=path)
        else:
            raise TransformError(f"路径 '{path}' 中 '{part}' 不是 dict 或 list", field=path)
    return current


def _eval_condition(item: dict[str, Any], where: dict[str, str]) -> bool:
    """Evaluate a simple where condition against a dict item.

    Supports: "> 0", ">= 10", "< 5", "== 'value'", "!= null", "!= 0"
    Also supports {"or": [...conditions...]} for OR logic.
    """
    if "or" in where:
        return any(_eval_condition(item, sub) for sub in where["or"])
    if "and" in where:
        return all(_eval_condition(item, sub) for sub in where["and"])

    for field_name, expr in where.items():
        if field_name in ("or", "and"):
            continue
        val = item.get(field_name)
        expr_str = str(expr).strip()

        match = re.match(r"^(>=|<=|>|<|==|!=)\s*(.+)$", expr_str)
        if not match:
            raise TransformError(f"无效的条件表达式: {expr_str}", operator="where")

        op, rhs_raw = match.group(1), match.group(2).strip()

        # Parse right-hand side
        if rhs_raw == "null" or rhs_raw == "None":
            rhs: Any = None
        elif rhs_raw.startswith("'") and rhs_raw.endswith("'"):
            rhs = rhs_raw.strip("'")
        elif rhs_raw.startswith('"') and rhs_raw.endswith('"'):
            rhs = rhs_raw.strip('"')
        else:
            try:
                rhs = float(rhs_raw) if "." in rhs_raw else int(rhs_raw)
            except ValueError:
                rhs = rhs_raw

        if op == "==":
            if not (val == rhs):
                return False
        elif op == "!=":
            if not (val != rhs):
                return False
        elif op == ">":
            if val is None or not (float(val) > float(rhs)):
                return False
        elif op == ">=":
            if val is None or not (float(val) >= float(rhs)):
                return False
        elif op == "<":
            if val is None or not (float(val) < float(rhs)):
                return False
        elif op == "<=":
            if val is None or not (float(val) <= float(rhs)):
                return False

    return True


def _filter_array(data: dict[str, Any], array_path: str, where: dict[str, str] | None) -> list[dict[str, Any]]:
    arr = _resolve_path(data, array_path)
    if not isinstance(arr, list):
        raise TransformError(f"'{array_path}' 不是数组", operator="filter", field=array_path)
    if where is None:
        return [item for item in arr if isinstance(item, dict)]
    return [item for item in arr if isinstance(item, dict) and _eval_condition(item, where)]


def _exec_one(spec: dict[str, Any] | str, data: dict[str, Any]) -> Any:
    """Execute a single transform spec against raw data."""
    if isinstance(spec, str):
        # Bare string treated as {"get": spec}
        return _resolve_path(data, spec)

    if not isinstance(spec, dict):
        return spec

    # literal
    if "literal" in spec:
        return spec["literal"]

    # When LLM emits multiple operator keys (e.g. get+count), prefer structural/aggregation over get.
    # select
    if "select" in spec:
        array_path = spec["select"]
        where = spec.get("where")
        map_spec = spec.get("map")
        value_format = spec.get("value_format", {})
        items = _filter_array(data, array_path, where)

        if map_spec is None:
            return items

        result = []
        for item in items:
            mapped: dict[str, Any] = {}
            for out_key, transform in map_spec.items():
                try:
                    if isinstance(transform, dict):
                        resolved = _resolve_item_spec(transform, item)
                        mapped[out_key] = _exec_one(resolved, data)
                    elif isinstance(transform, str) and transform.startswith("$."):
                        field_name = transform[2:]
                        val = item.get(field_name, "")
                        fmt = value_format.get(out_key)
                        mapped[out_key] = _apply_format(val, fmt) if fmt else val
                    else:
                        mapped[out_key] = transform
                except (TransformError, Exception) as e:
                    # Per-field failure is non-fatal; null the field, keep the item
                    logger.warning("select.map field '%s' failed: %s", out_key, e)
                    mapped[out_key] = None
            result.append(mapped)
        return result

    # sum
    if "sum" in spec:
        targets = spec["sum"]
        where = spec.get("where")
        fmt = spec.get("format")
        if isinstance(targets, str):
            targets = [targets]

        total = 0.0
        for target in targets:
            parts = target.split(".", 1)
            if len(parts) != 2:
                raise TransformError(f"sum 路径格式应为 'array.field': {target}", operator="sum")
            array_path, field_name = parts[0], parts[1]
            items = _filter_array(data, array_path, where)
            for item in items:
                v = item.get(field_name, 0)
                if v is not None:
                    total += float(v)
        return _apply_format(total, fmt)

    # count
    if "count" in spec:
        array_path = spec["count"]
        where = spec.get("where")
        fmt = spec.get("format")
        items = _filter_array(data, array_path, where)
        return _apply_format(len(items), fmt)

    # concat
    if "concat" in spec:
        parts = spec["concat"]
        if not isinstance(parts, list):
            raise TransformError("concat 参数必须是数组", operator="concat")
        result_parts: list[str] = []
        for part in parts:
            if isinstance(part, str):
                result_parts.append(part)
            elif isinstance(part, dict):
                val = _exec_one(part, data)
                result_parts.append(str(val) if val is not None else "")
            else:
                result_parts.append(str(part))
        return "".join(result_parts)

    # switch: map a field value to a label/literal.
    # Canonical: {"switch": "$.product_type", "cases": {"whole_life": "终身寿险"}, "default": "other"}
    # After _resolve_item_spec, "$.field" becomes {"literal": value}, so handle dict key_ref.
    if "switch" in spec:
        key_ref = spec["switch"]
        cases = spec.get("cases", {})
        default = spec.get("default", "")
        if isinstance(key_ref, dict):
            # Already resolved by _resolve_item_spec (e.g. {"literal": "whole_life"})
            key_val = str(_exec_one(key_ref, data))
        elif isinstance(key_ref, str):
            try:
                key_val = str(_resolve_path(data, key_ref))
            except TransformError:
                key_val = str(key_ref)
        else:
            key_val = str(key_ref)
        matched = cases.get(key_val, default)
        if isinstance(matched, dict):
            return _exec_one(matched, data)
        return matched if matched is not None else ""

    # get (after select/sum/count so multi-key specs prefer aggregation)
    if "get" in spec:
        path = spec["get"]
        default = spec.get("default")
        fmt = spec.get("format")
        if isinstance(path, str) and path.startswith("$."):
            raise TransformError(f"'$.' 引用只能在 select/map 中使用: {path}", operator="get")
        try:
            val = _resolve_path(data, path)
        except TransformError:
            if default is not None:
                return _apply_format(default, fmt)
            raise
        return _apply_format(val, fmt)

    raise TransformError(f"未知的 transform 操作: {list(spec.keys())}")


def _resolve_item_spec(spec: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Replace $. references with actual item values in a nested spec.

    Special case: {"get": "$.field", "format": "currency"} → {"literal": value, "format": "currency"}
    so the value is resolved from item then formatted by the literal+format path.
    """
    available_keys = list(item.keys()) if isinstance(item, dict) else []

    # If `get` key itself is a $. ref, collapse to literal with optional format
    if "get" in spec and isinstance(spec["get"], str) and spec["get"].startswith("$."):
        field_name = spec["get"][2:]
        val = item.get(field_name)
        if val is None and field_name not in item:
            logger.warning(
                "select.map: item missing field '%s' (available: %s)",
                field_name,
                available_keys,
            )
        fmt = spec.get("format")
        formatted = _apply_format(val, fmt) if fmt else val
        return {"literal": formatted if formatted is not None else ""}

    resolved = {}
    for k, v in spec.items():
        if isinstance(v, str) and v.startswith("$."):
            field_name = v[2:]
            val = item.get(field_name)
            if val is None and field_name not in item:
                logger.warning(
                    "select.map: item missing field '%s' (available: %s)",
                    field_name,
                    available_keys,
                )
            resolved[k] = {"literal": val if val is not None else ""}
        elif isinstance(v, list):
            resolved[k] = [
                {"literal": item.get(part[2:]) if item.get(part[2:]) is not None else ""}
                if isinstance(part, str) and part.startswith("$.")
                else part
                for part in v
            ]
        elif isinstance(v, dict):
            resolved[k] = _resolve_item_spec(v, item)
        else:
            resolved[k] = v
    return resolved


def execute_transforms(
    transforms: dict[str, Any],
    data: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Execute a dict of transform specs against raw data.

    Args:
        transforms: Mapping of output_key -> transform_spec.
        data: Raw business data from context.

    Returns:
        Tuple of (computed_data, warnings).
        computed_data: Dict of output_key -> computed_value.
        warnings: List of non-fatal warning messages.
    """
    computed: dict[str, Any] = {}
    warnings: list[str] = []

    for key, spec in transforms.items():
        try:
            merged = {**data, **computed}
            computed[key] = _exec_one(spec, merged)
        except TransformError as e:
            warnings.append(f"[TRANSFORM_WARN] {key}: {e}")
            logger.warning("Transform failed for key=%s: %s", key, e)
        except Exception as e:
            warnings.append(f"[TRANSFORM_ERROR] {key}: {e}")
            logger.exception("Unexpected error in transform key=%s", key)

    return computed, warnings
