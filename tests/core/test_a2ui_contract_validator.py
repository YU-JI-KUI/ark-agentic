import copy

from ark_agentic.core.a2ui.validator import validate_payload


def _valid_payload() -> dict:
    return {
        "event": "beginRendering",
        "version": "1.0.0",
        "surfaceId": "surface-1",
        "rootComponentId": "root-1",
        "components": [
            {
                "id": "root-1",
                "component": {
                    "Column": {
                        "children": {
                            "explicitList": ["text-1", "list-1"],
                        }
                    }
                },
            },
            {
                "id": "text-1",
                "component": {
                    "Text": {
                        "text": {"path": "title"},
                    }
                },
            },
            {
                "id": "list-1",
                "component": {
                    "List": {
                        "child": "list-item-1",
                        "emptyChild": "empty-1",
                        "dataSource": {"path": "items"},
                    }
                },
            },
            {
                "id": "list-item-1",
                "component": {
                    "Text": {
                        "text": {"literalString": "item"},
                    }
                },
            },
            {
                "id": "empty-1",
                "component": {
                    "Text": {
                        "text": {"literalString": "empty"},
                    }
                },
            },
        ],
        "data": {
            "title": "hello",
            "items": [1, 2],
        },
    }


def test_invalid_component_type_fails() -> None:
    payload = _valid_payload()
    payload["components"][1]["component"] = {"UnknownType": {"text": {"path": "title"}}}

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_COMPONENT_TYPE_INVALID" in result.error_codes


def test_duplicate_component_id_fails() -> None:
    payload = _valid_payload()
    payload["components"][1]["id"] = "root-1"

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_COMPONENT_ID_DUPLICATE" in result.error_codes


def test_root_component_id_missing_reference_fails() -> None:
    payload = _valid_payload()
    payload["rootComponentId"] = "not-exist"

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_ROOT_REF_MISSING" in result.error_codes


def test_list_child_and_empty_child_missing_reference_fail() -> None:
    payload = _valid_payload()
    payload["components"] = [
        comp
        for comp in payload["components"]
        if comp["id"] not in {"list-item-1", "empty-1"}
    ]

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_COMPONENT_REF_MISSING" in result.error_codes


def test_text_binding_with_path_and_literal_string_fails() -> None:
    payload = _valid_payload()
    payload["components"][1]["component"]["Text"]["text"] = {
        "path": "title",
        "literalString": "hello",
    }

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_BINDING_XOR" in result.error_codes


def test_text_binding_with_neither_path_nor_literal_string_fails() -> None:
    payload = _valid_payload()
    payload["components"][1]["component"]["Text"]["text"] = {}

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_BINDING_XOR" in result.error_codes


def test_payload_must_be_dict_fails_with_payload_invalid_code() -> None:
    result = validate_payload("not-a-dict")

    assert result.ok is False
    assert "A2UI_PAYLOAD_INVALID" in result.error_codes


def test_components_must_be_list_fails() -> None:
    payload = _valid_payload()
    payload["components"] = {"id": "root-1"}

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_COMPONENTS_INVALID" in result.error_codes


def test_components_entry_must_be_dict_fails() -> None:
    payload = _valid_payload()
    payload["components"][0] = "not-a-dict"

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_COMPONENT_ENTRY_INVALID" in result.error_codes


def test_component_object_must_be_single_key_dict_fails() -> None:
    payload = _valid_payload()
    payload["components"][0]["component"] = {
        "Column": {"children": {"explicitList": ["text-1"]}},
        "Text": {"text": {"literalString": "oops"}},
    }

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_COMPONENT_OBJECT_INVALID" in result.error_codes


def test_component_props_must_be_dict_fails() -> None:
    payload = _valid_payload()
    payload["components"][1]["component"] = {"Text": "not-a-dict"}

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_COMPONENT_PROPS_INVALID" in result.error_codes


def test_binding_field_must_be_dict_fails() -> None:
    payload = _valid_payload()
    payload["components"][1]["component"]["Text"]["text"] = "not-a-dict"

    result = validate_payload(payload)

    assert result.ok is False
    assert "A2UI_BINDING_INVALID" in result.error_codes


def test_valid_payload_passes() -> None:
    payload = _valid_payload()

    result = validate_payload(copy.deepcopy(payload))

    assert result.ok is True
    assert result.errors == []
    assert result.error_codes == []
