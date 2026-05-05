"""日期 claim 提取与事实来源归一化。

职责：
  - 从 answer 中提取 ISO / YYYYMMDD / 中文绝对 / 中文相对时间 claim
  - 对 tool source / context 做日期格式归一化（YYYYMMDD→ISO、中文→ISO 别名、相对→绝对）
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..runtime.validation import ExtractedClaim

# ============ Regex 常量 ============

# ISO 日期
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# 中文日期（greedy：YYYY年M月D日 | YYYY年M月 | YYYY年）
CHINESE_DATE_RE = re.compile(r"\d{4}年\d{1,2}月(?:\d{1,2}日)?|\d{4}年")
# 紧凑型 YYYYMMDD（限定 19xx/20xx 避免误匹配）
YYYYMMDD_RE = re.compile(r"\b((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b")
# 中文相对时间（从长到短避免子串截断）
RELATIVE_TIME_RE = re.compile(
    r"上上个?月|上个?月|上月|本月|这个?月|下个?月|下月"
    r"|今天|今日|昨天|昨日|前天|大前天"
    r"|本周|上周|这周|下周"
    r"|上季度|本季度|上个季度|这个季度"
    r"|去年|今年|明年|前年"
)

# resolve_relative_time 专用
_WEEKDAY_MAP: dict[str, int] = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
}
_RELATIVE_WEEK_RE = re.compile(r"^(本周|上周|下周)([一二三四五六日天])$")


# ============ 转换辅助 ============


def chinese_date_to_iso(text: str) -> str | None:
    """2026年3月15日 → 2026-03-15 / 2026年3月 → 2026-03 / 2026年 → 2026"""
    m = re.fullmatch(r"(\d{4})年(?:(\d{1,2})月(?:(\d{1,2})日)?)?", text)
    if not m:
        return None
    year, month, day = m.group(1), m.group(2), m.group(3)
    if month and day:
        return f"{year}-{int(month):02d}-{int(day):02d}"
    if month:
        return f"{year}-{int(month):02d}"
    return year


def normalize_compact_ymd(text: str) -> str:
    """将文中 YYYYMMDD 内联替换为 YYYY-MM-DD。"""
    return YYYYMMDD_RE.sub(r"\1-\2-\3", text)


def append_chinese_date_iso_aliases(text: str) -> str:
    """将「YYYY年M月D日」等片段对应的 ISO 追加到文末（已存在则跳过）。"""
    extras: list[str] = []
    seen: set[str] = set()
    for m in CHINESE_DATE_RE.finditer(text):
        iso = chinese_date_to_iso(m.group())
        if not iso or iso in text or iso in seen:
            continue
        seen.add(iso)
        extras.append(iso)
    return text + (" " + " ".join(extras) if extras else "")


def relative_time_to_forms(expr: str) -> set[str]:
    """将中文相对时间表述转换为等价的绝对日期表示集合。"""
    today = date.today()
    forms: set[str] = {expr}

    if expr in ("上个月", "上月"):
        last = today.replace(day=1) - timedelta(days=1)
        forms |= {
            last.strftime("%Y-%m"),
            last.strftime("%Y年%m月"),
            f"{last.year}年{last.month}月",
            last.replace(day=1).isoformat(),
        }
    elif expr in ("上上个月", "上上月"):
        first_of_last = today.replace(day=1) - timedelta(days=1)
        two_months_ago = first_of_last.replace(day=1) - timedelta(days=1)
        forms |= {
            two_months_ago.strftime("%Y-%m"),
            two_months_ago.replace(day=1).isoformat(),
        }
    elif expr in ("本月", "这个月", "这月"):
        forms |= {
            today.strftime("%Y-%m"),
            f"{today.year}年{today.month}月",
            today.replace(day=1).isoformat(),
        }
    elif expr in ("下个月", "下月"):
        if today.month == 12:
            nxt = today.replace(year=today.year + 1, month=1, day=1)
        else:
            nxt = today.replace(month=today.month + 1, day=1)
        forms |= {nxt.strftime("%Y-%m"), nxt.isoformat()}
    elif expr in ("今天", "今日"):
        forms.add(today.isoformat())
    elif expr in ("昨天", "昨日"):
        forms.add((today - timedelta(days=1)).isoformat())
    elif expr == "前天":
        forms.add((today - timedelta(days=2)).isoformat())
    elif expr == "大前天":
        forms.add((today - timedelta(days=3)).isoformat())
    elif expr in ("本周", "这周"):
        monday = today - timedelta(days=today.weekday())
        for i in range(7):
            forms.add((monday + timedelta(days=i)).isoformat())
    elif expr == "上周":
        monday = today - timedelta(days=today.weekday() + 7)
        for i in range(7):
            forms.add((monday + timedelta(days=i)).isoformat())
    elif expr == "下周":
        monday = today - timedelta(days=today.weekday() - 7)
        for i in range(7):
            forms.add((monday + timedelta(days=i)).isoformat())
    elif expr in ("上季度", "上个季度"):
        q = (today.month - 1) // 3
        year = today.year if q > 0 else today.year - 1
        q = q if q > 0 else 4
        start_month = (q - 1) * 3 + 1
        forms |= {f"{year}-{start_month:02d}", f"{year}年Q{q}"}
    elif expr in ("本季度", "这个季度"):
        q = (today.month - 1) // 3 + 1
        forms.add(f"{today.year}年Q{q}")
    elif expr == "去年":
        forms |= {str(today.year - 1), f"{today.year - 1}年"}
    elif expr == "今年":
        forms |= {str(today.year), f"{today.year}年"}
    elif expr == "明年":
        forms |= {str(today.year + 1), f"{today.year + 1}年"}
    elif expr == "前年":
        forms |= {str(today.year - 2), f"{today.year - 2}年"}

    return forms


def resolve_relative_time(text: str) -> str | None:
    """将中文相对时间表述转换为绝对日期（YYYY-MM-DD）。

    支持：今天/今日、昨天/昨日、前天、大前天、本/上/下周X。
    """
    text = text.strip()
    today = date.today()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text

    _DAY_OFFSET: dict[str, int] = {
        "今天": 0, "今日": 0, "昨天": -1, "昨日": -1, "前天": -2, "大前天": -3,
    }
    if text in _DAY_OFFSET:
        return (today + timedelta(days=_DAY_OFFSET[text])).isoformat()

    m = _RELATIVE_WEEK_RE.match(text)
    if m:
        prefix, weekday_char = m.group(1), m.group(2)
        target_weekday = _WEEKDAY_MAP[weekday_char]
        this_monday = today - timedelta(days=today.weekday())
        target = this_monday + timedelta(days=target_weekday)
        if prefix == "上周":
            target -= timedelta(weeks=1)
        elif prefix == "下周":
            target += timedelta(weeks=1)
        return target.isoformat()

    return None


# ============ Source 归一化 ============


def normalize_tool_source(text: str) -> str:
    """YYYYMMDD→ISO 内联替换 + 中文日期→ISO 别名追加。"""
    text = normalize_compact_ymd(text)
    return append_chinese_date_iso_aliases(text)


def normalize_context(text: str) -> str:
    """工具侧归一化 + 相对时间→绝对日期展开。"""
    text = normalize_compact_ymd(text)
    text = append_chinese_date_iso_aliases(text)
    extras: list[str] = []
    for rel in set(RELATIVE_TIME_RE.findall(text)):
        for form in relative_time_to_forms(rel):
            if form not in text and form not in extras:
                extras.append(form)
    return text + (" " + " ".join(extras) if extras else "")


# ============ ClaimExtractor 实现 ============


class DateClaimExtractor:
    """从 answer 中提取日期类 claim，并对事实来源做日期格式归一化。"""

    def extract_claims(self, text: str) -> list[ExtractedClaim]:
        from ..runtime.validation import ExtractedClaim

        claims: list[ExtractedClaim] = []
        seen: set[str] = set()

        def _add(value: str, normalized: list[str]) -> None:
            if value in seen:
                return
            seen.add(value)
            claims.append(ExtractedClaim(value=value, type="TIME", normalized_values=normalized))

        for iso_date in set(DATE_RE.findall(text)):
            _add(iso_date, [iso_date])

        for m in YYYYMMDD_RE.finditer(text):
            compact = m.group(0)
            iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            _add(compact, [compact, iso])

        for m in CHINESE_DATE_RE.finditer(text):
            cd = m.group()
            nv = [cd]
            iso_equiv = chinese_date_to_iso(cd)
            if iso_equiv and iso_equiv not in nv:
                nv.append(iso_equiv)
            _add(cd, nv)

        for rel in set(RELATIVE_TIME_RE.findall(text)):
            _add(rel, list(relative_time_to_forms(rel)))

        return claims

    def normalize_source(self, text: str, *, is_context: bool = False) -> str:
        return normalize_context(text) if is_context else normalize_tool_source(text)
