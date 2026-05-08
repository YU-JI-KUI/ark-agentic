"""数字 claim 提取与归一化。

职责：
  - 从 answer 中提取业务数值 claim（过滤噪声小数、年份、YYYYMMDD）
  - 数值归一化（千分位、百分比→小数比例）
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..runtime.validation import ExtractedClaim

from .dates import YYYYMMDD_RE

# 低于此绝对值的普通数字视为噪声（如「3 支」）；带 % 的收益率始终参与校验
MIN_BUSINESS_NUMBER = 100.0


# ============ 归一化辅助 ============


def _decimal_str_no_noise(d: Decimal) -> str:
    """Decimal → 普通十进制字符串，供 JSON 子串匹配。"""
    s = format(d, "f").rstrip("0").rstrip(".")
    if s in ("-0", "-0.0"):
        return "0"
    return s


def _ratio_str_from_percent_points(compact: str) -> str | None:
    """百分数读数 → 小数比例（9.21% → 0.0921）。用 Decimal 避免 float 噪音。"""
    try:
        d = Decimal(compact) / Decimal(100)
    except (InvalidOperation, ValueError):
        return None
    return _decimal_str_no_noise(d)


def _dedupe_forms(forms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in forms:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def normalize_number_forms(value: str, *, percent: bool = False) -> list[str]:
    """将数字文本归一化为可匹配的候选形式。

    percent=True 时追加「÷100」比例串。
    """
    compact = value.replace(",", "").strip()
    if not compact:
        return []
    forms: list[str] = [value]
    if compact not in forms:
        forms.append(compact)
    try:
        numeric = float(compact)
    except ValueError:
        return _dedupe_forms(forms)
    if numeric.is_integer():
        integer_form = str(int(numeric))
        if integer_form not in forms:
            forms.append(integer_form)
    else:
        decimal_form = str(numeric)
        if decimal_form not in forms:
            forms.append(decimal_form)

    if percent:
        ratio = _ratio_str_from_percent_points(compact)
        if ratio and ratio not in forms:
            forms.append(ratio)

    return _dedupe_forms(forms)


# ============ 数字 token 提取 ============


def extract_number_tokens(text: str) -> list[tuple[float, bool]]:
    """提取数值 token：(值, 是否为百分数写法)。过滤年份和 YYYYMMDD。"""
    if not text:
        return []
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    # `\w` 在 Python 正则下匹配 CJK 字符；金融文本中数字常紧贴单位（``500元``、
    # ``100股``）— 用 ``\d`` 边界，仅排除「数字粘连」歧义，允许中文单位后缀。
    pattern = re.compile(r"(?<!\d)(-?\d+(?:\.\d+)?)(\s*[%％])?(?!\d)")
    results: list[tuple[float, bool]] = []
    for m in pattern.finditer(cleaned):
        raw, pct = m.group(1), m.group(2)
        if re.fullmatch(r"\d{4}", raw) and 1900 <= int(raw) <= 2100:
            continue
        if YYYYMMDD_RE.fullmatch(raw):
            continue
        try:
            results.append((float(raw), pct is not None))
        except ValueError:
            pass
    return results


# 在原文中定位数字（含千分位），与 extract_number_tokens 使用相同的业务过滤规则
_NUMBER_SPAN_RE = re.compile(
    r"(?<!\d)"
    r"(?P<num>-?(?:(?:\d{1,3}(?:,\d{3})+)(?:\.\d+)?|\d+(?:\.\d+)?))"
    r"(?P<pct>\s*[%％])?"
    r"(?!\d)",
)


def canonical_number_claim_value(number: float) -> str:
    """与 ``NumberClaimExtractor.extract_claims`` 中 claim.value 规则一致。"""
    return str(int(number)) if float(number).is_integer() else str(number)


def iter_number_spans_in_text(text: str):
    """在原文中迭代数字 token 的字符区间与面值（支持千分位显示）。

    与 ``extract_number_tokens`` / ``NumberClaimExtractor`` 一致：过滤年份、
    YYYYMMDD、以及低于 ``MIN_BUSINESS_NUMBER`` 的非百分数数。

    Yields:
        (start, end, raw_text, numeric_value, is_percent)
    """
    if not text:
        return
    for m in _NUMBER_SPAN_RE.finditer(text):
        raw = m.group("num")
        pct = m.group("pct") is not None
        compact = raw.replace(",", "")
        if re.fullmatch(r"\d{4}", compact) and 1900 <= int(compact) <= 2100:
            continue
        if YYYYMMDD_RE.fullmatch(compact):
            continue
        try:
            numeric = float(compact)
        except ValueError:
            continue
        if abs(numeric) < MIN_BUSINESS_NUMBER and not pct:
            continue
        yield (m.start(), m.end(), m.group(0), numeric, pct)


def extract_numbers_from_text(text: str) -> list[float]:
    """提取文本中的数字（支持千分位、小数、负数、百分号）。"""
    return [n for n, _ in extract_number_tokens(text)]


# ============ ClaimExtractor 实现 ============


class NumberClaimExtractor:
    """从 answer 中提取数字类 claim。"""

    def extract_claims(self, text: str) -> list[ExtractedClaim]:
        from ..runtime.validation import ExtractedClaim

        claims: list[ExtractedClaim] = []
        seen: set[str] = set()
        for number, is_percent in extract_number_tokens(text):
            if abs(number) < MIN_BUSINESS_NUMBER and not is_percent:
                continue
            value = canonical_number_claim_value(number)
            if value in seen:
                continue
            seen.add(value)
            claims.append(
                ExtractedClaim(
                    value=value,
                    type="NUMBER",
                    normalized_values=normalize_number_forms(
                        value,
                        percent=is_percent,
                    ),
                )
            )
        return claims

    def normalize_source(self, text: str, *, is_context: bool = False) -> str:
        return text
