"""Narrow JSON-ish values that the generator stores on rows."""

from __future__ import annotations


def as_str(value: object) -> str:
    if isinstance(value, str):
        return value
    raise TypeError(f"expected str, got {type(value).__name__}")


def as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"expected int, got {type(value).__name__}")
    return value


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    raise TypeError(f"expected bool, got {type(value).__name__}")


def as_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"expected dict, got {type(value).__name__}")
    return {as_str(key): item for key, item in value.items()}


def as_str_list(value: object) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise TypeError(f"expected list[str], got {type(value).__name__}")
