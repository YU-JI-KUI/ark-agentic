"""
PresetRegistry — per-agent preset card registry.

In preset mode the extractor produces a frontend-ready payload (e.g.
TemplateRenderer output) as ``A2UIOutput.template_data``.  The tool
returns it directly — no component-tree assembly, no template.json.

Each extractor follows the ``CardExtractor`` protocol:
    (context: dict, card_args: dict | None) -> A2UIOutput
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .blocks import A2UIOutput

if TYPE_CHECKING:
    from ..tools.render_a2ui import CardExtractor

logger = logging.getLogger(__name__)


class PresetRegistry:
    """Per-agent preset card registry.

    Each entry maps a card type name to a ``CardExtractor`` callable:
        (context: dict, card_args: dict | None) -> A2UIOutput

    ``A2UIOutput.template_data`` is returned as-is to the frontend.
    """

    def __init__(self) -> None:
        self._extractors: dict[str, Any] = {}

    def register(self, card_type: str, extractor: CardExtractor) -> PresetRegistry:
        self._extractors[card_type] = extractor
        return self

    def get(self, card_type: str) -> CardExtractor | None:
        return self._extractors.get(card_type)

    @property
    def types(self) -> list[str]:
        return sorted(self._extractors.keys())

    def __len__(self) -> int:
        return len(self._extractors)

    def __bool__(self) -> bool:
        return bool(self._extractors)
