import pytest

from ark_agentic.core.a2ui.contract_models import validate_event_payload


def test_begin_rendering_missing_required_fields_fails() -> None:
    payload = {
        "event": "beginRendering",
        "version": "1.0.0",
        "surfaceId": "s1",
    }

    with pytest.raises(ValueError, match="rootComponentId"):
        validate_event_payload(payload)


def test_begin_rendering_components_catalog_id_xor_rule() -> None:
    both_present = {
        "event": "beginRendering",
        "version": "1.0.0",
        "surfaceId": "s1",
        "rootComponentId": "root-1",
        "components": [],
        "catalogId": "catalog-1",
    }
    neither_present = {
        "event": "beginRendering",
        "version": "1.0.0",
        "surfaceId": "s1",
        "rootComponentId": "root-1",
    }

    with pytest.raises(ValueError, match="exactly one of components or catalogId"):
        validate_event_payload(both_present)

    with pytest.raises(ValueError, match="exactly one of components or catalogId"):
        validate_event_payload(neither_present)


def test_data_model_update_missing_data_fails() -> None:
    payload = {
        "event": "dataModelUpdate",
        "version": "1.0.0",
        "surfaceId": "s1",
    }

    with pytest.raises(ValueError, match="requires data"):
        validate_event_payload(payload)


def test_surface_update_components_none_fails() -> None:
    payload = {
        "event": "surfaceUpdate",
        "version": "1.0.0",
        "surfaceId": "s1",
        "components": None,
    }

    with pytest.raises(ValueError, match="requires components"):
        validate_event_payload(payload)


def test_surface_update_components_non_list_fails() -> None:
    payload = {
        "event": "surfaceUpdate",
        "version": "1.0.0",
        "surfaceId": "s1",
        "components": "not-a-list",
    }

    with pytest.raises(ValueError, match="components to be a list"):
        validate_event_payload(payload)


def test_data_model_update_data_none_fails() -> None:
    payload = {
        "event": "dataModelUpdate",
        "version": "1.0.0",
        "surfaceId": "s1",
        "data": None,
    }

    with pytest.raises(ValueError, match="requires data"):
        validate_event_payload(payload)


def test_data_model_update_data_non_dict_fails() -> None:
    payload = {
        "event": "dataModelUpdate",
        "version": "1.0.0",
        "surfaceId": "s1",
        "data": [],
    }

    with pytest.raises(ValueError, match="data to be a dict"):
        validate_event_payload(payload)


def test_delete_surface_rejects_unknown_top_level_field() -> None:
    payload = {
        "event": "deleteSurface",
        "version": "1.0.0",
        "surfaceId": "s1",
        "data": {},
    }

    with pytest.raises(ValueError, match="unsupported fields"):
        validate_event_payload(payload)


def test_valid_payloads_pass() -> None:
    begin_payload = {
        "version": "1.0.0",
        "surfaceId": "s1",
        "rootComponentId": "root-1",
        "components": [],
        "data": {"title": "ok"},
    }
    surface_update_payload = {
        "event": "surfaceUpdate",
        "version": "1.0.0",
        "surfaceId": "s1",
        "components": [],
    }
    data_model_payload = {
        "event": "dataModelUpdate",
        "version": "1.0.0",
        "surfaceId": "s1",
        "data": {"k": "v"},
    }
    delete_payload = {
        "event": "deleteSurface",
        "version": "1.0.0",
        "surfaceId": "s1",
    }

    validate_event_payload(begin_payload)
    validate_event_payload(surface_update_payload)
    validate_event_payload(data_model_payload)
    validate_event_payload(delete_payload)
