"""保险业务 A2UI 模板、提取器、blocks 与 components"""

from .blocks import INSURANCE_BLOCKS, create_insurance_blocks
from .components import (
    BLOCK_DATA_SCHEMAS,
    CHANNEL_TYPES,
    COMPONENT_SCHEMAS,
    INSURANCE_COMPONENTS,
    SECTION_TYPES,
    create_insurance_components,
)

__all__ = [
    "BLOCK_DATA_SCHEMAS",
    "CHANNEL_TYPES",
    "COMPONENT_SCHEMAS",
    "INSURANCE_BLOCKS",
    "INSURANCE_COMPONENTS",
    "SECTION_TYPES",
    "create_insurance_blocks",
    "create_insurance_components",
]
