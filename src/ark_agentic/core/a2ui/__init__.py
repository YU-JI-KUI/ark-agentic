"""A2UI rendering capabilities (preset + dynamic)"""

from .renderer import render_from_template
from .flattener import TreeFlattener, ALLOWED_TYPES
from .transforms import execute_transforms, TransformError
from .contract_models import validate_event_payload, SUPPORTED_EVENTS
from .validator import validate_payload
from .guard import BlockDataError, validate_full_payload, validate_data_coverage
from .blocks import (
    A2UIOutput,
    _BLOCK_REGISTRY as BLOCK_REGISTRY,
    get_block_builder,
    get_block_types,
)
from .composer import BlockComposer
from .lean_registry import PresetRegistry

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
    "A2UIOutput",
    "BlockDataError",
    "BLOCK_REGISTRY",
    "get_block_builder",
    "get_block_types",
    "BlockComposer",
    "PresetRegistry",
]
