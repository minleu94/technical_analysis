from __future__ import annotations


def _normalize_warnings(warnings: tuple[str, ...] | list[str] | set[str] | None) -> tuple[str, ...]:
    if warnings is None:
        return ()
    normalized: list[str] = []
    for item in warnings:
        normalized.append(str(item))
    return tuple(normalized)
