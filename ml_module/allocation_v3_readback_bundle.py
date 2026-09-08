"""v3 research readback 的小型、內容定址輸入保存包。

這個模組只保存 frozen v3 gzip input 與 release/training lineage metadata。
它不複製 model、Direct/PIT store、SQLite 或任何全量資料，也不會修改來源。
每個 object 以自身 bytes 的 SHA-256 命名；bundle manifest 則以不含自身欄位
的 canonical body 產生 identity，重跑同一批資料時重用既有 object。
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from data_module.ml_storage_capacity import directory_size_bytes


BUNDLE_SCHEMA_VERSION = "allocation-v3-linear-readback-bundle.v1"
DEFAULT_MAX_BUNDLE_BYTES = 256 * 1024 * 1024
_OBJECTS_DIRECTORY = "objects/sha256"
_MANIFESTS_DIRECTORY = "manifests"
_SHA256_PREFIX = "sha256:"


@dataclass(frozen=True)
class ReadbackBundle:
    """已驗證的 immutable bundle 及其 input object 路徑。"""

    manifest_path: Path
    bundle_root: Path
    input_path: Path
    manifest: Mapping[str, Any]
    release_manifest: Mapping[str, Any]
    training_lineage: Mapping[str, Any]

    @property
    def bundle_identity_hash(self) -> str:
        value = self.manifest.get("bundle_identity_hash")
        if not isinstance(value, str):
            raise ValueError("bundle_identity_hash is missing")
        return value

    @property
    def input_hash(self) -> str:
        value = self.manifest.get("input", {}).get("sha256")
        if not isinstance(value, str):
            raise ValueError("bundle input hash is missing")
        return value


def _canonical_bytes(value: object, *, trailing_newline: bool = False) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if trailing_newline:
        return encoded + b"\n"
    return encoded


def _sha256_bytes(value: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _required_sha256(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(_SHA256_PREFIX)
        or len(value) != len(_SHA256_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{field_name} must be a sha256: digest")
    return value


def _read_json_bytes(raw: bytes, *, field_name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    return value


def _read_json_file(path: Path, *, field_name: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OSError(f"cannot read {field_name}: {path}") from exc
    return _read_json_bytes(raw, field_name=field_name)


def _normalise_source_refs(value: object, *, field_name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    refs: list[tuple[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError(f"{field_name}[{index}] must be [source_id, hash]")
        source_id, source_hash = item
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError(f"{field_name}[{index}] source_id is invalid")
        refs.append(
            (
                source_id,
                _required_sha256(source_hash, field_name=f"{field_name}[{index}].hash"),
            )
        )
    normalised = tuple(sorted(refs))
    if len(normalised) != len(set(normalised)):
        raise ValueError(f"{field_name} contains duplicate source ids")
    if not normalised:
        raise ValueError(f"{field_name} must not be empty")
    return normalised


def _read_input_envelope(path: Path) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"v3 input is missing: {resolved}")
    if not resolved.name.lower().endswith(".gz"):
        raise ValueError("v3 input must be gzip compressed")
    raw = resolved.read_bytes()
    try:
        payload = _read_json_bytes(
            gzip.decompress(raw),
            field_name="v3 input",
        )
    except (OSError, EOFError) as exc:
        raise ValueError("v3 input gzip payload is invalid") from exc
    if payload.get("schema_version") != "allocation-inference-input-v3":
        raise ValueError("v3 input schema_version mismatch")
    input_hash = _sha256_bytes(raw)
    contract_hash = _required_sha256(
        payload.get("feature_contract_hash"),
        field_name="v3 input feature_contract_hash",
    )
    parent_input_hash = _required_sha256(
        payload.get("parent_input_compressed_hash"),
        field_name="v3 input parent_input_compressed_hash",
    )
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("v3 input rows must be a non-empty array")
    first = rows[0]
    if not isinstance(first, Mapping):
        raise TypeError("v3 input rows must contain objects")
    expected_sources = _normalise_source_refs(
        first.get("source_manifest_hashes"),
        field_name="v3 input source_manifest_hashes",
    )
    expected_decision_at = first.get("decision_at")
    expected_dataset_identity = _required_sha256(
        first.get("dataset_identity_hash"),
        field_name="v3 input dataset_identity_hash",
    )
    if not isinstance(expected_decision_at, str) or not expected_decision_at:
        raise ValueError("v3 input decision_at is missing")
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"v3 input rows[{index}] must be an object")
        if row.get("targets") is not None:
            raise ValueError("v3 readback input must not contain targets")
        if row.get("feature_registry_hash") != contract_hash:
            raise ValueError(f"v3 input rows[{index}] feature contract differs")
        if row.get("dataset_identity_hash") != expected_dataset_identity:
            raise ValueError(f"v3 input rows[{index}] dataset identity differs")
        if row.get("decision_at") != expected_decision_at:
            raise ValueError(f"v3 input rows[{index}] decision timestamp differs")
        if _normalise_source_refs(
            row.get("source_manifest_hashes"),
            field_name=f"v3 input rows[{index}].source_manifest_hashes",
        ) != expected_sources:
            raise ValueError(f"v3 input rows[{index}] source lineage differs")
    metadata = {
        "input_hash": input_hash,
        "contract_hash": contract_hash,
        "parent_input_hash": parent_input_hash,
        "dataset_identity_hash": expected_dataset_identity,
        "decision_at": expected_decision_at,
        "source_manifest_hashes": [list(item) for item in expected_sources],
        "row_count": len(rows),
    }
    return raw, payload, metadata


def _training_lineage_snapshot(
    training: Mapping[str, Any],
    *,
    training_file_hash: str,
) -> dict[str, Any]:
    """保存 inference 所需的 training lineage，不攜帶 capacity/TEMP path。"""

    required_fields = (
        "schema_version",
        "manifest_hash",
        "v3_input_hash",
        "parent_store_manifest_hash",
        "parent_store_manifest_file_hash",
        "market_database_file_hash",
        "source_manifest_hashes",
        "feature_order",
        "feature_packs",
        "fit_fold_id",
        "meta_fold_id",
        "calibration_fold_ids",
        "profile",
        "horizon",
        "algorithm",
        "v3_contract_hash",
        "readback_inference_mode",
        "inference_readback",
        "meta_probability_input",
        "rank_contract",
    )
    snapshot: dict[str, Any] = {}
    for field_name in required_fields:
        if field_name not in training:
            raise ValueError(f"training manifest missing {field_name}")
        snapshot[field_name] = training[field_name]
    snapshot["manifest_file_hash"] = training_file_hash
    snapshot["source_manifest_hashes"] = [
        list(item)
        for item in _normalise_source_refs(
            training["source_manifest_hashes"],
            field_name="training.source_manifest_hashes",
        )
    ]
    _required_sha256(snapshot["manifest_hash"], field_name="training.manifest_hash")
    _required_sha256(
        snapshot["v3_input_hash"],
        field_name="training.v3_input_hash",
    )
    _required_sha256(
        snapshot["parent_store_manifest_hash"],
        field_name="training.parent_store_manifest_hash",
    )
    _required_sha256(
        snapshot["parent_store_manifest_file_hash"],
        field_name="training.parent_store_manifest_file_hash",
    )
    _required_sha256(
        snapshot["market_database_file_hash"],
        field_name="training.market_database_file_hash",
    )
    _required_sha256(
        snapshot["v3_contract_hash"],
        field_name="training.v3_contract_hash",
    )
    if not isinstance(snapshot["inference_readback"], Mapping):
        raise TypeError("training.inference_readback must be an object")
    return snapshot


def _validate_release_lineage(
    *,
    release: Mapping[str, Any],
    training: Mapping[str, Any],
    input_metadata: Mapping[str, Any],
    release_file_hash: str,
    training_file_hash: str,
) -> None:
    if release.get("schema_version") != "allocation-ml-inference-release.v1":
        raise ValueError("release manifest schema_version mismatch")
    for field_name in (
        "release_id",
        "release_identity_hash",
        "model_id",
        "dataset_id",
    ):
        value = release.get(field_name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"release manifest {field_name} is missing")
    _required_sha256(
        release.get("release_identity_hash"),
        field_name="release.release_identity_hash",
    )
    _required_sha256(
        release.get("feature_registry_hash"),
        field_name="release.feature_registry_hash",
    )
    _required_sha256(
        release.get("dataset_identity_hash"),
        field_name="release.dataset_identity_hash",
    )
    if release["feature_registry_hash"] != input_metadata["contract_hash"]:
        raise ValueError("release and v3 input feature contract differ")
    if release["dataset_identity_hash"] != input_metadata["dataset_identity_hash"]:
        raise ValueError("release and v3 input dataset identity differ")
    release_sources = _normalise_source_refs(
        release.get("source_manifest_hashes"),
        field_name="release.source_manifest_hashes",
    )
    input_sources = _normalise_source_refs(
        input_metadata["source_manifest_hashes"],
        field_name="input.source_manifest_hashes",
    )
    if release_sources != input_sources:
        raise ValueError("release and v3 input source lineage differ")
    if release.get("training_manifest_hash") != training.get("manifest_hash"):
        raise ValueError("release and training manifest identities differ")
    if training.get("manifest_file_hash") != training_file_hash:
        raise ValueError("training lineage manifest file hash differs")
    if training.get("v3_input_hash") != input_metadata["input_hash"]:
        raise ValueError("training manifest v3 input hash differs")
    if training.get("v3_contract_hash") != input_metadata["contract_hash"]:
        raise ValueError("training manifest v3 contract hash differs")
    if _normalise_source_refs(
        training.get("source_manifest_hashes"),
        field_name="training.source_manifest_hashes",
    ) != input_sources:
        raise ValueError("training and v3 input source lineage differ")
    del release_file_hash


def _path_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _ensure_output_root_safe(
    *,
    output_root: Path,
    release_root: Path,
    input_path: Path,
) -> Path:
    resolved_output = output_root.resolve()
    resolved_release = release_root.resolve()
    resolved_input = input_path.resolve()
    if _path_inside(resolved_output, resolved_release) or _path_inside(
        resolved_release,
        resolved_output,
    ):
        raise ValueError("bundle output root must not overlap release root")
    if _path_inside(resolved_output, resolved_input) or _path_inside(
        resolved_input,
        resolved_output,
    ):
        raise ValueError("bundle output root must not overlap v3 input")
    return resolved_output


def _object_path(output_root: Path, digest: str, extension: str) -> Path:
    hex_digest = _required_sha256(digest, field_name="object hash")[7:]
    return output_root / _OBJECTS_DIRECTORY / f"{hex_digest}.{extension}"


def _object_reference(
    output_root: Path,
    raw: bytes,
    *,
    extension: str,
) -> dict[str, Any]:
    digest = _sha256_bytes(raw)
    path = _object_path(output_root, digest, extension)
    return {
        "path": path.relative_to(output_root).as_posix(),
        "sha256": digest,
        "bytes": len(raw),
    }


def _verify_existing_object(path: Path, reference: Mapping[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"content-addressed object is not a file: {path}")
    declared_hash = _required_sha256(reference.get("sha256"), field_name="object.sha256")
    declared_bytes = reference.get("bytes")
    if isinstance(declared_bytes, bool) or not isinstance(declared_bytes, int):
        raise TypeError("object.bytes must be an integer")
    if path.stat().st_size != declared_bytes or _file_hash(path) != declared_hash:
        raise ValueError(f"content-addressed object bytes/hash mismatch: {path}")


def _planned_object_bytes(
    output_root: Path,
    reference: Mapping[str, Any],
) -> int:
    path_value = reference.get("path")
    if not isinstance(path_value, str):
        raise TypeError("object.path must be a string")
    path = (output_root / Path(path_value)).resolve()
    if not _path_inside(path, output_root):
        raise ValueError("object path escapes bundle output root")
    if os.path.lexists(path):
        _verify_existing_object(path, reference)
        return 0
    bytes_value = reference.get("bytes")
    if isinstance(bytes_value, bool) or not isinstance(bytes_value, int):
        raise TypeError("object.bytes must be an integer")
    if bytes_value < 0:
        raise ValueError("object.bytes must be non-negative")
    return bytes_value


def _atomic_create_bytes(path: Path, raw: bytes) -> bool:
    """以同目錄 temp + fsync + create-only hard-link 發布完整 bytes。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ValueError(f"immutable content-addressed path collision: {path}")
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
            # Windows/POSIX 的 hard-link 建立都是 create-only：若另一個
            # writer 已先發布同一 hash，不會覆寫其完整 object。
            os.link(temporary_path, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                raise ValueError(
                    f"immutable content-addressed path collision: {path}"
                )
            return False
        except OSError as exc:
            raise OSError(
                "content-addressed publish requires same-filesystem atomic link"
            ) from exc
        return True
    finally:
        if descriptor_open:
            os.close(descriptor)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _write_content_addressed_object(
    output_root: Path,
    raw: bytes,
    reference: Mapping[str, Any],
) -> bool:
    path_value = reference.get("path")
    if not isinstance(path_value, str):
        raise TypeError("object.path must be a string")
    path = (output_root / Path(path_value)).resolve()
    if not _path_inside(path, output_root):
        raise ValueError("object path escapes bundle output root")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        _verify_existing_object(path, reference)
        return False
    published = _atomic_create_bytes(path, raw)
    _verify_existing_object(path, reference)
    return published


def _safe_object_path(bundle_root: Path, reference: Mapping[str, Any]) -> Path:
    path_value = reference.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise TypeError("object.path must be a non-empty string")
    relative = Path(path_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("bundle object path must be relative")
    path = (bundle_root / relative).resolve()
    if not _path_inside(path, bundle_root):
        raise ValueError("bundle object path escapes bundle root")
    return path


def create_readback_bundle(
    *,
    v3_input_path: Path,
    release_root: Path,
    output_root: Path,
    max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES,
) -> dict[str, Any]:
    """建立或重用 immutable v3 readback bundle。"""

    if (
        isinstance(max_bundle_bytes, bool)
        or not isinstance(max_bundle_bytes, int)
        or max_bundle_bytes <= 0
        or max_bundle_bytes > DEFAULT_MAX_BUNDLE_BYTES
    ):
        raise ValueError(
            f"max_bundle_bytes must be in 1..{DEFAULT_MAX_BUNDLE_BYTES}"
        )
    input_path = v3_input_path.resolve()
    release_path = release_root.resolve()
    output = _ensure_output_root_safe(
        output_root=output_root,
        release_root=release_path,
        input_path=input_path,
    )
    input_bytes, _input_payload, input_metadata = _read_input_envelope(input_path)
    release_manifest_path = release_path / "release_manifest.json"
    training_manifest_path = release_path / "training_manifest.json"
    release_bytes = release_manifest_path.read_bytes()
    training_bytes = training_manifest_path.read_bytes()
    release = _read_json_bytes(release_bytes, field_name="release manifest")
    training = _read_json_bytes(training_bytes, field_name="training manifest")
    release_file_hash = _sha256_bytes(release_bytes)
    training_file_hash = _sha256_bytes(training_bytes)
    training_lineage = _training_lineage_snapshot(
        training,
        training_file_hash=training_file_hash,
    )
    _validate_release_lineage(
        release=release,
        training=training_lineage,
        input_metadata=input_metadata,
        release_file_hash=release_file_hash,
        training_file_hash=training_file_hash,
    )
    release_ref = _object_reference(output, release_bytes, extension="json")
    training_ref = _object_reference(
        output,
        _canonical_bytes(training_lineage, trailing_newline=True),
        extension="json",
    )
    input_ref = _object_reference(output, input_bytes, extension="json.gz")
    lineage = {
        "dataset_id": release["dataset_id"],
        "dataset_identity_hash": input_metadata["dataset_identity_hash"],
        "feature_contract_hash": input_metadata["contract_hash"],
        "parent_input_compressed_hash": input_metadata["parent_input_hash"],
        "decision_at": input_metadata["decision_at"],
        "row_count": input_metadata["row_count"],
        "source_manifest_hashes": input_metadata["source_manifest_hashes"],
        "readback_inference_mode": training_lineage["readback_inference_mode"],
    }
    body: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "release": {
            "release_id": release["release_id"],
            "release_identity_hash": release["release_identity_hash"],
            "release_manifest_file_hash": release_file_hash,
            "release_manifest_object": release_ref,
            "training_manifest_file_hash": training_file_hash,
            "training_lineage_object": training_ref,
            "training_manifest_hash": training_lineage["manifest_hash"],
        },
        "input": {
            **input_ref,
            "encoding": "gzip-json",
        },
        "lineage": lineage,
    }
    bundle_identity_hash = _sha256_bytes(_canonical_bytes(body))
    manifest_payload = {
        **body,
        "bundle_identity_hash": bundle_identity_hash,
    }
    manifest_bytes = _canonical_bytes(manifest_payload, trailing_newline=True)
    manifest_path = output / _MANIFESTS_DIRECTORY / (
        f"{bundle_identity_hash[7:]}.json"
    )
    references = (input_ref, release_ref, training_ref)
    existing_bytes = directory_size_bytes(output)
    planned_new_bytes = sum(
        _planned_object_bytes(output, reference) for reference in references
    )
    if os.path.lexists(manifest_path):
        existing_manifest_bytes = manifest_path.read_bytes()
        if existing_manifest_bytes != manifest_bytes:
            raise ValueError("immutable readback bundle identity collision")
    else:
        planned_new_bytes += len(manifest_bytes)
    if existing_bytes + planned_new_bytes > max_bundle_bytes:
        raise ValueError(
            "readback bundle exceeds persistent budget: "
            f"{existing_bytes + planned_new_bytes}>{max_bundle_bytes}"
        )
    new_bytes = 0
    for raw, reference in (
        (input_bytes, input_ref),
        (release_bytes, release_ref),
        (_canonical_bytes(training_lineage, trailing_newline=True), training_ref),
    ):
        if _write_content_addressed_object(output, raw, reference):
            new_bytes += int(reference["bytes"])
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    idempotent = os.path.lexists(manifest_path)
    if not idempotent:
        idempotent = not _atomic_create_bytes(manifest_path, manifest_bytes)
        if idempotent and manifest_path.read_bytes() != manifest_bytes:
            raise ValueError("immutable readback bundle identity collision")
        if not idempotent:
            new_bytes += len(manifest_bytes)
    final_bytes = directory_size_bytes(output)
    if final_bytes > max_bundle_bytes:
        raise ValueError(
            f"readback bundle output exceeds persistent budget: {final_bytes}"
        )
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "status": "readback_bundle_reused" if idempotent else "readback_bundle_created",
        "bundle_id": bundle_identity_hash,
        "bundle_identity_hash": bundle_identity_hash,
        "bundle_manifest": str(manifest_path.resolve()),
        "bundle_manifest_file_hash": _file_hash(manifest_path),
        "input_object": str(_safe_object_path(output, input_ref)),
        "input_hash": input_metadata["input_hash"],
        "input_bytes": len(input_bytes),
        "release_id": release["release_id"],
        "source_manifest_count": len(input_metadata["source_manifest_hashes"]),
        "new_bytes_written": new_bytes,
        "bundle_output_bytes": final_bytes,
        "max_bundle_bytes": max_bundle_bytes,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "broker_order_allowed": False,
    }


def load_readback_bundle(manifest_path: Path) -> ReadbackBundle:
    """讀取並驗證 bundle manifest、object hashes 與 source lineage。"""

    path = manifest_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"readback bundle manifest is missing: {path}")
    bundle_root = path.parent.parent if path.parent.name == _MANIFESTS_DIRECTORY else path.parent
    raw_manifest = path.read_bytes()
    manifest = _read_json_bytes(raw_manifest, field_name="readback bundle manifest")
    if manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError("readback bundle schema_version mismatch")
    identity = _required_sha256(
        manifest.get("bundle_identity_hash"),
        field_name="bundle_identity_hash",
    )
    body = dict(manifest)
    body.pop("bundle_identity_hash", None)
    if _sha256_bytes(_canonical_bytes(body)) != identity:
        raise ValueError("readback bundle identity hash mismatch")
    release_section = manifest.get("release")
    if not isinstance(release_section, Mapping):
        raise TypeError("readback bundle release section is missing")
    input_section = manifest.get("input")
    if not isinstance(input_section, Mapping):
        raise TypeError("readback bundle input section is missing")
    release_ref = release_section.get("release_manifest_object")
    training_ref = release_section.get("training_lineage_object")
    if not isinstance(release_ref, Mapping) or not isinstance(training_ref, Mapping):
        raise TypeError("readback bundle source manifest objects are missing")
    input_ref = input_section
    object_paths = {
        "input": _safe_object_path(bundle_root, input_ref),
        "release": _safe_object_path(bundle_root, release_ref),
        "training": _safe_object_path(bundle_root, training_ref),
    }
    for object_name, object_path in object_paths.items():
        _verify_existing_object(
            object_path,
            input_ref if object_name == "input" else release_ref if object_name == "release" else training_ref,
        )
    if input_section.get("encoding") != "gzip-json" or not object_paths["input"].name.endswith(
        ".json.gz"
    ):
        raise ValueError("readback bundle input object encoding is invalid")
    release_bytes = object_paths["release"].read_bytes()
    training_bytes = object_paths["training"].read_bytes()
    release = _read_json_bytes(release_bytes, field_name="bundled release manifest")
    training_lineage = _read_json_bytes(
        training_bytes,
        field_name="bundled training lineage",
    )
    input_bytes, _input_payload, input_metadata = _read_input_envelope(object_paths["input"])
    del input_bytes
    if _file_hash(object_paths["release"]) != release_section.get(
        "release_manifest_file_hash"
    ):
        raise ValueError("bundled release manifest file hash differs")
    if _file_hash(object_paths["training"]) != training_ref.get("sha256"):
        raise ValueError("bundled training lineage object hash differs")
    _validate_release_lineage(
        release=release,
        training=training_lineage,
        input_metadata=input_metadata,
        release_file_hash=str(release_section.get("release_manifest_file_hash")),
        training_file_hash=str(release_section.get("training_manifest_file_hash")),
    )
    if release.get("release_id") != release_section.get("release_id"):
        raise ValueError("bundled release id differs")
    if release.get("release_identity_hash") != release_section.get(
        "release_identity_hash"
    ):
        raise ValueError("bundled release identity differs")
    lineage = manifest.get("lineage")
    if not isinstance(lineage, Mapping):
        raise TypeError("readback bundle lineage is missing")
    if lineage.get("dataset_id") != release.get("dataset_id"):
        raise ValueError("bundle dataset id differs")
    if lineage.get("dataset_identity_hash") != input_metadata["dataset_identity_hash"]:
        raise ValueError("bundle dataset identity differs")
    if lineage.get("feature_contract_hash") != input_metadata["contract_hash"]:
        raise ValueError("bundle feature contract differs")
    if lineage.get("source_manifest_hashes") != input_metadata["source_manifest_hashes"]:
        raise ValueError("bundle source lineage differs")
    if lineage.get("decision_at") != input_metadata["decision_at"]:
        raise ValueError("bundle decision timestamp differs")
    return ReadbackBundle(
        manifest_path=path,
        bundle_root=bundle_root,
        input_path=object_paths["input"],
        manifest=manifest,
        release_manifest=release,
        training_lineage=training_lineage,
    )
