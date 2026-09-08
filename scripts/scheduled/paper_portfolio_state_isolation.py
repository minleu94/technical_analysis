"""將 D 槽 Paper state 以唯讀、可重驗的方式 seed 到 repository。

盤前排程是 repository state 的唯一 writer。D 槽既有 snapshot 只作一次性
SQLite consistent backup 的來源；之後 EOD 與 Formal 都讀 repository copy。
此模組不會覆寫既有 target，也不會以缺少 provenance 的 SQLite 檔案繼續執行。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid


STATE_SEED_SCHEMA_VERSION = "paper-portfolio-state-seed.v1"
STATE_HEAD_SCHEMA_VERSION = "paper-portfolio-state-head.v1"
REQUIRED_STATE_TABLES = frozenset(
    {
        "paper_portfolio_snapshots",
        "paper_portfolio_positions",
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _file_signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _source_bundle(path: Path) -> dict[str, object]:
    """讀取 main/WAL/SHM 的 hash 與 signature，供 seed 前後比對。"""

    if path.expanduser().is_symlink():
        raise RuntimeError(f"Paper state source must not be a symlink:{path}")
    resolved = _resolved(path)
    files: list[dict[str, object]] = []
    for candidate in (
        resolved,
        Path(f"{resolved}-wal"),
        Path(f"{resolved}-shm"),
    ):
        if not candidate.exists():
            continue
        if not candidate.is_file() or candidate.is_symlink():
            raise RuntimeError(f"Paper state source sidecar is not a regular file:{candidate}")
        files.append(
            {
                "path": str(candidate),
                "file_sha256": _file_hash(candidate),
                "file_signature": _file_signature(candidate),
            }
        )
    if not files or files[0]["path"] != str(resolved):
        raise RuntimeError(f"Paper state source is missing:{resolved}")
    return {
        "files": files,
        "bundle_sha256": _payload_hash(files),
    }


def _open_readonly(path: Path) -> sqlite3.Connection:
    if path.expanduser().is_symlink():
        raise RuntimeError(f"Paper state source must not be a symlink:{path}")
    resolved = _resolved(path)
    if not resolved.is_file() or resolved.is_symlink():
        raise RuntimeError(f"Paper state source is not a regular file:{resolved}")
    connection = sqlite3.connect(
        f"file:{resolved.as_posix()}?mode=ro",
        uri=True,
    )
    connection.execute("PRAGMA query_only=ON")
    return connection


def _validate_schema(connection: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing = sorted(REQUIRED_STATE_TABLES - tables)
    if missing:
        raise RuntimeError(f"Paper state schema is incomplete:{','.join(missing)}")


def _manifest_body(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Paper state seed manifest is unreadable:{path}") from error
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Paper state seed manifest is not an object:{path}")
    body = dict(value)
    declared = body.pop("content_sha256", None)
    if declared != _payload_hash(body):
        raise RuntimeError(f"Paper state seed manifest hash is invalid:{path}")
    return body


def _validate_existing(
    *,
    target: Path,
    manifest_path: Path,
    expected_source: Path | None = None,
    allow_unpublished_change: bool = False,
) -> dict[str, object]:
    resolved_target = _resolved(target)
    resolved_manifest = _resolved(manifest_path)
    if not resolved_target.is_file() or resolved_target.is_symlink():
        raise RuntimeError(f"Paper state target is not a regular file:{resolved_target}")
    if not resolved_manifest.is_file() or resolved_manifest.is_symlink():
        raise RuntimeError(
            f"Paper state target exists without immutable seed manifest:{resolved_target}"
        )
    body = _manifest_body(resolved_manifest)
    if body.get("schema_version") != STATE_SEED_SCHEMA_VERSION:
        raise RuntimeError("Paper state seed manifest schema is unsupported")
    if body.get("seed_method") != "sqlite_readonly_consistent_backup":
        raise RuntimeError("Paper state seed method is unsupported")
    source_info = body.get("source")
    if not isinstance(source_info, Mapping):
        raise RuntimeError("Paper state seed manifest source is invalid")
    if source_info.get("read_mode") != "sqlite_uri_mode_ro_and_query_only":
        raise RuntimeError("Paper state seed source read mode is unsupported")
    source_bundle = source_info.get("bundle")
    if not isinstance(source_bundle, Mapping) or body.get("source_bundle_sha256") != source_bundle.get("bundle_sha256"):
        raise RuntimeError("Paper state seed source bundle is invalid")
    if expected_source is not None:
        if expected_source.expanduser().is_symlink():
            raise RuntimeError("Paper state expected source must not be a symlink")
        if source_info.get("path") != str(_resolved(expected_source)):
            raise RuntimeError("Paper state seed source path changed")
    target_info = body.get("target")
    if not isinstance(target_info, Mapping):
        raise RuntimeError("Paper state seed manifest target is invalid")
    if target_info.get("path") != str(resolved_target):
        raise RuntimeError("Paper state seed manifest target path changed")
    expected_hash = target_info.get("seed_file_sha256", target_info.get("file_sha256"))
    actual_hash = _file_hash(resolved_target)
    head_path = resolved_manifest.with_name("state_head_manifest.json")
    if head_path.exists():
        if head_path.is_symlink():
            raise RuntimeError("Paper state head manifest must not be a symlink")
        head = _manifest_body(head_path)
        if head.get("schema_version") != STATE_HEAD_SCHEMA_VERSION:
            raise RuntimeError("Paper state head manifest schema is unsupported")
        if head.get("target_path") != str(resolved_target):
            raise RuntimeError("Paper state head target path changed")
        if head.get("seed_manifest_path") != str(resolved_manifest):
            raise RuntimeError("Paper state head seed manifest path changed")
        if head.get("seed_manifest_file_sha256") != _file_hash(resolved_manifest):
            raise RuntimeError("Paper state seed manifest changed after head publish")
        if not allow_unpublished_change and head.get("target_file_sha256") != actual_hash:
            raise RuntimeError("Paper state target changed after last published head")
    elif not allow_unpublished_change and expected_hash != actual_hash:
        raise RuntimeError("Paper state target changed without a published head")
    connection: sqlite3.Connection | None = None
    try:
        connection = _open_readonly(resolved_target)
        _validate_schema(connection)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    except sqlite3.Error as error:
        raise RuntimeError("Paper state target read failed") from error
    finally:
        if connection is not None:
            connection.close()
    if integrity != "ok":
        raise RuntimeError(f"Paper state target integrity check failed:{integrity}")
    return {
        "status": "existing_verified",
        "seeded": False,
        "manifest_path": str(resolved_manifest),
        "manifest_file_sha256": _file_hash(resolved_manifest),
        "source_bundle_sha256": body.get("source_bundle_sha256"),
        "target_file_sha256": actual_hash,
        "seeded_at": body.get("seeded_at"),
        "seed_method": body.get("seed_method"),
    }


def ensure_repo_state_from_readonly_source(
    *,
    source: Path,
    target: Path,
    manifest_path: Path,
    observed_at: datetime,
) -> dict[str, object]:
    """建立或驗證 repository state，且永遠不覆寫既有 target。

    ``source`` 以 SQLite ``mode=ro`` 開啟，backup 會在 source 的一致讀取
    snapshot 上執行。main/WAL/SHM hash 在讀取前後必須完全相同；若來源在
    backup 期間變動，暫存 target 會被刪除並回傳 blocker。target 與 manifest
    使用 create-only／hard-link publish，避免兩個盤前 instance 互相覆寫。
    """

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must include timezone")
    observed_utc = observed_at.astimezone(timezone.utc)
    resolved_source = _resolved(source)
    resolved_target = _resolved(target)
    resolved_manifest = _resolved(manifest_path)
    if source.expanduser().is_symlink():
        raise RuntimeError(f"Paper state source must not be a symlink:{source}")
    if target.expanduser().is_symlink():
        raise RuntimeError(f"Paper state target must not be a symlink:{target}")
    if manifest_path.expanduser().is_symlink():
        raise RuntimeError(f"Paper state seed manifest must not be a symlink:{manifest_path}")
    if resolved_target == resolved_source:
        raise RuntimeError("Paper state seed target must differ from source")
    if resolved_target.exists() and resolved_target.is_symlink():
        raise RuntimeError(f"Paper state target must not be a symlink:{resolved_target}")
    if resolved_manifest.exists() and resolved_manifest.is_symlink():
        raise RuntimeError(f"Paper state seed manifest must not be a symlink:{resolved_manifest}")
    if resolved_target.exists():
        return _validate_existing(
            target=resolved_target,
            manifest_path=resolved_manifest,
            expected_source=resolved_source,
        )
    if resolved_manifest.exists():
        raise RuntimeError("Paper state seed manifest exists but target is missing")
    if not resolved_source.is_file() or resolved_source.is_symlink():
        raise RuntimeError(f"Paper state source is not a regular file:{resolved_source}")
    resolved_target.parent.mkdir(parents=True, exist_ok=True)

    before_bundle = _source_bundle(resolved_source)
    temporary = resolved_target.with_name(
        f".{resolved_target.name}.{uuid.uuid4().hex}.seed"
    )
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = _open_readonly(resolved_source)
        _validate_schema(source_connection)
        target_connection = sqlite3.connect(temporary)
        source_connection.backup(target_connection)
        target_connection.commit()
        target_connection.close()
        target_connection = None
        source_connection.close()
        source_connection = None
        after_bundle = _source_bundle(resolved_source)
        if before_bundle != after_bundle:
            raise RuntimeError("Paper state source changed during readonly seed")
        temporary_connection = _open_readonly(temporary)
        try:
            _validate_schema(temporary_connection)
            integrity = str(
                temporary_connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
        finally:
            temporary_connection.close()
        if integrity != "ok":
            raise RuntimeError(f"Paper state seed integrity check failed:{integrity}")
        # hard-link 建立是原子的；若另一個 instance 先發布 target，這裡會失敗，
        # 不會取代競爭中的 target。
        try:
            os.link(temporary, resolved_target)
        except FileExistsError:
            return _validate_existing(
                target=resolved_target,
                manifest_path=resolved_manifest,
                expected_source=resolved_source,
            )
        target_hash = _file_hash(resolved_target)
        body: dict[str, object] = {
            "schema_version": STATE_SEED_SCHEMA_VERSION,
            "seeded_at": observed_utc.isoformat(),
            "seed_method": "sqlite_readonly_consistent_backup",
            "source": {
                "path": str(resolved_source),
                "read_mode": "sqlite_uri_mode_ro_and_query_only",
                "required_tables": sorted(REQUIRED_STATE_TABLES),
                "bundle": before_bundle,
            },
            "source_bundle_sha256": before_bundle["bundle_sha256"],
            "target": {
                "path": str(resolved_target),
                "file_sha256": target_hash,
                "seed_file_sha256": target_hash,
                "file_signature": _file_signature(resolved_target),
            },
            "writes_source": False,
            "formal_credit": False,
            "broker_execution": False,
        }
        payload = {**body, "content_sha256": _payload_hash(body)}
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        try:
            with resolved_manifest.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            # 另一個 writer 先建立 manifest；宣告成功前仍須驗證兩個 immutable
            # 物件。
            return _validate_existing(
                target=resolved_target,
                manifest_path=resolved_manifest,
                expected_source=resolved_source,
            )
        return {
            "status": "seeded",
            "seeded": True,
            "manifest_path": str(resolved_manifest),
            "manifest_file_sha256": _file_hash(resolved_manifest),
            "source_bundle_sha256": before_bundle["bundle_sha256"],
            "target_file_sha256": target_hash,
            "seeded_at": body["seeded_at"],
            "seed_method": body["seed_method"],
        }
    except sqlite3.Error as error:
        raise RuntimeError(f"Paper state readonly backup failed:{type(error).__name__}") from error
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        for sidecar in (
            temporary,
            Path(f"{temporary}-wal"),
            Path(f"{temporary}-shm"),
        ):
            try:
                sidecar.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # 遺留暫存檔會在下一輪保持可觀測；cleanup 絕不刪除 target 或 source。
                pass


def verify_repo_state_seed(
    *,
    target: Path,
    manifest_path: Path,
    source: Path | None = None,
) -> dict[str, object]:
    """驗證既有 repository state 的 immutable seed manifest，不讀取 D source。"""

    return _validate_existing(
        target=target,
        manifest_path=manifest_path,
        expected_source=source,
    )


def publish_repo_state_head(
    *,
    target: Path,
    manifest_path: Path,
    observed_at: datetime,
) -> dict[str, object]:
    """記錄 append-only state 最新檔案 hash，保留 seed manifest 不可變。"""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must include timezone")
    seed = _validate_existing(
        target=target,
        manifest_path=manifest_path,
        allow_unpublished_change=True,
    )
    resolved_target = _resolved(target)
    resolved_manifest = _resolved(manifest_path)
    head_path = resolved_manifest.with_name("state_head_manifest.json")
    body: dict[str, object] = {
        "schema_version": STATE_HEAD_SCHEMA_VERSION,
        "published_at": observed_at.astimezone(timezone.utc).isoformat(),
        "target_path": str(resolved_target),
        "target_file_sha256": _file_hash(resolved_target),
        "target_file_signature": _file_signature(resolved_target),
        "seed_manifest_path": str(resolved_manifest),
        "seed_manifest_file_sha256": _file_hash(resolved_manifest),
        "formal_credit": False,
        "broker_execution": False,
    }
    payload = {**body, "content_sha256": _payload_hash(body)}
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    temporary = head_path.with_name(f".{head_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, head_path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {
        "status": "published",
        "path": str(head_path),
        "file_sha256": _file_hash(head_path),
        "target_file_sha256": body["target_file_sha256"],
        "seed_status": seed["status"],
        "published_at": body["published_at"],
    }


__all__ = [
    "REQUIRED_STATE_TABLES",
    "STATE_SEED_SCHEMA_VERSION",
    "ensure_repo_state_from_readonly_source",
    "publish_repo_state_head",
    "verify_repo_state_seed",
]
