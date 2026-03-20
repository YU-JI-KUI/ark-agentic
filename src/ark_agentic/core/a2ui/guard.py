"""
Unified A2UI validation entry point.

Composes event-level (contract_models) and component-level (validator)
checks into a single call.  Also provides data-coverage validation
to catch binding paths that reference missing data keys.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .contract_models import validate_event_payload
from .validator import validate_payload, ValidationResult

logger = logging.getLogger(__name__)


class BlockDataError(Exception):
    """Raised when a block builder receives data missing required keys."""

    def __init__(self, block_type: str, missing_keys: list[str]):
        self.block_type = block_type
        self.missing_keys = missing_keys
        super().__init__(
            f"Block '{block_type}' missing required data keys: {', '.join(missing_keys)}"
        )


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


def validate_data_coverage(payload: dict[str, Any]) -> list[str]:
    """Check that all `path` bindings in components reference keys present in `payload['data']`.

    Only checks bindings that use `path` (not `literalString`).
    Returns a list of warning strings for missing paths.
    """
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return []

    data_keys = set(data.keys())
    warnings: list[str] = []
    components = payload.get("components", [])

    for comp_entry in components:
        if not isinstance(comp_entry, dict):
            continue
        comp_id = comp_entry.get("id", "?")
        component = comp_entry.get("component", {})
        if not isinstance(component, dict):
            continue

        for _comp_type, props in component.items():
            if not isinstance(props, dict):
                continue
            for field_name, field_value in props.items():
                if not isinstance(field_value, dict):
                    continue
                path_val = field_value.get("path")
                if path_val is None:
                    continue
                if field_value.get("literalString") is not None:
                    continue
                if isinstance(path_val, str) and path_val and path_val not in data_keys:
                    # item.* paths are resolved by List components at render time
                    if not path_val.startswith("item."):
                        warnings.append(
                            f"[DATA_COVERAGE] Component '{comp_id}' field '{field_name}' "
                            f"references path '{path_val}' not found in payload.data"
                        )

    return warnings


def validate_full_payload(
    payload: dict[str, Any],
    *,
    strict: bool = True,
) -> GuardResult:
    """Run all validation layers on a complete A2UI payload.

    Args:
        payload: The full A2UI event payload.
        strict: If True, event contract violations are errors; otherwise warnings.

    Returns:
        GuardResult with combined errors and warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # L1: Event contract
    try:
        validate_event_payload(payload)
    except ValueError as e:
        msg = f"[EVENT_CONTRACT] {e}"
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)

    # L2: Component/binding validation
    vr: ValidationResult = validate_payload(payload)
    if not vr.ok:
        for code, err in zip(vr.error_codes, vr.errors):
            errors.append(f"[{code}] {err}")

    # L3: Data coverage
    coverage_warnings = validate_data_coverage(payload)
    warnings.extend(coverage_warnings)

    return GuardResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
    )
