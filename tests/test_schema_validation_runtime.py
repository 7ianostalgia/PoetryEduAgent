from __future__ import annotations

import pytest

from backend.utils import SchemaValidationError, validate_json_schema


SCHEMA = {
    "type": "object",
    "required": ["detected"],
    "additionalProperties": False,
    "properties": {
        "detected": {
            "type": "object",
            "required": ["ancient_bed"],
            "additionalProperties": False,
            "properties": {"ancient_bed": {"type": "boolean"}},
        }
    },
}


def test_runtime_schema_validation_accepts_exact_shape():
    validate_json_schema({"detected": {"ancient_bed": False}}, SCHEMA)


def test_runtime_schema_validation_rejects_misspelled_field():
    with pytest.raises(SchemaValidationError, match="ancient_bed"):
        validate_json_schema({"detected": {"ancence_bed": False}}, SCHEMA)
