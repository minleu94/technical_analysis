"""Read-only SQLite backup inventory with an explicit, conservative retention recommendation."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_module.config import TWStockConfig


def _quick_check(path: Path) -> str:
    try:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            return str(connection.execute("PRAGMA quick_check").fetchone()[0])
    except sqlite3.Error as exc:
        return f"error:{type(exc).__name__}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Run read-only SQLite quick_check for every DB snapshot.")
    parser.add_argument("--sha256", action="store_true", help="Compute a content hash for every DB snapshot.")
    args = parser.parse_args()
    config = TWStockConfig()
    roots = (config.sqlite_dir, config.backup_dir)
    snapshots_by_path: dict[str, dict[str, Any]] = {}
    for root in roots:
        for path in root.rglob("*.db"):
            resolved_path = path.resolve()
            stat = path.stat()
            snapshots_by_path[str(resolved_path)] = {
                "path": str(resolved_path),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "quick_check": _quick_check(path) if args.verify else "not_run",
                "sha256": _sha256(path) if args.sha256 else "not_run",
            }
    snapshots = list(snapshots_by_path.values())
    snapshots.sort(key=lambda item: item["modified_at"], reverse=True)
    full = [item for item in snapshots if item["size_bytes"] >= 1024**3]
    keep_paths = {str(config.db_file.resolve()), *[item["path"] for item in full if item["path"] != str(config.db_file.resolve())][:3]}
    result: dict[str, Any] = {
        "mode": "read_only_audit",
        "policy": "retain active DB plus three newest verified full snapshots; never delete automatically",
        "snapshot_count": len(snapshots),
        "full_snapshot_count": len(full),
        "total_bytes": sum(item["size_bytes"] for item in snapshots),
        "snapshots": snapshots,
        "recommended_keep": sorted(keep_paths),
        "manual_review_required_before_deletion": [item["path"] for item in full if item["path"] not in keep_paths],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
