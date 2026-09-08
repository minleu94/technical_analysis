"""Shared column-name resolution primitive for analysis modules.

The domain-specific ``*_column_support`` modules keep their historical
resolver names as compatibility facades.  The lookup order is intentionally
centralized here so pattern, technical, and ML analysis cannot drift apart.
"""

from collections.abc import Collection, Mapping


def resolve_column(
    columns: Collection[str],
    reverse_mapping: Mapping[str, str],
    eng_name: str,
) -> str | None:
    """Resolve a canonical English column to the preferred available name."""
    chinese_name = reverse_mapping.get(eng_name)
    if chinese_name in columns:
        return chinese_name
    if eng_name in columns:
        return eng_name
    return None


__all__ = ["resolve_column"]
