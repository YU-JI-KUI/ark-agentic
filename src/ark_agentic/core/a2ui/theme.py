"""A2UI visual design tokens — the single source of truth for brand identity.

Each field describes a visual attribute (color, shape, spacing density).
Protocol constraints (width=100, style="default") are hardcoded in rendering code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class A2UITheme(BaseModel):
    """Immutable set of visual design tokens for an A2UI surface."""

    model_config = ConfigDict(frozen=True)

    # ---- color palette ----
    accent: str = "#FF6600"
    title_color: str = "#333333"
    body_color: str = "#333333"
    hint_color: str = "#999999"
    note_color: str = "#666666"
    card_bg: str = "#FFFFFF"
    page_bg: str = "#F5F5F5"
    divider_color: str = "#F5F5F5"

    # ---- shape & density ----
    card_radius: str = "middle"
    card_width: int = 96
    card_padding: int = 16
    header_padding: int = 20
    section_gap: int = 12
    header_gap: int = 8
    kv_row_width: int = 98

    # ---- root surface spacing ----
    root_padding: int | list[int] = 2
    root_gap: int = 0
