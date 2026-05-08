"""Post-hoc citation annotation — final-answer-only hook.

The citation hook fires in RunnerCallbacks.before_loop_end (after the ReAct
loop, on the final non-tool-call response).  Tool outputs are filtered by
AgentTool.data_source=True before matching.

Public API:
  CiteSpan             — inline span descriptor (source_id, tool_name, start, end, matched_text)
  CiteEntry            — summary entry for the citation_list event
  CiteAnnotator        — Protocol for annotation strategies
  SpanLocator          — Protocol for per-claim-type span finders (OCP extension point)
  DefaultCiteAnnotator — default strategy (reuses grounding claim extraction)
  NumberSpanLocator    — locator that aligns 千分位 显示 against grounding 面值
  SubstringSpanLocator — verbatim ``str.find`` locator for ENTITY/TIME claims
  create_cite_annotation_hook — factory → BeforeLoopEndCallback
"""

from .annotator import DefaultCiteAnnotator, NumberSpanLocator, SubstringSpanLocator
from .hook import create_cite_annotation_hook
from .protocol import CiteAnnotator, SpanLocator
from .types import CiteEntry, CiteSpan

__all__ = [
    "CiteAnnotator",
    "CiteEntry",
    "CiteSpan",
    "DefaultCiteAnnotator",
    "NumberSpanLocator",
    "SpanLocator",
    "SubstringSpanLocator",
    "create_cite_annotation_hook",
]
