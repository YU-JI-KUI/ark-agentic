"""StockIndex：离线建索引

将股票列表预处理后构建以下内存映射，支持 O(1) 精确查找：
- code_map:     {code -> StockEntity}
- name_map:     {name -> StockEntity}
- pinyin_map:   {pinyin -> StockEntity}
- initials_map: {首字母缩写 -> [StockEntity]}  （可能多个）

同时暴露向量化列表供 rapidfuzz 批量模糊匹配使用。
"""

from __future__ import annotations

from typing import Any

from .models import StockEntity


def _infer_exchange(code: str) -> str:
    """根据股票代码推断交易所"""
    if not code or not code.isdigit():
        return "SH"
    prefix = code[0]
    if prefix == "6":
        return "SH"
    if prefix in ("0", "3"):
        return "SZ"
    if prefix in ("8", "4"):
        return "BJ"
    return "SH"


def _to_pinyin(text: str) -> str:
    """将中文文本转为全拼（无声调、小写、连续拼接）"""
    try:
        from pypinyin import Style, pinyin

        return "".join(p[0] for p in pinyin(text, style=Style.NORMAL, errors="ignore"))
    except ImportError:
        return text.lower()


def _to_initials(text: str) -> str:
    """将中文文本转为拼音首字母缩写"""
    try:
        from pypinyin import Style, pinyin

        return "".join(p[0][0] for p in pinyin(text, style=Style.FIRST_LETTER, errors="ignore"))
    except ImportError:
        return ""


class StockIndex:
    """A 股内存索引

    使用方式：
        index = StockIndex(raw_rows)  # raw_rows: list of dict with code/name/exchange
        entity = index.find_by_code("600519")
    """

    def __init__(self, raw_rows: list[dict[str, Any]]) -> None:
        self._code_map: dict[str, StockEntity] = {}
        self._name_map: dict[str, StockEntity] = {}
        self._pinyin_map: dict[str, StockEntity] = {}
        self._initials_map: dict[str, list[StockEntity]] = {}

        # 用于批量模糊匹配的向量
        self._all_codes: list[str] = []
        self._all_names: list[str] = []
        self._all_pinyins: list[str] = []
        self._all_entities: list[StockEntity] = []

        self._build(raw_rows)

    def _build(self, raw_rows: list[dict[str, Any]]) -> None:
        for row in raw_rows:
            code = str(row.get("code", "")).strip().zfill(6)
            name = str(row.get("name", "")).strip()
            if not code or not name:
                continue

            exchange = row.get("exchange") or _infer_exchange(code)
            full_code = f"{code}.{exchange}"
            py = _to_pinyin(name)
            initials = _to_initials(name)

            entity = StockEntity(
                code=code,
                name=name,
                exchange=exchange,
                full_code=full_code,
                pinyin=py,
                initials=initials,
            )

            self._code_map[code] = entity
            self._name_map[name] = entity
            self._pinyin_map[py] = entity

            if initials:
                self._initials_map.setdefault(initials, []).append(entity)

            self._all_codes.append(code)
            self._all_names.append(name)
            self._all_pinyins.append(py)
            self._all_entities.append(entity)

    # ── 精确查找 ────────────────────────────────────────────────────

    def find_by_code(self, code: str) -> StockEntity | None:
        return self._code_map.get(code.strip().zfill(6))

    def find_by_name(self, name: str) -> StockEntity | None:
        return self._name_map.get(name.strip())

    def find_by_pinyin(self, py: str) -> StockEntity | None:
        return self._pinyin_map.get(py.strip().lower())

    def find_by_initials(self, initials: str) -> list[StockEntity]:
        return self._initials_map.get(initials.strip().lower(), [])

    # ── 批量匹配所需的向量 ──────────────────────────────────────────

    @property
    def all_codes(self) -> list[str]:
        return self._all_codes

    @property
    def all_names(self) -> list[str]:
        return self._all_names

    @property
    def all_pinyins(self) -> list[str]:
        return self._all_pinyins

    @property
    def all_entities(self) -> list[StockEntity]:
        return self._all_entities

    def get_entity_by_name(self, name: str) -> StockEntity | None:
        return self._name_map.get(name)

    def get_entity_by_pinyin(self, py: str) -> StockEntity | None:
        return self._pinyin_map.get(py)

    def __len__(self) -> int:
        return len(self._all_entities)
