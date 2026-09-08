"""固化 bounded Direct/OOC shared numeric reuse 的實跑證據。

這個入口只讀取已完成的 repo output manifest、shared registry 與 OOC artifact；
它不讀取 D 槽、不重建資料、不訓練模型，也不修改任何來源。``snapshot``
子命令可在 OOC resume 前後保存串流 hash 快照，``report`` 子命令則驗證：

* Direct 兩個公開 CLI run 使用相同年度 semantic descriptor／artifact key，
  第二次在建立年度 workspace 前全部重用且新增 bytes 為零；
* OOC CLI 直接以 shared numeric path 消費第二個 Direct manifest，兩個獨立
  output root 以同一 semantic key 重用 OOF／final base／meta payload，且
  第二次不重訓、不重複寫入 shared bytes；
* upstream lineage、容量預算、研究旗標與尚未滿足的正式輸入 blocker 均保留。

若未提供第二個 OOC manifest，report 仍只報告既有 resume 證據；只有同時提供
第二個 manifest 與 shared artifact registry 並通過每個 artifact 的 key、schema、
content hash 與 custody event 驗證時，才會將跨 run reuse 標記為完成。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import sqlite3
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.ml_storage_capacity import directory_size_bytes
from ml_module.allocation_ooc_shared_artifact_store import (
    OOCSharedArtifactStore,
)


SCHEMA_VERSION = "ml-direct-ooc-shared-reuse-qa.v2"
SNAPSHOT_SCHEMA_VERSION = "ml-direct-ooc-shared-reuse-snapshot.v1"
SHA256_PREFIX = "sha256:"
_CHUNK_BYTES = 1024 * 1024
_OPERATIONAL_RESUME_FILES = frozenset(
    {
        "capacity_checkpoint.json",
        "checkpoint.json",
        "heartbeat.json",
    }
)


class EvidenceError(ValueError):
    """來源 evidence 不完整、hash 不符或輸出範圍不安全。"""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: object) -> str:
    return SHA256_PREFIX + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
    return SHA256_PREFIX + digest.hexdigest()


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{field_name} must be a non-empty string")
    return value


def _required_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceError(f"{field_name} must be an integer")
    return value


def _required_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{field_name} must be an object")
    return value


def _required_list(value: object, *, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvidenceError(f"{field_name} must be an array")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EvidenceError(f"JSON evidence is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read JSON evidence: {path}") from exc
    if not isinstance(payload, dict):
        raise EvidenceError(f"JSON evidence must be an object: {path}")
    return payload


def _load_hashed_manifest(
    path: Path,
    *,
    expected_schema: str,
) -> tuple[dict[str, Any], dict[str, str | int]]:
    payload = _load_json(path)
    if payload.get("schema_version") != expected_schema:
        raise EvidenceError(
            f"{path} schema is not {expected_schema}: "
            f"{payload.get('schema_version')!r}"
        )
    expected_hash = _required_text(
        payload.get("manifest_hash"), field_name=f"{path}.manifest_hash"
    )
    if not expected_hash.startswith(SHA256_PREFIX):
        raise EvidenceError(f"{path}.manifest_hash is not sha256")
    body = dict(payload)
    body.pop("manifest_hash", None)
    calculated = _sha256_json(body)
    if calculated != expected_hash:
        raise EvidenceError(
            f"{path} logical manifest hash mismatch: {calculated} != {expected_hash}"
        )
    return payload, {
        "path": str(path.resolve()),
        "manifest_hash": expected_hash,
        "file_sha256": _sha256_file(path),
        "file_bytes": int(path.stat().st_size),
    }


def _paths_overlap(first: Path, second: Path) -> bool:
    first_resolved = first.resolve()
    second_resolved = second.resolve()
    return (
        first_resolved == second_resolved
        or first_resolved in second_resolved.parents
        or second_resolved in first_resolved.parents
    )


def _ensure_output_disjoint(
    output_path: Path,
    *,
    source_roots: Sequence[Path],
) -> Path:
    output = output_path.resolve()
    for source_root in source_roots:
        source = source_root.resolve()
        if _paths_overlap(output, source):
            raise EvidenceError(
                f"evidence output overlaps read-only source: {output} / {source}"
            )
        if output.exists() and source.exists():
            try:
                if os.path.samefile(output, source):
                    raise EvidenceError(
                        f"evidence output aliases read-only source: {output}"
                    )
            except FileNotFoundError:
                pass
            except OSError:
                # Parent/child overlap above remains the fail-closed check.  A
                # platform that cannot resolve samefile must not turn a source
                # path into a writable output by assumption.
                raise EvidenceError(
                    f"cannot verify output/source identity: {output} / {source}"
                )
    return output


def _iter_regular_files(root: Path) -> list[tuple[str, Path, int]]:
    """以 scandir 串流列出一般檔案，遇到 metadata error 時停止。"""

    if not root.exists():
        raise EvidenceError(f"evidence root is missing: {root}")
    if not root.is_dir():
        raise EvidenceError(f"evidence root is not a directory: {root}")
    entries: list[tuple[str, Path, int]] = []
    pending = [root.resolve()]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as children:
                for child in children:
                    child_path = Path(child.path)
                    try:
                        child_stat = child.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise EvidenceError(
                            f"cannot inspect evidence path: {child_path}"
                        ) from exc
                    if stat.S_ISLNK(child_stat.st_mode):
                        continue
                    junction_checker = getattr(child_path, "is_junction", None)
                    if callable(junction_checker):
                        try:
                            if bool(junction_checker()):
                                continue
                        except OSError as exc:
                            raise EvidenceError(
                                f"cannot inspect evidence junction: {child_path}"
                            ) from exc
                    if stat.S_ISDIR(child_stat.st_mode):
                        pending.append(child_path)
                    elif stat.S_ISREG(child_stat.st_mode):
                        relative = child_path.relative_to(root.resolve()).as_posix()
                        entries.append(
                            (relative, child_path, int(child_stat.st_size))
                        )
        except OSError as exc:
            raise EvidenceError(f"cannot enumerate evidence root: {current}") from exc
    entries.sort(key=lambda item: item[0])
    return entries


def snapshot_directory(*, root: Path, output_path: Path) -> dict[str, Any]:
    """保存不含 mtime 的檔案 size/hash snapshot，便於 resume 前後比較。"""

    resolved_root = root.resolve()
    output = _ensure_output_disjoint(output_path, source_roots=(resolved_root,))
    files: dict[str, dict[str, str | int]] = {}
    for relative, path, size in _iter_regular_files(resolved_root):
        files[relative] = {
            "bytes": size,
            "sha256": _sha256_file(path),
        }
    body: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "root": str(resolved_root),
        "directory_size_bytes": directory_size_bytes(resolved_root),
        "files": files,
    }
    payload = {**body, "snapshot_hash": _sha256_json(body)}
    _atomic_create_json(output, payload)
    return {
        **payload,
        "path": str(output),
        "file_sha256": _sha256_file(output),
    }


def _load_snapshot(path: Path, *, expected_root: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise EvidenceError(f"unsupported snapshot schema: {path}")
    expected_hash = _required_text(
        payload.get("snapshot_hash"), field_name=f"{path}.snapshot_hash"
    )
    body = dict(payload)
    body.pop("snapshot_hash", None)
    if _sha256_json(body) != expected_hash:
        raise EvidenceError(f"snapshot logical hash mismatch: {path}")
    if Path(_required_text(payload.get("root"), field_name="snapshot.root")).resolve() != expected_root.resolve():
        raise EvidenceError(f"snapshot root mismatch: {path}")
    files = _required_mapping(payload.get("files"), field_name="snapshot.files")
    for relative, item in files.items():
        _required_mapping(item, field_name=f"snapshot.files[{relative}]")
    return payload


def _atomic_create_json(path: Path, payload: Mapping[str, Any]) -> bool:
    raw = (_canonical_json(payload) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise EvidenceError(f"immutable QA output collision: {path}")
        return False
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(raw_path)
    descriptor_open = True
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor_open = False
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                raise EvidenceError(f"immutable QA output collision: {path}")
            return False
        return True
    finally:
        if descriptor_open:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _direct_year_summary(year: Mapping[str, Any]) -> dict[str, Any]:
    year_number = _required_int(year.get("year"), field_name="direct.year")
    publication = _required_mapping(
        year.get("shared_artifact_publication"),
        field_name=f"direct.year={year_number}.shared_artifact_publication",
    )
    statuses = _required_list(
        publication.get("statuses"),
        field_name=f"direct.year={year_number}.statuses",
    )
    descriptor = _required_mapping(
        year.get("shared_year_descriptor"),
        field_name=f"direct.year={year_number}.shared_year_descriptor",
    )
    descriptor_reference = _required_mapping(
        descriptor.get("block_reference"),
        field_name=f"direct.year={year_number}.descriptor.block_reference",
    )
    descriptor_key = _required_text(
        descriptor_reference.get("key_hash"),
        field_name=f"direct.year={year_number}.descriptor.key_hash",
    )
    artifact_keys: dict[str, str] = {}
    object_hashes: dict[str, str] = {}
    status_rows: list[dict[str, Any]] = []
    for raw_status in statuses:
        status = _required_mapping(
            raw_status,
            field_name=f"direct.year={year_number}.status",
        )
        artifact_id = _required_text(
            status.get("artifact_id"), field_name="direct.status.artifact_id"
        )
        artifact_keys[artifact_id] = _required_text(
            status.get("key_hash"), field_name=f"direct.{artifact_id}.key_hash"
        )
        object_hashes[artifact_id] = _required_text(
            status.get("object_hash"), field_name=f"direct.{artifact_id}.object_hash"
        )
        status_rows.append(
            {
                "artifact_id": artifact_id,
                "status": _required_text(
                    status.get("status"), field_name=f"direct.{artifact_id}.status"
                ),
                "key_hash": artifact_keys[artifact_id],
                "object_hash": object_hashes[artifact_id],
                "new_bytes_written": _required_int(
                    status.get("new_bytes_written"),
                    field_name=f"direct.{artifact_id}.new_bytes_written",
                ),
            }
        )
    return {
        "year": year_number,
        "row_count": _required_int(year.get("row_count"), field_name="direct.row_count"),
        "feature_count": _required_int(
            year.get("feature_count"), field_name="direct.feature_count"
        ),
        "artifact_storage": _required_text(
            year.get("artifact_storage"), field_name="direct.artifact_storage"
        ),
        "descriptor_key_hash": descriptor_key,
        "artifact_key_hashes": dict(sorted(artifact_keys.items())),
        "artifact_object_hashes": dict(sorted(object_hashes.items())),
        "status_rows": sorted(status_rows, key=lambda item: str(item["artifact_id"])),
        "new_bytes_written": _required_int(
            publication.get("new_bytes_written"),
            field_name=f"direct.year={year_number}.new_bytes_written",
        ),
        "reuse_before_build": publication.get("reuse_before_build") is True,
    }


def _direct_run_summary(
    *,
    path: Path,
    manifest: Mapping[str, Any],
    metadata: Mapping[str, str | int],
) -> dict[str, Any]:
    years = _required_list(manifest.get("years"), field_name="direct.years")
    year_rows = [_direct_year_summary(_required_mapping(item, field_name="direct.year")) for item in years]
    year_rows.sort(key=lambda item: int(item["year"]))
    run_directory = path.parent
    run_local_files: dict[str, list[str]] = {}
    for year in year_rows:
        year_directory = run_directory / f"year={int(year['year']):04d}"
        run_local_files[str(year["year"])] = [
            relative
            for relative, _file_path, _size in _iter_regular_files(year_directory)
        ]
    return {
        "path": str(path.resolve()),
        "manifest_hash": metadata["manifest_hash"],
        "file_sha256": metadata["file_sha256"],
        "file_bytes": metadata["file_bytes"],
        "run_id": _required_text(manifest.get("run_id"), field_name="direct.run_id"),
        "dataset_identity_hash": _required_text(
            manifest.get("dataset_identity_hash"), field_name="direct.dataset_identity_hash"
        ),
        "source_manifest_hashes": manifest.get("source_manifest_hashes"),
        "row_count": _required_int(manifest.get("row_count"), field_name="direct.row_count"),
        "feature_count": _required_int(
            manifest.get("feature_count"), field_name="direct.feature_count"
        ),
        "fold_count": _required_int(manifest.get("fold_count"), field_name="direct.fold_count"),
        "years": year_rows,
        "run_directory_bytes": directory_size_bytes(run_directory),
        "run_local_year_files": run_local_files,
        "capacity": _required_mapping(
            _required_mapping(manifest.get("execution"), field_name="direct.execution").get(
                "capacity_budget"
            ),
            field_name="direct.execution.capacity_budget",
        ),
        "execution": {
            key: value
            for key, value in _required_mapping(
                manifest.get("execution"), field_name="direct.execution"
            ).items()
            if key
            in {
                "peak_rss_bytes",
                "peak_temporary_bytes",
                "temporary_storage_budget_bytes",
                "persistent_storage_budget_bytes",
                "full_market_ready",
                "readiness_failed_checks",
            }
        },
    }


def _shared_registry_summary(root: Path) -> dict[str, Any]:
    files = _iter_regular_files(root)
    objects = [item for item in files if item[0].startswith("objects/")]
    keys = [item for item in files if item[0].startswith("keys/")]
    return {
        "path": str(root.resolve()),
        "directory_size_bytes": directory_size_bytes(root),
        "file_count": len(files),
        "object_count": len(objects),
        "key_count": len(keys),
        "object_bytes": sum(item[2] for item in objects),
        "key_bytes": sum(item[2] for item in keys),
    }


def _compare_snapshot_files(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, Any]:
    before_files = _required_mapping(before.get("files"), field_name="before.files")
    after_files = _required_mapping(after.get("files"), field_name="after.files")
    all_paths = sorted(set(before_files) | set(after_files))
    changed: list[str] = []
    immutable_changed: list[str] = []
    for relative in all_paths:
        if before_files.get(relative) != after_files.get(relative):
            changed.append(str(relative))
            if Path(str(relative)).name not in _OPERATIONAL_RESUME_FILES:
                immutable_changed.append(str(relative))
    return {
        "all_files_unchanged": not changed,
        "immutable_artifacts_unchanged": not immutable_changed,
        "changed_files": changed,
        "changed_immutable_files": immutable_changed,
        "before_directory_size_bytes": _required_int(
            before.get("directory_size_bytes"), field_name="before.directory_size_bytes"
        ),
        "after_directory_size_bytes": _required_int(
            after.get("directory_size_bytes"), field_name="after.directory_size_bytes"
        ),
    }


def _ooc_artifact_inventory(
    *,
    manifest: Mapping[str, Any],
    run_directory: Path,
    shared_artifact_store: OOCSharedArtifactStore | None = None,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for field_name in ("base_experts", "final_base_experts", "meta_folds"):
        for raw in _required_list(manifest.get(field_name), field_name=f"ooc.{field_name}"):
            item = _required_mapping(raw, field_name=f"ooc.{field_name}.item")
            artifact_directory = _required_text(
                item.get("artifact_path"),
                field_name=f"ooc.{field_name}.artifact_path",
            )
            payload_summary = _validate_ooc_artifact(
                artifact=item,
                run_directory=run_directory,
                field_name=f"ooc.{field_name}.artifacts",
                shared_artifact_store=shared_artifact_store,
            )
            records.append(
                {
                    "kind": field_name,
                    "artifact_path": artifact_directory,
                    "artifact_identity": _ooc_artifact_identity(item),
                    "manifest_hash": _required_text(
                        item.get("manifest_hash"), field_name=f"ooc.{field_name}.manifest_hash"
                    ),
                    **payload_summary,
                }
            )
    final_meta = _required_mapping(manifest.get("final_meta"), field_name="ooc.final_meta")
    final_meta_directory = _required_text(
        final_meta.get("artifact_path"), field_name="ooc.final_meta.artifact_path"
    )
    payload_summary = _validate_ooc_artifact(
        artifact=final_meta,
        run_directory=run_directory,
        field_name="ooc.final_meta.artifacts",
        shared_artifact_store=shared_artifact_store,
    )
    records.append(
        {
            "kind": "final_meta",
            "artifact_path": final_meta_directory,
            "artifact_identity": _ooc_artifact_identity(final_meta),
            "manifest_hash": _required_text(
                final_meta.get("manifest_hash"), field_name="ooc.final_meta.manifest_hash"
            ),
            **payload_summary,
        }
    )
    files = _iter_regular_files(run_directory)
    return {
        "run_directory_bytes": directory_size_bytes(run_directory),
        "file_count": len(files),
        "file_sha256_by_path": {
            relative: _sha256_file(path) for relative, path, _size in files
        },
        "artifact_record_count": len(records),
        "artifact_records": records,
    }


def _ooc_artifact_identity(artifact: Mapping[str, Any]) -> str:
    """用 artifact kind 與完整 scope 形成 QA 比較 key。"""

    return _canonical_json(
        {
            field_name: artifact.get(field_name)
            for field_name in (
                "artifact_kind",
                "fold_id",
                "pack_id",
                "horizon_trading_days",
                "algorithm",
                "expert_id",
            )
        }
    )


def _validate_ooc_artifact(
    *,
    artifact: Mapping[str, Any],
    run_directory: Path,
    field_name: str,
    shared_artifact_store: OOCSharedArtifactStore | None,
) -> dict[str, Any]:
    """驗證一份 local 或 shared immutable artifact 的所有 payload。"""

    expected_manifest_hash = _required_text(
        artifact.get("manifest_hash"), field_name=f"{field_name}.manifest_hash"
    )
    full_body = dict(artifact)
    full_body.pop("manifest_hash", None)
    # ``artifact_path`` is run manifest routing metadata appended after the
    # artifact's own immutable manifest hash; it is not part of the shared
    # descriptor core.
    full_body.pop("artifact_path", None)
    full_body.pop("_run_directory", None)
    if _sha256_json(full_body) != expected_manifest_hash:
        raise EvidenceError(f"{field_name} manifest hash mismatch")
    references = _required_list(artifact.get("artifacts"), field_name=field_name)
    shared_reference = artifact.get("shared_artifact_reference")
    payload_paths: dict[str, Path] = {}
    storage = "run_local"
    key_hash: str | None = None
    if shared_reference is not None:
        if shared_artifact_store is None:
            raise EvidenceError(
                f"{field_name} declares shared artifact without shared registry"
            )
        try:
            resolution = shared_artifact_store.resolve_reference(
                _required_mapping(
                    shared_reference,
                    field_name=f"{field_name}.shared_artifact_reference",
                )
            )
        except (OSError, TypeError, ValueError, KeyError) as exc:
            raise EvidenceError(
                f"{field_name} shared reference cannot be resolved"
            ) from exc
        key_hash = _required_text(
            artifact.get("shared_artifact_key_hash"),
            field_name=f"{field_name}.shared_artifact_key_hash",
        )
        if key_hash != resolution.semantic_key_hash:
            raise EvidenceError(f"{field_name} shared semantic key mismatch")
        core = dict(artifact)
        core.pop("manifest_hash", None)
        core.pop("shared_artifact_reference", None)
        core.pop("artifact_path", None)
        core.pop("_run_directory", None)
        if _sha256_json(core) != resolution.core_manifest_hash:
            raise EvidenceError(f"{field_name} shared core manifest hash mismatch")
        if core != dict(resolution.artifact_manifest):
            raise EvidenceError(f"{field_name} shared core manifest differs")
        payload_paths = dict(resolution.file_paths)
        storage = "shared_immutable"
    else:
        _validate_ooc_artifact_files(
            run_directory=run_directory,
            artifact_directory=_required_text(
                artifact.get("artifact_path"),
                field_name=f"{field_name}.artifact_path",
            ),
            artifact_refs=references,
            field_name=field_name,
        )
        base = (
            run_directory
            / _required_text(
                artifact.get("artifact_path"),
                field_name=f"{field_name}.artifact_path",
            )
        ).resolve()
        for raw_reference in references:
            reference = _required_mapping(raw_reference, field_name=f"{field_name}.item")
            relative = _required_text(
                reference.get("path"), field_name=f"{field_name}.path"
            )
            payload_paths[relative] = (base / relative).resolve()

    payload_hashes: dict[str, str] = {}
    for raw_reference in references:
        reference = _required_mapping(raw_reference, field_name=f"{field_name}.item")
        relative = _required_text(
            reference.get("path"), field_name=f"{field_name}.path"
        )
        path = payload_paths.get(relative)
        if path is None or not path.is_file():
            raise EvidenceError(f"{field_name} payload is missing: {relative}")
        expected_bytes = _required_int(
            reference.get("byte_count"), field_name=f"{field_name}.byte_count"
        )
        if int(path.stat().st_size) != expected_bytes:
            raise EvidenceError(f"{field_name} payload size mismatch: {relative}")
        expected_hash = _required_text(
            reference.get("file_sha256"), field_name=f"{field_name}.file_sha256"
        )
        actual_hash = _sha256_file(path)
        if actual_hash != expected_hash:
            raise EvidenceError(f"{field_name} payload hash mismatch: {relative}")
        payload_hashes[relative] = actual_hash
    # Shared descriptors must cover exactly the run manifest's listed
    # payloads; local validation already checked path traversal/coverage.
    if storage == "shared_immutable" and set(payload_hashes) != set(payload_paths):
        raise EvidenceError(f"{field_name} shared payload coverage differs")
    return {
        "artifact_storage": storage,
        "shared_artifact_key_hash": key_hash,
        "payload_hashes": dict(sorted(payload_hashes.items())),
    }


def _validate_ooc_artifact_files(
    *,
    run_directory: Path,
    artifact_directory: str,
    artifact_refs: object,
    field_name: str,
) -> None:
    references = _required_list(artifact_refs, field_name=field_name)
    base = (run_directory / artifact_directory).resolve()
    if run_directory.resolve() not in base.parents:
        raise EvidenceError(f"{field_name} escapes the OOC run directory")
    for raw_reference in references:
        reference = _required_mapping(raw_reference, field_name=f"{field_name}.item")
        relative_name = _required_text(
            reference.get("path"), field_name=f"{field_name}.path"
        )
        artifact_path = (base / relative_name).resolve()
        if base not in artifact_path.parents:
            raise EvidenceError(f"{field_name} contains a path traversal")
        if not artifact_path.is_file():
            raise EvidenceError(f"OOC artifact file is missing: {artifact_path}")
        expected_bytes = _required_int(
            reference.get("byte_count"), field_name=f"{field_name}.byte_count"
        )
        actual_bytes = int(artifact_path.stat().st_size)
        if actual_bytes != expected_bytes:
            raise EvidenceError(
                f"OOC artifact size mismatch: {artifact_path}: "
                f"{actual_bytes} != {expected_bytes}"
            )
        expected_hash = _required_text(
            reference.get("file_sha256"), field_name=f"{field_name}.file_sha256"
        )
        if _sha256_file(artifact_path) != expected_hash:
            raise EvidenceError(f"OOC artifact hash mismatch: {artifact_path}")


def _ooc_audit_event_types(run_directory: Path) -> dict[str, int]:
    """只讀讀取 OOC custody event，保存第二次實際 reuse 的階段證據。"""

    audit_path = run_directory / "custody.sqlite"
    if not audit_path.is_file():
        raise EvidenceError(f"OOC custody sqlite is missing: {audit_path}")
    try:
        connection = sqlite3.connect(
            f"file:{audit_path.as_posix()}?mode=ro",
            uri=True,
        )
        try:
            rows = connection.execute(
                "SELECT event_type, COUNT(*) FROM custody_events GROUP BY event_type"
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        raise EvidenceError(f"cannot read OOC custody sqlite: {audit_path}") from exc
    return {str(event_type): int(count) for event_type, count in rows}


def _compare_ooc_runs(
    *,
    first_inventory: Mapping[str, Any],
    second_inventory: Mapping[str, Any],
    first_events: Mapping[str, int],
    second_events: Mapping[str, int],
) -> dict[str, Any]:
    first_records = {
        str(item["artifact_identity"]): item
        for item in _required_list(
            first_inventory.get("artifact_records"),
            field_name="ooc.first.artifact_records",
        )
    }
    second_records = {
        str(item["artifact_identity"]): item
        for item in _required_list(
            second_inventory.get("artifact_records"),
            field_name="ooc.second.artifact_records",
        )
    }
    if set(first_records) != set(second_records):
        raise EvidenceError("OOC runs do not cover the same artifact identities")
    comparisons: list[dict[str, Any]] = []
    for identity in sorted(first_records):
        first = first_records[identity]
        second = second_records[identity]
        first_key = first.get("shared_artifact_key_hash")
        second_key = second.get("shared_artifact_key_hash")
        first_payloads = first.get("payload_hashes")
        second_payloads = second.get("payload_hashes")
        comparisons.append(
            {
                "artifact_identity": identity,
                "same_semantic_key": first_key == second_key,
                "same_payload_hashes": first_payloads == second_payloads,
                "first_storage": first.get("artifact_storage"),
                "second_storage": second.get("artifact_storage"),
                "shared_artifact_key_hash": second_key,
                "payload_hashes": second_payloads,
            }
        )
    required_reuse_events = {
        "base_expert_shared_reused",
        "final_base_expert_shared_reused",
        "meta_fold_shared_reused",
        "final_meta_shared_reused",
    }
    observed_reuse_events = {
        event_type
        for event_type, count in second_events.items()
        if count > 0
    }
    return {
        "artifact_count": len(comparisons),
        "all_semantic_keys_equal": all(
            bool(item["same_semantic_key"]) for item in comparisons
        ),
        "all_payload_hashes_equal": all(
            bool(item["same_payload_hashes"]) for item in comparisons
        ),
        "all_second_artifacts_shared": all(
            item["second_storage"] == "shared_immutable" for item in comparisons
        ),
        "second_run_reuse_events_complete": required_reuse_events.issubset(
            observed_reuse_events
        ),
        "required_reuse_event_types": sorted(required_reuse_events),
        "first_run_event_counts": dict(sorted(first_events.items())),
        "second_run_event_counts": dict(sorted(second_events.items())),
        "artifacts": comparisons,
    }


def build_report(
    *,
    direct_first_path: Path,
    direct_second_path: Path,
    shared_numeric_store: Path,
    ooc_manifest_path: Path,
    output_dir: Path,
    before_snapshot_path: Path | None = None,
    after_snapshot_path: Path | None = None,
    ooc_shared_artifact_store: Path | None = None,
    ooc_second_manifest_path: Path | None = None,
    shared_artifact_before_snapshot_path: Path | None = None,
    shared_artifact_after_snapshot_path: Path | None = None,
) -> dict[str, Any]:
    direct_first, direct_first_meta = _load_hashed_manifest(
        direct_first_path, expected_schema="portfolio-ml-ooc-store.v3"
    )
    direct_second, direct_second_meta = _load_hashed_manifest(
        direct_second_path, expected_schema="portfolio-ml-ooc-store.v3"
    )
    ooc_manifest, ooc_meta = _load_hashed_manifest(
        ooc_manifest_path, expected_schema="allocation-ooc-training.v5"
    )
    ooc_second_manifest: dict[str, Any] | None = None
    ooc_second_meta: dict[str, str | int] | None = None
    if ooc_second_manifest_path is not None:
        if ooc_shared_artifact_store is None:
            raise EvidenceError(
                "second OOC manifest requires --ooc-shared-artifact-store"
            )
        ooc_second_manifest, ooc_second_meta = _load_hashed_manifest(
            ooc_second_manifest_path,
            expected_schema="allocation-ooc-training.v5",
        )
    source_roots_list: list[Path] = [
        direct_first_path.parent,
        direct_second_path.parent,
        shared_numeric_store,
        ooc_manifest_path.parent,
    ]
    if ooc_shared_artifact_store is not None:
        source_roots_list.append(ooc_shared_artifact_store)
    if ooc_second_manifest_path is not None:
        source_roots_list.append(ooc_second_manifest_path.parent)
    source_roots = tuple(source_roots_list)
    output = _ensure_output_disjoint(output_dir, source_roots=source_roots)

    first_summary = _direct_run_summary(
        path=direct_first_path,
        manifest=direct_first,
        metadata=direct_first_meta,
    )
    second_summary = _direct_run_summary(
        path=direct_second_path,
        manifest=direct_second,
        metadata=direct_second_meta,
    )
    first_years = {int(item["year"]): item for item in first_summary["years"]}
    second_years = {int(item["year"]): item for item in second_summary["years"]}
    if set(first_years) != set(second_years):
        raise EvidenceError("Direct runs do not cover the same years")
    year_comparisons: list[dict[str, Any]] = []
    for year in sorted(first_years):
        first = first_years[year]
        second = second_years[year]
        same_keys = (
            first["descriptor_key_hash"] == second["descriptor_key_hash"]
            and first["artifact_key_hashes"] == second["artifact_key_hashes"]
        )
        second_reused = bool(second["reuse_before_build"])
        second_new_bytes = int(second["new_bytes_written"])
        year_comparisons.append(
            {
                "year": year,
                "descriptor_key_hash": second["descriptor_key_hash"],
                "artifact_key_hashes": second["artifact_key_hashes"],
                "artifact_object_hashes": second["artifact_object_hashes"],
                "same_semantic_keys": same_keys,
                "second_run_reuse_before_build": second_reused,
                "second_run_new_bytes_written": second_new_bytes,
                "first_run_new_bytes_written": int(first["new_bytes_written"]),
                "second_run_local_year_files": second_summary["run_local_year_files"].get(
                    str(year), []
                ),
            }
        )
    direct_store = _shared_registry_summary(shared_numeric_store)
    ooc_run_directory = ooc_manifest_path.parent
    ooc_execution = _required_mapping(ooc_manifest.get("execution"), field_name="ooc.execution")
    ooc_store_hash = _required_text(
        ooc_manifest.get("store_manifest_hash"), field_name="ooc.store_manifest_hash"
    )
    if ooc_store_hash != direct_second_meta["manifest_hash"]:
        raise EvidenceError("OOC store manifest hash does not point to Direct B")
    ooc_store_file_hash = _required_text(
        ooc_manifest.get("store_manifest_file_hash"), field_name="ooc.store_manifest_file_hash"
    )
    if ooc_store_file_hash != direct_second_meta["file_sha256"]:
        raise EvidenceError("OOC store manifest file hash does not point to Direct B")

    ooc_shared_store = (
        None
        if ooc_shared_artifact_store is None
        else OOCSharedArtifactStore(ooc_shared_artifact_store)
    )

    resume_comparison: dict[str, Any] | None = None
    if (before_snapshot_path is None) != (after_snapshot_path is None):
        raise EvidenceError("before and after OOC snapshots must be supplied together")
    if before_snapshot_path is not None and after_snapshot_path is not None:
        before = _load_snapshot(before_snapshot_path, expected_root=ooc_run_directory)
        after = _load_snapshot(after_snapshot_path, expected_root=ooc_run_directory)
        resume_comparison = _compare_snapshot_files(before, after)

    ooc_artifacts = _ooc_artifact_inventory(
        manifest=ooc_manifest,
        run_directory=ooc_run_directory,
        shared_artifact_store=ooc_shared_store,
    )
    ooc_reuse_comparison: dict[str, Any] | None = None
    ooc_second_artifacts: dict[str, Any] | None = None
    shared_artifact_snapshot_comparison: dict[str, Any] | None = None
    if ooc_second_manifest is not None and ooc_second_manifest_path is not None:
        ooc_second_run_directory = ooc_second_manifest_path.parent
        ooc_second_artifacts = _ooc_artifact_inventory(
            manifest=ooc_second_manifest,
            run_directory=ooc_second_run_directory,
            shared_artifact_store=ooc_shared_store,
        )
        first_events = _ooc_audit_event_types(ooc_run_directory)
        second_events = _ooc_audit_event_types(ooc_second_run_directory)
        ooc_reuse_comparison = _compare_ooc_runs(
            first_inventory=ooc_artifacts,
            second_inventory=ooc_second_artifacts,
            first_events=first_events,
            second_events=second_events,
        )
    if (shared_artifact_before_snapshot_path is None) != (
        shared_artifact_after_snapshot_path is None
    ):
        raise EvidenceError(
            "shared artifact before and after snapshots must be supplied together"
        )
    if (
        shared_artifact_before_snapshot_path is not None
        and shared_artifact_after_snapshot_path is not None
    ):
        if ooc_shared_artifact_store is None:
            raise EvidenceError(
                "shared artifact snapshots require --ooc-shared-artifact-store"
            )
        shared_before = _load_snapshot(
            shared_artifact_before_snapshot_path,
            expected_root=ooc_shared_artifact_store,
        )
        shared_after = _load_snapshot(
            shared_artifact_after_snapshot_path,
            expected_root=ooc_shared_artifact_store,
        )
        shared_artifact_snapshot_comparison = _compare_snapshot_files(
            shared_before,
            shared_after,
        )
    ooc_identity = _required_mapping(ooc_manifest.get("run_identity"), field_name="ooc.run_identity")
    ooc_promotion = _required_mapping(ooc_manifest.get("promotion"), field_name="ooc.promotion")
    ooc_validation = _required_mapping(ooc_manifest.get("validation"), field_name="ooc.validation")
    lineage = {
        "direct_first_manifest": first_summary,
        "direct_second_manifest": second_summary,
        "ooc_manifest": {
            **ooc_meta,
            "run_id": _required_text(ooc_manifest.get("run_id"), field_name="ooc.run_id"),
            "dataset_identity_hash": _required_text(
                ooc_manifest.get("dataset_identity_hash"), field_name="ooc.dataset_identity_hash"
            ),
            "store_manifest_hash": ooc_store_hash,
            "store_manifest_file_hash": ooc_store_file_hash,
        },
    }
    if ooc_second_manifest is not None and ooc_second_meta is not None:
        lineage["ooc_second_manifest"] = {
            **ooc_second_meta,
            "run_id": _required_text(
                ooc_second_manifest.get("run_id"),
                field_name="ooc.second.run_id",
            ),
            "dataset_identity_hash": _required_text(
                ooc_second_manifest.get("dataset_identity_hash"),
                field_name="ooc.second.dataset_identity_hash",
            ),
            "store_manifest_hash": _required_text(
                ooc_second_manifest.get("store_manifest_hash"),
                field_name="ooc.second.store_manifest_hash",
            ),
            "store_manifest_file_hash": _required_text(
                ooc_second_manifest.get("store_manifest_file_hash"),
                field_name="ooc.second.store_manifest_file_hash",
            ),
        }
    if ooc_shared_artifact_store is not None:
        lineage["ooc_shared_artifact_store"] = _shared_registry_summary(
            ooc_shared_artifact_store
        )
    manifest_body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "bounded_shared_reuse_evidence_completed",
        "scope": {
            "input_mode": "accepted_repo_output_only",
            "source_data_modified": False,
            "new_fold_read": False,
            "full_history_rebuilt": False,
            "bounded_direct_cli_runs": 2,
            "bounded_ooc_training_runs": (
                2 if ooc_second_manifest is not None else 1
            ),
            "bounded_ooc_resume_runs": 0 if ooc_second_manifest is not None else 2,
            "training_repeated_for_qa": False,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
            "persistent_new_bytes_budget": 1024**3,
            "temporary_peak_bytes_budget": 1024**3,
            "safety_reserve_bytes": 200 * 1024**3,
            "memory_budget_mb": 4096,
        },
        "lineage": lineage,
        "direct_numeric_reuse": {
            "shared_registry": direct_store,
            "same_run_identity": first_summary["run_id"] == second_summary["run_id"],
            "same_dataset_identity": first_summary["dataset_identity_hash"]
            == second_summary["dataset_identity_hash"],
            "same_year_semantic_keys": all(
                bool(item["same_semantic_keys"]) for item in year_comparisons
            ),
            "second_run_reused_before_build": all(
                bool(item["second_run_reuse_before_build"]) for item in year_comparisons
            ),
            "second_run_new_bytes_written": sum(
                int(item["second_run_new_bytes_written"]) for item in year_comparisons
            ),
            "first_run_new_bytes_written": sum(
                int(item["first_run_new_bytes_written"]) for item in year_comparisons
            ),
            "years": year_comparisons,
            "run_local_year_numeric_files": {
                "first": first_summary["run_local_year_files"],
                "second": second_summary["run_local_year_files"],
            },
        },
        "ooc_shared_consumer": {
            "run_id": _required_text(ooc_manifest.get("run_id"), field_name="ooc.run_id"),
            "training_profile": _required_text(
                ooc_manifest.get("training_profile"), field_name="ooc.training_profile"
            ),
            "algorithm": ooc_identity.get("algorithms"),
            "horizons": ooc_identity.get("horizons"),
            "store_manifest_hash": ooc_store_hash,
            "store_manifest_file_hash": ooc_store_file_hash,
            "row_count": _required_int(ooc_manifest.get("row_count"), field_name="ooc.row_count"),
            "feature_count": _required_int(
                ooc_manifest.get("feature_count"), field_name="ooc.feature_count"
            ),
            "base_expert_count": _required_int(
                ooc_manifest.get("base_expert_count"), field_name="ooc.base_expert_count"
            ),
            "meta_fold_count": _required_int(
                ooc_manifest.get("meta_fold_count"), field_name="ooc.meta_fold_count"
            ),
            "artifact_inventory": ooc_artifacts,
            "shared_artifact_store": (
                None
                if ooc_shared_artifact_store is None
                else _shared_registry_summary(ooc_shared_artifact_store)
            ),
            "second_run_artifact_inventory": ooc_second_artifacts,
            "shared_artifact_snapshot_comparison": shared_artifact_snapshot_comparison,
            "resume_snapshot_comparison": resume_comparison,
            "execution": {
                key: ooc_execution.get(key)
                for key in (
                    "peak_rss_bytes",
                    "memory_budget_mb",
                    "memory_budget_enforced",
                    "capacity_quota_enforced_during_checkpoints",
                    "capacity_budget",
                )
            },
            "formal_oos_allowed": ooc_manifest.get("formal_oos_allowed"),
            "production_alpha_bp": ooc_manifest.get("production_alpha_bp"),
            "broker_order_allowed": ooc_manifest.get("broker_order_allowed"),
            "promotion_eligible": ooc_promotion.get("promotion_eligible"),
            "promotion_blockers": ooc_promotion.get("blockers"),
            "calibration_status": _required_mapping(
                ooc_validation.get("calibration"), field_name="ooc.validation.calibration"
            ).get("status"),
        },
        "ooc_cross_run_reuse_assessment": {
            "implemented": (
                ooc_reuse_comparison is not None
                and bool(ooc_reuse_comparison["all_semantic_keys_equal"])
                and bool(ooc_reuse_comparison["all_payload_hashes_equal"])
                and bool(ooc_reuse_comparison["all_second_artifacts_shared"])
                and bool(ooc_reuse_comparison["second_run_reuse_events_complete"])
            ),
            "current_resume_scope": (
                "two_independent_output_roots_with_shared_immutable_artifacts"
                if ooc_reuse_comparison is not None
                else "same_run_identity_and_output_root"
            ),
            "candidate_key_schema_version": "allocation-ooc-artifact-key.v1",
            "candidate_key_fields": [
                "artifact_schema_version",
                "artifact_kind_and_scope",
                "store_manifest_hash_and_file_hash",
                "dataset_identity_hash",
                "feature_registry_hash_and_order",
                "feature_scales_and_preprocessing_contract",
                "fold_id_and_train_test_reference_hashes",
                "fold_time_ranges_and_purge_embargo_policy",
                "algorithm_horizon_and_all_hyperparameters",
                "training_profile_and_complexity_policy",
                "rank_contract",
                "family_weight_policy",
                "calibration_contract_and_withheld_oof_identity",
                "maturity_policy_and_source_lineage",
                "implementation_contract_version",
            ],
            "isolation_rules": [
                "base_expert_oof、final_base、meta_oof、final_meta、calibrator 分開 key 與 registry namespace",
                "不同 feature pack、fold、horizon、profile、rank 或 family policy 不得共用 artifact",
                "校準器必須綁定實際 withheld OOF row identity、時間順序與 fit/calibration 不重疊證據",
                "reference 只保存相對 immutable object/key path；不引入可變 latest pointer",
                "publish 前使用 shared store canonical OS lock 並把 temporary 與 persistent bytes 一併預留",
                "artifact consumer 必須驗 key、content hash、schema 與 parent lineage；失效時重建新 key",
            ],
            "comparison": ooc_reuse_comparison,
            "shared_artifact_snapshot_comparison": shared_artifact_snapshot_comparison,
            "current_run_reuse_evidence": (
                "OOC run A/B consumed the same Direct B shared numeric store; "
                "each OOF/final-base/meta artifact resolved through the same "
                "semantic key and immutable payload reference."
                if ooc_reuse_comparison is not None
                else "OOC manifest is consumed from Direct B shared numeric references; "
                "this report did not receive a second OOC run."
            ),
        },
    }
    manifest_payload = {
        **manifest_body,
        "manifest_hash": _sha256_json(manifest_body),
    }
    summary_body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "bounded_shared_reuse_summary_completed",
        "evidence_manifest_hash": manifest_payload["manifest_hash"],
        "evidence_manifest_filename": "reuse_evidence_manifest.json",
        "direct": {
            "first_run_id": first_summary["run_id"],
            "second_run_id": second_summary["run_id"],
            "years": [int(item["year"]) for item in year_comparisons],
            "same_semantic_keys": manifest_body["direct_numeric_reuse"][
                "same_year_semantic_keys"
            ],
            "second_run_reused_before_build": manifest_body["direct_numeric_reuse"][
                "second_run_reused_before_build"
            ],
            "first_run_new_bytes_written": manifest_body["direct_numeric_reuse"][
                "first_run_new_bytes_written"
            ],
            "second_run_new_bytes_written": manifest_body["direct_numeric_reuse"][
                "second_run_new_bytes_written"
            ],
            "shared_registry_bytes": direct_store["directory_size_bytes"],
        },
        "ooc": {
            "run_id": ooc_manifest["run_id"],
            "status": ooc_manifest["status"],
            "training_profile": ooc_manifest["training_profile"],
            "store_manifest_hash": ooc_store_hash,
            "artifact_directory_bytes": ooc_artifacts["run_directory_bytes"],
            "resume_snapshot_comparison": resume_comparison,
            "second_run_id": (
                None
                if ooc_second_manifest is None
                else ooc_second_manifest.get("run_id")
            ),
            "cross_run_model_reuse_implemented": manifest_body[
                "ooc_cross_run_reuse_assessment"
            ]["implemented"],
            "cross_run_comparison": ooc_reuse_comparison,
            "shared_artifact_snapshot_comparison": shared_artifact_snapshot_comparison,
            "formal_oos_allowed": ooc_manifest["formal_oos_allowed"],
            "production_alpha_bp": ooc_manifest["production_alpha_bp"],
        },
        "scope": manifest_body["scope"],
    }
    summary_payload = {
        **summary_body,
        "summary_hash": _sha256_json(summary_body),
    }
    _atomic_create_json(output / "reuse_evidence_manifest.json", manifest_payload)
    _atomic_create_json(output / "reuse_summary.json", summary_payload)
    return {
        "output_dir": str(output),
        "manifest_path": str((output / "reuse_evidence_manifest.json").resolve()),
        "manifest_hash": manifest_payload["manifest_hash"],
        "manifest_file_sha256": _sha256_file(output / "reuse_evidence_manifest.json"),
        "summary_path": str((output / "reuse_summary.json").resolve()),
        "summary_hash": summary_payload["summary_hash"],
        "summary_file_sha256": _sha256_file(output / "reuse_summary.json"),
        "direct_second_run_new_bytes_written": manifest_body["direct_numeric_reuse"][
            "second_run_new_bytes_written"
        ],
        "shared_registry_bytes": direct_store["directory_size_bytes"],
        "ooc_artifact_directory_bytes": ooc_artifacts["run_directory_bytes"],
        "ooc_resume_snapshot_comparison": resume_comparison,
        "ooc_cross_run_model_reuse_implemented": manifest_body[
            "ooc_cross_run_reuse_assessment"
        ]["implemented"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot", help="保存 OOC run 檔案 hash 快照")
    snapshot.add_argument("--root", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    report = subparsers.add_parser("report", help="建立 bounded Direct/OOC reuse evidence")
    report.add_argument("--direct-first-manifest", type=Path, required=True)
    report.add_argument("--direct-second-manifest", type=Path, required=True)
    report.add_argument("--shared-numeric-store", type=Path, required=True)
    report.add_argument("--ooc-manifest", type=Path, required=True)
    report.add_argument(
        "--ooc-second-manifest",
        type=Path,
        help="第二個獨立 OOC output root 的完成 manifest",
    )
    report.add_argument(
        "--ooc-shared-artifact-store",
        type=Path,
        help="OOC artifact semantic key／payload shared registry",
    )
    report.add_argument("--output-dir", type=Path, required=True)
    report.add_argument("--before-snapshot", type=Path)
    report.add_argument("--after-snapshot", type=Path)
    report.add_argument(
        "--shared-artifact-before-snapshot",
        type=Path,
        help="shared artifact registry 在第二次 OOC run 前的 snapshot",
    )
    report.add_argument(
        "--shared-artifact-after-snapshot",
        type=Path,
        help="shared artifact registry 在第二次 OOC run 後的 snapshot",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            result = snapshot_directory(root=args.root, output_path=args.output)
        else:
            result = build_report(
                direct_first_path=args.direct_first_manifest,
                direct_second_path=args.direct_second_manifest,
                shared_numeric_store=args.shared_numeric_store,
                ooc_manifest_path=args.ooc_manifest,
                output_dir=args.output_dir,
                before_snapshot_path=args.before_snapshot,
                after_snapshot_path=args.after_snapshot,
                ooc_shared_artifact_store=args.ooc_shared_artifact_store,
                ooc_second_manifest_path=args.ooc_second_manifest,
                shared_artifact_before_snapshot_path=(
                    args.shared_artifact_before_snapshot
                ),
                shared_artifact_after_snapshot_path=(
                    args.shared_artifact_after_snapshot
                ),
            )
    except (EvidenceError, OSError, TypeError, ValueError, KeyError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
