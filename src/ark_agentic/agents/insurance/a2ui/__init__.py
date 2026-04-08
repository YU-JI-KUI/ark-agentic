"""保险业务 A2UI 模板、提取器、blocks 与 components"""

from .template_extractors import (
    policy_detail_extractor,
    withdraw_plan_extractor,
    withdraw_summary_extractor,
)
from .blocks import INSURANCE_BLOCKS, create_insurance_blocks
from .components import INSURANCE_COMPONENTS, create_insurance_components

__all__ = [
    "withdraw_summary_extractor",
    "withdraw_plan_extractor",
    "policy_detail_extractor",
    "INSURANCE_BLOCKS",
    "INSURANCE_COMPONENTS",
    "create_insurance_blocks",
    "create_insurance_components",
]
