"""Guards that keep Terra generation artifacts outside formal data paths."""

from __future__ import annotations

from pathlib import Path
import re


_SAFE_RUN_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,80}\Z")


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
    if (
        candidate == protected_data_root
        or protected_data_root in candidate.parents
    ):
        raise ValueError("development_output_root must be outside DATA_ROOT")
    if candidate == protected_formal_db:
        raise ValueError("development_output_root must not be the formal database")
    if candidate.exists() and not candidate.is_dir():
        raise ValueError("development_output_root must be a directory")
    return candidate


def resolve_development_output_dir(
    root: Path,
    run_id: str,
    *,
    data_root: Path,
    formal_db: Path,
) -> Path:
    """Resolve one run directory while preserving the TEMP-root boundary."""
    safe_root = validate_development_output_root(
        root,
        data_root=data_root,
        formal_db=formal_db,
    )
    if not isinstance(run_id, str) or _SAFE_RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError(
            "run_id must be 3-81 lowercase letters, digits, hyphens, or underscores"
        )
    target = (safe_root / run_id).resolve()
    try:
        target.relative_to(safe_root)
    except ValueError as exc:
        raise ValueError("run_id must resolve inside development_output_root") from exc
    return target
