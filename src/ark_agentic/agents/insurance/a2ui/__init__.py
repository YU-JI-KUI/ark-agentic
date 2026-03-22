"""保险业务 A2UI 模板、提取器、blocks 与 components"""

from .template_extractors import (
    policy_detail_extractor,
    withdraw_plan_extractor,
    withdraw_summary_extractor,
)
from .blocks import INSURANCE_BLOCKS
from .components import INSURANCE_COMPONENTS

__all__ = [
    "withdraw_summary_extractor",
    "withdraw_plan_extractor",
    "policy_detail_extractor",
    "INSURANCE_BLOCKS",
    "INSURANCE_COMPONENTS",
]
