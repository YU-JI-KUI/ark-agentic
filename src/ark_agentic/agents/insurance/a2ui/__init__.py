"""保险业务 A2UI 模板与提取器"""

from .extractors import withdraw_summary_extractor, withdraw_plan_extractor, policy_detail_extractor

__all__ = ["withdraw_summary_extractor", "withdraw_plan_extractor", "policy_detail_extractor"]
