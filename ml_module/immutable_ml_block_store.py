"""跨 run 共用的 immutable ML block registry。

這個 registry 只處理小型、已完成 publication 的 immutable bytes。它不會
搬移或清理 D 槽來源，也不直接修改 PIT／Direct／OOC 的來源內容。各 consumer
以明確的 shared-root 參數接入，仍保留既有 local path 分支。每個 reference
同時綁定語意 key 與 bytes hash：source version、feature／label
contract、maturity policy、時間範圍及 artifact schema 任一改變，都不能
靜默重用舊 reference；相同 bytes 則可由不同 run 共用同一個 object。

object 與 key record 都採同目錄 temp、fsync、create-only hard-link 發布。
因此中斷不會留下「看似完整」的最終 hash object；硬終止留下的 ``.partial``
仍由共用容量 scanner 計入，必須交由受控清理流程處理。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping, Sequence

from data_module.ml_storage_capacity import (
    StorageCapacityError,
    StorageCapacityExceededError,
    acquire_heavy_chain_reservation,
    directory_size_bytes,
    release_heavy_chain_reservation,
)


BLOCK_STORE_SCHEMA_VERSION = "ml-immutable-block-store.v1"
BLOCK_KEY_SCHEMA_VERSION = "ml-immutable-block-key.v1"
BLOCK_RECORD_SCHEMA_VERSION = "ml-immutable-block-record.v1"
BLOCK_REFERENCE_SCHEMA_VERSION = "ml-immutable-block-reference.v1"
DEFAULT_MAX_STORE_BYTES = 256 * 1024 * 1024
_SHA256_PREFIX = "sha256:"
_NONE_CONTRACT = "none"


class ImmutableBlockCapacityError(ValueError, StorageCapacityExceededError):
    """兼容舊 ValueError 呼叫端的結構化 immutable store 容量錯誤。"""

    def __init__(self, message: str, *, preflight: Mapping[str, Any]) -> None:
        StorageCapacityExceededError.__init__(self, message, preflight=preflight)


def _canonical_bytes(value: object, *, trailing_newline: bool = False) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return encoded + (b"\n" if trailing_newline else b"")


def _sha256_bytes(raw: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
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


def _required_contract_hash(value: object, *, field_name: str) -> str:
    if value == _NONE_CONTRACT:
        return _NONE_CONTRACT
    return _required_sha256(value, field_name=field_name)


def _normalise_source_manifest_hashes(
    value: object,
    *,
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{field_name} must be a non-empty array")
    result: list[tuple[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"{field_name}[{index}] must be [source_id, hash]")
        source_id, source_hash = item
        result.append(
            (
                _required_text(source_id, field_name=f"{field_name}[{index}].id"),
                _required_sha256(
                    source_hash,
                    field_name=f"{field_name}[{index}].hash",
                ),
            )
        )
    normalised = tuple(sorted(result))
    if len({source_id for source_id, _source_hash in normalised}) != len(
        normalised
    ):
        raise ValueError(f"{field_name} contains duplicate source references")
    return normalised


def _time_kind_and_value(value: str, *, field_name: str) -> tuple[str, object]:
    if len(value) == 10:
        try:
            return "date", date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be ISO date or timestamp") from exc
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO date or timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} timestamp must include timezone")
    return "timestamp", parsed.astimezone(timezone.utc)


def _validate_time_range(start: str, end: str) -> None:
    start_kind, start_value = _time_kind_and_value(start, field_name="time_start")
    end_kind, end_value = _time_kind_and_value(end, field_name="time_end")
    if start_kind != end_kind:
        raise ValueError("time range start and end must use the same ISO shape")
    if start_kind == "date":
        if not isinstance(start_value, date) or not isinstance(end_value, date):
            raise TypeError("date time range values are invalid")
    elif not isinstance(start_value, datetime) or not isinstance(end_value, datetime):
        raise TypeError("timestamp time range values are invalid")
    if start_value > end_value:
        raise ValueError("time range start must not exceed end")


@dataclass(frozen=True)
class ImmutableBlockKey:
    """決定 block 是否可重用的語意失效 key。"""

    block_type: str
    artifact_schema_version: str
    source_version: str
    source_manifest_hashes: tuple[tuple[str, str], ...]
    feature_contract_hash: str
    label_contract_hash: str
    maturity_policy: str
    time_start: str
    time_end: str
    encoding: str
    lane: str

    def __post_init__(self) -> None:
        for field_name in (
            "block_type",
            "artifact_schema_version",
            "source_version",
            "maturity_policy",
            "time_start",
            "time_end",
            "encoding",
            "lane",
        ):
            _required_text(getattr(self, field_name), field_name=field_name)
        if self.lane not in {"formal", "research_shadow"}:
            raise ValueError("lane must be formal or research_shadow")
        object.__setattr__(
            self,
            "source_manifest_hashes",
            _normalise_source_manifest_hashes(
                self.source_manifest_hashes,
                field_name="source_manifest_hashes",
            ),
        )
        _required_contract_hash(
            self.feature_contract_hash,
            field_name="feature_contract_hash",
        )
        _required_contract_hash(
            self.label_contract_hash,
            field_name="label_contract_hash",
        )
        _validate_time_range(self.time_start, self.time_end)

    def payload(self) -> dict[str, Any]:
        """返回不含 filesystem path 的 canonical key payload。"""

        return {
            "schema_version": BLOCK_KEY_SCHEMA_VERSION,
            "block_type": self.block_type,
            "artifact_schema_version": self.artifact_schema_version,
            "source_version": self.source_version,
            "source_manifest_hashes": [
                [source_id, source_hash]
                for source_id, source_hash in self.source_manifest_hashes
            ],
            "feature_contract_hash": self.feature_contract_hash,
            "label_contract_hash": self.label_contract_hash,
            "maturity_policy": self.maturity_policy,
            "time_range": {
                "start": self.time_start,
                "end": self.time_end,
            },
            "encoding": self.encoding,
            "lane": self.lane,
        }

    @property
    def key_hash(self) -> str:
        return _sha256_bytes(_canonical_bytes(self.payload()))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ImmutableBlockKey:
        expected_fields = {
            "schema_version",
            "block_type",
            "artifact_schema_version",
            "source_version",
            "source_manifest_hashes",
            "feature_contract_hash",
            "label_contract_hash",
            "maturity_policy",
            "time_range",
            "encoding",
            "lane",
        }
        if set(payload) != expected_fields:
            raise ValueError("immutable block key fields are incomplete or unknown")
        if payload.get("schema_version") != BLOCK_KEY_SCHEMA_VERSION:
            raise ValueError("immutable block key schema_version mismatch")
        time_range = payload.get("time_range")
        if not isinstance(time_range, Mapping):
            raise TypeError("immutable block key time_range must be an object")
        if set(time_range) != {"start", "end"}:
            raise ValueError("immutable block key time_range fields are invalid")
        return cls(
            block_type=_required_text(
                payload.get("block_type"),
                field_name="block_type",
            ),
            artifact_schema_version=_required_text(
                payload.get("artifact_schema_version"),
                field_name="artifact_schema_version",
            ),
            source_version=_required_text(
                payload.get("source_version"),
                field_name="source_version",
            ),
            source_manifest_hashes=_normalise_source_manifest_hashes(
                payload.get("source_manifest_hashes"),
                field_name="source_manifest_hashes",
            ),
            feature_contract_hash=_required_contract_hash(
                payload.get("feature_contract_hash"),
                field_name="feature_contract_hash",
            ),
            label_contract_hash=_required_contract_hash(
                payload.get("label_contract_hash"),
                field_name="label_contract_hash",
            ),
            maturity_policy=_required_text(
                payload.get("maturity_policy"),
                field_name="maturity_policy",
            ),
            time_start=_required_text(
                time_range.get("start"),
                field_name="time_range.start",
            ),
            time_end=_required_text(
                time_range.get("end"),
                field_name="time_range.end",
            ),
            encoding=_required_text(
                payload.get("encoding"),
                field_name="encoding",
            ),
            lane=_required_text(payload.get("lane"), field_name="lane"),
        )


@dataclass(frozen=True)
class ImmutableBlock:
    """已驗證的 block；reference 只含可搬移的相對路徑。"""

    store_root: Path
    key: ImmutableBlockKey
    reference: Mapping[str, Any]
    object_path: Path

    @property
    def object_hash(self) -> str:
        object_ref = self.reference.get("object")
        if not isinstance(object_ref, Mapping):
            raise ValueError("immutable block object reference is missing")
        return str(object_ref["sha256"])

    @property
    def object_bytes(self) -> int:
        object_ref = self.reference.get("object")
        if not isinstance(object_ref, Mapping):
            raise ValueError("immutable block object reference is missing")
        return int(object_ref["bytes"])

    def read_bytes(self) -> bytes:
        """在 caller 已通過 loader 驗證後讀取 block bytes。"""

        raw = self.object_path.read_bytes()
        if _sha256_bytes(raw) != self.object_hash:
            raise ValueError("immutable block changed after load")
        if len(raw) != self.object_bytes:
            raise ValueError("immutable block byte count changed after load")
        return raw


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
        raise ValueError(f"{field_name} escapes store root")
    return resolved


def _object_reference(raw: bytes) -> dict[str, Any]:
    digest = _sha256_bytes(raw)
    return {
        "path": f"objects/sha256/{digest[7:]}.blob",
        "sha256": digest,
        "bytes": len(raw),
    }


def _object_reference_from_file(source_path: Path) -> dict[str, Any]:
    """以串流方式取得來源檔案的 content-addressed object identity。"""

    source = Path(source_path).resolve()
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"immutable block source is not a regular file: {source}")
    digest = _file_sha256(source)
    return {
        "path": f"objects/sha256/{digest[7:]}.blob",
        "sha256": digest,
        "bytes": source.stat().st_size,
    }


def _validate_object_reference(
    value: object,
    *,
    store_root: Path,
    field_name: str,
) -> tuple[dict[str, Any], Path]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    expected_fields = {"path", "sha256", "bytes"}
    if set(value) != expected_fields:
        raise ValueError(f"{field_name} fields are invalid")
    digest = _required_sha256(value.get("sha256"), field_name=f"{field_name}.sha256")
    size = value.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError(f"{field_name}.bytes must be a non-negative integer")
    path = _safe_relative_path(
        store_root,
        value.get("path"),
        field_name=f"{field_name}.path",
    )
    expected_path = (
        store_root / "objects" / "sha256" / f"{digest[7:]}.blob"
    ).resolve()
    if path != expected_path:
        raise ValueError(f"{field_name}.path is not content addressed")
    return dict(value), path


def _verify_object(path: Path, reference: Mapping[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"immutable block object is not a regular file: {path}")
    expected_size = reference.get("bytes")
    expected_hash = _required_sha256(
        reference.get("sha256"),
        field_name="object.sha256",
    )
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or path.stat().st_size != expected_size
        or _file_sha256(path) != expected_hash
    ):
        raise ValueError(f"immutable block object bytes/hash mismatch: {path}")


def _atomic_create_bytes(path: Path, raw: bytes) -> bool:
    """以同目錄 temp + fsync + create-only link 發布完整 bytes。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ValueError(f"immutable block path collision: {path}")
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
            # create-only link 不會覆寫另一個 process 已發布的完整 object。
            os.link(temporary_path, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                raise ValueError(f"immutable block path collision: {path}")
            return False
        except OSError as exc:
            raise OSError(
                "immutable block publish requires same-filesystem atomic link"
            ) from exc
        return True
    finally:
        if descriptor_open:
            os.close(descriptor)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            # 硬終止不會進入 finally；此處只保留可診斷的 partial，並由
            # directory_size_bytes 在下一次容量檢查計入它。
            pass


def _atomic_create_file(
    path: Path,
    source_path: Path,
    object_reference: Mapping[str, Any],
) -> bool:
    """串流複製來源至同目錄 partial，再以 create-only link 發布。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        _verify_object(path, object_reference)
        return False
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.stem}.",
        suffix=".partial",
        dir=path.parent,
    )
    temporary_path = Path(raw_path)
    descriptor_open = True
    try:
        digest = hashlib.sha256()
        copied_bytes = 0
        expected_hash = str(object_reference["sha256"])
        expected_bytes = int(object_reference["bytes"])
        with (
            source_path.open("rb") as source,
            os.fdopen(descriptor, "wb") as target,
        ):
            descriptor_open = False
            while chunk := source.read(1 << 20):
                if copied_bytes + len(chunk) > expected_bytes:
                    raise ValueError(
                        "immutable block source changed while publishing"
                    )
                target.write(chunk)
                digest.update(chunk)
                copied_bytes += len(chunk)
            target.flush()
            os.fsync(target.fileno())
        if (
            copied_bytes != expected_bytes
            or _SHA256_PREFIX + digest.hexdigest() != expected_hash
        ):
            raise ValueError("immutable block source changed while publishing")
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            _verify_object(path, object_reference)
            return False
        except OSError as exc:
            raise OSError(
                "immutable block publish requires same-filesystem atomic link"
            ) from exc
        return True
    finally:
        if descriptor_open:
            os.close(descriptor)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            # 硬終止不會進入 finally；partial 由容量 scanner 計入。
            pass


def _record_payload(
    *,
    key: ImmutableBlockKey,
    object_reference: Mapping[str, Any],
) -> tuple[dict[str, Any], bytes]:
    body: dict[str, Any] = {
        "schema_version": BLOCK_RECORD_SCHEMA_VERSION,
        "store_schema_version": BLOCK_STORE_SCHEMA_VERSION,
        "key_hash": key.key_hash,
        "key": key.payload(),
        "object": dict(object_reference),
    }
    payload = {
        **body,
        "record_hash": _sha256_bytes(_canonical_bytes(body)),
    }
    return payload, _canonical_bytes(payload, trailing_newline=True)


def _read_json_file(path: Path, *, field_name: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    return value


def _parse_record(
    record: Mapping[str, Any],
    *,
    store_root: Path,
) -> tuple[ImmutableBlockKey, dict[str, Any], str]:
    expected_fields = {
        "schema_version",
        "store_schema_version",
        "key_hash",
        "key",
        "object",
        "record_hash",
    }
    if set(record) != expected_fields:
        raise ValueError("immutable block record fields are invalid")
    if record.get("schema_version") != BLOCK_RECORD_SCHEMA_VERSION:
        raise ValueError("immutable block record schema_version mismatch")
    if record.get("store_schema_version") != BLOCK_STORE_SCHEMA_VERSION:
        raise ValueError("immutable block store schema_version mismatch")
    record_hash = _required_sha256(
        record.get("record_hash"),
        field_name="record_hash",
    )
    body = dict(record)
    body.pop("record_hash", None)
    if _sha256_bytes(_canonical_bytes(body)) != record_hash:
        raise ValueError("immutable block record hash mismatch")
    key_value = record.get("key")
    if not isinstance(key_value, Mapping):
        raise TypeError("immutable block record key is missing")
    key = ImmutableBlockKey.from_payload(key_value)
    if record.get("key_hash") != key.key_hash:
        raise ValueError("immutable block record key hash mismatch")
    object_reference, _object_path_value = _validate_object_reference(
        record.get("object"),
        store_root=store_root,
        field_name="record.object",
    )
    return key, object_reference, record_hash


def _planned_missing_bytes(path: Path, raw: bytes) -> int:
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ValueError(f"immutable block path collision: {path}")
        return 0
    return len(raw)


def _planned_missing_object_bytes(
    path: Path,
    object_reference: Mapping[str, Any],
) -> int:
    if os.path.lexists(path):
        _verify_object(path, object_reference)
        return 0
    return int(object_reference["bytes"])


def _validate_nonnegative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _observed_temporary_bytes(
    temporary_roots: Sequence[Path],
    explicit_peak_bytes: int | None,
) -> int | None:
    """讀取 caller 提供的暫存根目錄，並合併已量測的歷史峰值。"""

    if explicit_peak_bytes is not None:
        _validate_nonnegative_int(
            explicit_peak_bytes,
            field_name="temporary_peak_bytes_observed",
        )
    if not temporary_roots:
        return explicit_peak_bytes
    current_bytes = sum(
        directory_size_bytes(Path(root)) for root in temporary_roots
    )
    if explicit_peak_bytes is None:
        return current_bytes
    return max(explicit_peak_bytes, current_bytes)


def _acquire_publish_reservation(
    lock_path: Path,
    *,
    wait_ms: int,
) -> Any:
    """在有限等待內取得 process-safe OS lock。"""

    _validate_nonnegative_int(wait_ms, field_name="lock_wait_ms")
    deadline = time.monotonic() + wait_ms / 1000
    while True:
        reservation = acquire_heavy_chain_reservation(lock_path)
        if reservation is not None:
            return reservation
        if time.monotonic() >= deadline:
            raise StorageCapacityError(
                "immutable block store publish lock is busy",
                preflight={
                    "stage": "immutable_block_publish",
                    "lock_path": str(lock_path),
                    "lock_acquired": False,
                    "blocker": "publish_lock_busy",
                },
            )
        time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))


def immutable_block_store_lock_path(store_root: Path) -> Path:
    """回傳此 registry 唯一的 canonical lock path。"""

    root = Path(store_root).resolve()
    return root.parent / ".ml_immutable_block_store.lock"


def _capacity_exceeded(
    message: str,
    *,
    lock_path: Path,
    persistent_existing_bytes: int,
    persistent_new_bytes_estimate: int,
    max_store_bytes: int,
    temporary_peak_bytes_observed: int | None,
    temporary_budget_bytes: int | None,
    blocker: str,
) -> ImmutableBlockCapacityError:
    return ImmutableBlockCapacityError(
        message,
        preflight={
            "stage": "immutable_block_publish",
            "lock_path": str(lock_path),
            "lock_acquired": True,
            "persistent_existing_bytes": persistent_existing_bytes,
            "persistent_new_bytes_estimate": persistent_new_bytes_estimate,
            "persistent_budget_bytes": max_store_bytes,
            "temporary_peak_bytes_observed": temporary_peak_bytes_observed,
            "temporary_budget_bytes": temporary_budget_bytes,
            "blocker": blocker,
        },
    )


def publish_immutable_block(
    *,
    store_root: Path,
    key: ImmutableBlockKey,
    raw: bytes | None,
    max_store_bytes: int = DEFAULT_MAX_STORE_BYTES,
    lock_path: Path | None = None,
    lock_wait_ms: int = 5_000,
    temporary_roots: Sequence[Path] = (),
    temporary_peak_bytes_observed: int | None = None,
    temporary_budget_bytes: int | None = None,
    _source_path: Path | None = None,
) -> dict[str, Any]:
    """發布或重用一個跨 run immutable block。

    ``reference`` 內的 path 一律相對於 ``store_root``；呼叫端可把它嵌入
    任意 run manifest，搬移整個 registry 後再以新 root 呼叫 loader。
    """

    if _source_path is None:
        if not isinstance(raw, bytes):
            raise TypeError("raw must be bytes")
        assert isinstance(raw, bytes)
    elif raw is not None:
        raise TypeError("raw and _source_path are mutually exclusive")
    if (
        isinstance(max_store_bytes, bool)
        or not isinstance(max_store_bytes, int)
        or max_store_bytes <= 0
        or max_store_bytes > DEFAULT_MAX_STORE_BYTES
    ):
        raise ValueError(
            f"max_store_bytes must be in 1..{DEFAULT_MAX_STORE_BYTES}"
        )
    root = Path(store_root).resolve()
    canonical_lock_path = immutable_block_store_lock_path(root)
    resolved_lock_path = (
        Path(lock_path).resolve() if lock_path is not None else canonical_lock_path
    )
    if resolved_lock_path != canonical_lock_path:
        raise ValueError(
            "lock_path must equal the immutable block store canonical lock: "
            f"{canonical_lock_path}"
        )
    if temporary_budget_bytes is not None:
        _validate_nonnegative_int(
            temporary_budget_bytes,
            field_name="temporary_budget_bytes",
        )
    resolved_temporary_roots = tuple(Path(path).resolve() for path in temporary_roots)
    source_path = (
        Path(_source_path).resolve() if _source_path is not None else None
    )
    if source_path is not None:
        object_reference = _object_reference_from_file(source_path)
    else:
        assert isinstance(raw, bytes)
        object_reference = _object_reference(raw)
    object_path = _safe_relative_path(
        root,
        object_reference["path"],
        field_name="object.path",
    )
    record_payload, record_bytes = _record_payload(
        key=key,
        object_reference=object_reference,
    )
    key_path = (
        root / "keys" / f"{key.key_hash[7:]}.json"
    ).resolve()
    _safe_relative_path(root, key_path.relative_to(root).as_posix(), field_name="key.path")

    reservation = _acquire_publish_reservation(
        resolved_lock_path,
        wait_ms=lock_wait_ms,
    )
    try:
        if os.path.lexists(key_path):
            existing_record = _read_json_file(
                key_path,
                field_name="immutable block key record",
            )
            existing_key, existing_object, _existing_record_hash = _parse_record(
                existing_record,
                store_root=root,
            )
            if (
                existing_key.payload() != key.payload()
                or existing_object != object_reference
                or key_path.read_bytes() != record_bytes
            ):
                raise ValueError("immutable block key collision with different record")
        if os.path.lexists(object_path):
            _verify_object(object_path, object_reference)

        temporary_peak = _observed_temporary_bytes(
            resolved_temporary_roots,
            temporary_peak_bytes_observed,
        )
        if temporary_budget_bytes is not None and (
            temporary_peak is None or temporary_peak > temporary_budget_bytes
        ):
            blocker = (
                "temporary_peak_bytes_unknown"
                if temporary_peak is None
                else "temporary_peak_bytes_budget_exceeded"
            )
            raise _capacity_exceeded(
                "immutable block temporary peak is outside budget",
                lock_path=resolved_lock_path,
                persistent_existing_bytes=directory_size_bytes(root),
                persistent_new_bytes_estimate=0,
                max_store_bytes=max_store_bytes,
                temporary_peak_bytes_observed=temporary_peak,
                temporary_budget_bytes=temporary_budget_bytes,
                blocker=blocker,
            )

        existing_bytes = directory_size_bytes(root)
        if source_path is not None:
            planned_new_bytes = _planned_missing_object_bytes(
                object_path,
                object_reference,
            )
        else:
            assert isinstance(raw, bytes)
            planned_new_bytes = _planned_missing_bytes(object_path, raw)
        planned_new_bytes += _planned_missing_bytes(key_path, record_bytes)
        if existing_bytes + planned_new_bytes > max_store_bytes:
            raise _capacity_exceeded(
                "immutable block store exceeds persistent budget: "
                f"{existing_bytes + planned_new_bytes}>{max_store_bytes}",
                lock_path=resolved_lock_path,
                persistent_existing_bytes=existing_bytes,
                persistent_new_bytes_estimate=planned_new_bytes,
                max_store_bytes=max_store_bytes,
                temporary_peak_bytes_observed=temporary_peak,
                temporary_budget_bytes=temporary_budget_bytes,
                blocker="persistent_budget_exceeded",
            )

        if source_path is not None:
            object_created = _atomic_create_file(
                object_path,
                source_path,
                object_reference,
            )
        else:
            assert isinstance(raw, bytes)
            object_created = _atomic_create_bytes(object_path, raw)
        _verify_object(object_path, object_reference)
        record_created = _atomic_create_bytes(key_path, record_bytes)
        if key_path.read_bytes() != record_bytes:
            raise ValueError("immutable block key record changed during publish")
        final_bytes = directory_size_bytes(root)
        if final_bytes > max_store_bytes:
            raise _capacity_exceeded(
                "immutable block store output exceeds persistent budget: "
                f"{final_bytes}>{max_store_bytes}",
                lock_path=resolved_lock_path,
                persistent_existing_bytes=existing_bytes,
                persistent_new_bytes_estimate=planned_new_bytes,
                max_store_bytes=max_store_bytes,
                temporary_peak_bytes_observed=temporary_peak,
                temporary_budget_bytes=temporary_budget_bytes,
                blocker="persistent_output_budget_exceeded",
            )
        if object_created and record_created:
            status = "immutable_block_created"
        elif object_created:
            status = "immutable_block_repaired"
        elif record_created:
            status = "immutable_block_reference_created"
        else:
            status = "immutable_block_reused"
        reference = {
            "schema_version": BLOCK_REFERENCE_SCHEMA_VERSION,
            "store_schema_version": BLOCK_STORE_SCHEMA_VERSION,
            "key_hash": key.key_hash,
            "key": key.payload(),
            "key_manifest": {
                "path": key_path.relative_to(root).as_posix(),
                "sha256": _file_sha256(key_path),
                "bytes": key_path.stat().st_size,
            },
            "object": object_reference,
        }
        return {
            "schema_version": BLOCK_REFERENCE_SCHEMA_VERSION,
            "status": status,
            "reference": reference,
            "key_hash": key.key_hash,
            "object_hash": object_reference["sha256"],
            "object_bytes": int(object_reference["bytes"]),
            "object_created": object_created,
            "reference_created": record_created,
            "new_bytes_written": (
                (
                    int(object_reference["bytes"])
                    if object_created
                    else 0
                )
                + (len(record_bytes) if record_created else 0)
            ),
            "store_bytes": final_bytes,
            "max_store_bytes": max_store_bytes,
            "persistent_existing_bytes": existing_bytes,
            "persistent_new_bytes_estimate": planned_new_bytes,
            "temporary_peak_bytes_observed": temporary_peak,
            "temporary_budget_bytes": temporary_budget_bytes,
            "lock_path": str(resolved_lock_path),
            "lock_held_through_publish": True,
        }
    finally:
        release_heavy_chain_reservation(reservation)


def publish_immutable_block_file(
    *,
    store_root: Path,
    key: ImmutableBlockKey,
    source_path: Path,
    max_store_bytes: int = DEFAULT_MAX_STORE_BYTES,
    lock_path: Path | None = None,
    lock_wait_ms: int = 5_000,
    temporary_roots: Sequence[Path] = (),
    temporary_peak_bytes_observed: int | None = None,
    temporary_budget_bytes: int | None = None,
) -> dict[str, Any]:
    """以 bounded 串流方式發布既有檔案，不先建立完整 bytes object。"""

    return publish_immutable_block(
        store_root=store_root,
        key=key,
        raw=None,
        max_store_bytes=max_store_bytes,
        lock_path=lock_path,
        lock_wait_ms=lock_wait_ms,
        temporary_roots=temporary_roots,
        temporary_peak_bytes_observed=temporary_peak_bytes_observed,
        temporary_budget_bytes=temporary_budget_bytes,
        _source_path=source_path,
    )


def load_immutable_block(
    *,
    store_root: Path,
    reference: Mapping[str, Any],
) -> ImmutableBlock:
    """以相對 reference 載入並重新驗證 key record 與 object bytes。"""

    root = Path(store_root).resolve()
    expected_fields = {
        "schema_version",
        "store_schema_version",
        "key_hash",
        "key",
        "key_manifest",
        "object",
    }
    if set(reference) != expected_fields:
        raise ValueError("immutable block reference fields are invalid")
    if reference.get("schema_version") != BLOCK_REFERENCE_SCHEMA_VERSION:
        raise ValueError("immutable block reference schema_version mismatch")
    if reference.get("store_schema_version") != BLOCK_STORE_SCHEMA_VERSION:
        raise ValueError("immutable block reference store schema_version mismatch")
    key_value = reference.get("key")
    if not isinstance(key_value, Mapping):
        raise TypeError("immutable block reference key is missing")
    key = ImmutableBlockKey.from_payload(key_value)
    if reference.get("key_hash") != key.key_hash:
        raise ValueError("immutable block reference key hash mismatch")
    key_path = _safe_relative_path(
        root,
        (
            reference.get("key_manifest", {}).get("path")
            if isinstance(reference.get("key_manifest"), Mapping)
            else None
        ),
        field_name="key_manifest.path",
    )
    expected_key_path = (root / "keys" / f"{key.key_hash[7:]}.json").resolve()
    if key_path != expected_key_path:
        raise ValueError("immutable block key manifest path is not content addressed")
    key_manifest = reference.get("key_manifest")
    if not isinstance(key_manifest, Mapping):
        raise TypeError("immutable block key_manifest is missing")
    if set(key_manifest) != {"path", "sha256", "bytes"}:
        raise ValueError("immutable block key_manifest fields are invalid")
    key_manifest_hash = _required_sha256(
        key_manifest.get("sha256"),
        field_name="key_manifest.sha256",
    )
    key_manifest_bytes = key_manifest.get("bytes")
    if (
        isinstance(key_manifest_bytes, bool)
        or not isinstance(key_manifest_bytes, int)
        or key_manifest_bytes < 0
    ):
        raise ValueError("key_manifest.bytes must be a non-negative integer")
    if (
        not key_path.is_file()
        or key_path.stat().st_size != key_manifest_bytes
        or _file_sha256(key_path) != key_manifest_hash
    ):
        raise ValueError("immutable block key manifest bytes/hash mismatch")
    record = _read_json_file(key_path, field_name="immutable block key record")
    record_key, record_object, _record_hash = _parse_record(
        record,
        store_root=root,
    )
    object_reference, object_path = _validate_object_reference(
        reference.get("object"),
        store_root=root,
        field_name="reference.object",
    )
    if record_key.payload() != key.payload() or record_object != object_reference:
        raise ValueError("immutable block reference differs from key record")
    _verify_object(object_path, object_reference)
    return ImmutableBlock(
        store_root=root,
        key=key,
        reference=dict(reference),
        object_path=object_path,
    )


__all__ = [
    "BLOCK_KEY_SCHEMA_VERSION",
    "BLOCK_RECORD_SCHEMA_VERSION",
    "BLOCK_REFERENCE_SCHEMA_VERSION",
    "BLOCK_STORE_SCHEMA_VERSION",
    "DEFAULT_MAX_STORE_BYTES",
    "ImmutableBlock",
    "ImmutableBlockCapacityError",
    "ImmutableBlockKey",
    "immutable_block_store_lock_path",
    "load_immutable_block",
    "publish_immutable_block",
    "publish_immutable_block_file",
]
