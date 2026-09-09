"""讀取並驗證 Formal／Paper 日常 wrapper 的受控候選 runtime 設定。

候選設定由 repository 內的 create-only builder 產生；這個模組是既有
Python wrapper 的 process boundary。它不會把環境變數整份落盤，也不會
修改 scheduler、D 槽或任何來源資料庫。設定不存在時保留既有入口的
defaults；設定存在時則必須完整通過 bytes/config hash、角色環境、日期與
safety contract，未到自然 activation 日只能等待，不能提前消費。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


FORMAL_RUNTIME_CONFIG_ENV = "FORMAL_DAILY_RUNTIME_CONFIG"
RUNTIME_CONFIG_ROOT_ENV = "FORMAL_DAILY_RUNTIME_CONFIG_ROOT"
RUNTIME_ENVIRONMENT_FILE_ENV = "FORMAL_DAILY_RUNTIME_ENVIRONMENT_FILE"
RUNTIME_CONFIG_SCHEMA_VERSION = "formal-paper-9-9-candidate-runtime-config.v1"
RUNTIME_ROLLING_SCHEMA_VERSION = "formal-paper-runtime-roll-forward.v1"
TAIPEI = ZoneInfo("Asia/Taipei")
_SHA256_PREFIX = "sha256:"
_SHA256_LENGTH = len(_SHA256_PREFIX) + 64
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_ENVIRONMENT_FILE = (
    _REPO_ROOT / "output" / "v4_next_formal" / "formal_runtime_environment_binding.json"
)
_RUNTIME_ENVIRONMENT_ALLOWED_KEYS = frozenset(
    {
        "BALDR_PYTHON",
        "DATA_ROOT",
        FORMAL_RUNTIME_CONFIG_ENV,
        RUNTIME_CONFIG_ROOT_ENV,
        "FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE",
        "FORMAL_DAILY_RUNTIME_ROLL_FORWARD_ROOT",
        "FORMAL_DAILY_MARKET_DB",
        "FORMAL_DAILY_RULE_BASELINE_ROOT",
        "FORMAL_DAILY_CALENDAR_CACHE_ROOT",
        "FORMAL_DAILY_PUBLICATION_ROOT",
        "FORMAL_DAILY_RULE_SOURCE_ROOT",
        "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT",
        "FORMAL_DAILY_PAPER_SNAPSHOT_DB",
        "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB",
        "FORMAL_DAILY_PAPER_RECEIPT_ROOT",
        "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST",
    }
)
_RUNTIME_ENVIRONMENT_REQUIRED_KEYS = frozenset(
    {
        FORMAL_RUNTIME_CONFIG_ENV,
        RUNTIME_CONFIG_ROOT_ENV,
        "FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE",
        "FORMAL_DAILY_RUNTIME_ROLL_FORWARD_ROOT",
        "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST",
    }
)
_MINIMUM_REQUIRED_ENVIRONMENT: dict[str, frozenset[str]] = {
    "rule_source_wrapper": frozenset({FORMAL_RUNTIME_CONFIG_ENV}),
    "pit_preopen_wrapper": frozenset({FORMAL_RUNTIME_CONFIG_ENV}),
    "pit_sidecar_wrapper": frozenset({FORMAL_RUNTIME_CONFIG_ENV}),
    "formal_input_wrapper": frozenset(
        {FORMAL_RUNTIME_CONFIG_ENV, "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST"}
    ),
    "paper_eod_wrapper": frozenset({FORMAL_RUNTIME_CONFIG_ENV}),
}


class FormalRuntimeConfigError(ValueError):
    """runtime candidate 無法在 wrapper 邊界被客觀驗證。"""


def _payload_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _SHA256_PREFIX + hashlib.sha256(encoded).hexdigest()


def _bytes_hash(raw: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(raw)
    return _SHA256_PREFIX + digest.hexdigest()


def _create_only_bytes(
    path: Path,
    encoded: bytes,
    *,
    mismatch_error: str,
) -> tuple[str, str]:
    """Create a file without an exists-check/replace race.

    The temporary bytes are fsynced first, then linked into the destination.
    ``os.link`` is an atomic no-overwrite operation on the Windows filesystem
    used by this project; a concurrent creator therefore cannot replace the
    first publisher.  An identical concurrent publication is idempotently
    read back, while different bytes fail closed.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise FormalRuntimeConfigError(
                f"runtime_environment_binding_unreadable:{type(error).__name__}"
            ) from error
        if existing == encoded:
            return "reused", _bytes_hash(existing)
        raise FormalRuntimeConfigError(mismatch_error)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as error:
                raise FormalRuntimeConfigError(
                    f"runtime_environment_binding_unreadable:{type(error).__name__}"
                ) from error
            if existing == encoded:
                return "reused", _bytes_hash(existing)
            raise FormalRuntimeConfigError(mismatch_error)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "created", _bytes_hash(encoded)


def _file_hash(path: Path) -> str:
    """以單次讀取計算檔案 hash；供其他 wrapper 讀回使用。"""

    return _bytes_hash(path.read_bytes())


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise FormalRuntimeConfigError(f"{field}_must_be_object")
    return {str(key): item for key, item in value.items()}


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalRuntimeConfigError(f"{field}_missing")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    text = _required_text(value, field)
    if len(text) != _SHA256_LENGTH or not text.startswith(_SHA256_PREFIX):
        raise FormalRuntimeConfigError(f"{field}_invalid_sha256")
    try:
        int(text[len(_SHA256_PREFIX) :], 16)
    except ValueError as error:
        raise FormalRuntimeConfigError(f"{field}_invalid_sha256") from error
    return text


def _load_json(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FormalRuntimeConfigError(
            f"runtime_config_unreadable:{type(error).__name__}"
        ) from error
    if not isinstance(value, Mapping):
        raise FormalRuntimeConfigError("runtime_config_must_be_object")
    return {str(key): item for key, item in value.items()}


def _parse_date(value: object, field: str) -> date:
    text = _required_text(value, field)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise FormalRuntimeConfigError(f"{field}_invalid_date") from error
    if parsed.isoformat() != text:
        raise FormalRuntimeConfigError(f"{field}_invalid_date")
    return parsed


def _observed(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise FormalRuntimeConfigError("observed_requires_timezone")
    return result.astimezone(timezone.utc)


def _repo_output_path(path: Path, field: str) -> Path:
    resolved = path.expanduser().resolve()
    output_root = (_REPO_ROOT / "output").resolve()
    try:
        resolved.relative_to(output_root)
    except ValueError as error:
        raise FormalRuntimeConfigError(f"{field}_outside_repository_output") from error
    return resolved


def _runtime_environment_path() -> Path | None:
    raw = os.environ.get(RUNTIME_ENVIRONMENT_FILE_ENV)
    if isinstance(raw, str) and raw.strip():
        return _repo_output_path(
            Path(raw.strip()),
            "runtime_environment_binding",
        )
    if DEFAULT_RUNTIME_ENVIRONMENT_FILE.is_file():
        return DEFAULT_RUNTIME_ENVIRONMENT_FILE.resolve()
    return None


def _environment_values_from_contract(payload: Mapping[str, object]) -> dict[str, str]:
    contracts = _mapping(payload.get("wrapper_contract"), "wrapper_contract")
    values: dict[str, str] = {}
    for role, raw_contract in contracts.items():
        contract = _mapping(raw_contract, f"wrapper_contract.{role}")
        environment = _mapping(
            contract.get("environment"),
            f"wrapper_contract.{role}.environment",
        )
        for raw_name, raw_value in environment.items():
            name = str(raw_name)
            if not isinstance(raw_value, str) or raw_value.startswith("omitted;"):
                continue
            if not raw_value.strip():
                raise FormalRuntimeConfigError(
                    f"wrapper_contract.{role}.environment.{name}_missing"
                )
            if name not in _RUNTIME_ENVIRONMENT_ALLOWED_KEYS:
                raise FormalRuntimeConfigError(
                    f"runtime_environment_key_not_allowlisted:{name}"
                )
            value = raw_value.strip()
            previous = values.get(name)
            if previous is not None and previous != value:
                raise FormalRuntimeConfigError(
                    f"runtime_environment_conflicting_value:{name}"
                )
            values[name] = value
    missing = sorted(_RUNTIME_ENVIRONMENT_REQUIRED_KEYS - values.keys())
    if missing:
        raise FormalRuntimeConfigError(
            "runtime_environment_required_key_missing:" + ",".join(missing)
        )
    return values


def _read_binding_config(
    config_path: Path,
    *,
    raw: bytes | None = None,
) -> tuple[Path, bytes, dict[str, object], dict[str, str]]:
    """Read and validate one candidate before deriving process environment.

    ``raw`` is accepted by the binding loader so JSON parsing, the candidate
    config hash, and the source file hash all refer to the same immutable byte
    snapshot.  The deployment boundary uses the same helper as the active
    binding builder; a hand-written environment file cannot silently point at
    a valid config while carrying a different set of paths.
    """

    resolved_config = _repo_output_path(config_path, "runtime_config")
    if raw is None:
        if not resolved_config.is_file():
            raise FormalRuntimeConfigError(f"runtime_config_missing:{resolved_config}")
        try:
            raw = resolved_config.read_bytes()
        except OSError as error:
            raise FormalRuntimeConfigError(
                f"runtime_config_unreadable:{type(error).__name__}"
            ) from error
    if raw is None:  # pragma: no cover - narrowed after the read branch
        raise FormalRuntimeConfigError("runtime_config_unreadable:empty_snapshot")
    config = _load_json(raw)
    if config.get("schema_version") != RUNTIME_CONFIG_SCHEMA_VERSION:
        raise FormalRuntimeConfigError("runtime_config_schema_invalid")
    if config.get("status") != "candidate_ready_for_root_review":
        raise FormalRuntimeConfigError("runtime_config_status_invalid")
    supplied_config_hash = _sha256(config.get("config_hash"), "runtime_config.config_hash")
    config_body = dict(config)
    config_body.pop("config_hash", None)
    if _payload_hash(config_body) != supplied_config_hash:
        raise FormalRuntimeConfigError("runtime_config_config_hash_mismatch")
    values = _environment_values_from_contract(config)
    if Path(values[FORMAL_RUNTIME_CONFIG_ENV]).expanduser().resolve() != resolved_config:
        raise FormalRuntimeConfigError("runtime_environment_config_path_mismatch")
    root = Path(values[RUNTIME_CONFIG_ROOT_ENV]).expanduser().resolve()
    try:
        resolved_config.relative_to(root)
    except ValueError as error:
        raise FormalRuntimeConfigError(
            "runtime_environment_config_outside_declared_root"
        ) from error
    return resolved_config, raw, config, values


def read_runtime_environment_values(config_path: Path) -> dict[str, str]:
    """Return the validated process-only environment map for a candidate."""

    return dict(_read_binding_config(config_path)[3])


def build_runtime_environment_binding(
    config_path: Path,
    *,
    output_path: Path = DEFAULT_RUNTIME_ENVIRONMENT_FILE,
    owner_decision_id: str,
    approved_at: datetime | None = None,
) -> tuple[str, str]:
    """建立一次性、allowlist/hash 綁定檔；已存在且不同時拒絕覆寫。"""

    resolved_output = _repo_output_path(output_path, "runtime_environment_binding")
    resolved_config, config_raw, _config, values = _read_binding_config(config_path)
    decision_id = _required_text(owner_decision_id, "owner_decision_id")
    approved = _observed(approved_at)
    if approved > datetime.now(timezone.utc):
        raise FormalRuntimeConfigError("owner_decision_timestamp_in_future")
    body: dict[str, object] = {
        "schema_version": "formal-runtime-environment-binding.v1",
        "status": "active",
        "binding_id": f"formal-runtime:{decision_id}",
        "approved_at": approved.isoformat(timespec="microseconds"),
        "approval": {
            "owner_decision_id": decision_id,
            "identity": "machine root review",
            "scope": "candidate-only five-role runtime environment binding",
        },
        "source_config_path": str(resolved_config),
        "source_config_file_hash": _bytes_hash(config_raw),
        "environment": dict(sorted(values.items())),
        "safety": {
            "candidate_only": True,
            "formal_oos_allowed": False,
            "writes_market_database": False,
            "writes_formal_controlled_paths": False,
            "writes_scheduler": False,
            "broker_order_allowed": False,
        },
    }
    payload = {**body, "content_sha256": _payload_hash(body)}
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    return _create_only_bytes(
        resolved_output,
        encoded,
        mismatch_error="runtime_environment_binding_existing_bytes_mismatch",
    )


def load_runtime_environment_binding() -> Path | None:
    """讀取並套用 active binding；只允許固定 allowlist 與 exact hashes。"""

    path = _runtime_environment_path()
    if path is None:
        return None
    if not path.is_file():
        raise FormalRuntimeConfigError(f"runtime_environment_binding_missing:{path}")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise FormalRuntimeConfigError(
            f"runtime_environment_binding_unreadable:{type(error).__name__}"
        ) from error
    payload = _load_json(raw)
    if payload.get("schema_version") != "formal-runtime-environment-binding.v1":
        raise FormalRuntimeConfigError("runtime_environment_binding_schema_invalid")
    if payload.get("status") != "active":
        raise FormalRuntimeConfigError("runtime_environment_binding_status_invalid")
    declared_content_hash = _sha256(
        payload.get("content_sha256"),
        "runtime_environment_binding.content_sha256",
    )
    body = dict(payload)
    body.pop("content_sha256", None)
    if _payload_hash(body) != declared_content_hash:
        raise FormalRuntimeConfigError("runtime_environment_binding_content_hash_mismatch")
    approval = _mapping(payload.get("approval"), "runtime_environment_binding.approval")
    _required_text(approval.get("owner_decision_id"), "owner_decision_id")
    approved_at = _required_text(payload.get("approved_at"), "approved_at")
    try:
        approved = _observed(datetime.fromisoformat(approved_at))
    except (TypeError, ValueError) as error:
        raise FormalRuntimeConfigError("runtime_environment_binding_approved_at_invalid") from error
    if approved > datetime.now(timezone.utc):
        raise FormalRuntimeConfigError("runtime_environment_binding_timestamp_in_future")
    safety = _mapping(payload.get("safety"), "runtime_environment_binding.safety")
    for key in (
        "formal_oos_allowed",
        "writes_market_database",
        "writes_formal_controlled_paths",
        "writes_scheduler",
        "broker_order_allowed",
    ):
        if safety.get(key) is not False:
            raise FormalRuntimeConfigError(
                f"runtime_environment_binding.safety.{key}_must_be_false"
            )
    if safety.get("candidate_only") is not True:
        raise FormalRuntimeConfigError(
            "runtime_environment_binding.safety_candidate_only_invalid"
        )
    source_config = Path(
        _required_text(payload.get("source_config_path"), "source_config_path")
    ).expanduser().resolve()
    source_config = _repo_output_path(source_config, "source_config_path")
    if not source_config.is_file():
        raise FormalRuntimeConfigError(
            f"runtime_environment_binding_source_config_missing:{source_config}"
        )
    try:
        source_raw = source_config.read_bytes()
    except OSError as error:
        raise FormalRuntimeConfigError(
            f"runtime_environment_binding_source_config_unreadable:{type(error).__name__}"
        ) from error
    if _bytes_hash(source_raw) != _sha256(
        payload.get("source_config_file_hash"),
        "source_config_file_hash",
    ):
        raise FormalRuntimeConfigError(
            "runtime_environment_binding_source_config_hash_mismatch"
        )
    values = _mapping(payload.get("environment"), "runtime_environment_binding.environment")
    unknown = sorted(set(values) - _RUNTIME_ENVIRONMENT_ALLOWED_KEYS)
    if unknown:
        raise FormalRuntimeConfigError(
            "runtime_environment_binding_key_not_allowlisted:" + ",".join(unknown)
        )
    environment: dict[str, str] = {}
    for name, raw_value in values.items():
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise FormalRuntimeConfigError(
                f"runtime_environment_binding_value_invalid:{name}"
            )
        environment[str(name)] = raw_value.strip()
    # Re-derive the map from the exact source-config bytes.  Content hashes
    # detect accidental edits, while this comparison prevents a separately
    # re-hashed binding from pointing a valid candidate at a different DB,
    # publication root, or clock.
    source_payload = _load_json(source_raw)
    expected_environment = _environment_values_from_contract(source_payload)
    if environment != expected_environment:
        raise FormalRuntimeConfigError(
            "runtime_environment_binding_config_environment_mismatch"
        )
    missing = sorted(_RUNTIME_ENVIRONMENT_REQUIRED_KEYS - environment.keys())
    if missing:
        raise FormalRuntimeConfigError(
            "runtime_environment_binding_required_key_missing:" + ",".join(missing)
        )
    if Path(environment[FORMAL_RUNTIME_CONFIG_ENV]).expanduser().resolve() != source_config:
        raise FormalRuntimeConfigError(
            "runtime_environment_binding_config_path_mismatch"
        )
    root = Path(environment[RUNTIME_CONFIG_ROOT_ENV]).expanduser().resolve()
    try:
        source_config.relative_to(root)
    except ValueError as error:
        raise FormalRuntimeConfigError(
            "runtime_environment_binding_config_outside_root"
        ) from error
    # All fields are validated before mutating this process environment.  A
    # fresh Task Scheduler process therefore gets one deterministic allowlist.
    # Preserve a process-local date binding already selected by the loader;
    # otherwise a repeated role read would reset it to the initial preactivation
    # path before selecting the same exact natural-day file again.
    current_runtime = os.environ.get(FORMAL_RUNTIME_CONFIG_ENV)
    preserve_runtime = False
    if isinstance(current_runtime, str) and current_runtime.strip():
        current_path = Path(current_runtime.strip()).expanduser().resolve()
        try:
            current_path.relative_to(root)
            preserve_runtime = current_path.is_file()
        except ValueError:
            preserve_runtime = False
    for name in sorted(environment):
        if name == FORMAL_RUNTIME_CONFIG_ENV and preserve_runtime:
            continue
        os.environ[name] = environment[name]
    return path


def disable_runtime_environment_binding(
    output_path: Path = DEFAULT_RUNTIME_ENVIRONMENT_FILE,
) -> tuple[str, str]:
    """以不可啟用的 marker 停用 binding，供可逆 rollback 使用。"""

    resolved_output = _repo_output_path(output_path, "runtime_environment_binding")
    body: dict[str, object] = {
        "schema_version": "formal-runtime-environment-binding.v1",
        "status": "inactive",
        "disabled_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "safety": {
            "candidate_only": True,
            "formal_oos_allowed": False,
            "writes_market_database": False,
            "writes_formal_controlled_paths": False,
            "writes_scheduler": False,
            "broker_order_allowed": False,
        },
    }
    payload = {**body, "content_sha256": _payload_hash(body)}
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved_output.with_name(
        f".{resolved_output.name}.{os.getpid()}.tmp"
    )
    try:
        with temporary.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, resolved_output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "disabled", _bytes_hash(encoded)


def _normalise_environment_value(name: str, value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    # The builder stores absolute Windows paths.  Comparing resolved paths
    # permits cmd.exe's harmless relative spelling while still rejecting a
    # different source/output location.  Non-path contract values remain
    # exact strings.
    if (
        name.endswith(("_PATH", "_ROOT", "_DB", "_DIR"))
        or name in {"BALDR_PYTHON", "DATA_ROOT"}
    ):
        try:
            return str(Path(text).expanduser().resolve()).casefold()
        except (OSError, RuntimeError):
            return text.casefold()
    return text


def _validate_environment_contract(
    contract: Mapping[str, object],
    *,
    role: str,
    config_path: Path,
) -> dict[str, object]:
    role_contract = _mapping(contract.get(role), f"wrapper_contract.{role}")
    environment = _mapping(
        role_contract.get("environment"),
        f"wrapper_contract.{role}.environment",
    )
    expected_runtime_path = _normalise_environment_value(
        FORMAL_RUNTIME_CONFIG_ENV,
        str(environment.get(FORMAL_RUNTIME_CONFIG_ENV, "")),
    )
    if expected_runtime_path != _normalise_environment_value(
        FORMAL_RUNTIME_CONFIG_ENV,
        str(config_path),
    ):
        raise FormalRuntimeConfigError(
            f"{role}_runtime_config_binding_path_mismatch"
        )
    required_environment = role_contract.get("required_environment", [])
    if not isinstance(required_environment, list):
        raise FormalRuntimeConfigError(
            f"wrapper_contract.{role}.required_environment_invalid"
        )
    required_names: set[str] = set()
    for item in required_environment:
        if not isinstance(item, str) or not item.strip():
            raise FormalRuntimeConfigError(
                f"wrapper_contract.{role}.required_environment_invalid"
            )
        required_names.add(item.strip())
    # A hand-authored or older candidate must not bypass the process-boundary
    # pin simply by omitting ``required_environment``.  These minimums are
    # part of the loader contract; the builder may require additional keys.
    required_names.update(_MINIMUM_REQUIRED_ENVIRONMENT.get(role, frozenset()))
    missing_required = sorted(
        name
        for name in required_names
        if not isinstance(os.environ.get(name), str)
        or not os.environ.get(name, "").strip()
    )
    if missing_required:
        raise FormalRuntimeConfigError(
            f"{role}_required_environment_missing:{','.join(missing_required)}"
        )
    mismatches: list[str] = []
    checked: dict[str, str] = {}
    for key, expected in environment.items():
        name = str(key)
        if name == FORMAL_RUNTIME_CONFIG_ENV:
            expected_text = str(expected)
        elif not isinstance(expected, str) or expected.startswith("omitted;"):
            continue
        else:
            expected_text = expected
        actual = os.environ.get(name)
        if actual is None or not actual.strip():
            # Optional legacy values may be omitted; every value explicitly
            # marked required above must already be present at this process
            # boundary so a Python default cannot silently select old paths.
            continue
        checked[name] = actual
        if _normalise_environment_value(name, actual) != _normalise_environment_value(
            name, expected_text
        ):
            mismatches.append(name)
    if mismatches:
        raise FormalRuntimeConfigError(
            f"{role}_environment_mismatch:{','.join(sorted(mismatches))}"
        )
    entrypoint = role_contract.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint.strip():
        raise FormalRuntimeConfigError(f"{role}_entrypoint_missing")
    return {
        "entrypoint": entrypoint,
        "environment_keys": sorted(str(key) for key in environment),
        "environment_values_checked": sorted(checked),
        "environment_match": True,
        "rule_source_predecessor": (
            dict(_mapping(role_contract.get("rule_source_predecessor"), "rule_source_predecessor"))
            if isinstance(role_contract.get("rule_source_predecessor"), Mapping)
            else None
        ),
    }


def _validate_rolling_contract(value: object) -> dict[str, object]:
    rolling = _mapping(value, "rolling_contract")
    if rolling.get("schema_version") != RUNTIME_ROLLING_SCHEMA_VERSION:
        raise FormalRuntimeConfigError("rolling_contract_schema_invalid")
    if rolling.get("natural_date_timezone") != "Asia/Taipei":
        raise FormalRuntimeConfigError("rolling_contract_timezone_invalid")
    if rolling.get("same_candidate_reuse_prohibited") is not True:
        raise FormalRuntimeConfigError("rolling_contract_reuse_guard_missing")
    if rolling.get("requires_date_scoped_config") is not True:
        raise FormalRuntimeConfigError("rolling_contract_date_scope_missing")
    path_patterns = _mapping(rolling.get("path_patterns"), "rolling_contract.path_patterns")
    required_patterns = {
        "runtime_config",
        "pit_archive_manifest",
        "rule_source_bundle_manifest",
        "rule_history_manifest",
        "portfolio_clock_manifest",
        "formal_pit_sidecar",
        "paper_eod_receipt_root",
        "causal_ledger_manifest",
    }
    if not required_patterns.issubset(path_patterns):
        raise FormalRuntimeConfigError("rolling_contract_path_patterns_incomplete")
    for key in required_patterns:
        _required_text(path_patterns.get(key), f"rolling_contract.path_patterns.{key}")
    date_fields = rolling.get("date_scoped_fields")
    if not isinstance(date_fields, list) or not date_fields:
        raise FormalRuntimeConfigError("rolling_contract_date_fields_missing")
    for item in date_fields:
        _required_text(item, "rolling_contract.date_scoped_field")
    sequence = rolling.get("consumer_sequence")
    if not isinstance(sequence, list) or not sequence:
        raise FormalRuntimeConfigError("rolling_contract_consumer_sequence_missing")
    return {
        "schema_version": RUNTIME_ROLLING_SCHEMA_VERSION,
        "natural_date_timezone": "Asia/Taipei",
        "same_candidate_reuse_prohibited": True,
        "requires_date_scoped_config": True,
        "date_scoped_fields": [str(item) for item in date_fields],
        "path_patterns": {str(key): str(value) for key, value in path_patterns.items()},
        "consumer_sequence": [str(item) for item in sequence],
        "late_replay_policy": rolling.get("late_replay_policy"),
    }


def _safe_projection(
    *,
    path: Path,
    payload: Mapping[str, object],
    file_hash: str,
    config_hash: str,
    activation: date,
    observed: datetime,
    role: str,
    role_projection: Mapping[str, object],
    rolling: Mapping[str, object],
) -> dict[str, object]:
    local_date = observed.astimezone(TAIPEI).date()
    if local_date < activation:
        activation_status = "waiting_for_activation"
    elif local_date == activation:
        activation_status = "active"
    else:
        raise FormalRuntimeConfigError(
            f"runtime_config_expired:{activation.isoformat()}:{local_date.isoformat()}"
        )
    publication_paths = payload.get("publication_paths")
    published = (
        {str(key): str(value) for key, value in publication_paths.items()}
        if isinstance(publication_paths, Mapping)
        else {}
    )
    return {
        "status": "verified",
        "role": role,
        "path": str(path),
        "file_hash": file_hash,
        "config_hash": config_hash,
        "schema_version": payload.get("schema_version"),
        "activation_trading_day": activation.isoformat(),
        "activation_status": activation_status,
        "observed_at": observed.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ),
        "decision_timezone": "Asia/Taipei",
        "role_contract": dict(role_projection),
        "publication_paths": published,
        "rolling_contract": dict(rolling),
        "candidate_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "writes_formal_controlled_paths": False,
        "writes_market_database": False,
        "historical_backfill_claimed": False,
    }


def load_formal_runtime_config(
    path: Path,
    *,
    role: str,
    observed: datetime | None = None,
) -> dict[str, object]:
    """讀取一份已指定的 runtime config，並回傳不含 secret 的 attestation。"""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FormalRuntimeConfigError(f"runtime_config_missing:{resolved}")
    try:
        raw = resolved.read_bytes()
    except OSError as error:
        raise FormalRuntimeConfigError(
            f"runtime_config_unreadable:{type(error).__name__}"
        ) from error
    # Parse and hash the same immutable byte snapshot.  A second read could
    # otherwise validate one version and attest another after a replacement.
    file_hash = _bytes_hash(raw)
    payload = _load_json(raw)
    if payload.get("schema_version") != RUNTIME_CONFIG_SCHEMA_VERSION:
        raise FormalRuntimeConfigError("runtime_config_schema_invalid")
    if payload.get("status") != "candidate_ready_for_root_review":
        raise FormalRuntimeConfigError("runtime_config_status_invalid")
    supplied_hash = _sha256(payload.get("config_hash"), "runtime_config.config_hash")
    body = dict(payload)
    body.pop("config_hash", None)
    if _payload_hash(body) != supplied_hash:
        raise FormalRuntimeConfigError("runtime_config_config_hash_mismatch")
    binding = _mapping(payload.get("runtime_config_binding"), "runtime_config_binding")
    binding_path = _required_text(binding.get("path"), "runtime_config_binding.path")
    if Path(binding_path).expanduser().resolve() != resolved:
        raise FormalRuntimeConfigError("runtime_config_binding.path_mismatch")
    embedded_file_hash = binding.get("file_hash")
    if embedded_file_hash is not None:
        if _sha256(embedded_file_hash, "runtime_config_binding.file_hash") != file_hash:
            raise FormalRuntimeConfigError("runtime_config_binding.file_hash_mismatch")
    if binding.get("environment_variable") != FORMAL_RUNTIME_CONFIG_ENV:
        raise FormalRuntimeConfigError("runtime_config_binding.environment_invalid")
    activation = _parse_date(
        payload.get("activation_trading_day"),
        "activation_trading_day",
    )
    runtime_attestation = _mapping(
        payload.get("runtime_attestation"),
        "runtime_attestation",
    )
    if runtime_attestation.get("observed_clock_is_runtime_only") is not True:
        raise FormalRuntimeConfigError("runtime_attestation_clock_invalid")
    if runtime_attestation.get("secret_values_emitted") is not False:
        raise FormalRuntimeConfigError("runtime_attestation_secret_boundary_invalid")
    safety = _mapping(payload.get("safety"), "safety")
    for key in (
        "writes_market_database",
        "writes_formal_controlled_paths",
        "writes_scheduler",
        "broker_execution",
        "historical_backfill_claimed",
    ):
        if safety.get(key) is not False:
            raise FormalRuntimeConfigError(f"safety.{key}_must_be_false")
    if safety.get("read_only_sources") is not True or safety.get("candidate_only") is not True:
        raise FormalRuntimeConfigError("safety_candidate_boundary_invalid")
    rolling = _validate_rolling_contract(payload.get("rolling_contract"))
    role_projection = _validate_environment_contract(
        _mapping(payload.get("wrapper_contract"), "wrapper_contract"),
        role=role,
        config_path=resolved,
    )
    return _safe_projection(
        path=resolved,
        payload=payload,
        file_hash=file_hash,
        config_hash=supplied_hash,
        activation=activation,
        observed=_observed(observed),
        role=role,
        role_projection=role_projection,
        rolling=rolling,
    )


def load_optional_formal_runtime_config(
    *,
    role: str,
    observed: datetime | None = None,
) -> dict[str, object] | None:
    """由 wrapper process environment 綁定 runtime config。

    若呼叫端一次性 pin 了 ``FORMAL_DAILY_RUNTIME_CONFIG_ROOT``，只依目前
    台北自然日讀取同名 date-scoped JSON，並在目前 process 內更新
    ``FORMAL_DAILY_RUNTIME_CONFIG``。這不是 latest 掃描：缺少當日檔案時，
    只有既有 explicit path 可供 pre-activation waiting fallback；已過期的
    explicit path 仍由正式 loader 拒絕。
    """

    load_runtime_environment_binding()
    raw_root = os.environ.get(RUNTIME_CONFIG_ROOT_ENV)
    raw_path = os.environ.get(FORMAL_RUNTIME_CONFIG_ENV)
    selected_path: Path | None = None
    if isinstance(raw_root, str) and raw_root.strip():
        observed_utc = _observed(observed)
        selected = (
            Path(raw_root.strip()).expanduser().resolve()
            / f"{observed_utc.astimezone(TAIPEI).date().isoformat()}.json"
        )
        if selected.is_file():
            selected_path = selected
            os.environ[FORMAL_RUNTIME_CONFIG_ENV] = str(selected)
        elif not isinstance(raw_path, str) or not raw_path.strip():
            raise FormalRuntimeConfigError(
                "runtime_config_date_scoped_missing:"
                f"{observed_utc.astimezone(TAIPEI).date().isoformat()}"
            )
    if selected_path is None:
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None
        selected_path = Path(raw_path.strip())
    if selected_path is None:  # pragma: no cover - narrowed above
        return None
    return load_formal_runtime_config(
        selected_path,
        role=role,
        observed=observed,
    )


__all__ = [
    "FORMAL_RUNTIME_CONFIG_ENV",
    "RUNTIME_CONFIG_ROOT_ENV",
    "RUNTIME_ENVIRONMENT_FILE_ENV",
    "DEFAULT_RUNTIME_ENVIRONMENT_FILE",
    "FormalRuntimeConfigError",
    "build_runtime_environment_binding",
    "read_runtime_environment_values",
    "load_runtime_environment_binding",
    "disable_runtime_environment_binding",
    "RUNTIME_CONFIG_SCHEMA_VERSION",
    "load_formal_runtime_config",
    "load_optional_formal_runtime_config",
]
