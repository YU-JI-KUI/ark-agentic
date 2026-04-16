"""保险业务 A2UI 模板、提取器、blocks 与 components"""

from .blocks import INSURANCE_BLOCKS, create_insurance_blocks
from .components import COMPONENT_SCHEMAS, INSURANCE_COMPONENTS, create_insurance_components

__all__ = [
    "COMPONENT_SCHEMAS",
    "INSURANCE_BLOCKS",
    "INSURANCE_COMPONENTS",
    "create_insurance_blocks",
    "create_insurance_components",
]
