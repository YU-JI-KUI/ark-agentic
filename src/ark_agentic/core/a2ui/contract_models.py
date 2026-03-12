"""Strict contract validation for A2UI event payloads."""

from __future__ import annotations

from typing import Any

SUPPORTED_EVENTS = {
    "beginRendering",
    "surfaceUpdate",
    "dataModelUpdate",
    "deleteSurface",
}

_ALLOWED_BY_EVENT: dict[str, set[str]] = {
    "beginRendering": {
        "event",
        "version",
        "surfaceId",
        "rootComponentId",
        "components",
        "catalogId",
        "style",
        "data",
        "hideVoteRecorder",
        "exposureData",
    },
    "surfaceUpdate": {
        "event",
        "version",
        "surfaceId",
        "components",
        "rootComponentId",
        "exposureData",
    },
    "dataModelUpdate": {
        "event",
        "version",
        "surfaceId",
        "data",
        "exposureData",
    },
    "deleteSurface": {
        "event",
        "version",
        "surfaceId",
    },
}


def _has_non_empty_value(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    return value is not None and value != ""


def _validate_begin_rendering(payload: dict[str, Any]) -> None:
    if not _has_non_empty_value(payload, "surfaceId"):
        raise ValueError("beginRendering requires surfaceId")
    if not _has_non_empty_value(payload, "rootComponentId"):
        raise ValueError("beginRendering requires rootComponentId")

    has_components = "components" in payload
    has_catalog_id = _has_non_empty_value(payload, "catalogId")

    if has_components == has_catalog_id:
        raise ValueError(
            "beginRendering requires exactly one of components or catalogId"
        )


def _validate_surface_update(payload: dict[str, Any]) -> None:
    if not _has_non_empty_value(payload, "surfaceId"):
        raise ValueError("surfaceUpdate requires surfaceId")
    if "components" not in payload:
        raise ValueError("surfaceUpdate requires components")
    if payload.get("components") is None:
        raise ValueError("surfaceUpdate requires components")
    if not isinstance(payload.get("components"), list):
        raise ValueError("surfaceUpdate requires components to be a list")


def _validate_data_model_update(payload: dict[str, Any]) -> None:
    if not _has_non_empty_value(payload, "surfaceId"):
        raise ValueError("dataModelUpdate requires surfaceId")
    if "data" not in payload:
        raise ValueError("dataModelUpdate requires data")
    if payload.get("data") is None:
        raise ValueError("dataModelUpdate requires data")
    if not isinstance(payload.get("data"), dict):
        raise ValueError("dataModelUpdate requires data to be a dict")


def _validate_delete_surface(payload: dict[str, Any]) -> None:
    if not _has_non_empty_value(payload, "surfaceId"):
        raise ValueError("deleteSurface requires surfaceId")


def validate_event_payload(payload: dict[str, Any]) -> None:
    """Validate top-level A2UI payload against strict event contracts.

    Raises:
        ValueError: if event type, top-level fields, or required fields are invalid.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    event = payload.get("event", "beginRendering")
    if event not in SUPPORTED_EVENTS:
        raise ValueError(f"Unsupported event: {event}")

    allowed_fields = _ALLOWED_BY_EVENT[event]
    illegal_fields = sorted(set(payload.keys()) - allowed_fields)
    if illegal_fields:
        raise ValueError(f"{event} contains unsupported fields: {illegal_fields}")

    if event == "beginRendering":
        _validate_begin_rendering(payload)
    elif event == "surfaceUpdate":
        _validate_surface_update(payload)
    elif event == "dataModelUpdate":
        _validate_data_model_update(payload)
    elif event == "deleteSurface":
        _validate_delete_surface(payload)
