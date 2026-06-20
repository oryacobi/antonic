from typing import Any, Mapping, Sequence

from ant.errors import InvalidAntQueryError

SUPPORTED_FIELD_OPERATORS = {"$eq", "$ne", "$in", "$nin", "$gt", "$gte", "$lt", "$lte", "$exists"}
SUPPORTED_LOGICAL_OPERATORS = {"$and", "$or"}
SUPPORTED_UPDATE_OPERATORS = {"$set", "$inc", "$unset"}


def validate_query(query: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(query)
    _validate_query_document(normalized)
    return normalized


def validate_update(update: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(update)
    if not normalized:
        raise InvalidAntQueryError("update must not be empty")

    for operator, changes in normalized.items():
        if operator not in SUPPORTED_UPDATE_OPERATORS:
            raise InvalidAntQueryError(f"unsupported update operator: {operator}")
        if not isinstance(changes, Mapping):
            raise InvalidAntQueryError(f"{operator} update value must be a mapping")
        for field in changes:
            _validate_field_name(field)
            if _field_root(field) == "id":
                raise InvalidAntQueryError("updates cannot change id")
    return normalized


def validate_projection(projection: Any) -> None:
    if projection is None:
        return
    if isinstance(projection, Mapping):
        for field in projection:
            _validate_field_name(field)
        return
    if isinstance(projection, Sequence) and not isinstance(projection, (str, bytes)):
        for field in projection:
            _validate_field_name(field)
        return
    raise InvalidAntQueryError("projection must be a mapping or sequence of field names")


def validate_sort(sort: Any) -> None:
    if sort is None:
        return
    if not isinstance(sort, Sequence) or isinstance(sort, (str, bytes)):
        raise InvalidAntQueryError("sort must be a sequence of (field, direction) tuples")
    for item in sort:
        if not isinstance(item, tuple) or len(item) != 2:
            raise InvalidAntQueryError("sort must contain (field, direction) tuples")
        _validate_field_name(item[0])


def _validate_query_document(query: Mapping[str, Any]) -> None:
    for key, value in query.items():
        if not isinstance(key, str) or not key:
            raise InvalidAntQueryError("query field names must be non-empty strings")

        if key.startswith("$"):
            if key not in SUPPORTED_LOGICAL_OPERATORS:
                raise InvalidAntQueryError(f"unsupported query operator: {key}")
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise InvalidAntQueryError(f"{key} requires a sequence of query documents")
            for item in value:
                if not isinstance(item, Mapping):
                    raise InvalidAntQueryError(f"{key} entries must be query documents")
                _validate_query_document(item)
            continue

        _validate_field_name(key)
        if isinstance(value, Mapping) and _contains_operator(value):
            for operator, operand in value.items():
                if not isinstance(operator, str) or not operator.startswith("$"):
                    raise InvalidAntQueryError("operator mappings cannot mix operators and field values")
                if operator not in SUPPORTED_FIELD_OPERATORS:
                    raise InvalidAntQueryError(f"unsupported query operator: {operator}")
                _validate_operator_operand(operator, operand)


def _contains_operator(value: Mapping[Any, Any]) -> bool:
    return any(isinstance(key, str) and key.startswith("$") for key in value)


def _validate_operator_operand(operator: str, operand: Any) -> None:
    if operator in {"$in", "$nin"} and (
        not isinstance(operand, Sequence) or isinstance(operand, (str, bytes))
    ):
        raise InvalidAntQueryError(f"{operator} requires a sequence")
    if operator == "$exists" and not isinstance(operand, bool):
        raise InvalidAntQueryError("$exists requires a boolean")


def _validate_field_name(field: Any) -> None:
    if not isinstance(field, str) or not field:
        raise InvalidAntQueryError("field names must be non-empty strings")
    if _field_root(field) == "_id":
        raise InvalidAntQueryError("use id instead of _id")
    if field.startswith("$"):
        raise InvalidAntQueryError(f"field names cannot start with $: {field}")


def _field_root(field: str) -> str:
    return field.split(".", 1)[0]
