from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil


DEFAULT_KEEP_DATES = 5


def create_retained_backup(
    source_file: Path,
    backup_dir: Path,
    *,
    label: str | None = None,
    timestamp: str | None = None,
    keep_dates: int = DEFAULT_KEEP_DATES,
) -> Path | None:
    source_file = Path(source_file)
    if not source_file.exists():
        return None

    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = _backup_prefix(source_file, label)
    backup_file = backup_dir / f"{prefix}_{timestamp}{source_file.suffix}"
    shutil.copy2(source_file, backup_file)
    cleanup_backup_series(backup_dir, prefix=prefix, keep_dates=keep_dates)
    return backup_file


def cleanup_backup_series(backup_dir: Path, *, prefix: str, keep_dates: int = DEFAULT_KEEP_DATES) -> None:
    if keep_dates < 1:
        keep_dates = 1

    backups_by_date: dict[str, list[Path]] = {}
    for backup_file in Path(backup_dir).glob(f"{prefix}_*"):
        if not backup_file.is_file():
            continue
        date_key, _ = _backup_sort_key(backup_file, prefix)
        if not date_key:
            continue
        backups_by_date.setdefault(date_key, []).append(backup_file)

    for backup_files in backups_by_date.values():
        sorted_files = sorted(
            backup_files,
            key=lambda path: (_backup_sort_key(path, prefix), path.stat().st_mtime),
            reverse=True,
        )
        for backup_file in sorted_files[1:]:
            _unlink_if_exists(backup_file)

    keep_date_keys = sorted(backups_by_date.keys(), reverse=True)[:keep_dates]
    for date_key, backup_files in backups_by_date.items():
        if date_key in keep_date_keys:
            continue
        for backup_file in backup_files:
            _unlink_if_exists(backup_file)


def _backup_prefix(source_file: Path, label: str | None) -> str:
    if not label:
        return source_file.stem
    return f"{source_file.stem}_{label}"


def _backup_sort_key(backup_file: Path, prefix: str) -> tuple[str, str]:
    pattern = rf"^{re.escape(prefix)}_(?P<date>\d{{8}})(?:_(?P<time>\d{{6}}))?$"
    match = re.match(pattern, backup_file.stem)
    if not match:
        return ("", "")
    return (match.group("date"), match.group("time") or "")


def _unlink_if_exists(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        return
