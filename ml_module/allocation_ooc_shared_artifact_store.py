"""OOC 訓練 artifact 的跨 run immutable shared registry。

本模組只保存已完成 OOC artifact 的 payload bytes 與完整語意 key。run
manifest 只保存相對 reference；第二個 run 命中相同 key 時不建立訓練
workspace，也不把相同的 joblib／OOF bytes 再寫入 run-local 目錄。所有
object 與 descriptor 都沿用 immutable ML block store 的 canonical OS lock、
串流 hash 與容量預留。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from ml_module.immutable_ml_block_store import (
    BLOCK_STORE_SCHEMA_VERSION,
    DEFAULT_MAX_STORE_BYTES,
    ImmutableBlock,
    ImmutableBlockKey,
    immutable_block_store_lock_path,
    load_immutable_block,
    publish_immutable_block,
    publish_immutable_block_file,
)


OOC_ARTIFACT_STORE_SCHEMA_VERSION = "allocation-ooc-artifact-store.v1"
OOC_ARTIFACT_KEY_SCHEMA_VERSION = "allocation-ooc-artifact-key.v1"
OOC_ARTIFACT_DESCRIPTOR_SCHEMA_VERSION = (
    "allocation-ooc-artifact-descriptor.v1"
)
OOC_ARTIFACT_REFERENCE_SCHEMA_VERSION = "allocation-ooc-artifact-reference.v1"
OOC_ARTIFACT_FILE_SCHEMA_VERSION = "allocation-ooc-artifact-file.v1"
_SHA256_PREFIX = "sha256:"
_CHUNK_BYTES = 1 << 20

_SEMANTIC_FIELDS = frozenset(
    {
        "schema_version",
        "namespace",
        "artifact_kind",
        "artifact_scope",
        "store_lineage",
        "feature_contract",
        "label_target_contract",
        "split_contract",
        "maturity_contract",
        "model_contract",
        "training_contract",
        "calibration_contract",
        "implementation_contract",
        "time_range",
        "lane",
    }
)
_ARTIFACT_NAMESPACE_BY_KIND = {
    "base_oof_expert": "base_oof",
    "final_base_expert": "final_base",
    "meta_oof_allocator": "meta_oof",
    "final_meta_allocator": "final_meta",
    "calibrator": "calibrator",
}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_bytes(value: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
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
        raise ValueError(f"{field_name} must be a sha256 digest")
    return value


def _required_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return value


def _required_list(value: object, *, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be an array")
    return value


def _safe_relative_path(root: Path, value: object, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute() or value.startswith(("/", "\\")):
        raise ValueError(f"{field_name} must be relative")
    if ".." in relative.parts:
        raise ValueError(f"{field_name} must not contain parent traversal")
    resolved = (root / relative).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"{field_name} escapes store root")
    return resolved


def _normalise_hash_pairs(
    value: object,
    *,
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    raw = _required_list(value, field_name=field_name)
    if not raw:
        raise ValueError(f"{field_name} must not be empty")
    result: list[tuple[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"{field_name}[{index}] must be [id, hash]")
        source_id = _required_text(item[0], field_name=f"{field_name}[{index}].id")
        source_hash = _required_sha256(
            item[1],
            field_name=f"{field_name}[{index}].hash",
        )
        result.append((source_id, source_hash))
    result.sort()
    if len({source_id for source_id, _ in result}) != len(result):
        raise ValueError(f"{field_name} contains duplicate ids")
    return tuple(result)


def _normalise_semantic_key(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != _SEMANTIC_FIELDS:
        raise ValueError("OOC artifact semantic key fields are incomplete or unknown")
    if value.get("schema_version") != OOC_ARTIFACT_KEY_SCHEMA_VERSION:
        raise ValueError("unsupported OOC artifact semantic key schema")
    artifact_kind = _required_text(
        value.get("artifact_kind"),
        field_name="artifact_kind",
    )
    namespace = _required_text(value.get("namespace"), field_name="namespace")
    expected_namespace = _ARTIFACT_NAMESPACE_BY_KIND.get(artifact_kind)
    if expected_namespace is None or namespace != expected_namespace:
        raise ValueError(
            "OOC artifact kind and namespace are incompatible"
        )
    artifact_scope = _required_mapping(
        value.get("artifact_scope"),
        field_name="artifact_scope",
    )
    if not artifact_scope:
        raise ValueError("artifact_scope must not be empty")
    lane = _required_text(value.get("lane"), field_name="lane")
    if lane not in {"formal", "research_shadow"}:
        raise ValueError("OOC artifact lane is invalid")
    store_lineage = _required_mapping(
        value.get("store_lineage"),
        field_name="store_lineage",
    )
    for name in (
        "store_manifest_hash",
        "store_manifest_file_hash",
        "dataset_identity_hash",
    ):
        _required_sha256(store_lineage.get(name), field_name=f"store_lineage.{name}")
    _normalise_hash_pairs(
        store_lineage.get("source_manifest_hashes"),
        field_name="store_lineage.source_manifest_hashes",
    )
    feature_contract = _required_mapping(
        value.get("feature_contract"),
        field_name="feature_contract",
    )
    _required_sha256(
        feature_contract.get("registry_hash"),
        field_name="feature_contract.registry_hash",
    )
    label_contract = _required_mapping(
        value.get("label_target_contract"),
        field_name="label_target_contract",
    )
    _required_sha256(
        label_contract.get("contract_hash"),
        field_name="label_target_contract.contract_hash",
    )
    split = _required_mapping(value.get("split_contract"), field_name="split_contract")
    if not split:
        raise ValueError("split_contract must not be empty")
    maturity = _required_mapping(
        value.get("maturity_contract"),
        field_name="maturity_contract",
    )
    if not maturity:
        raise ValueError("maturity_contract must not be empty")
    model = _required_mapping(value.get("model_contract"), field_name="model_contract")
    if not model:
        raise ValueError("model_contract must not be empty")
    training = _required_mapping(
        value.get("training_contract"),
        field_name="training_contract",
    )
    if not training:
        raise ValueError("training_contract must not be empty")
    _required_mapping(
        value.get("calibration_contract"),
        field_name="calibration_contract",
    )
    _required_mapping(
        value.get("implementation_contract"),
        field_name="implementation_contract",
    )
    time_range = _required_mapping(value.get("time_range"), field_name="time_range")
    time_start = _required_text(time_range.get("start"), field_name="time_range.start")
    time_end = _required_text(time_range.get("end"), field_name="time_range.end")
    if len(time_start) != 10 or len(time_end) != 10:
        raise ValueError("OOC artifact time range must use ISO dates")
    if time_start > time_end:
        raise ValueError("OOC artifact time range is reversed")
    return json.loads(_canonical_json(value))


def semantic_key_hash(value: Mapping[str, Any]) -> str:
    """計算不含 filesystem path 的完整 OOC artifact semantic key hash。"""

    return _sha256_json(_normalise_semantic_key(value))


def _source_manifest_hashes(
    semantic_key: Mapping[str, Any],
    *,
    core_manifest_hash: str,
    content_hash: str | None = None,
) -> tuple[tuple[str, str], ...]:
    store = _required_mapping(
        semantic_key["store_lineage"],
        field_name="store_lineage",
    )
    pairs = [
        ("store_manifest", str(store["store_manifest_hash"])),
        ("store_manifest_file", str(store["store_manifest_file_hash"])),
        ("dataset_identity", str(store["dataset_identity_hash"])),
        ("artifact_manifest", core_manifest_hash),
    ]
    if content_hash is not None:
        pairs.append(("artifact_content", content_hash))
    return tuple(sorted(pairs))


def _feature_hash(semantic_key: Mapping[str, Any]) -> str:
    feature = _required_mapping(
        semantic_key["feature_contract"],
        field_name="feature_contract",
    )
    return _required_sha256(
        feature["registry_hash"],
        field_name="feature_contract.registry_hash",
    )


def _label_hash(semantic_key: Mapping[str, Any]) -> str:
    label = _required_mapping(
        semantic_key["label_target_contract"],
        field_name="label_target_contract",
    )
    return _required_sha256(
        label["contract_hash"],
        field_name="label_target_contract.contract_hash",
    )


def _maturity_policy(semantic_key: Mapping[str, Any]) -> str:
    maturity = _required_mapping(
        semantic_key["maturity_contract"],
        field_name="maturity_contract",
    )
    return "allocation-ooc-maturity.v1:" + _sha256_json(maturity)[7:]


def _time_range(semantic_key: Mapping[str, Any]) -> tuple[str, str]:
    value = _required_mapping(semantic_key["time_range"], field_name="time_range")
    return (
        _required_text(value.get("start"), field_name="time_range.start"),
        _required_text(value.get("end"), field_name="time_range.end"),
    )


def _generic_key(
    *,
    block_type: str,
    artifact_schema_version: str,
    source_version: str,
    semantic_key: Mapping[str, Any],
    core_manifest_hash: str,
    content_hash: str | None = None,
    encoding: str,
) -> ImmutableBlockKey:
    time_start, time_end = _time_range(semantic_key)
    return ImmutableBlockKey(
        block_type=block_type,
        artifact_schema_version=artifact_schema_version,
        source_version=source_version,
        source_manifest_hashes=_source_manifest_hashes(
            semantic_key,
            core_manifest_hash=core_manifest_hash,
            content_hash=content_hash,
        ),
        feature_contract_hash=_feature_hash(semantic_key),
        label_contract_hash=_label_hash(semantic_key),
        maturity_policy=_maturity_policy(semantic_key),
        time_start=time_start,
        time_end=time_end,
        encoding=encoding,
        lane=_required_text(semantic_key.get("lane"), field_name="lane"),
    )


def _descriptor_key(
    semantic_key: Mapping[str, Any],
    *,
    core_manifest_hash: str,
) -> ImmutableBlockKey:
    source_version = _canonical_json(
        {
            "schema_version": OOC_ARTIFACT_KEY_SCHEMA_VERSION,
            "semantic_key": _normalise_semantic_key(semantic_key),
            "descriptor": OOC_ARTIFACT_DESCRIPTOR_SCHEMA_VERSION,
        }
    )
    return _generic_key(
        block_type="allocation-ooc-artifact-descriptor",
        artifact_schema_version=OOC_ARTIFACT_DESCRIPTOR_SCHEMA_VERSION,
        source_version=source_version,
        semantic_key=semantic_key,
        core_manifest_hash=core_manifest_hash,
        encoding="json",
    )


def _file_key(
    semantic_key: Mapping[str, Any],
    *,
    core_manifest_hash: str,
    relative_path: str,
    content_hash: str,
) -> ImmutableBlockKey:
    source_version = _canonical_json(
        {
            "schema_version": OOC_ARTIFACT_FILE_SCHEMA_VERSION,
            "semantic_key_hash": semantic_key_hash(semantic_key),
            "core_manifest_hash": core_manifest_hash,
            "relative_path": relative_path,
            "content_sha256": content_hash,
        }
    )
    return _generic_key(
        block_type="allocation-ooc-artifact-file",
        artifact_schema_version=OOC_ARTIFACT_FILE_SCHEMA_VERSION,
        source_version=source_version,
        semantic_key=semantic_key,
        core_manifest_hash=core_manifest_hash,
        content_hash=content_hash,
        encoding="binary",
    )


def _key_reference_from_store(
    store_root: Path,
    key_hash: str,
) -> Mapping[str, Any] | None:
    key_hash = _required_sha256(key_hash, field_name="key_hash")
    key_path = (store_root / "keys" / f"{key_hash[7:]}.json").resolve()
    if not key_path.is_file():
        return None
    if store_root not in key_path.parents:
        raise ValueError("OOC shared key path escapes store root")
    try:
        record = json.loads(key_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("OOC shared key record is unreadable") from exc
    if not isinstance(record, Mapping):
        raise TypeError("OOC shared key record must be an object")
    if record.get("key_hash") != key_hash:
        raise ValueError("OOC shared key record hash mismatch")
    key_manifest = {
        "path": key_path.relative_to(store_root).as_posix(),
        "sha256": _file_sha256(key_path),
        "bytes": key_path.stat().st_size,
    }
    return {
        "schema_version": "ml-immutable-block-reference.v1",
        "store_schema_version": BLOCK_STORE_SCHEMA_VERSION,
        "key_hash": key_hash,
        "key": record.get("key"),
        "key_manifest": key_manifest,
        "object": record.get("object"),
    }


def _descriptor_reference_index(
    store_root: Path,
) -> dict[str, Mapping[str, Any]]:
    """建立 semantic hash → descriptor reference 的 bounded lookup。"""

    keys_root = (store_root / "keys").resolve()
    if not keys_root.exists():
        return {}
    if keys_root.is_symlink() or not keys_root.is_dir():
        raise ValueError("OOC shared key registry is not a regular directory")
    index: dict[str, Mapping[str, Any]] = {}
    try:
        key_paths = sorted(keys_root.glob("*.json"))
    except OSError as exc:
        raise ValueError("OOC shared key registry is not enumerable") from exc
    for key_path in key_paths:
        record = _key_reference_from_store(
            store_root,
            _SHA256_PREFIX + key_path.stem,
        )
        if record is None:
            continue
        raw_key = record.get("key")
        if not isinstance(raw_key, Mapping):
            raise ValueError("OOC shared key record key is missing")
        if raw_key.get("block_type") != "allocation-ooc-artifact-descriptor":
            continue
        source_version = raw_key.get("source_version")
        if not isinstance(source_version, str):
            raise ValueError("OOC descriptor key source version is missing")
        try:
            source = json.loads(source_version)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("OOC descriptor key source version is invalid") from exc
        if not isinstance(source, Mapping):
            raise TypeError("OOC descriptor key source version must be an object")
        semantic_key = _required_mapping(
            source.get("semantic_key"),
            field_name="descriptor_key.semantic_key",
        )
        semantic_hash = semantic_key_hash(semantic_key)
        existing = index.get(semantic_hash)
        if existing is not None and existing != record:
            raise ValueError(
                "multiple OOC descriptors bind the same semantic key"
            )
        index[semantic_hash] = record
    return index


def _read_descriptor(block: ImmutableBlock) -> dict[str, Any]:
    try:
        payload = json.loads(block.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("OOC shared artifact descriptor is not JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("OOC shared artifact descriptor must be an object")
    expected = {
        "schema_version",
        "store_schema_version",
        "semantic_key_hash",
        "semantic_key",
        "core_manifest_hash",
        "artifact_manifest",
        "files",
    }
    if set(payload) != expected:
        raise ValueError("OOC shared artifact descriptor fields are invalid")
    if payload.get("schema_version") != OOC_ARTIFACT_DESCRIPTOR_SCHEMA_VERSION:
        raise ValueError("OOC shared artifact descriptor schema mismatch")
    if payload.get("store_schema_version") != OOC_ARTIFACT_STORE_SCHEMA_VERSION:
        raise ValueError("OOC shared artifact descriptor store schema mismatch")
    semantic_key = _required_mapping(
        payload.get("semantic_key"),
        field_name="descriptor.semantic_key",
    )
    if payload.get("semantic_key_hash") != semantic_key_hash(semantic_key):
        raise ValueError("OOC shared artifact descriptor semantic key mismatch")
    _required_sha256(
        payload.get("core_manifest_hash"),
        field_name="descriptor.core_manifest_hash",
    )
    artifact_manifest = _required_mapping(
        payload.get("artifact_manifest"),
        field_name="descriptor.artifact_manifest",
    )
    if _sha256_json(artifact_manifest) != payload.get("core_manifest_hash"):
        raise ValueError("OOC shared artifact core manifest hash mismatch")
    return payload


def _resolution_from_descriptor(
    *,
    store_root: Path,
    descriptor_block: ImmutableBlock,
    expected_semantic_key: Mapping[str, Any],
) -> "OOCArtifactResolution":
    descriptor = _read_descriptor(descriptor_block)
    expected_key = _normalise_semantic_key(expected_semantic_key)
    descriptor_key = _required_mapping(
        descriptor.get("semantic_key"),
        field_name="descriptor.semantic_key",
    )
    if descriptor_key != expected_key:
        raise ValueError("OOC shared artifact semantic key differs from request")
    semantic_hash = semantic_key_hash(expected_key)
    if descriptor.get("semantic_key_hash") != semantic_hash:
        raise ValueError("OOC shared artifact semantic key hash mismatch")
    core_manifest_hash = _required_sha256(
        descriptor.get("core_manifest_hash"),
        field_name="descriptor.core_manifest_hash",
    )
    artifact_manifest = dict(
        _required_mapping(
            descriptor.get("artifact_manifest"),
            field_name="descriptor.artifact_manifest",
        )
    )
    file_entries = _required_list(descriptor.get("files"), field_name="descriptor.files")
    file_paths: dict[str, Path] = {}
    seen: set[str] = set()
    for index, raw_file in enumerate(file_entries):
        item = _required_mapping(raw_file, field_name=f"descriptor.files[{index}]")
        relative = _required_text(item.get("path"), field_name="descriptor.file.path")
        if relative in seen:
            raise ValueError("OOC shared descriptor contains duplicate file path")
        seen.add(relative)
        file_hash = _required_sha256(
            item.get("file_sha256"),
            field_name=f"descriptor.files[{relative}].file_sha256",
        )
        byte_count = item.get("byte_count")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise ValueError("OOC shared descriptor file byte_count is invalid")
        reference = _required_mapping(
            item.get("block_reference"),
            field_name=f"descriptor.files[{relative}].block_reference",
        )
        block = load_immutable_block(store_root=store_root, reference=reference)
        expected_file_key = _file_key(
            expected_key,
            core_manifest_hash=core_manifest_hash,
            relative_path=relative,
            content_hash=file_hash,
        )
        if block.key.payload() != expected_file_key.payload():
            raise ValueError("OOC shared file semantic key mismatch")
        if block.object_hash != file_hash or block.object_bytes != byte_count:
            raise ValueError("OOC shared file bytes/hash mismatch")
        file_paths[relative] = block.object_path
    manifest_files: dict[str, Mapping[str, Any]] = {}
    for raw_file in _required_list(
        artifact_manifest.get("artifacts"),
        field_name="artifact_manifest.artifacts",
    ):
        item = _required_mapping(raw_file, field_name="artifact_manifest.artifact")
        relative = _required_text(item.get("path"), field_name="artifact.path")
        if relative:
            manifest_files[relative] = item
    if set(manifest_files) != set(file_paths):
        raise ValueError("OOC shared descriptor artifact file coverage mismatch")
    for relative, item in manifest_files.items():
        if item.get("file_sha256") != _file_sha256(file_paths[relative]):
            raise ValueError("OOC shared descriptor payload hash mismatch")
        if item.get("byte_count") != file_paths[relative].stat().st_size:
            raise ValueError("OOC shared descriptor payload size mismatch")
    public_reference = {
        "schema_version": OOC_ARTIFACT_REFERENCE_SCHEMA_VERSION,
        "store_schema_version": OOC_ARTIFACT_STORE_SCHEMA_VERSION,
        "artifact_key_hash": semantic_hash,
        "descriptor": dict(descriptor_block.reference),
    }
    return OOCArtifactResolution(
        store_root=store_root,
        semantic_key=expected_key,
        semantic_key_hash=semantic_hash,
        core_manifest_hash=core_manifest_hash,
        artifact_manifest=artifact_manifest,
        reference=public_reference,
        file_paths=file_paths,
        descriptor_object_path=descriptor_block.object_path,
    )


@dataclass(frozen=True)
class OOCArtifactResolution:
    """已驗證的 OOC artifact；payload 直接位於 shared object path。"""

    store_root: Path
    semantic_key: Mapping[str, Any]
    semantic_key_hash: str
    core_manifest_hash: str
    artifact_manifest: Mapping[str, Any]
    reference: Mapping[str, Any]
    file_paths: Mapping[str, Path]
    descriptor_object_path: Path


class OOCSharedArtifactStore:
    """以 semantic key 查找／發布 OOC artifact bundle。"""

    def __init__(
        self,
        root: Path,
        *,
        max_store_bytes: int = DEFAULT_MAX_STORE_BYTES,
    ) -> None:
        if (
            isinstance(max_store_bytes, bool)
            or not isinstance(max_store_bytes, int)
            or max_store_bytes <= 0
            or max_store_bytes > DEFAULT_MAX_STORE_BYTES
        ):
            raise ValueError(
                f"max_store_bytes must be in 1..{DEFAULT_MAX_STORE_BYTES}"
            )
        self.root = Path(root).resolve()
        self.max_store_bytes = max_store_bytes
        self._descriptor_index: dict[str, Mapping[str, Any]] | None = None

    @property
    def lock_path(self) -> Path:
        return immutable_block_store_lock_path(self.root)

    def resolve(
        self,
        semantic_key: Mapping[str, Any],
    ) -> OOCArtifactResolution | None:
        normalised = _normalise_semantic_key(semantic_key)
        key_hash = semantic_key_hash(normalised)
        if self._descriptor_index is None:
            self._descriptor_index = _descriptor_reference_index(self.root)
        record_reference = self._descriptor_index.get(key_hash)
        if record_reference is None:
            return None
        descriptor_block = load_immutable_block(
            store_root=self.root,
            reference=record_reference,
        )
        expected_descriptor_key = _descriptor_key(
            normalised,
            core_manifest_hash=_required_sha256(
                _read_descriptor(descriptor_block).get("core_manifest_hash"),
                field_name="descriptor.core_manifest_hash",
            ),
        )
        if descriptor_block.key.payload() != expected_descriptor_key.payload():
            raise ValueError("OOC shared descriptor key does not bind semantic key")
        return _resolution_from_descriptor(
            store_root=self.root,
            descriptor_block=descriptor_block,
            expected_semantic_key=normalised,
        )

    def resolve_reference(
        self,
        reference: Mapping[str, Any],
    ) -> OOCArtifactResolution:
        expected = {
            "schema_version",
            "store_schema_version",
            "artifact_key_hash",
            "descriptor",
        }
        if set(reference) != expected:
            raise ValueError("OOC shared artifact reference fields are invalid")
        if reference.get("schema_version") != OOC_ARTIFACT_REFERENCE_SCHEMA_VERSION:
            raise ValueError("OOC shared artifact reference schema mismatch")
        if reference.get("store_schema_version") != OOC_ARTIFACT_STORE_SCHEMA_VERSION:
            raise ValueError("OOC shared artifact reference store schema mismatch")
        descriptor_reference = _required_mapping(
            reference.get("descriptor"),
            field_name="reference.descriptor",
        )
        descriptor_block = load_immutable_block(
            store_root=self.root,
            reference=descriptor_reference,
        )
        descriptor = _read_descriptor(descriptor_block)
        semantic_key = _required_mapping(
            descriptor.get("semantic_key"),
            field_name="descriptor.semantic_key",
        )
        if reference.get("artifact_key_hash") != semantic_key_hash(semantic_key):
            raise ValueError("OOC shared artifact reference key mismatch")
        return _resolution_from_descriptor(
            store_root=self.root,
            descriptor_block=descriptor_block,
            expected_semantic_key=semantic_key,
        )

    def publish(
        self,
        *,
        semantic_key: Mapping[str, Any],
        artifact_manifest: Mapping[str, Any],
        source_directory: Path,
        temporary_roots: tuple[Path, ...] = (),
        temporary_peak_bytes_observed: int | None = None,
        temporary_budget_bytes: int | None = None,
    ) -> dict[str, Any]:
        normalised_key = _normalise_semantic_key(semantic_key)
        key_hash = semantic_key_hash(normalised_key)
        source_root = Path(source_directory).resolve()
        if source_root.is_symlink() or not source_root.is_dir():
            raise ValueError("OOC artifact source directory is not regular")
        core = dict(artifact_manifest)
        if "manifest_hash" in core:
            supplied_hash = _required_sha256(
                core.pop("manifest_hash"),
                field_name="artifact_manifest.manifest_hash",
            )
            if supplied_hash != _sha256_json(core):
                raise ValueError("OOC artifact core manifest hash mismatch")
        core_manifest_hash = _sha256_json(core)
        files: list[tuple[str, Path, str, int]] = []
        for index, raw_file in enumerate(
            _required_list(core.get("artifacts"), field_name="artifact_manifest.artifacts")
        ):
            item = _required_mapping(raw_file, field_name=f"artifact_manifest.artifacts[{index}]")
            relative = _required_text(item.get("path"), field_name="artifact.path")
            source_path = (source_root / relative).resolve()
            if source_root not in source_path.parents or source_path.is_symlink() or not source_path.is_file():
                raise ValueError("OOC artifact payload escapes source directory")
            expected_hash = _required_sha256(
                item.get("file_sha256"),
                field_name=f"artifact.{relative}.file_sha256",
            )
            expected_bytes = item.get("byte_count")
            if (
                isinstance(expected_bytes, bool)
                or not isinstance(expected_bytes, int)
                or expected_bytes < 0
            ):
                raise ValueError("OOC artifact payload byte_count is invalid")
            if source_path.stat().st_size != expected_bytes or _file_sha256(source_path) != expected_hash:
                raise ValueError("OOC artifact payload changed before publish")
            files.append((relative, source_path, expected_hash, expected_bytes))
        files.sort(key=lambda item: item[0])
        if len({item[0] for item in files}) != len(files):
            raise ValueError("OOC artifact payload paths are duplicated")

        # 同一完整 semantic key 只能綁定一份 core manifest。若上游依賴
        # 未被 key 捕捉而產出不同 bytes，必須在任何新 object 寫入前拒絕，
        # 避免 registry 留下兩個無法判定的 descriptor。
        existing_resolution = self.resolve(normalised_key)
        if existing_resolution is not None:
            if existing_resolution.core_manifest_hash != core_manifest_hash:
                raise ValueError(
                    "OOC semantic key is already bound to a different artifact"
                )
            if dict(existing_resolution.artifact_manifest) != core:
                raise ValueError(
                    "OOC semantic key artifact manifest differs from registry"
                )

        file_results: list[dict[str, Any]] = []
        for relative, source_path, content_hash, byte_count in files:
            key = _file_key(
                normalised_key,
                core_manifest_hash=core_manifest_hash,
                relative_path=relative,
                content_hash=content_hash,
            )
            result = publish_immutable_block_file(
                store_root=self.root,
                key=key,
                source_path=source_path,
                max_store_bytes=self.max_store_bytes,
                temporary_roots=temporary_roots,
                temporary_peak_bytes_observed=temporary_peak_bytes_observed,
                temporary_budget_bytes=temporary_budget_bytes,
            )
            file_results.append(
                {
                    "path": relative,
                    "file_sha256": content_hash,
                    "byte_count": byte_count,
                    "block_reference": result["reference"],
                    "status": result["status"],
                    "new_bytes_written": result["new_bytes_written"],
                }
            )
        descriptor_body = {
            "schema_version": OOC_ARTIFACT_DESCRIPTOR_SCHEMA_VERSION,
            "store_schema_version": OOC_ARTIFACT_STORE_SCHEMA_VERSION,
            "semantic_key_hash": key_hash,
            "semantic_key": normalised_key,
            "core_manifest_hash": core_manifest_hash,
            "artifact_manifest": core,
            "files": [
                {
                    "path": item["path"],
                    "file_sha256": item["file_sha256"],
                    "byte_count": item["byte_count"],
                    "block_reference": item["block_reference"],
                }
                for item in file_results
            ],
        }
        descriptor_raw = (_canonical_json(descriptor_body) + "\n").encode("utf-8")
        descriptor_result = publish_immutable_block(
            store_root=self.root,
            key=_descriptor_key(
                normalised_key,
                core_manifest_hash=core_manifest_hash,
            ),
            raw=descriptor_raw,
            max_store_bytes=self.max_store_bytes,
            temporary_roots=temporary_roots,
            temporary_peak_bytes_observed=temporary_peak_bytes_observed,
            temporary_budget_bytes=temporary_budget_bytes,
        )
        all_reused = descriptor_result["status"] == "immutable_block_reused" and all(
            item["status"] == "immutable_block_reused" for item in file_results
        )
        resolution = self.resolve_reference(
            {
                "schema_version": OOC_ARTIFACT_REFERENCE_SCHEMA_VERSION,
                "store_schema_version": OOC_ARTIFACT_STORE_SCHEMA_VERSION,
                "artifact_key_hash": key_hash,
                "descriptor": descriptor_result["reference"],
            }
        )
        # A caller may resolve before publishing the first descriptor.  Drop
        # that negative/old cache so subsequent runs in this process observe
        # the newly published immutable descriptor.
        self._descriptor_index = None
        return {
            "status": "immutable_ooc_artifact_reused" if all_reused else "immutable_ooc_artifact_created",
            "artifact_key_hash": key_hash,
            "core_manifest_hash": core_manifest_hash,
            "reference": resolution.reference,
            "file_paths": dict(resolution.file_paths),
            "file_results": file_results,
            "descriptor_status": descriptor_result["status"],
            "new_bytes_written": sum(
                int(item["new_bytes_written"]) for item in file_results
            ) + int(descriptor_result["new_bytes_written"]),
            "store_bytes": descriptor_result["store_bytes"],
            "lock_path": str(self.lock_path),
            "lock_held_through_publish": True,
        }


__all__ = [
    "OOC_ARTIFACT_DESCRIPTOR_SCHEMA_VERSION",
    "OOC_ARTIFACT_FILE_SCHEMA_VERSION",
    "OOC_ARTIFACT_KEY_SCHEMA_VERSION",
    "OOC_ARTIFACT_REFERENCE_SCHEMA_VERSION",
    "OOC_ARTIFACT_STORE_SCHEMA_VERSION",
    "OOCArtifactResolution",
    "OOCSharedArtifactStore",
    "semantic_key_hash",
]
