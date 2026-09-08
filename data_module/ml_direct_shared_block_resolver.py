"""Direct numeric 年度 artifact 的 immutable shared reference。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ml_module.immutable_ml_block_store import (
    ImmutableBlockKey,
    load_immutable_block,
    publish_immutable_block,
    publish_immutable_block_file,
)


DIRECT_NUMERIC_ARTIFACT_REFERENCE_SCHEMA_VERSION = (
    "portfolio-ml-direct-numeric-artifact-reference.v1"
)
# v2 explicitly binds annual semantic dependencies (including sector custody
# and the pre-build descriptor contract); v1 references remain loadable but
# are never silently reused by the new builder.
DIRECT_NUMERIC_ARTIFACT_KEY_VERSION = "direct-numeric-year-key.v2"
DIRECT_NUMERIC_MATURITY_POLICY_VERSION = (
    "direct-numeric-maturity-v1"
)
DIRECT_NUMERIC_YEAR_DESCRIPTOR_SCHEMA_VERSION = (
    "portfolio-ml-direct-year-descriptor.v1"
)
DIRECT_NUMERIC_YEAR_DESCRIPTOR_ARTIFACT_ID = "year.descriptor.json"
DIRECT_NUMERIC_ARTIFACT_IDS = (
    "features.values.i64",
    "features.masks.u8",
    "targets.i32",
    "labels.i32",
    "labels.masks.u8",
    "rows.sqlite",
    "replay_source.sqlite",
    "carry.state.gz",
)

_SHA256_PREFIX = "sha256:"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _required_sha256(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(_SHA256_PREFIX)
        or len(value) != len(_SHA256_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{field_name} must be a sha256: digest")
    return value


def direct_numeric_artifact_key(
    *,
    artifact_id: str,
    year: int,
    source_version: str,
    source_manifest_hashes: Sequence[tuple[str, str]],
    feature_contract_hash: str,
    label_contract_hash: str,
    time_start: str,
    time_end: str,
    encoding: str,
    lane: str = "formal",
    maturity_policy: str = DIRECT_NUMERIC_MATURITY_POLICY_VERSION,
) -> ImmutableBlockKey:
    """建立年度 artifact key；所有資料／carry 依賴必須先進 source hashes。"""

    if artifact_id not in DIRECT_NUMERIC_ARTIFACT_IDS:
        raise ValueError(f"unsupported direct numeric artifact: {artifact_id}")
    if isinstance(year, bool) or not isinstance(year, int):
        raise TypeError("year must be integer")
    if year < 1_900 or year > 3_000:
        raise ValueError("year is outside supported range")
    _required_text(source_version, field_name="source_version")
    _required_text(encoding, field_name="encoding")
    return ImmutableBlockKey(
        block_type=f"portfolio-ml-direct-numeric/{artifact_id}",
        artifact_schema_version=(
            f"{DIRECT_NUMERIC_ARTIFACT_REFERENCE_SCHEMA_VERSION}:{artifact_id}"
        ),
        source_version=(
            f"{DIRECT_NUMERIC_ARTIFACT_KEY_VERSION}:year={year}:"
            f"{source_version}"
        ),
        source_manifest_hashes=tuple(source_manifest_hashes),
        feature_contract_hash=_required_sha256(
            feature_contract_hash,
            field_name="feature_contract_hash",
        ),
        label_contract_hash=_required_sha256(
            label_contract_hash,
            field_name="label_contract_hash",
        ),
        maturity_policy=_required_text(
            maturity_policy,
            field_name="maturity_policy",
        ),
        time_start=_required_text(time_start, field_name="time_start"),
        time_end=_required_text(time_end, field_name="time_end"),
        encoding=encoding,
        lane=lane,
    )


def publish_direct_numeric_artifact(
    *,
    store_root: Path,
    source_path: Path,
    key: ImmutableBlockKey,
    temporary_roots: Sequence[Path] = (),
    temporary_peak_bytes_observed: int | None = None,
    temporary_budget_bytes: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """串流發布單一年度 artifact，回傳 telemetry 與可搬移 manifest entry。"""

    if not source_path.is_file() or source_path.is_symlink():
        raise ValueError(f"direct numeric artifact source is not a regular file: {source_path}")
    result = publish_immutable_block_file(
        store_root=store_root,
        key=key,
        source_path=source_path,
        temporary_roots=temporary_roots,
        temporary_peak_bytes_observed=temporary_peak_bytes_observed,
        temporary_budget_bytes=temporary_budget_bytes,
    )
    reference = result.get("reference")
    if not isinstance(reference, Mapping):
        raise ValueError("immutable publisher did not return a block reference")
    entry = {
        "artifact_id": key.block_type.rsplit("/", 1)[-1],
        "storage": "immutable_shared",
        "byte_count": int(result["object_bytes"]),
        "file_sha256": _required_sha256(
            result.get("object_hash"),
            field_name="object_hash",
        ),
        "block_reference": dict(reference),
    }
    return result, entry


def direct_numeric_year_descriptor_key(
    *,
    year: int,
    source_version: str,
    source_manifest_hashes: Sequence[tuple[str, str]],
    feature_contract_hash: str,
    label_contract_hash: str,
    time_start: str,
    time_end: str,
    lane: str = "formal",
    maturity_policy: str = DIRECT_NUMERIC_MATURITY_POLICY_VERSION,
) -> ImmutableBlockKey:
    """建立不含 output shape 的年度 descriptor key，供 pre-build reuse。"""

    if isinstance(year, bool) or not isinstance(year, int):
        raise TypeError("year must be integer")
    return ImmutableBlockKey(
        block_type="portfolio-ml-direct-numeric/year-descriptor",
        artifact_schema_version=DIRECT_NUMERIC_YEAR_DESCRIPTOR_SCHEMA_VERSION,
        source_version=(
            f"{DIRECT_NUMERIC_ARTIFACT_KEY_VERSION}:year={year}:"
            f"{_required_text(source_version, field_name='source_version')}"
        ),
        source_manifest_hashes=tuple(source_manifest_hashes),
        feature_contract_hash=_required_sha256(
            feature_contract_hash,
            field_name="feature_contract_hash",
        ),
        label_contract_hash=_required_sha256(
            label_contract_hash,
            field_name="label_contract_hash",
        ),
        maturity_policy=_required_text(
            maturity_policy,
            field_name="maturity_policy",
        ),
        time_start=_required_text(time_start, field_name="time_start"),
        time_end=_required_text(time_end, field_name="time_end"),
        encoding="json:direct-year-descriptor.v1",
        lane=lane,
    )


def _reference_entry(
    *,
    artifact_id: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    reference = result.get("reference")
    if not isinstance(reference, Mapping):
        raise ValueError("immutable publisher did not return a block reference")
    return {
        "artifact_id": artifact_id,
        "storage": "immutable_shared",
        "byte_count": int(result["object_bytes"]),
        "file_sha256": _required_sha256(
            result.get("object_hash"),
            field_name="object_hash",
        ),
        "block_reference": dict(reference),
    }


def publish_direct_year_descriptor(
    *,
    store_root: Path,
    key: ImmutableBlockKey,
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """發布小型年度 metadata，讓後續 run 可在 build 前重用 numeric refs。"""

    if key.block_type != "portfolio-ml-direct-numeric/year-descriptor":
        raise ValueError("descriptor key block type is invalid")
    body = dict(payload)
    body.setdefault(
        "schema_version",
        DIRECT_NUMERIC_YEAR_DESCRIPTOR_SCHEMA_VERSION,
    )
    body["descriptor_key_hash"] = key.key_hash
    raw = (
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    result = publish_immutable_block(
        store_root=Path(store_root).resolve(),
        key=key,
        raw=raw,
    )
    return result, _reference_entry(
        artifact_id=DIRECT_NUMERIC_YEAR_DESCRIPTOR_ARTIFACT_ID,
        result=result,
    )


def _load_block_by_key(
    *,
    store_root: Path,
    key: ImmutableBlockKey,
) -> Any | None:
    key_path = (
        Path(store_root).resolve()
        / "keys"
        / f"{key.key_hash[7:]}.json"
    )
    if not key_path.is_file():
        return None
    try:
        record = json.loads(key_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("direct shared descriptor key record is unreadable") from exc
    if not isinstance(record, Mapping):
        raise ValueError("direct shared descriptor key record is invalid")
    if record.get("key_hash") != key.key_hash:
        raise ValueError("direct shared descriptor key hash mismatch")
    record_key = record.get("key")
    if not isinstance(record_key, Mapping) or dict(record_key) != key.payload():
        raise ValueError("direct shared descriptor semantic key mismatch")
    object_reference = record.get("object")
    if not isinstance(object_reference, Mapping):
        raise ValueError("direct shared descriptor object reference is missing")
    key_manifest = {
        "path": key_path.relative_to(Path(store_root).resolve()).as_posix(),
        "sha256": _file_sha256(key_path),
        "bytes": key_path.stat().st_size,
    }
    return load_immutable_block(
        store_root=Path(store_root).resolve(),
        reference={
            "schema_version": "ml-immutable-block-reference.v1",
            "store_schema_version": "ml-immutable-block-store.v1",
            "key_hash": key.key_hash,
            "key": key.payload(),
            "key_manifest": key_manifest,
            "object": dict(object_reference),
        },
    )


def find_direct_year_descriptor(
    *,
    store_root: Path,
    key: ImmutableBlockKey,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """依 exact semantic key 找 descriptor；找不到時不讀取 numeric source。"""

    block = _load_block_by_key(store_root=Path(store_root), key=key)
    if block is None:
        return None
    try:
        payload = json.loads(block.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("direct shared year descriptor JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("direct shared year descriptor must be an object")
    if payload.get("schema_version") != DIRECT_NUMERIC_YEAR_DESCRIPTOR_SCHEMA_VERSION:
        raise ValueError("direct shared year descriptor schema mismatch")
    if payload.get("descriptor_key_hash") != key.key_hash:
        raise ValueError("direct shared year descriptor key binding mismatch")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("direct shared year descriptor artifacts are missing")
    descriptor_entry = {
        "artifact_id": DIRECT_NUMERIC_YEAR_DESCRIPTOR_ARTIFACT_ID,
        "storage": "immutable_shared",
        "byte_count": block.object_bytes,
        "file_sha256": block.object_hash,
        "block_reference": dict(block.reference),
    }
    return payload, descriptor_entry


def resolve_direct_year_descriptor(
    entry: Mapping[str, Any],
    *,
    shared_store_root: Path,
) -> dict[str, Any]:
    """讀取並驗證已保存的年度 descriptor。"""

    expected_fields = {
        "artifact_id",
        "storage",
        "byte_count",
        "file_sha256",
        "block_reference",
    }
    if set(entry) != expected_fields:
        raise ValueError("direct year descriptor entry fields are invalid")
    if entry.get("artifact_id") != DIRECT_NUMERIC_YEAR_DESCRIPTOR_ARTIFACT_ID:
        raise ValueError("direct year descriptor artifact id is invalid")
    if entry.get("storage") != "immutable_shared":
        raise ValueError("direct year descriptor is not shared")
    byte_count = entry.get("byte_count")
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
        raise ValueError("direct year descriptor byte_count is invalid")
    file_hash = _required_sha256(
        entry.get("file_sha256"),
        field_name="direct year descriptor file_sha256",
    )
    reference = entry.get("block_reference")
    if not isinstance(reference, Mapping):
        raise ValueError("direct year descriptor block_reference is missing")
    block = load_immutable_block(
        store_root=Path(shared_store_root).resolve(),
        reference=reference,
    )
    if block.object_bytes != byte_count or block.object_hash != file_hash:
        raise ValueError("direct year descriptor bytes/hash mismatch")
    if block.key.block_type != "portfolio-ml-direct-numeric/year-descriptor":
        raise ValueError("direct year descriptor key type is invalid")
    try:
        payload = json.loads(block.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("direct year descriptor JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("direct year descriptor must be an object")
    if payload.get("schema_version") != DIRECT_NUMERIC_YEAR_DESCRIPTOR_SCHEMA_VERSION:
        raise ValueError("direct year descriptor schema mismatch")
    if payload.get("descriptor_key_hash") != block.key.key_hash:
        raise ValueError("direct year descriptor key binding mismatch")
    return payload


def resolve_direct_numeric_artifact(
    entry: Mapping[str, Any],
    *,
    shared_store_root: Path,
) -> Path:
    """驗證 shared reference 後回傳 immutable object path。"""

    expected_fields = {
        "artifact_id",
        "storage",
        "byte_count",
        "file_sha256",
        "block_reference",
    }
    if set(entry) != expected_fields:
        raise ValueError("direct shared artifact entry fields are invalid")
    artifact_id = entry.get("artifact_id")
    if artifact_id not in DIRECT_NUMERIC_ARTIFACT_IDS:
        raise ValueError("direct shared artifact id is invalid")
    if entry.get("storage") != "immutable_shared":
        raise ValueError("direct artifact is not an immutable shared entry")
    byte_count = entry.get("byte_count")
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
        raise ValueError("direct shared artifact byte_count is invalid")
    file_hash = _required_sha256(
        entry.get("file_sha256"),
        field_name="direct shared artifact file_sha256",
    )
    reference = entry.get("block_reference")
    if not isinstance(reference, Mapping):
        raise ValueError("direct shared artifact block_reference is missing")
    block = load_immutable_block(
        store_root=Path(shared_store_root).resolve(),
        reference=reference,
    )
    if block.object_bytes != byte_count or block.object_hash != file_hash:
        raise ValueError("direct shared artifact bytes/hash mismatch")
    if block.key.block_type != f"portfolio-ml-direct-numeric/{artifact_id}":
        raise ValueError("direct shared artifact key does not bind artifact id")
    return block.object_path


def _local_artifact_path(
    entry: Mapping[str, Any],
    *,
    year_directory: Path,
    artifact_id: str,
) -> Path:
    path_value = entry.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError(f"local direct artifact path is missing: {artifact_id}")
    relative = Path(path_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("local direct artifact path must remain under year directory")
    path = (year_directory / relative).resolve()
    root = year_directory.resolve()
    if path != root and root not in path.parents:
        raise ValueError("local direct artifact path escapes year directory")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"local direct artifact is missing: {path}")
    byte_count = entry.get("byte_count")
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
        raise ValueError(f"local direct artifact byte_count is invalid: {artifact_id}")
    file_hash = _required_sha256(
        entry.get("file_sha256"),
        field_name=f"local direct artifact file_sha256[{artifact_id}]",
    )
    if path.stat().st_size != byte_count or _file_sha256(path) != file_hash:
        raise ValueError(f"local direct artifact bytes/hash mismatch: {artifact_id}")
    return path


def resolve_direct_year_artifact_paths(
    year_manifest: Mapping[str, Any],
    *,
    year_directory: Path,
    shared_store_root: Path | None = None,
) -> dict[str, Path]:
    """解析年度 manifest 的 local/shared artifact，拒絕遺失或混淆項目。"""

    raw_artifacts = year_manifest.get("artifacts")
    if not isinstance(raw_artifacts, (list, tuple)):
        raise ValueError("direct year artifacts must be an array")
    result: dict[str, Path] = {}
    for raw_entry in raw_artifacts:
        if not isinstance(raw_entry, Mapping):
            raise TypeError("direct year artifact entry must be an object")
        artifact_id = raw_entry.get("artifact_id")
        if artifact_id is None and isinstance(raw_entry.get("path"), str):
            artifact_id = Path(str(raw_entry["path"])).name
        if artifact_id not in DIRECT_NUMERIC_ARTIFACT_IDS:
            raise ValueError("direct year artifact id is invalid")
        artifact_name = str(artifact_id)
        if artifact_name in result:
            raise ValueError(f"duplicate direct year artifact: {artifact_name}")
        if raw_entry.get("storage") == "immutable_shared":
            if shared_store_root is None:
                raise ValueError(
                    "shared_store_root is required for immutable direct artifacts"
                )
            result[artifact_name] = resolve_direct_numeric_artifact(
                raw_entry,
                shared_store_root=shared_store_root,
            )
        else:
            result[artifact_name] = _local_artifact_path(
                raw_entry,
                year_directory=year_directory,
                artifact_id=artifact_name,
            )
    expected = set(DIRECT_NUMERIC_ARTIFACT_IDS)
    if set(result) != expected:
        missing = sorted(expected - set(result))
        extra = sorted(set(result) - expected)
        raise ValueError(
            "direct year artifacts are incomplete: "
            f"missing={missing}, extra={extra}"
        )
    return result


__all__ = [
    "DIRECT_NUMERIC_ARTIFACT_IDS",
    "DIRECT_NUMERIC_ARTIFACT_KEY_VERSION",
    "DIRECT_NUMERIC_ARTIFACT_REFERENCE_SCHEMA_VERSION",
    "DIRECT_NUMERIC_MATURITY_POLICY_VERSION",
    "DIRECT_NUMERIC_YEAR_DESCRIPTOR_ARTIFACT_ID",
    "DIRECT_NUMERIC_YEAR_DESCRIPTOR_SCHEMA_VERSION",
    "direct_numeric_artifact_key",
    "direct_numeric_year_descriptor_key",
    "find_direct_year_descriptor",
    "publish_direct_numeric_artifact",
    "publish_direct_year_descriptor",
    "resolve_direct_numeric_artifact",
    "resolve_direct_year_descriptor",
    "resolve_direct_year_artifact_paths",
]
