"""在正式 Research Run Registry 的唯讀 snapshot 上驗證 transaction 契約。

工具只用 read-only SQLite connection 讀取明確指定的正式 Registry，接著把
一致性 snapshot 複製到 OS TEMP；insert／read-back／rollback／quick_check
全部只發生在 TEMP clone。它不會開啟正式 Registry 的寫入 handle，也不會
把 clone proof 解讀成正式 ACL 或正式寫入已成功。
"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import uuid
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.research_run_repository import ResearchRunRepository


SCHEMA_VERSION = "research-registry-snapshot-transaction.v1"
EXPECTED_REGISTRY_SCHEMA_VERSION = ResearchRunRepository.SCHEMA_VERSION
EXPECTED_REGISTRY_SCHEMA_NAME = ResearchRunRepository.SCHEMA_NAME
REQUIRED_TABLES = {"schema_version", "research_runs"}
REQUIRED_COLUMNS = {
    "run_id",
    "run_name",
    "run_type",
    "payload_hash",
    "created_at",
    "storage_state",
    "integrity_status",
}


def inspect_registry_transaction(
    registry_path: str | Path,
    *,
    confirm: bool = False,
) -> dict[str, Any]:
    """Return a read-only source plus TEMP clone transaction report."""

    source = Path(registry_path).expanduser().resolve()
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": _utc_now(),
        "registry_path": str(source),
        "read_only_source": True,
        "formal_write_attempted": False,
        "writes_formal_registry": False,
        "clone_write_scope": "OS_TEMP_only",
    }
    if not confirm:
        return {
            **base,
            "status": "confirmation_required",
            "write_probe": "not_run",
            "side_effect_free": True,
            "diagnostics": [
                "需要明確傳入 --confirm-snapshot-probe；未讀取或建立 clone"
            ],
        }

    if not source.is_file():
        return {
            **base,
            "status": "blocked",
            "write_probe": "not_run",
            "side_effect_free": True,
            "diagnostics": ["registry_file_missing"],
        }

    source_before = _file_fingerprint(source)
    clone_path: Path | None = None
    diagnostics: list[str] = []
    transaction: dict[str, Any] = {}
    schema: dict[str, Any] = {}
    cleanup_succeeded = False
    try:
        with tempfile.TemporaryDirectory(prefix=".research-registry-snapshot-") as temp_name:
            clone_path = Path(temp_name) / "research_runs.sqlite"
            _backup_read_only_source(source, clone_path)
            schema = _inspect_schema(clone_path)
            if schema.get("schema_version") != EXPECTED_REGISTRY_SCHEMA_VERSION:
                diagnostics.append("research_registry_schema_version_mismatch")
            if schema.get("missing_tables"):
                diagnostics.append("research_registry_required_table_missing")
            if schema.get("missing_columns"):
                diagnostics.append("research_registry_required_column_missing")
            if schema.get("quick_check_before") != "ok":
                diagnostics.append("research_registry_clone_quick_check_failed")
            if not diagnostics:
                transaction = _run_clone_transaction(clone_path)
                if transaction.get("quick_check_after") != "ok":
                    diagnostics.append("research_registry_clone_post_quick_check_failed")
                if transaction.get("row_count_unchanged") is not True:
                    diagnostics.append("research_registry_clone_row_count_changed")
                if transaction.get("rolled_back_row_absent") is not True:
                    diagnostics.append("research_registry_clone_rollback_failed")
            source_after = _file_fingerprint(source)
            source_unchanged = source_before == source_after
            if not source_unchanged:
                diagnostics.append("formal_registry_changed_during_read_only_probe")
            base.update(
                {
                    "source_before": source_before,
                    "source_after": source_after,
                    "source_unchanged": source_unchanged,
                    "clone_path": str(clone_path),
                    "clone_retained": False,
                    "schema": schema,
                    "transaction": transaction,
                }
            )
        cleanup_succeeded = clone_path is not None and not clone_path.exists()
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        diagnostics.append(f"{type(exc).__name__}: {exc}")
        if clone_path is not None:
            cleanup_succeeded = not clone_path.exists()

    if not cleanup_succeeded:
        diagnostics.append("research_registry_clone_cleanup_failed")
    base["cleanup_succeeded"] = cleanup_succeeded
    base["diagnostics"] = diagnostics
    base["side_effect_free"] = False
    base["write_probe"] = "formal_registry_read_only_snapshot_clone_transaction"
    base["status"] = "passed" if not diagnostics and cleanup_succeeded else "failed"
    return base


def _backup_read_only_source(source: Path, clone_path: Path) -> None:
    clone_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect_read_only(source)) as source_connection:
        with closing(sqlite3.connect(clone_path)) as clone_connection:
            source_connection.backup(clone_connection)


def _inspect_schema(path: Path) -> dict[str, Any]:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA query_only=ON")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        schema_row = connection.execute(
            "SELECT version FROM schema_version WHERE name = ?",
            (EXPECTED_REGISTRY_SCHEMA_NAME,),
        ).fetchone()
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(research_runs)")
        }
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        row_count = connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()
    return {
        "schema_name": EXPECTED_REGISTRY_SCHEMA_NAME,
        "schema_version": int(schema_row[0]) if schema_row is not None else None,
        "tables": sorted(tables),
        "missing_tables": sorted(REQUIRED_TABLES - tables),
        "missing_columns": sorted(REQUIRED_COLUMNS - columns),
        "quick_check_before": str(quick_check[0]) if quick_check else None,
        "row_count_before": int(row_count[0]) if row_count else None,
    }


def _run_clone_transaction(path: Path) -> dict[str, Any]:
    run_id = f"runtime-registry-snapshot-probe:{uuid.uuid4().hex}"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA query_only=OFF")
        row_before = connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()
        row_count_before = int(row_before[0]) if row_before else 0
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO research_runs(run_id, run_name, run_type, payload_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "formal registry snapshot probe",
                "runtime_probe",
                "sha256:formal-registry-snapshot-probe",
                _utc_now(),
            ),
        )
        visible = connection.execute(
            "SELECT run_id FROM research_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        connection.rollback()
        rolled_back = connection.execute(
            "SELECT run_id FROM research_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        row_after = connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()
        row_count_after = int(row_after[0]) if row_after else -1
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
    return {
        "run_id": run_id,
        "insert_visible_before_rollback": visible == (run_id,),
        "rolled_back_row_absent": rolled_back is None,
        "row_count_before": row_count_before,
        "row_count_after": row_count_after,
        "row_count_unchanged": row_count_before == row_count_after,
        "quick_check_after": str(quick_check[0]) if quick_check else None,
    }


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _file_fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "size_bytes": int(stat.st_size),
        "modified_at": datetime.fromtimestamp(
            stat.st_mtime, timezone.utc
        ).isoformat(timespec="seconds"),
        "sha256": digest.hexdigest(),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _write_output(path: Path, rendered: str) -> None:
    target = path.expanduser().resolve()
    if not _is_inside(target, Path(tempfile.gettempdir()).resolve()):
        raise ValueError("output must remain inside the OS TEMP directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered.rstrip("\n") + "\n", encoding="utf-8")


def _render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Research Registry Snapshot Transaction",
        "",
        f"- status: `{payload.get('status', 'unknown')}`",
        f"- registry: `{payload.get('registry_path', '')}`",
        f"- write_probe: `{payload.get('write_probe', 'not_run')}`",
        f"- formal_write_attempted: `{payload.get('formal_write_attempted', False)}`",
        f"- source_unchanged: `{payload.get('source_unchanged', 'not_run')}`",
        f"- cleanup_succeeded: `{payload.get('cleanup_succeeded', 'not_run')}`",
        "",
        "此結果只代表正式 Registry 的 read-only snapshot clone 可在 TEMP 完成 schema／insert／rollback／quick_check；不代表正式 Registry ACL 或正式寫入已成功。",
    ]
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.extend(["", "Diagnostics:", ""])
        lines.extend(f"- `{item}`" for item in diagnostics)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True, help="明確指定正式或候選 Research Registry SQLite")
    parser.add_argument(
        "--confirm-snapshot-probe",
        action="store_true",
        help="確認只在 OS TEMP clone 執行 write／rollback；正式 Registry 永不開啟寫入",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="可選；報告必須寫在 OS TEMP")
    args = parser.parse_args(argv)
    try:
        payload = inspect_registry_transaction(
            args.registry,
            confirm=args.confirm_snapshot_probe,
        )
        rendered = (
            _render_markdown(payload)
            if args.format == "markdown"
            else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        )
        if args.output is not None:
            _write_output(args.output, rendered)
        print(rendered)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "read_only_source": True,
                    "formal_write_attempted": False,
                    "writes_formal_registry": False,
                },
                ensure_ascii=False,
            )
        )
        return 2
    return 0 if payload.get("status") == "passed" else 2


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
