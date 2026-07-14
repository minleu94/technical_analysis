"""Guards that keep Terra generation artifacts outside formal data paths."""

from __future__ import annotations

from pathlib import Path


def validate_development_output_root(
    root: Path,
    *,
    data_root: Path,
    formal_db: Path,
) -> Path:
    """Return a safe external root without creating it."""
    candidate = root.expanduser().resolve()
    protected_data_root = data_root.expanduser().resolve()
    protected_formal_db = formal_db.expanduser().resolve()
    protected_database_root = protected_formal_db.parent.parent
    if (
        candidate == protected_data_root
        or protected_data_root in candidate.parents
        or candidate == protected_database_root
        or protected_database_root in candidate.parents
    ):
        raise ValueError("development_output_root must be outside DATA_ROOT")
    if candidate == protected_formal_db:
        raise ValueError("development_output_root must not be the formal database")
    if candidate.exists() and not candidate.is_dir():
        raise ValueError("development_output_root must be a directory")
    return candidate
