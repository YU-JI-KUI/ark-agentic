"""A2UI rendering capabilities (template + dynamic)"""

from .renderer import render_from_template
from .flattener import TreeFlattener, ALLOWED_TYPES
from .transforms import execute_transforms, TransformError
from .contract_models import validate_event_payload, SUPPORTED_EVENTS
from .validator import validate_payload
from .blocks import (
    _BLOCK_REGISTRY as BLOCK_REGISTRY,
    get_block_builder,
    get_block_types,
)
from .composer import BlockComposer

__all__ = [
    "render_from_template",
    "TreeFlattener",
    "ALLOWED_TYPES",
    "execute_transforms",
    "TransformError",
    "validate_event_payload",
    "SUPPORTED_EVENTS",
    "validate_payload",
    "BLOCK_REGISTRY",
    "get_block_builder",
    "get_block_types",
    "BlockComposer",
]
