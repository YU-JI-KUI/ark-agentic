"""Payload-level validation for A2UI components and bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_COMPONENT_TYPES = frozenset(
    {
        "Row",
        "Column",
        "Card",
        "List",
        "Table",
        "Popup",
        "Text",
        "RichText",
        "Image",
        "Icon",
        "Tag",
        "Circle",
        "Divider",
        "Line",
        "Button",
    }
)

_BINDING_FIELDS_BY_COMPONENT: dict[str, set[str]] = {
    "Text": {"text"},
    "RichText": {"text"},
    "Image": {"url"},
    "Icon": {"name"},
    "Tag": {"text"},
    "Button": {"text"},
    "List": {"dataSource"},
}

_COMMON_BINDING_FIELDS = {"hide"}


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]
    error_codes: list[str]


def _is_non_empty(value: Any) -> bool:
    return value is not None and value != ""


def _get_binding_presence(binding: dict[str, Any]) -> tuple[bool, bool]:
    has_path = _is_non_empty(binding.get("path"))
    has_literal = _is_non_empty(binding.get("literalString"))
    return has_path, has_literal


def _extract_component_references(component_props: dict[str, Any]) -> list[str]:
    refs: list[str] = []

    children = component_props.get("children")
    if isinstance(children, dict):
        explicit_list = children.get("explicitList")
        if isinstance(explicit_list, list):
            refs.extend([ref for ref in explicit_list if isinstance(ref, str) and ref])
    elif isinstance(children, list):
        refs.extend([ref for ref in children if isinstance(ref, str) and ref])

    for single_key in ("child", "emptyChild"):
        single_ref = component_props.get(single_key)
        if isinstance(single_ref, str) and single_ref:
            refs.append(single_ref)

    return refs


def _add_error(
    errors: list[str],
    error_codes: list[str],
    code: str,
    message: str,
) -> None:
    errors.append(message)
    if code not in error_codes:
        error_codes.append(code)


def validate_payload(payload: Any) -> ValidationResult:
    """Validate A2UI payload at component/binding layer.

    This validator is intentionally payload-focused and can be composed with
    top-level event validation from contract_models.validate_event_payload.
    """
    errors: list[str] = []
    error_codes: list[str] = []

    if not isinstance(payload, dict):
        return ValidationResult(
            ok=False,
            errors=["payload must be a dict"],
            error_codes=["A2UI_PAYLOAD_INVALID"],
        )

    raw_components = payload.get("components", [])
    if not isinstance(raw_components, list):
        return ValidationResult(
            ok=False,
            errors=["components must be a list"],
            error_codes=["A2UI_COMPONENTS_INVALID"],
        )

    components = raw_components

    component_ids: list[str] = []
    component_id_set: set[str] = set()

    for entry in components:
        if not isinstance(entry, dict):
            continue
        comp_id = entry.get("id")
        if isinstance(comp_id, str) and comp_id:
            component_ids.append(comp_id)

    for comp_id in component_ids:
        if comp_id in component_id_set:
            _add_error(
                errors,
                error_codes,
                "A2UI_COMPONENT_ID_DUPLICATE",
                f"Duplicate component id: {comp_id}",
            )
        component_id_set.add(comp_id)

    for idx, entry in enumerate(components):
        if not isinstance(entry, dict):
            _add_error(
                errors,
                error_codes,
                "A2UI_COMPONENT_ENTRY_INVALID",
                f"components[{idx}] must be a dict",
            )
            continue

        comp_id = entry.get("id") if isinstance(entry.get("id"), str) else f"<component@{idx}>"
        component_obj = entry.get("component")
        if not isinstance(component_obj, dict) or len(component_obj) != 1:
            _add_error(
                errors,
                error_codes,
                "A2UI_COMPONENT_OBJECT_INVALID",
                (
                    f"Component '{comp_id}' must have a component object that is a dict with exactly one key"
                ),
            )
            continue

        comp_type, comp_props = next(iter(component_obj.items()))

        if comp_type not in SUPPORTED_COMPONENT_TYPES:
            _add_error(
                errors,
                error_codes,
                "A2UI_COMPONENT_TYPE_INVALID",
                f"Unsupported component type: {comp_type} (component index: {idx})",
            )
            continue

        if not isinstance(comp_props, dict):
            _add_error(
                errors,
                error_codes,
                "A2UI_COMPONENT_PROPS_INVALID",
                f"Component '{comp_id}' props for type '{comp_type}' must be a dict",
            )
            continue

        # Validate references: children / child / emptyChild
        for ref_id in _extract_component_references(comp_props):
            if ref_id not in component_id_set:
                _add_error(
                    errors,
                    error_codes,
                    "A2UI_COMPONENT_REF_MISSING",
                    f"Component '{comp_id}' references missing component id: {ref_id}",
                )

        # Validate binding XOR for known binding fields.
        binding_fields = set(_BINDING_FIELDS_BY_COMPONENT.get(comp_type, set()))
        binding_fields.update(_COMMON_BINDING_FIELDS)
        for field_name in binding_fields:
            if field_name not in comp_props:
                continue
            binding_val = comp_props.get(field_name)
            if not isinstance(binding_val, dict):
                _add_error(
                    errors,
                    error_codes,
                    "A2UI_BINDING_INVALID",
                    f"Component '{comp_id}' field '{field_name}' binding must be a dict",
                )
                continue

            has_path, has_literal = _get_binding_presence(binding_val)
            if has_path == has_literal:
                _add_error(
                    errors,
                    error_codes,
                    "A2UI_BINDING_XOR",
                    (
                        f"Component '{comp_id}' field '{field_name}' must contain exactly one of "
                        "'path' or 'literalString'"
                    ),
                )

    root_component_id = payload.get("rootComponentId")
    if _is_non_empty(root_component_id) and isinstance(root_component_id, str):
        if root_component_id not in component_id_set:
            _add_error(
                errors,
                error_codes,
                "A2UI_ROOT_REF_MISSING",
                f"rootComponentId '{root_component_id}' is not found in components",
            )

    return ValidationResult(ok=not errors, errors=errors, error_codes=error_codes)

