from __future__ import annotations

from typing import Any, Mapping


class SchemaValidationError(ValueError):
    """Raised when structured model output violates its JSON Schema."""


TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def validate_json_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str = "$",
) -> None:
    expected_type = schema.get("type")
    if expected_type:
        python_type = TYPE_MAP.get(str(expected_type))
        if python_type is None:
            raise SchemaValidationError(f"{path}: 不支持的 schema type {expected_type}")
        if expected_type == "integer" and isinstance(value, bool):
            raise SchemaValidationError(f"{path}: 期望 integer，实际为 boolean")
        if expected_type == "number" and isinstance(value, bool):
            raise SchemaValidationError(f"{path}: 期望 number，实际为 boolean")
        if not isinstance(value, python_type):
            raise SchemaValidationError(
                f"{path}: 期望 {expected_type}，实际为 {type(value).__name__}"
            )

    if isinstance(value, dict):
        required = schema.get("required") or []
        missing = [key for key in required if key not in value]
        if missing:
            raise SchemaValidationError(f"{path}: 缺少必填字段 {missing}")
        properties = schema.get("properties") or {}
        for key, child_schema in properties.items():
            if key in value:
                validate_json_schema(
                    value[key],
                    child_schema,
                    path=f"{path}.{key}",
                )
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise SchemaValidationError(f"{path}: 存在未声明字段 {extras}")

    if isinstance(value, list) and "items" in schema:
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise SchemaValidationError(
                f"{path}: 数组长度小于 {schema['minItems']}"
            )
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise SchemaValidationError(
                f"{path}: 数组长度大于 {schema['maxItems']}"
            )
        if schema.get("uniqueItems"):
            normalized = [repr(item) for item in value]
            if len(normalized) != len(set(normalized)):
                raise SchemaValidationError(f"{path}: 数组元素必须唯一")
        for index, item in enumerate(value):
            validate_json_schema(item, schema["items"], path=f"{path}[{index}]")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{path}: 值 {value!r} 不在允许范围内")
