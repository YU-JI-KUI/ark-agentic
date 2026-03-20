"""A2UI rendering capabilities (preset + dynamic)"""

from .renderer import render_from_template
from .flattener import TreeFlattener, ALLOWED_TYPES
from .transforms import execute_transforms, TransformError
from .contract_models import validate_event_payload, SUPPORTED_EVENTS
from .validator import validate_payload
from .guard import BlockDataError, validate_full_payload, validate_data_coverage
from .blocks import (
    _BLOCK_REGISTRY as BLOCK_REGISTRY,
    get_block_builder,
    get_block_types,
)
from .composer import BlockComposer
from .lean_registry import build_lean_payload, register_lean_card, list_lean_types

__all__ = [
    "render_from_template",
    "TreeFlattener",
    "ALLOWED_TYPES",
    "execute_transforms",
    "TransformError",
    "validate_event_payload",
    "SUPPORTED_EVENTS",
    "validate_payload",
    "validate_full_payload",
    "validate_data_coverage",
    "BlockDataError",
    "BLOCK_REGISTRY",
    "get_block_builder",
    "get_block_types",
    "BlockComposer",
    "build_lean_payload",
    "register_lean_card",
    "list_lean_types",
]
