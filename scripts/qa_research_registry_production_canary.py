"""執行一次明確核准的 Research Registry production transaction canary。

預設只做正式 Registry 的唯讀 schema／quick-check／row-count 預檢。只有
owner approval、無並行 writer acknowledgement 與 explicit confirm 同時成立
時，才會在真正的 ``research_runs.db`` 開啟短生命週期 transaction，插入一筆
唯一 canary row、讀回後 rollback，再用唯讀連線確認 row、內容 hash 與 row count
均未留下 durable change。操作前會把正式 DB snapshot 到 OS TEMP；成功後刪除
該暫存 backup，驗證失敗則保留 backup 路徑供人工處理。

這不是一般 readiness probe：它會在明確核准後對正式 Registry 產生可回滾的
write attempt，因此不應由 scheduler 或 UI 自動呼叫，也不會修改其他資料表。
"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import uuid
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.research_run_repository import ResearchRunRepository  # noqa: E402


CANARY_SCHEMA_VERSION = "research-registry-production-canary.v1"
OWNER_APPROVAL_TOKEN = "research-registry-transaction-canary"
NO_CONCURRENT_WRITER_TOKEN = "no-concurrent-writer"
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


def inspect_production_registry(registry_path: str | Path) -> dict[str, Any]:
    """Read the real Registry without creating schema or opening a write handle."""

    source = Path(registry_path).expanduser().resolve()
    state: dict[str, Any] = {
        "registry_path": str(source),
        "registry_exists": source.is_file(),
        "schema_name": ResearchRunRepository.SCHEMA_NAME,
        "expected_schema_version": ResearchRunRepository.SCHEMA_VERSION,
        "schema_version": None,
        "missing_tables": sorted(REQUIRED_TABLES),
        "missing_columns": sorted(REQUIRED_COLUMNS),
        "quick_check": None,
        "row_count": None,
        "journal_mode": None,
        "fingerprint": _fingerprint(source) if source.is_file() else None,
    }
    if not source.is_file():
        state["diagnostic"] = "registry_file_missing"
        return state
    try:
        with closing(_connect_read_only(source)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            schema_row = connection.execute(
                "SELECT version FROM schema_version WHERE name = ?",
                (ResearchRunRepository.SCHEMA_NAME,),
            ).fetchone()
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(research_runs)")
            }
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            row_count = connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        state.update(
            {
                "schema_version": int(schema_row[0]) if schema_row is not None else None,
                "missing_tables": sorted(REQUIRED_TABLES - tables),
                "missing_columns": sorted(REQUIRED_COLUMNS - columns),
                "quick_check": str(quick_check[0]) if quick_check else None,
                "row_count": int(row_count[0]) if row_count else None,
                "journal_mode": str(journal_mode[0]) if journal_mode else None,
            }
        )
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        state["diagnostic"] = f"{type(exc).__name__}: {exc}"
    return state


def execute_production_registry_canary(
    *,
    registry_path: str | Path,
    output_root: str | Path,
    protected_roots: Sequence[str | Path],
    backup_root: str | Path | None = None,
    owner_approval: str | None = None,
    no_concurrent_writer_ack: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Run a guarded, rollback-only transaction against the real Registry."""

    source = Path(registry_path).expanduser().resolve()
    resolved_output = Path(output_root).expanduser().resolve()
    protected = _resolve_roots(protected_roots)
    base: dict[str, Any] = {
        "schema_version": CANARY_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "mode": "production_registry_canary",
        "registry_path": str(source),
        "output_root": str(resolved_output),
        "protected_roots": [str(item) for item in protected],
        "owner_approval": bool(owner_approval),
        "no_concurrent_writer_ack": bool(no_concurrent_writer_ack),
        "confirmation_required": True,
        "confirm_production_registry_canary": bool(confirm),
        "read_only_preflight": True,
        "production_write_attempted": False,
        "production_sqlite_write_attempted": False,
        "durable_change_allowed": False,
        "writes_allowed": False,
        "side_effect_free": True,
        "backup": None,
        "rollback": {
            "available": False,
            "attempted": False,
            "succeeded": None,
        },
    }

    input_error = _validate_inputs(
        registry_path=source,
        output_root=resolved_output,
        protected_roots=protected,
    )
    if input_error:
        return {**base, "status": "blocked", "blocker": input_error}

    pre_state = inspect_production_registry(source)
    base["pre_state"] = pre_state
    if not pre_state.get("registry_exists"):
        return {**base, "status": "blocked", "blocker": "registry_file_missing"}
    if pre_state.get("schema_version") != ResearchRunRepository.SCHEMA_VERSION:
        return {
            **base,
            "status": "blocked",
            "blocker": "registry_schema_version_mismatch",
        }
    if pre_state.get("missing_tables") or pre_state.get("missing_columns"):
        return {
            **base,
            "status": "blocked",
            "blocker": "registry_schema_incomplete",
        }
    if pre_state.get("quick_check") != "ok":
        return {
            **base,
            "status": "blocked",
            "blocker": "registry_quick_check_failed",
        }
    if not confirm:
        return {
            **base,
            "status": "confirmation_required",
            "next_safe_step": (
                "先停用並行 Registry writer，再同時提供 owner_approval="
                f"{OWNER_APPROVAL_TOKEN}、no_concurrent_writer_ack="
                f"{NO_CONCURRENT_WRITER_TOKEN} 與 explicit confirm。"
            ),
        }
    if owner_approval != OWNER_APPROVAL_TOKEN:
        return {
            **base,
            "status": "blocked",
            "blocker": "owner_approval_token_required",
        }
    if no_concurrent_writer_ack != NO_CONCURRENT_WRITER_TOKEN:
        return {
            **base,
            "status": "blocked",
            "blocker": "no_concurrent_writer_ack_required",
        }

    backup_directory = _prepare_backup_directory(backup_root)
    backup_path = backup_directory / "research_runs_before_canary.db"
    backup: dict[str, Any] = {
        "status": "blocked",
        "directory": str(backup_directory),
        "sqlite_file": str(backup_path),
        "retained": True,
    }
    try:
        _backup_read_only_source(source, backup_path)
        backup["sha256"] = _sha256_file(backup_path)
        backup["status"] = "created"
        base["backup"] = backup
        base["side_effect_free"] = False
        base["rollback"]["available"] = True
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        base["backup"] = {
            **backup,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        return {**base, "status": "blocked", "blocker": "registry_canary_backup_failed"}

    run_id = f"runtime-registry-production-canary:{uuid.uuid4().hex}"
    visible = False
    rolled_back = False
    transaction_started = False
    connection: sqlite3.Connection | None = None
    error: Exception | None = None
    try:
        connection = sqlite3.connect(source, timeout=5.0)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("BEGIN IMMEDIATE")
        transaction_started = True
        base["production_write_attempted"] = True
        base["production_sqlite_write_attempted"] = True
        connection.execute(
            """
            INSERT INTO research_runs(run_id, run_name, run_type, payload_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "Research Registry production transaction canary",
                "runtime_production_canary",
                "sha256:research-registry-production-canary",
                _utc_now(),
            ),
        )
        visible = (
            connection.execute(
                "SELECT run_id FROM research_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            == (run_id,)
        )
        connection.rollback()
        rolled_back = True
        base["rollback"]["attempted"] = True
        base["rollback"]["succeeded"] = True
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        error = exc
        if connection is not None and transaction_started:
            base["rollback"]["attempted"] = True
            try:
                connection.rollback()
                rolled_back = True
                base["rollback"]["succeeded"] = True
            except (OSError, sqlite3.Error) as rollback_error:
                base["rollback"]["succeeded"] = False
                base["rollback"]["error_type"] = type(rollback_error).__name__
                base["rollback"]["error"] = str(rollback_error)
    finally:
        if connection is not None:
            connection.close()

    post_state = inspect_production_registry(source)
    post_state["canary_row_present"] = _row_present(source, run_id)
    base["post_state"] = post_state
    pre_fingerprint = (pre_state.get("fingerprint") or {})
    post_fingerprint = (post_state.get("fingerprint") or {})
    content_unchanged = (
        pre_fingerprint.get("sha256") == post_fingerprint.get("sha256")
        and pre_fingerprint.get("size_bytes") == post_fingerprint.get("size_bytes")
    )
    validation: dict[str, Any] = {
        "insert_visible_before_rollback": visible,
        "rollback_completed": rolled_back,
        "rolled_back_row_absent": post_state.get("canary_row_present") is False,
        "row_count_unchanged": pre_state.get("row_count") == post_state.get("row_count"),
        "registry_content_unchanged": content_unchanged,
        "quick_check_after": post_state.get("quick_check"),
    }
    validation["ok"] = all(
        (
            validation["insert_visible_before_rollback"],
            validation["rollback_completed"],
            validation["rolled_back_row_absent"],
            validation["row_count_unchanged"],
            validation["registry_content_unchanged"],
            validation["quick_check_after"] == "ok",
        )
    )
    base["validation"] = validation
    if error is not None:
        base["error_type"] = type(error).__name__
        base["error"] = str(error)
    if validation["ok"]:
        _cleanup_backup_directory(backup_directory)
        base["backup"]["retained"] = False
        base["rollback"]["succeeded"] = True
        return {
            **base,
            "status": "measured",
            "writes_allowed": True,
            "durable_change_allowed": False,
            "durable_change_detected": False,
            "next_safe_step": "保留 single-writer policy；正式 canary 仍需 owner review 此 artifact。",
        }
    return {
        **base,
        "status": "blocked",
        "blocker": "registry_canary_validation_failed",
        "next_safe_step": "停止其他 Registry writer，保留 backup，先人工比對 post_state 後再處理。",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--protected-root", type=Path, action="append", required=True)
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--owner-approval")
    parser.add_argument("--no-concurrent-writer-ack")
    parser.add_argument("--confirm-production-registry-canary", action="store_true")
    parser.add_argument("--output-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    args = build_parser().parse_args(argv)
    protected = _resolve_roots(args.protected_root)
    if args.output_json is not None:
        output_target = args.output_json.expanduser().resolve()
        if not _is_inside(output_target, Path(tempfile.gettempdir()).resolve()):
            print(
                json.dumps(
                    {
                        "schema_version": CANARY_SCHEMA_VERSION,
                        "status": "blocked",
                        "blocker": "output_json_must_remain_in_os_temp",
                        "production_write_attempted": False,
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        if any(_is_inside(output_target, root) for root in protected):
            print(
                json.dumps(
                    {
                        "schema_version": CANARY_SCHEMA_VERSION,
                        "status": "blocked",
                        "blocker": "output_json_inside_protected_root",
                        "production_write_attempted": False,
                    },
                    ensure_ascii=False,
                )
            )
            return 2
    try:
        report = execute_production_registry_canary(
            registry_path=args.registry,
            output_root=args.output_root,
            protected_roots=args.protected_root,
            backup_root=args.backup_root,
            owner_approval=args.owner_approval,
            no_concurrent_writer_ack=args.no_concurrent_writer_ack,
            confirm=args.confirm_production_registry_canary,
        )
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        report = {
            "schema_version": CANARY_SCHEMA_VERSION,
            "status": "blocked",
            "blocker": "registry_canary_input_or_runtime_error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "production_write_attempted": False,
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("status") == "measured" else 2


def _validate_inputs(
    *,
    registry_path: Path,
    output_root: Path,
    protected_roots: Sequence[Path],
) -> str | None:
    expected_registry = (output_root / "research_runs" / "research_runs.db").resolve()
    if not protected_roots:
        return "protected_root_required"
    if not output_root.is_dir():
        return "output_root_must_preexist_as_directory"
    if registry_path != expected_registry:
        return "registry_path_must_match_output_root_research_registry"
    if not any(_is_inside(output_root, root) for root in protected_roots):
        return "output_root_not_covered_by_protected_root"
    if not any(_is_inside(registry_path, root) for root in protected_roots):
        return "registry_not_covered_by_protected_root"
    return None


def _prepare_backup_directory(backup_root: str | Path | None) -> Path:
    temp_root = Path(tempfile.gettempdir()).resolve()
    if backup_root is None:
        return Path(tempfile.mkdtemp(prefix="research-registry-canary-", dir=str(temp_root))).resolve()
    resolved = Path(backup_root).expanduser().resolve()
    if not _is_inside(resolved, temp_root):
        raise ValueError("backup_root_must_remain_in_os_temp")
    if not resolved.is_dir():
        raise ValueError("backup_root_must_preexist_as_directory")
    directory = (resolved / f"research-registry-canary-{uuid.uuid4().hex}").resolve()
    directory.mkdir()
    return directory


def _cleanup_backup_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _backup_read_only_source(source: Path, target: Path) -> None:
    with closing(_connect_read_only(source)) as source_connection:
        with closing(sqlite3.connect(target)) as target_connection:
            source_connection.backup(target_connection)


def _row_present(path: Path, run_id: str) -> bool | None:
    try:
        with closing(_connect_read_only(path)) as connection:
            row = connection.execute(
                "SELECT run_id FROM research_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return row == (run_id,)
    except (OSError, sqlite3.Error):
        return None


def _fingerprint(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "size_bytes": int(stat.st_size),
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "sha256": digest.hexdigest(),
    }


def _sha256_file(path: Path) -> str:
    fingerprint = _fingerprint(path)
    if fingerprint is None:
        raise FileNotFoundError(str(path))
    return str(fingerprint["sha256"])


def _resolve_roots(values: Sequence[str | Path]) -> tuple[Path, ...]:
    return tuple(Path(value).expanduser().resolve() for value in values)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "CANARY_SCHEMA_VERSION",
    "NO_CONCURRENT_WRITER_TOKEN",
    "OWNER_APPROVAL_TOKEN",
    "execute_production_registry_canary",
    "inspect_production_registry",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
