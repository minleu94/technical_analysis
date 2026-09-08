"""PIT 年度 shard 的跨 run immutable block resolver。

這個模組把既有 ``ml-pit-year-shard-dataset.v1`` 的 gzip bytes 發布成
shared block reference。原始 PIT publication 仍保持不變；新的 manifest 只
保存相對 reference，consumer 載入時直接讀 shared object，不把 bytes 複製回
run-local 目錄。沒有 shared reference 的舊 local manifest 仍由同一 resolver
依原 ``path``、compressed hash 與 content hash 驗證。

語意 key 的 ``source_version`` 同時綁定單一 shard 的語意 contract 與
compressed/content bytes hash。因而同一 publication 只改一個 shard 時，未改
shard 可以重用，改過的 shard 會產生新的 key/object；parent
publication/dataset hash 仍完整保留在 derived manifest 供 lineage audit。
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from ml_module.immutable_ml_block_store import (
    DEFAULT_MAX_STORE_BYTES,
    ImmutableBlockKey,
    load_immutable_block,
    publish_immutable_block,
    publish_immutable_block_file,
)


PIT_PUBLICATION_SCHEMA_VERSION = "ml-pit-year-shards.v1"
PIT_DATASET_SCHEMA_VERSION = "ml-pit-year-shard-dataset.v1"
SHARED_PIT_PUBLICATION_SCHEMA_VERSION = "ml-pit-shared-block-publication.v1"
SHARED_PIT_SHARD_RECORD_SCHEMA_VERSION = "ml-pit-shared-block-shard.v1"
_SHA256_PREFIX = "sha256:"
_PIT_BLOCK_TYPE = "pit_shard"
_PIT_ENCODING = "gzip_jsonl"
_PIT_MATURITY_POLICY = "raw_observed_only.v1"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_bytes(raw: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(raw).hexdigest()


def _sha256_json(payload: object) -> str:
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def pit_dataset_feature_contract_hash(
    dataset_manifest: Mapping[str, Any],
) -> str:
    """回傳與 PIT shared key 相同的 feature contract digest。"""

    return _sha256_json(
        {
            "schema_version": dataset_manifest.get("schema_version"),
            "dataset_id": dataset_manifest.get("dataset_id"),
            "format": dataset_manifest.get("format"),
            "features": dataset_manifest.get("features", []),
        }
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _required_hash(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(_SHA256_PREFIX)
        or len(value) != len(_SHA256_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{field_name} must be a sha256: digest")
    return value


def _read_json(path: Path, *, field_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} is not readable JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    return payload


def _verify_manifest_hash(
    payload: Mapping[str, Any],
    *,
    field_name: str,
) -> str:
    declared = _required_hash(payload.get("manifest_hash"), field_name=f"{field_name}.manifest_hash")
    body = dict(payload)
    body.pop("manifest_hash", None)
    actual = _sha256_json(body)
    if actual != declared:
        raise ValueError(f"{field_name} manifest_hash mismatch")
    return declared


def _path_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _safe_relative_path(root: Path, value: object, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute() or value.startswith(("/", "\\")):
        raise ValueError(f"{field_name} must be relative")
    if ".." in relative.parts:
        raise ValueError(f"{field_name} must not contain parent traversal")
    resolved = (root / relative).resolve()
    if not _path_inside(resolved, root):
        raise ValueError(f"{field_name} escapes root")
    return resolved


def _content_sha256(raw: bytes, *, field_name: str) -> str:
    try:
        digest = hashlib.sha256()
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
    except (OSError, EOFError) as exc:
        raise ValueError(f"{field_name} is not valid gzip JSONL") from exc
    return _SHA256_PREFIX + digest.hexdigest()


def _content_sha256_path(path: Path, *, field_name: str) -> str:
    """以串流 gzip 解壓計算 content hash，不把完整 shard 載入記憶體。"""

    try:
        digest = hashlib.sha256()
        with path.open("rb") as raw_handle:
            with gzip.GzipFile(fileobj=raw_handle, mode="rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(chunk)
    except (OSError, EOFError) as exc:
        raise ValueError(f"{field_name} is not valid gzip JSONL") from exc
    return _SHA256_PREFIX + digest.hexdigest()


def _validate_shard_bytes(
    raw: bytes,
    record: Mapping[str, Any],
    *,
    field_prefix: str,
) -> tuple[str, str, int]:
    compressed_hash = _required_hash(
        record.get("compressed_sha256"),
        field_name=f"{field_prefix}.compressed_sha256",
    )
    content_hash = _required_hash(
        record.get("content_sha256"),
        field_name=f"{field_prefix}.content_sha256",
    )
    declared_bytes = record.get("compressed_bytes")
    if (
        isinstance(declared_bytes, bool)
        or not isinstance(declared_bytes, int)
        or declared_bytes < 0
    ):
        raise ValueError(f"{field_prefix}.compressed_bytes must be non-negative integer")
    if len(raw) != declared_bytes:
        raise ValueError(f"{field_prefix}.compressed_bytes mismatch")
    if _sha256_bytes(raw) != compressed_hash:
        raise ValueError(f"{field_prefix}.compressed_sha256 mismatch")
    if _content_sha256(raw, field_name=field_prefix) != content_hash:
        raise ValueError(f"{field_prefix}.content_sha256 mismatch")
    return compressed_hash, content_hash, declared_bytes


def _validate_shard_path(
    path: Path,
    record: Mapping[str, Any],
    *,
    field_prefix: str,
) -> tuple[str, str, int]:
    """驗證檔案但只以串流方式讀取，供 assembler 直接消費 shared object。"""

    compressed_hash = _required_hash(
        record.get("compressed_sha256"),
        field_name=f"{field_prefix}.compressed_sha256",
    )
    content_hash = _required_hash(
        record.get("content_sha256"),
        field_name=f"{field_prefix}.content_sha256",
    )
    declared_bytes = record.get("compressed_bytes")
    if (
        isinstance(declared_bytes, bool)
        or not isinstance(declared_bytes, int)
        or declared_bytes < 0
    ):
        raise ValueError(f"{field_prefix}.compressed_bytes must be non-negative integer")
    if path.stat().st_size != declared_bytes:
        raise ValueError(f"{field_prefix}.compressed_bytes mismatch")
    if _file_sha256(path) != compressed_hash:
        raise ValueError(f"{field_prefix}.compressed_sha256 mismatch")
    if _content_sha256_path(path, field_name=field_prefix) != content_hash:
        raise ValueError(f"{field_prefix}.content_sha256 mismatch")
    return compressed_hash, content_hash, declared_bytes


@dataclass(frozen=True)
class PITResolvedShard:
    """已驗證的 local 或 shared PIT shard 路徑。"""

    path: Path
    compressed_sha256: str
    content_sha256: str
    compressed_bytes: int
    shared: bool

    def read_bytes(self) -> bytes:
        raw = self.path.read_bytes()
        _validate_shard_bytes(
            raw,
            {
                "compressed_sha256": self.compressed_sha256,
                "content_sha256": self.content_sha256,
                "compressed_bytes": self.compressed_bytes,
            },
            field_prefix="resolved shard",
        )
        return raw


def resolve_pit_shard_record(
    *,
    record: Mapping[str, Any],
    publication_root: Path,
    shared_store_root: Path | None = None,
    expected_feature_contract_hash: str | None = None,
    expected_maturity_policy: str | None = None,
    expected_lane: str | None = None,
) -> PITResolvedShard:
    """解析 shared reference 或舊 local path，兩者都重新驗證 bytes。"""

    block_reference = record.get("block_reference")
    if block_reference is not None:
        if shared_store_root is None:
            raise ValueError("shared_store_root is required for block_reference")
        block = load_immutable_block(
            store_root=Path(shared_store_root),
            reference=block_reference,
        )
        if block.key.block_type != _PIT_BLOCK_TYPE:
            raise ValueError("shared block is not a PIT shard")
        if block.key.artifact_schema_version != PIT_DATASET_SCHEMA_VERSION:
            raise ValueError("shared block artifact schema is not PIT dataset schema")
        if block.key.encoding != _PIT_ENCODING:
            raise ValueError("shared block encoding is not gzip_jsonl")
        if (
            expected_feature_contract_hash is not None
            and block.key.feature_contract_hash != expected_feature_contract_hash
        ):
            raise ValueError("shared block feature contract mismatch")
        if (
            expected_maturity_policy is not None
            and block.key.maturity_policy != expected_maturity_policy
        ):
            raise ValueError("shared block maturity policy mismatch")
        if expected_lane is not None and block.key.lane != expected_lane:
            raise ValueError("shared block lane mismatch")
        compressed_hash = record.get("compressed_sha256", block.object_hash)
        content_hash = record.get("content_sha256")
        if content_hash is None:
            content_hash = _content_sha256_path(
                block.object_path,
                field_name="shared shard",
            )
        _validate_shard_path(
            block.object_path,
            {
                "compressed_sha256": compressed_hash,
                "content_sha256": content_hash,
                "compressed_bytes": block.object_bytes,
            },
            field_prefix="shared shard",
        )
        return PITResolvedShard(
            path=block.object_path,
            compressed_sha256=str(compressed_hash),
            content_sha256=str(content_hash),
            compressed_bytes=block.object_bytes,
            shared=True,
        )

    local_path = _safe_relative_path(
        Path(publication_root).resolve(),
        record.get("path"),
        field_name="local shard.path",
    )
    if local_path.is_symlink() or not local_path.is_file():
        raise ValueError(f"local shard path is not a regular file: {local_path}")
    compressed_hash, content_hash, compressed_bytes = _validate_shard_path(
        local_path,
        record,
        field_prefix="local shard",
    )
    return PITResolvedShard(
        path=local_path,
        compressed_sha256=compressed_hash,
        content_sha256=content_hash,
        compressed_bytes=compressed_bytes,
        shared=False,
    )


def _time_bound(value: object, *, fallback: str, field_name: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if fallback.strip():
        return fallback
    raise ValueError(f"{field_name} is missing")


def _atomic_create_json(path: Path, payload: Mapping[str, Any]) -> bool:
    """以 temp + fsync + create-only hard link 寫 immutable manifest。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (_canonical_json(payload) + "\n").encode("utf-8")
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ValueError(f"immutable PIT manifest collision: {path}")
        return False
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.stem}.",
        suffix=".partial",
        dir=path.parent,
    )
    temporary_path = Path(raw_path)
    descriptor_open = True
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor_open = False
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                raise ValueError(f"immutable PIT manifest collision: {path}")
            return False
        return True
    finally:
        if descriptor_open:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class SharedPITPublication:
    """derived PIT manifest 與 assembler 可直接讀取的 shared dataset view。"""

    publication_id: str
    output_root: Path
    manifest_path: Path
    dataset_manifest_path: Path
    latest_manifest_path: Path
    manifest_hash: str
    dataset_id: str
    shard_count: int
    row_count: int
    block_results: tuple[Mapping[str, Any], ...]


def _validate_source_publication(
    dataset_manifest_path: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any], str, str]:
    dataset_path = Path(dataset_manifest_path).resolve()
    if not dataset_path.is_file():
        raise ValueError(f"dataset manifest does not exist: {dataset_path}")
    dataset_manifest = _read_json(dataset_path, field_name="PIT dataset manifest")
    if dataset_manifest.get("schema_version") != PIT_DATASET_SCHEMA_VERSION:
        raise ValueError("PIT dataset manifest schema mismatch")
    dataset_hash = _verify_manifest_hash(
        dataset_manifest,
        field_name="PIT dataset manifest",
    )
    publication_root = dataset_path.parent.parent.resolve()
    publication_manifest_path = publication_root / "manifest.json"
    publication_manifest = _read_json(
        publication_manifest_path,
        field_name="PIT publication manifest",
    )
    if publication_manifest.get("schema_version") != PIT_PUBLICATION_SCHEMA_VERSION:
        raise ValueError("PIT publication manifest schema mismatch")
    publication_hash = _verify_manifest_hash(
        publication_manifest,
        field_name="PIT publication manifest",
    )
    dataset_id = dataset_manifest.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("PIT dataset manifest dataset_id is required")
    datasets = publication_manifest.get("datasets")
    if not isinstance(datasets, Mapping):
        raise ValueError("PIT publication manifest datasets is missing")
    publication_dataset = datasets.get(dataset_id)
    if not isinstance(publication_dataset, Mapping):
        raise ValueError("PIT publication manifest dataset entry is missing")
    if publication_dataset.get("manifest_hash") != dataset_hash:
        raise ValueError("PIT publication/dataset manifest hash mismatch")
    expected_path = f"{dataset_id}/manifest.json"
    if publication_dataset.get("manifest_path") != expected_path:
        raise ValueError("PIT publication dataset manifest path mismatch")
    return (
        publication_root,
        dataset_manifest,
        publication_manifest,
        dataset_hash,
        publication_hash,
    )


def build_shared_pit_publication(
    *,
    dataset_manifest_path: Path,
    shared_store_root: Path,
    output_root: Path,
    lock_path: Path | None = None,
    max_store_bytes: int = DEFAULT_MAX_STORE_BYTES,
    maturity_policy: str = _PIT_MATURITY_POLICY,
    lane: str = "research_shadow",
) -> SharedPITPublication:
    """把一個既有 PIT dataset manifest 接到 shared immutable registry。"""

    (
        source_root,
        dataset_manifest,
        publication_manifest,
        dataset_hash,
        publication_hash,
    ) = _validate_source_publication(dataset_manifest_path)
    store_root = Path(shared_store_root).resolve()
    destination_root = Path(output_root).resolve()
    if _path_inside(destination_root, source_root) or _path_inside(source_root, destination_root):
        raise ValueError("shared PIT output must not overlap source publication")
    if _path_inside(destination_root, store_root) or _path_inside(store_root, destination_root):
        raise ValueError("shared PIT output must not overlap shared block store")
    source_fingerprint = _required_hash(
        dataset_manifest.get("source_fingerprint"),
        field_name="PIT dataset source_fingerprint",
    )
    eligibility_hash = _required_hash(
        dataset_manifest.get("eligibility_manifest_hash"),
        field_name="PIT dataset eligibility_manifest_hash",
    )
    feature_contract_hash = pit_dataset_feature_contract_hash(dataset_manifest)
    # source_fingerprint 綁定整個 SQLite 檔案的 mtime/size；它放在
    # derived lineage，但不能放入每個 shard 的 key，否則只改一個年度也
    # 會使所有未改 shard 失效。每個 shard 的 compressed/content hash 已
    # 進 source_version；這裡再綁穩定的 producer/source contract。
    source_contract_hash = _sha256_json(
        {
            "source_kind": "sqlite_pit_publication",
            "publication_schema_version": PIT_PUBLICATION_SCHEMA_VERSION,
            "dataset_schema_version": PIT_DATASET_SCHEMA_VERSION,
            "dataset_id": dataset_manifest["dataset_id"],
        }
    )
    source_refs = (
        ("pit.eligibility_manifest", eligibility_hash),
        ("pit.source_contract", source_contract_hash),
    )
    decision_at = str(dataset_manifest.get("decision_at", ""))
    shards = dataset_manifest.get("shards")
    if not isinstance(shards, list) or not shards:
        raise ValueError("PIT dataset manifest shards must be a non-empty array")

    shard_records: list[Mapping[str, Any]] = []
    consumer_shard_records: list[Mapping[str, Any]] = []
    block_results: list[Mapping[str, Any]] = []
    row_count = 0
    for raw_record in sorted(
        shards,
        key=lambda item: (
            int(item.get("year", -1)) if isinstance(item, Mapping) else -1,
            str(item.get("path", "")) if isinstance(item, Mapping) else "",
        ),
    ):
        if not isinstance(raw_record, Mapping):
            raise TypeError("PIT shard record must be an object")
        year = raw_record.get("year")
        if isinstance(year, bool) or not isinstance(year, int):
            raise ValueError("PIT shard year must be an integer")
        source_path = _safe_relative_path(
            source_root,
            raw_record.get("path"),
            field_name="PIT source shard.path",
        )
        resolved_source = resolve_pit_shard_record(
            record=raw_record,
            publication_root=source_root,
        )
        if resolved_source.shared:
            raise ValueError("source PIT manifest unexpectedly contains shared reference")
        compressed_hash = resolved_source.compressed_sha256
        content_hash = resolved_source.content_sha256
        source_version_identity = _sha256_json(
            {
                "block_type": _PIT_BLOCK_TYPE,
                "artifact_schema_version": PIT_DATASET_SCHEMA_VERSION,
                "dataset_id": dataset_manifest["dataset_id"],
                "year": year,
                "source_manifest_hashes": [list(item) for item in source_refs],
                "feature_contract_hash": feature_contract_hash,
                "label_contract_hash": "none",
                "maturity_policy": maturity_policy,
                "lane": lane,
                "encoding": _PIT_ENCODING,
            }
        )
        source_version = (
            f"pit-shard-source.v2:{source_version_identity}:"
            f"compressed={compressed_hash}:content={content_hash}"
        )
        key = ImmutableBlockKey(
            block_type=_PIT_BLOCK_TYPE,
            artifact_schema_version=PIT_DATASET_SCHEMA_VERSION,
            source_version=source_version,
            source_manifest_hashes=source_refs,
            feature_contract_hash=feature_contract_hash,
            label_contract_hash="none",
            maturity_policy=maturity_policy,
            time_start=_time_bound(
                raw_record.get("min_available_at"),
                fallback=decision_at,
                field_name="PIT shard min_available_at",
            ),
            time_end=_time_bound(
                raw_record.get("max_available_at"),
                fallback=decision_at,
                field_name="PIT shard max_available_at",
            ),
            encoding=_PIT_ENCODING,
            lane=lane,
        )
        result = publish_immutable_block_file(
            store_root=store_root,
            key=key,
            source_path=resolved_source.path,
            max_store_bytes=max_store_bytes,
            lock_path=lock_path,
        )
        result_record = {
            "schema_version": SHARED_PIT_SHARD_RECORD_SCHEMA_VERSION,
            "dataset_id": dataset_manifest["dataset_id"],
            "year": year,
            "source_path": raw_record["path"],
            "compressed_sha256": compressed_hash,
            "content_sha256": content_hash,
            "compressed_bytes": resolved_source.compressed_bytes,
            "row_count": raw_record.get("row_count", 0),
            "key_hash": result["key_hash"],
            "object_hash": result["object_hash"],
            "block_reference": result["reference"],
        }
        consumer_record = dict(raw_record)
        # 共享 view 不保留可被舊 local reader 誤用的 run-local path；
        # source_path 只作 lineage，實際 bytes 由明確傳入的 shared store 讀取。
        consumer_record.pop("path", None)
        consumer_record["source_path"] = raw_record["path"]
        consumer_record["schema_version"] = SHARED_PIT_SHARD_RECORD_SCHEMA_VERSION
        consumer_record["compressed_sha256"] = compressed_hash
        consumer_record["content_sha256"] = content_hash
        consumer_record["compressed_bytes"] = resolved_source.compressed_bytes
        consumer_record["block_reference"] = result["reference"]
        consumer_record["shared_store_schema_version"] = (
            "ml-immutable-block-store.v1"
        )
        shard_records.append(result_record)
        consumer_shard_records.append(consumer_record)
        block_results.append(
            {
                **result_record,
                "status": result["status"],
                "new_bytes_written": result["new_bytes_written"],
            }
        )
        row_count += int(raw_record.get("row_count", 0))

    consumer_manifest_body = dict(dataset_manifest)
    consumer_manifest_body.pop("manifest_hash", None)
    consumer_manifest_body["shards"] = consumer_shard_records
    consumer_manifest_body["shared_block_store"] = {
        "schema_version": "ml-immutable-block-store.v1",
        "source_dataset_manifest_hash": dataset_hash,
        "source_publication_manifest_hash": publication_hash,
        "feature_contract_hash": feature_contract_hash,
        "maturity_policy": maturity_policy,
        "lane": lane,
        "references_are_relative": True,
        "run_local_shard_copy": False,
        "consumer_requires_shared_store_root": True,
    }
    consumer_manifest_hash = _sha256_json(consumer_manifest_body)
    consumer_manifest = {
        **consumer_manifest_body,
        "manifest_hash": consumer_manifest_hash,
    }

    body: dict[str, Any] = {
        "schema_version": SHARED_PIT_PUBLICATION_SCHEMA_VERSION,
        "stage": "shared_immutable_pit_shards",
        "dataset_id": dataset_manifest["dataset_id"],
        "format": _PIT_ENCODING,
        "source": {
            "publication_manifest_hash": publication_hash,
            "dataset_manifest_hash": dataset_hash,
            "dataset_manifest_schema_version": PIT_DATASET_SCHEMA_VERSION,
            "source_fingerprint": source_fingerprint,
            "eligibility_manifest_hash": eligibility_hash,
        },
        "semantic_contract": {
            "feature_contract_hash": feature_contract_hash,
            "label_contract_hash": "none",
            "maturity_policy": maturity_policy,
            "lane": lane,
            "source_version_policy": "per_shard_compressed_and_content_hash.v1",
        },
        "shared_store": {
            "schema_version": "ml-immutable-block-store.v1",
            "references_are_relative": True,
            "run_local_shard_copy": False,
        },
        "consumer_dataset_manifest": {
            "schema_version": PIT_DATASET_SCHEMA_VERSION,
            "manifest_hash": consumer_manifest_hash,
            "run_local_shard_copy": False,
        },
        "shard_count": len(shard_records),
        "row_count": row_count,
        "shards": shard_records,
        "execution": {
            "source_publication_root_is_read_only": True,
            "source_database_is_not_opened": True,
            "production_action_allowed": False,
            "alpha_bp": 0,
        },
    }
    identity_hash = _sha256_json(body)
    publication_id = "pit-shared-" + identity_hash[7:31]
    manifest_body = {**body, "publication_id": publication_id}
    manifest_hash = _sha256_json(manifest_body)
    manifest = {**manifest_body, "manifest_hash": manifest_hash}
    publication_directory = destination_root / "runs" / publication_id
    manifest_path = publication_directory / "manifest.json"
    _atomic_create_json(manifest_path, manifest)
    dataset_manifest_path = (
        publication_directory / str(dataset_manifest["dataset_id"]) / "manifest.json"
    )
    _atomic_create_json(dataset_manifest_path, consumer_manifest)
    latest_manifest_path = destination_root / "latest_manifest.json"
    pointer = {
        "schema_version": "ml-pit-shared-block-pointer.v1",
        "publication_id": publication_id,
        "manifest_path": f"runs/{publication_id}/manifest.json",
        "manifest_hash": manifest_hash,
    }
    if latest_manifest_path.exists():
        existing_pointer = _read_json(
            latest_manifest_path,
            field_name="shared PIT latest pointer",
        )
        if existing_pointer != pointer:
            pointer_raw = (_canonical_json(pointer) + "\n").encode("utf-8")
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{latest_manifest_path.stem}.",
                suffix=".partial",
                dir=latest_manifest_path.parent,
            )
            temporary = Path(raw_path)
            descriptor_open = True
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    descriptor_open = False
                    handle.write(pointer_raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, latest_manifest_path)
            finally:
                if descriptor_open:
                    os.close(descriptor)
                temporary.unlink(missing_ok=True)
    else:
        _atomic_create_json(latest_manifest_path, pointer)
    return SharedPITPublication(
        publication_id=publication_id,
        output_root=destination_root,
        manifest_path=manifest_path,
        dataset_manifest_path=dataset_manifest_path,
        latest_manifest_path=latest_manifest_path,
        manifest_hash=manifest_hash,
        dataset_id=str(dataset_manifest["dataset_id"]),
        shard_count=len(shard_records),
        row_count=row_count,
        block_results=tuple(block_results),
    )


def load_shared_pit_publication(
    *,
    manifest_path: Path,
    shared_store_root: Path,
) -> tuple[PITResolvedShard, ...]:
    """載入 derived manifest 並逐 shard 驗證 shared object。"""

    path = Path(manifest_path).resolve()
    payload = _read_json(path, field_name="shared PIT publication manifest")
    if payload.get("schema_version") != SHARED_PIT_PUBLICATION_SCHEMA_VERSION:
        raise ValueError("shared PIT publication schema mismatch")
    _verify_manifest_hash(payload, field_name="shared PIT publication manifest")
    semantic_contract = payload.get("semantic_contract")
    if not isinstance(semantic_contract, Mapping):
        raise ValueError("shared PIT semantic_contract is missing")
    feature_contract_hash = _required_hash(
        semantic_contract.get("feature_contract_hash"),
        field_name="shared PIT semantic_contract.feature_contract_hash",
    )
    maturity_policy = semantic_contract.get("maturity_policy")
    lane = semantic_contract.get("lane")
    if not isinstance(maturity_policy, str) or not maturity_policy.strip():
        raise ValueError("shared PIT semantic_contract.maturity_policy is missing")
    if not isinstance(lane, str) or not lane.strip():
        raise ValueError("shared PIT semantic_contract.lane is missing")
    shards = payload.get("shards")
    if not isinstance(shards, list) or not shards:
        raise ValueError("shared PIT publication shards must be non-empty")
    source_root = path.parent.parent.parent
    resolved: list[PITResolvedShard] = []
    for record in shards:
        if not isinstance(record, Mapping):
            raise TypeError("shared PIT publication shard must be an object")
        resolved.append(
            resolve_pit_shard_record(
                record=record,
                publication_root=source_root,
                shared_store_root=Path(shared_store_root),
                expected_feature_contract_hash=feature_contract_hash,
                expected_maturity_policy=maturity_policy,
                expected_lane=lane,
            )
        )
    declared_count = payload.get("shard_count")
    if (
        isinstance(declared_count, bool)
        or not isinstance(declared_count, int)
        or declared_count != len(resolved)
    ):
        raise ValueError("shared PIT publication shard_count mismatch")
    return tuple(resolved)


__all__ = [
    "PIT_DATASET_SCHEMA_VERSION",
    "PIT_PUBLICATION_SCHEMA_VERSION",
    "PITResolvedShard",
    "SHARED_PIT_PUBLICATION_SCHEMA_VERSION",
    "SHARED_PIT_SHARD_RECORD_SCHEMA_VERSION",
    "SharedPITPublication",
    "build_shared_pit_publication",
    "load_shared_pit_publication",
    "pit_dataset_feature_contract_hash",
    "resolve_pit_shard_record",
]
