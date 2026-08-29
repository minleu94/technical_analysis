"""唯讀盤點 ML Direct/OOC 儲存容量與人工 retention 候選。

此工具只讀取明確指定的根目錄與檔案 metadata，輸出容量／大小排序與
可逆處置建議；不刪除、不搬移、不修改 lock、pointer、SQLite 或任何
正式資料。它適合在 Direct/OOC filesystem headroom preflight 阻塞後，
先整理給 owner 審核的候選清單。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.console_encoding import configure_utf8_console


SCHEMA_VERSION = "ml-storage-retention-inventory.v1"
DEFAULT_MINIMUM_FREE_SPACE_BYTES = 20 * 1024**3
DEFAULT_MAX_DEPTH = 6
DEFAULT_MAX_FILES = 250_000
DEFAULT_MIN_CANDIDATE_SIZE_BYTES = 512 * 1024**2
DEFAULT_TOP_N = 25

_REVIEW_MARKERS = {
    "backup",
    "backups",
    "checkpoint",
    "checkpoints",
    "copy",
    "replay",
    "snapshot",
    "restore",
    "old",
    "archive",
}
_ML_MARKERS = {
    "direct",
    "ooc",
    "release_v4",
    "ml_pit_year_shards",
    "training",
    "numeric",
    "run",
    "runs",
}


class _ScanLimitReached(RuntimeError):
    """Internal signal used to stop metadata traversal at a bounded limit."""


def _resolve_roots(values: Iterable[str | Path]) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[str] = set()
    for value in values:
        path = Path(value).expanduser().resolve()
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        roots.append(path)
    if not roots:
        raise ValueError("at least one --root is required")
    return tuple(roots)


def _path_markers(path: Path) -> set[str]:
    return {part.casefold() for part in path.parts}


def _candidate_kind(path: Path) -> str | None:
    markers = _path_markers(path)
    tokens = {
        token
        for part in markers
        for token in part.replace("-", "_").split("_")
        if token
    }
    if tokens & _REVIEW_MARKERS:
        return "retention_review_candidate"
    if tokens & _ML_MARKERS or markers & _ML_MARKERS:
        return "ml_run_review_candidate"
    return None


def _iso_mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(
            timespec="seconds"
        )
    except OSError:
        return None


def _manifest_metadata(path: Path) -> dict[str, Any]:
    """Read a small, direct-child manifest when one exists; never recurse or write."""

    if not path.is_dir():
        return {}
    for name in ("manifest.json", "run_manifest.json", "status.json"):
        manifest_path = path / name
        try:
            if not manifest_path.is_file() or manifest_path.stat().st_size > 16 * 1024**2:
                continue
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        return {
            "manifest_path": str(manifest_path.resolve()),
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "run_id": payload.get("run_id"),
        }
    return {}


def _scan_root(
    root: Path,
    *,
    max_depth: int,
    max_files: int,
    min_candidate_size_bytes: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return bounded directory/file metadata without mutating the tree."""

    if max_depth < 0:
        raise ValueError("max-depth must be non-negative")
    if max_files <= 0:
        raise ValueError("max-files must be positive")
    if min_candidate_size_bytes < 0:
        raise ValueError("min-candidate-size-bytes must be non-negative")

    errors: list[str] = []
    candidates: list[dict[str, Any]] = []
    scanned_files = 0
    scanned_directories = 0
    truncated = False

    def visit(path: Path, depth: int) -> tuple[int, int]:
        nonlocal scanned_files, scanned_directories, truncated
        scanned_directories += 1
        total_bytes = 0
        file_count = 0
        try:
            entries = path.iterdir()
        except (OSError, ValueError) as exc:
            errors.append(f"{path}:{type(exc).__name__}")
            return 0, 0

        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    child_bytes, child_files = visit(entry, depth + 1)
                    total_bytes += child_bytes
                    file_count += child_files
                    continue
                if not entry.is_file():
                    continue
                if scanned_files >= max_files:
                    truncated = True
                    raise _ScanLimitReached
                size_bytes = int(entry.stat().st_size)
                scanned_files += 1
                total_bytes += size_bytes
                file_count += 1
                if size_bytes >= min_candidate_size_bytes:
                    kind = _candidate_kind(entry)
                    if kind is not None:
                        candidates.append(
                            {
                                "path": str(entry.resolve()),
                                "kind": kind,
                                "size_bytes": size_bytes,
                                "modified_at": _iso_mtime(entry),
                                "manual_review_required": True,
                                "reversible_action": (
                                    "owner_confirm_then_move_to_external_archive_or_delete"
                                ),
                                "automatic_delete_allowed": False,
                            }
                        )
            except _ScanLimitReached:
                raise
            except (OSError, ValueError) as exc:
                errors.append(f"{entry}:{type(exc).__name__}")

        if depth <= max_depth:
            kind = _candidate_kind(path)
            if kind is not None and total_bytes >= min_candidate_size_bytes:
                candidate = {
                        "path": str(path.resolve()),
                        "kind": kind,
                        "size_bytes": total_bytes,
                        "modified_at": _iso_mtime(path),
                        "file_count": file_count,
                        "manual_review_required": True,
                        "reversible_action": (
                            "owner_confirm_then_move_to_external_archive_or_delete"
                        ),
                        "automatic_delete_allowed": False,
                    }
                candidate.update(_manifest_metadata(path))
                candidates.append(candidate)
        return total_bytes, file_count

    try:
        root_bytes, root_file_count = visit(root, 0)
    except _ScanLimitReached:
        truncated = True
        root_bytes = 0
        root_file_count = scanned_files

    try:
        usage = shutil.disk_usage(root)
        disk = {
            "probe_path": str(root),
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
        }
    except OSError as exc:
        disk = {
            "probe_path": str(root),
            "error": f"{type(exc).__name__}: {exc}",
        }

    summary = {
        "root": str(root),
        "exists": root.exists(),
        "is_directory": root.is_dir(),
        "scanned_bytes": int(root_bytes),
        "scanned_file_count": int(root_file_count),
        "scanned_directory_count": int(scanned_directories),
        "scan_truncated": bool(truncated),
        "errors": sorted(set(errors)),
        "disk": disk,
    }
    return summary, candidates


def inspect_storage_retention(
    roots: Iterable[str | Path],
    *,
    minimum_free_space_bytes: int = DEFAULT_MINIMUM_FREE_SPACE_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_files: int = DEFAULT_MAX_FILES,
    min_candidate_size_bytes: int = DEFAULT_MIN_CANDIDATE_SIZE_BYTES,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    """Build a query-only capacity and retention projection."""

    if minimum_free_space_bytes <= 0:
        raise ValueError("minimum-free-space-bytes must be positive")
    if top_n <= 0:
        raise ValueError("top-n must be positive")

    resolved_roots = _resolve_roots(roots)
    root_reports: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for root in resolved_roots:
        if not root.exists() or not root.is_dir():
            root_reports.append(
                {
                    "root": str(root),
                    "exists": root.exists(),
                    "is_directory": root.is_dir(),
                    "scanned_bytes": 0,
                    "scanned_file_count": 0,
                    "scanned_directory_count": 0,
                    "scan_truncated": False,
                    "errors": ["root_missing_or_not_directory"],
                    "disk": {"probe_path": str(root)},
                }
            )
            continue
        report, root_candidates = _scan_root(
            root,
            max_depth=max_depth,
            max_files=max_files,
            min_candidate_size_bytes=min_candidate_size_bytes,
        )
        root_reports.append(report)
        candidates.extend(root_candidates)

    # A directory and its child can both be candidates. Keep both for auditability,
    # but deduplicate identical paths and rank by size.
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        unique[candidate["path"]] = candidate
    ranked_candidates = sorted(
        unique.values(),
        key=lambda item: (-int(item["size_bytes"]), str(item["path"]).casefold()),
    )[:top_n]

    disk_reports = [
        report["disk"]
        for report in root_reports
        if isinstance(report.get("disk"), dict)
        and isinstance(report["disk"].get("free_bytes"), int)
    ]
    free_bytes = min(
        (int(item["free_bytes"]) for item in disk_reports),
        default=None,
    )
    if free_bytes is None:
        status = "inspection_partial"
    elif free_bytes < minimum_free_space_bytes:
        status = "capacity_blocked"
    else:
        status = "headroom_ok"

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "roots": [str(path) for path in resolved_roots],
        "configuration": {
            "minimum_free_space_bytes": int(minimum_free_space_bytes),
            "max_depth": int(max_depth),
            "max_files": int(max_files),
            "min_candidate_size_bytes": int(min_candidate_size_bytes),
            "top_n": int(top_n),
        },
        "disk": {
            "minimum_observed_free_bytes": free_bytes,
            "within_minimum_free_space": (
                free_bytes is not None and free_bytes >= minimum_free_space_bytes
            ),
        },
        "root_reports": root_reports,
        "retention_candidates": ranked_candidates,
        "safety": {
            "read_only": True,
            "deletion_attempted": False,
            "move_attempted": False,
            "lock_or_pointer_modified": False,
            "automatic_delete_allowed": False,
            "truncated_scan_requires_manual_recheck": any(
                bool(report.get("scan_truncated")) for report in root_reports
            ),
        },
    }


def _validate_output_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved.relative_to(temp_root)
    except ValueError as exc:
        raise ValueError("output must be inside the OS TEMP directory") from exc
    return resolved


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        required=True,
        help="要盤點的明確目錄；可重複指定，不會掃描相鄰路徑",
    )
    parser.add_argument(
        "--minimum-free-space-bytes",
        type=int,
        default=DEFAULT_MINIMUM_FREE_SPACE_BYTES,
    )
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument(
        "--min-candidate-size-bytes",
        type=int,
        default=DEFAULT_MIN_CANDIDATE_SIZE_BYTES,
    )
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# ML Storage Retention Inventory",
        "",
        f"- status: `{report['status']}`",
        f"- minimum observed free bytes: `{report['disk']['minimum_observed_free_bytes']}`",
        f"- minimum required free bytes: `{report['configuration']['minimum_free_space_bytes']}`",
        "",
        "| Path | Kind | Size (bytes) | Manual review |",
        "|---|---|---:|---|",
    ]
    for item in report.get("retention_candidates", []):
        lines.append(
            f"| `{item['path']}` | `{item['kind']}` | `{item['size_bytes']}` | yes |"
        )
    if not report.get("retention_candidates"):
        lines.append("| （沒有超過門檻的候選） | — | 0 | — |")
    lines.extend(
        [
            "",
            "此報告只盤點 metadata；不刪除、不搬移、不修改 lock／pointer。",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    configure_utf8_console()
    args = _parser().parse_args(argv)
    report = inspect_storage_retention(
        args.root,
        minimum_free_space_bytes=args.minimum_free_space_bytes,
        max_depth=args.max_depth,
        max_files=args.max_files,
        min_candidate_size_bytes=args.min_candidate_size_bytes,
        top_n=args.top_n,
    )
    rendered = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else _render_markdown(report)
    )
    if args.output is None:
        print(rendered, end="")
    else:
        output = _validate_output_path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
