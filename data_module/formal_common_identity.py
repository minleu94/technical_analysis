"""三項 Formal source 的共同 clock／Rule lineage identity producer。

這個模組位於每日 producer 與 controlled handoff 之間。呼叫端必須傳入
三個 exact source path 與三個 exact producer receipt path；模組不掃描目錄、
不猜 ``latest``，而是以正式 consumer 重讀同一組 bytes 後才建立
create-only identity。identity 仍是 candidate evidence，永遠不會修改
受控環境、D 槽來源或 Formal credit。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, cast
from zoneinfo import ZoneInfo

from data_module.formal_daily_input_producer import (
    DailyFormalInputPaths,
    FormalDailyInputProducerError,
    _readback_explicit_formal_sources,
)
from data_module.formal_pit_sector_publisher import (
    FORMAL_PIT_SECTOR_RECEIPT_SCHEMA_VERSION,
    read_formal_pit_sector_receipt,
)
from data_module.prospective_activation_environment import FORMAL_PATH_ENV_NAMES
from data_module.prospective_formal_clock import (
    canonical_json,
    file_sha256,
    load_clock_manifest,
    load_clock_manifest_for_capture,
)


FORMAL_COMMON_IDENTITY_SCHEMA_VERSION = "formal-common-identity-manifest.v1"
FORMAL_COMMON_IDENTITY_VERSION = "formal-common-identity-producer.v1"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TAIPEI = ZoneInfo("Asia/Taipei")

_INPUT_BY_ENV = {
    FORMAL_PATH_ENV_NAMES[0]: "causal_non_cash_portfolio_ledger",
    FORMAL_PATH_ENV_NAMES[1]: "formal_rule_champion_snapshot_history",
    FORMAL_PATH_ENV_NAMES[2]: "pit_sector_membership",
}
_ENV_BY_INPUT = {value: key for key, value in _INPUT_BY_ENV.items()}


class FormalCommonIdentityError(ValueError):
    """共同 identity 無法由 exact producer／consumer evidence 建立。"""


def build_formal_common_identity_manifest(
    *,
    source_paths: Mapping[str, Path | str],
    source_receipt_paths: Mapping[str, Path | str],
    portfolio_clock_manifest: Path,
    market_db: Path,
    output_root: Path,
    development_output_root: Path,
    training_as_of: str,
    observed: datetime,
    daily_rule_lineage: Mapping[str, object],
) -> dict[str, object]:
    """以三個 exact source、receipt 與 consumer readback 建立 identity。

    ``source_paths``／``source_receipt_paths`` 的 key 必須是完整的
    ``BALDR_ML_*`` environment name。daily Rule clock 可與 portfolio clock
    不同，但它只會被保存為 lineage；三項 entry 的 common clock 永遠是
    cumulative portfolio clock。
    """

    observed_utc = _aware_datetime(observed, "observed")
    normalized_sources = _normalize_path_map(
        source_paths,
        field="source_paths",
        required_keys=FORMAL_PATH_ENV_NAMES,
    )
    normalized_receipts = _normalize_path_map(
        source_receipt_paths,
        field="source_receipt_paths",
        required_keys=FORMAL_PATH_ENV_NAMES,
    )
    clock_path = _resolve_file(portfolio_clock_manifest, "portfolio_clock_manifest")
    clock = _load_clock_for_identity(clock_path, now=observed_utc)
    if clock.activation_trading_day > observed_utc.astimezone(TAIPEI).date():
        raise FormalCommonIdentityError(
            "common portfolio clock activation is after observed"
        )
    clock_payload = clock.payload
    portfolio_activation = clock.activation_trading_day.isoformat()
    policy_hash = _required_sha256(clock_payload.get("policy_hash"), "clock.policy_hash")
    universe_hash = _required_sha256(
        clock_payload.get("universe_hash"), "clock.universe_hash"
    )
    training_as_of_utc = _aware_datetime(training_as_of, "training_as_of")
    if training_as_of_utc > observed_utc:
        raise FormalCommonIdentityError("training_as_of is after observed")

    lineage = _validate_daily_rule_lineage(
        daily_rule_lineage,
        portfolio_activation=portfolio_activation,
        common_policy_hash=policy_hash,
        observed_date=observed_utc.astimezone(TAIPEI).date(),
    )

    formal_paths = DailyFormalInputPaths(
        output_root=output_root,
        development_output_root=development_output_root,
        market_db=market_db,
        formal_ledger_path=normalized_sources[FORMAL_PATH_ENV_NAMES[0]],
        formal_rule_history_path=normalized_sources[FORMAL_PATH_ENV_NAMES[1]],
        formal_sector_path=normalized_sources[FORMAL_PATH_ENV_NAMES[2]],
    )
    try:
        readback, blockers = _readback_explicit_formal_sources(
            formal_paths,
            training_as_of=training_as_of,
        )
    except Exception as error:  # noqa: BLE001 - preserve source blocker
        raise FormalCommonIdentityError(
            "formal consumer readback failed:" + _safe_error(error)
        ) from error
    if blockers:
        raise FormalCommonIdentityError(
            "formal consumer blockers:" + ",".join(sorted(set(blockers)))
        )
    if set(readback) != set(_INPUT_BY_ENV.values()):
        raise FormalCommonIdentityError("formal consumer readback is incomplete")
    for input_name, result in readback.items():
        if result.get("formal_ready") is not True:
            raise FormalCommonIdentityError(
                f"{input_name} consumer is not formal_ready"
            )
        if result.get("formal_consumer_compatible") is not True:
            raise FormalCommonIdentityError(
                f"{input_name} consumer is not compatible"
            )
        if result.get("consumer_verified") is not True:
            raise FormalCommonIdentityError(
                f"{input_name} consumer verification is missing"
            )

    receipt_evidence: dict[str, dict[str, object]] = {}
    entries: dict[str, dict[str, object]] = {}
    for environment_name in FORMAL_PATH_ENV_NAMES:
        input_name = _INPUT_BY_ENV[environment_name]
        source_path = normalized_sources[environment_name]
        receipt_path = normalized_receipts[environment_name]
        receipt = _read_and_validate_receipt(
            receipt_path,
            input_name=input_name,
            source_path=source_path,
            observed=observed_utc,
            common_clock=_clock_binding_projection(
                clock,
                clock_path=clock_path,
                policy_hash=policy_hash,
                universe_hash=universe_hash,
            ),
            daily_rule_lineage=lineage,
        )
        readback_result = readback[input_name]
        if _resolved_text(readback_result.get("path")) != str(source_path):
            raise FormalCommonIdentityError(
                f"{input_name} consumer path differs from supplied source"
            )
        if readback_result.get("file_hash") != file_sha256(source_path):
            raise FormalCommonIdentityError(
                f"{input_name} consumer file hash changed during identity build"
            )
        receipt_evidence[environment_name] = receipt
        entry: dict[str, object] = {
            "environment_name": environment_name,
            "input": input_name,
            "path": str(source_path),
            "path_hash": _payload_hash(
                {"env_name": environment_name, "path": str(source_path)}
            ),
            "file_hash": file_sha256(source_path),
            "receipt_path": str(receipt_path),
            "receipt_file_hash": receipt["receipt_file_hash"],
            "receipt_hash": receipt["receipt_hash"],
            "receipt_schema_version": receipt["schema_version"],
            "producer_consumer_verified": True,
            "producer_candidate_only": receipt["candidate_only"],
            "consumer_verified": True,
            "formal_ready": True,
            "formal_consumer_compatible": True,
            "clock_id": clock.clock_id,
            "clock_manifest_hash": clock.manifest_hash,
            "clock_scope": "cumulative_portfolio_state",
            "policy_hash": policy_hash,
            "universe_hash": universe_hash,
            "portfolio_policy_hash": policy_hash,
            "portfolio_universe_hash": universe_hash,
            "daily_rule_lineage_hash": _payload_hash(lineage),
            "daily_rule_lineage_clock_id": lineage["clock_id"],
            "daily_rule_lineage_source_window_hash": lineage["source_window_hash"],
        }
        entries[environment_name] = entry

    body: dict[str, object] = {
        "schema_version": FORMAL_COMMON_IDENTITY_SCHEMA_VERSION,
        "identity_version": FORMAL_COMMON_IDENTITY_VERSION,
        "status": "machine_verified_candidate",
        "producer": "data_module.formal_common_identity",
        "observed_at": observed_utc.isoformat(),
        "training_as_of": training_as_of,
        "common_portfolio_clock": {
            "path": str(clock_path),
            "file_hash": file_sha256(clock_path),
            "clock_id": clock.clock_id,
            "clock_manifest_hash": clock.manifest_hash,
            "activation_trading_day": portfolio_activation,
            "policy_hash": policy_hash,
            "universe_hash": universe_hash,
            "scope": "cumulative_portfolio_state",
            "reset_on_natural_day": False,
        },
        "daily_rule_lineage": lineage,
        "entries": entries,
        "producer_receipts": receipt_evidence,
        "consumer_readback": readback,
        "formal_ready_input_count": 3,
        "formal_consumer_compatible_count": 3,
        "producer_receipt_candidate_count": sum(
            value["producer_candidate_only"] is True
            for value in entries.values()
        ),
        "candidate_only": True,
        "formal_ready": True,
        "formal_consumer_compatible": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "writes_formal_controlled_paths": False,
        "writes_market_database": False,
        "historical_backfill_claimed": False,
        "secret_values_emitted": False,
    }
    return {**body, "identity_hash": _payload_hash(body)}


def write_immutable_formal_common_identity_manifest(
    output_path: Path,
    manifest: Mapping[str, object],
) -> str:
    """以 canonical JSON、fsync、create-only 保存 identity。"""

    _validate_identity_hash(manifest)
    output = output_path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (canonical_json(dict(manifest)) + "\n").encode("utf-8")
    try:
        with output.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise FormalCommonIdentityError(
            "common identity output already exists"
        ) from error
    return _bytes_hash(encoded)


def read_formal_common_identity_manifest(
    path: Path,
    *,
    source_paths: Mapping[str, Path | str] | None = None,
    portfolio_clock_manifest: Path | None = None,
    market_db: Path | None = None,
    output_root: Path | None = None,
    development_output_root: Path | None = None,
    training_as_of: str | None = None,
    observed: datetime | None = None,
    verify_consumers: bool = True,
) -> dict[str, object]:
    """重驗 identity、三份 receipt、clock 與 exact consumer。

    handoff reader 會傳入 proposed source paths；傳入後 identity 內的 path
    必須逐一相等，避免 identity 自己宣告另一組來源。
    """

    manifest_path = _resolve_file(path, "common_identity_manifest")
    raw = manifest_path.read_bytes()
    try:
        payload_value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FormalCommonIdentityError("common identity JSON is invalid") from error
    if not isinstance(payload_value, Mapping):
        raise FormalCommonIdentityError("common identity root must be an object")
    payload = {str(key): value for key, value in payload_value.items()}
    if raw != (canonical_json(payload) + "\n").encode("utf-8"):
        raise FormalCommonIdentityError("common identity JSON is not canonical")
    if payload.get("schema_version") != FORMAL_COMMON_IDENTITY_SCHEMA_VERSION:
        raise FormalCommonIdentityError("common identity schema is invalid")
    _validate_identity_hash(payload)
    observed_utc = _aware_datetime(
        observed if observed is not None else datetime.now(timezone.utc),
        "observed",
    )
    identity_observed = _aware_datetime(
        payload.get("observed_at"),
        "common identity observed_at",
    )
    if identity_observed > observed_utc:
        raise FormalCommonIdentityError(
            "common identity observed_at is after observed"
        )
    recorded_training_as_of = _aware_datetime(
        payload.get("training_as_of"),
        "common identity training_as_of",
    )
    if recorded_training_as_of > observed_utc:
        raise FormalCommonIdentityError(
            "common identity training_as_of is after observed"
        )
    if training_as_of is not None:
        requested_training_as_of = _aware_datetime(
            training_as_of,
            "training_as_of",
        )
        if requested_training_as_of > observed_utc:
            raise FormalCommonIdentityError(
                "training_as_of is after observed"
            )
        if requested_training_as_of != recorded_training_as_of:
            raise FormalCommonIdentityError(
                "training_as_of differs from common identity"
            )
    expected_sources = _normalize_path_map(
        source_paths,
        field="source_paths",
        required_keys=FORMAL_PATH_ENV_NAMES,
    ) if source_paths is not None else None
    entries = _entries(payload)
    common = _mapping(payload.get("common_portfolio_clock"), "common_portfolio_clock")
    expected_clock_path = portfolio_clock_manifest
    if expected_clock_path is None:
        expected_clock_text = common.get("path")
        if not isinstance(expected_clock_text, str):
            raise FormalCommonIdentityError("common clock path is missing")
        expected_clock_path = Path(expected_clock_text)
    clock_path = _resolve_file(expected_clock_path, "portfolio_clock_manifest")
    clock = _load_clock_for_identity(clock_path, now=observed_utc)
    observed_taipei_date = observed_utc.astimezone(TAIPEI).date()
    if clock.activation_trading_day > observed_taipei_date:
        raise FormalCommonIdentityError(
            "common portfolio clock activation is after observed"
        )
    if common.get("clock_id") != clock.clock_id:
        raise FormalCommonIdentityError("common clock id mismatch")
    if common.get("clock_manifest_hash") != clock.manifest_hash:
        raise FormalCommonIdentityError("common clock manifest hash mismatch")
    if common.get("file_hash") != file_sha256(clock_path):
        raise FormalCommonIdentityError("common clock file hash mismatch")
    common_policy_hash = _required_sha256(
        common.get("policy_hash"), "common.policy_hash"
    )
    common_universe_hash = _required_sha256(
        common.get("universe_hash"), "common.universe_hash"
    )
    if clock.payload.get("policy_hash") != common_policy_hash:
        raise FormalCommonIdentityError("common policy hash does not match clock")
    if clock.payload.get("universe_hash") != common_universe_hash:
        raise FormalCommonIdentityError("common universe hash does not match clock")
    if common.get("activation_trading_day") != clock.activation_trading_day.isoformat():
        raise FormalCommonIdentityError("common clock activation date mismatch")
    if common.get("scope") != "cumulative_portfolio_state":
        raise FormalCommonIdentityError("common clock scope is invalid")
    if common.get("reset_on_natural_day") is not False:
        raise FormalCommonIdentityError("common clock reset guard is invalid")

    lineage = _validate_daily_rule_lineage(
        payload.get("daily_rule_lineage"),
        portfolio_activation=str(common.get("activation_trading_day")),
        common_policy_hash=common_policy_hash,
        observed_date=observed_taipei_date,
    )
    receipt_map = _mapping(payload.get("producer_receipts"), "producer_receipts")
    readback_payload = _mapping(payload.get("consumer_readback"), "consumer_readback")
    for environment_name in FORMAL_PATH_ENV_NAMES:
        entry = entries[environment_name]
        entry_path = _resolve_file(entry.get("path"), f"{environment_name}.path")
        if expected_sources is not None and entry_path != expected_sources[environment_name]:
            raise FormalCommonIdentityError(
                f"{environment_name} identity path differs from proposed path"
            )
        expected_path_hash = _payload_hash(
            {"env_name": environment_name, "path": str(entry_path)}
        )
        if entry.get("path_hash") != expected_path_hash:
            raise FormalCommonIdentityError(f"{environment_name} path hash mismatch")
        if entry.get("file_hash") != file_sha256(entry_path):
            raise FormalCommonIdentityError(f"{environment_name} file hash mismatch")
        if entry.get("clock_id") != clock.clock_id or entry.get(
            "clock_manifest_hash"
        ) != clock.manifest_hash:
            raise FormalCommonIdentityError(
                f"{environment_name} common clock binding mismatch"
            )
        if entry.get("daily_rule_lineage_hash") != _payload_hash(lineage):
            raise FormalCommonIdentityError(
                f"{environment_name} daily Rule lineage binding mismatch"
            )
        receipt_value = receipt_map.get(environment_name)
        if not isinstance(receipt_value, Mapping):
            raise FormalCommonIdentityError(
                f"{environment_name} producer receipt evidence missing"
            )
        receipt_path = _resolve_file(
            entry.get("receipt_path"), f"{environment_name}.receipt_path"
        )
        receipt_evidence = _read_and_validate_receipt(
            receipt_path,
            input_name=_INPUT_BY_ENV[environment_name],
            source_path=entry_path,
            observed=observed_utc,
            common_clock=_clock_binding_projection(
                clock,
                clock_path=clock_path,
                policy_hash=common_policy_hash,
                universe_hash=common_universe_hash,
            ),
            daily_rule_lineage=lineage,
        )
        if dict(receipt_value) != receipt_evidence:
            raise FormalCommonIdentityError(
                f"{environment_name} receipt evidence changed"
            )
        if entry.get("receipt_file_hash") != receipt_evidence["receipt_file_hash"]:
            raise FormalCommonIdentityError(
                f"{environment_name} receipt file hash mismatch"
            )
        if entry.get("receipt_hash") != receipt_evidence["receipt_hash"]:
            raise FormalCommonIdentityError(f"{environment_name} receipt hash mismatch")
        readback_value = readback_payload.get(_INPUT_BY_ENV[environment_name])
        if not isinstance(readback_value, Mapping):
            raise FormalCommonIdentityError(
                f"{environment_name} consumer readback missing"
            )
        if readback_value.get("path") != str(entry_path):
            raise FormalCommonIdentityError(
                f"{environment_name} consumer readback path mismatch"
            )
        if readback_value.get("file_hash") != file_sha256(entry_path):
            raise FormalCommonIdentityError(
                f"{environment_name} consumer readback file hash mismatch"
            )
        if readback_value.get("formal_ready") is not True or readback_value.get(
            "formal_consumer_compatible"
        ) is not True or readback_value.get("consumer_verified") is not True:
            raise FormalCommonIdentityError(
                f"{environment_name} recorded consumer is not verified"
            )

    if verify_consumers:
        if market_db is None or output_root is None or development_output_root is None:
            raise FormalCommonIdentityError(
                "consumer verification requires market/output roots"
            )
        if training_as_of is None:
            training_as_of = str(payload.get("training_as_of"))
        ledger_source_path = _resolve_file(
            entries[FORMAL_PATH_ENV_NAMES[0]].get("path"),
            f"{FORMAL_PATH_ENV_NAMES[0]}.path",
        )
        rule_source_path = _resolve_file(
            entries[FORMAL_PATH_ENV_NAMES[1]].get("path"),
            f"{FORMAL_PATH_ENV_NAMES[1]}.path",
        )
        sector_source_path = _resolve_file(
            entries[FORMAL_PATH_ENV_NAMES[2]].get("path"),
            f"{FORMAL_PATH_ENV_NAMES[2]}.path",
        )
        formal_paths = DailyFormalInputPaths(
            output_root=output_root,
            development_output_root=development_output_root,
            market_db=market_db,
            formal_ledger_path=ledger_source_path,
            formal_rule_history_path=rule_source_path,
            formal_sector_path=sector_source_path,
        )
        results, blockers = _readback_explicit_formal_sources(
            formal_paths,
            training_as_of=training_as_of,
        )
        if blockers:
            raise FormalCommonIdentityError(
                "consumer revalidation blockers:" + ",".join(sorted(set(blockers)))
            )
        for input_name, result in results.items():
            recorded = readback_payload.get(input_name)
            if not isinstance(recorded, Mapping):
                raise FormalCommonIdentityError(
                    f"{input_name} consumer readback is missing"
                )
            for field in ("path", "file_hash", "manifest_hash", "consumer"):
                if field in recorded and result.get(field) != recorded.get(field):
                    raise FormalCommonIdentityError(
                        f"{input_name} consumer {field} changed during readback"
                    )
            if result.get("formal_ready") is not True or result.get(
                "formal_consumer_compatible"
            ) is not True or result.get("consumer_verified") is not True:
                raise FormalCommonIdentityError(
                    f"{input_name} consumer revalidation is not verified"
                )
    return payload


def _normalize_path_map(
    values: Mapping[str, Path | str] | None,
    *,
    field: str,
    required_keys: tuple[str, ...],
) -> dict[str, Path]:
    if values is None:
        raise FormalCommonIdentityError(f"{field} is required")
    if set(values) != set(required_keys):
        raise FormalCommonIdentityError(f"{field} must contain exactly the three Formal keys")
    result: dict[str, Path] = {}
    for key in required_keys:
        value = values.get(key)
        if not isinstance(value, (Path, str)) or not str(value).strip():
            raise FormalCommonIdentityError(f"{field}.{key} is missing")
        result[key] = _resolve_file(value, f"{field}.{key}")
    return result


def _resolve_file(value: object, field: str) -> Path:
    if not isinstance(value, (Path, str)) or not str(value).strip():
        raise FormalCommonIdentityError(f"{field} is missing")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FormalCommonIdentityError(f"{field} is missing: {path}")
    return path


def _load_clock_for_identity(path: Path, *, now: datetime) -> Any:
    try:
        return load_clock_manifest(path, now=now)
    except Exception as first_error:  # noqa: BLE001 - active boundary fallback
        try:
            return load_clock_manifest_for_capture(path, now=now)
        except Exception as second_error:  # noqa: BLE001 - retain both context
            raise FormalCommonIdentityError(
                "portfolio clock cannot be loaded:" + _safe_error(second_error)
            ) from first_error


def _validate_daily_rule_lineage(
    value: object,
    *,
    portfolio_activation: str,
    common_policy_hash: str,
    observed_date: date | None = None,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise FormalCommonIdentityError("daily_rule_lineage must be an object")
    lineage = {str(key): item for key, item in value.items()}
    required = (
        "clock_id",
        "clock_manifest_hash",
        "activation_trading_day",
        "universe_hash",
        "source_window_hash",
    )
    for field in required:
        if not isinstance(lineage.get(field), str) or not str(lineage[field]).strip():
            raise FormalCommonIdentityError(f"daily_rule_lineage.{field} is missing")
    for field in ("clock_manifest_hash", "universe_hash", "source_window_hash"):
        if not _is_sha256(lineage[field]):
            raise FormalCommonIdentityError(f"daily_rule_lineage.{field} is invalid")
    if lineage.get("policy_hash") is not None:
        if not _is_sha256(lineage["policy_hash"]):
            raise FormalCommonIdentityError("daily_rule_lineage.policy_hash is invalid")
        if lineage["policy_hash"] != common_policy_hash:
            raise FormalCommonIdentityError("daily Rule policy differs from common policy")
    try:
        activation = date.fromisoformat(str(lineage["activation_trading_day"]))
    except ValueError as error:
        raise FormalCommonIdentityError(
            "daily_rule_lineage.activation_trading_day is invalid"
        ) from error

    try:
        portfolio_date = date.fromisoformat(portfolio_activation)
    except ValueError as error:
        raise FormalCommonIdentityError("common portfolio activation is invalid") from error
    if activation < portfolio_date:
        raise FormalCommonIdentityError(
            "daily_rule_lineage.activation_trading_day precedes portfolio activation"
        )
    if observed_date is not None and activation > observed_date:
        raise FormalCommonIdentityError(
            "daily_rule_lineage.activation_trading_day is after observed"
        )
    return lineage


def _clock_binding_projection(
    clock: Any,
    *,
    clock_path: Path,
    policy_hash: str,
    universe_hash: str,
) -> dict[str, object]:
    """Return the exact common portfolio clock identity used by receipts."""

    return {
        "path": str(clock_path),
        "file_hash": file_sha256(clock_path),
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "activation_trading_day": clock.activation_trading_day.isoformat(),
        "policy_hash": policy_hash,
        "universe_hash": universe_hash,
        "scope": "cumulative_portfolio_state",
    }


def _read_and_validate_receipt(
    path: Path,
    *,
    input_name: str,
    source_path: Path,
    observed: datetime,
    common_clock: Mapping[str, object] | None = None,
    daily_rule_lineage: Mapping[str, object] | None = None,
) -> dict[str, object]:
    resolved = _resolve_file(path, f"{input_name}.receipt")
    raw = resolved.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FormalCommonIdentityError(f"{input_name} receipt JSON is invalid") from error
    if not isinstance(value, Mapping):
        raise FormalCommonIdentityError(f"{input_name} receipt must be an object")
    payload = {str(key): item for key, item in value.items()}
    schema = payload.get("schema_version")
    if schema == FORMAL_PIT_SECTOR_RECEIPT_SCHEMA_VERSION:
        try:
            checked = read_formal_pit_sector_receipt(
                resolved,
                sidecar_path=source_path,
                decision_at=observed,
            )
        except Exception as error:  # noqa: BLE001 - source-specific validator
            raise FormalCommonIdentityError(
                f"{input_name} PIT receipt rejected:" + _safe_error(error)
            ) from error
        result = dict(checked)
        result["receipt_file_hash"] = _bytes_hash(raw)
        result["receipt_hash"] = payload.get("receipt_hash")
        result["schema_version"] = schema
        result["candidate_only"] = payload.get("candidate_only") is True
        result.update(
            _validate_receipt_source_binding(
                result,
                input_name=input_name,
                source_path=source_path,
                common_clock=common_clock,
                daily_rule_lineage=daily_rule_lineage,
            )
        )
        return result
    if schema != "formal-input-daily-source-receipt.v1":
        raise FormalCommonIdentityError(f"{input_name} receipt schema is invalid")
    supplied = payload.get("receipt_hash")
    body = dict(payload)
    body.pop("receipt_hash", None)
    if not _is_sha256(supplied) or _payload_hash(body) != supplied:
        raise FormalCommonIdentityError(f"{input_name} receipt hash mismatch")
    if payload.get("input") != input_name:
        raise FormalCommonIdentityError(f"{input_name} receipt input mismatch")
    receipt_observed = _aware_datetime(
        payload.get("observed_at"),
        f"{input_name} receipt.observed_at",
    )
    if receipt_observed > observed:
        raise FormalCommonIdentityError(
            f"{input_name} receipt observed_at is after observed"
        )
    result_value = payload.get("result")
    if not isinstance(result_value, Mapping):
        raise FormalCommonIdentityError(f"{input_name} receipt result is missing")
    result = {str(key): item for key, item in result_value.items()}
    result_observed_value = result.get("observed_at")
    if result_observed_value is not None:
        result_observed = _aware_datetime(
            result_observed_value,
            f"{input_name} receipt.result.observed_at",
        )
        if result_observed > observed:
            raise FormalCommonIdentityError(
                f"{input_name} receipt result observed_at is after observed"
            )
    source_value = _source_path_from_result(result)
    if source_value is None or _resolved_text(source_value) != str(source_path):
        raise FormalCommonIdentityError(f"{input_name} receipt source path mismatch")
    if not _producer_consumer_verified(result):
        raise FormalCommonIdentityError(f"{input_name} receipt consumer is not verified")
    for field in (
        "formal_oos_allowed",
        "promotion_eligible",
        "broker_order_allowed",
        "writes_formal_controlled_paths",
        "historical_backfill_claimed",
    ):
        if payload.get(field) is True or result.get(field) is True:
            raise FormalCommonIdentityError(f"{input_name} receipt safety flag is invalid:{field}")
    source_binding = _validate_receipt_source_binding(
        result,
        input_name=input_name,
        source_path=source_path,
        common_clock=common_clock,
        daily_rule_lineage=daily_rule_lineage,
    )
    return {
        "schema_version": schema,
        "receipt_hash": cast(str, supplied),
        "receipt_file_hash": _bytes_hash(raw),
        "candidate_only": result.get("candidate_only") is True,
        "consumer_verified": True,
        "source_path": str(source_path),
        "receipt_observed_at": receipt_observed.isoformat(),
        "producer": payload.get("producer"),
        "result_consumer": result.get("consumer"),
        "result_formal_consumer_compatible": result.get("formal_consumer_compatible"),
        "result_formal_ready": result.get("formal_ready"),
        **source_binding,
    }


def _validate_receipt_source_binding(
    result: Mapping[str, object],
    *,
    input_name: str,
    source_path: Path,
    common_clock: Mapping[str, object] | None,
    daily_rule_lineage: Mapping[str, object] | None,
) -> dict[str, object]:
    """Bind a receipt to the bytes and identity it claims to consume.

    A producer receipt may contain several hashes for different artifacts.  We
    only compare fields that identify the source path itself, and reject any
    conflicting value instead of selecting a convenient one.  This prevents a
    valid receipt for source A from being paired with a valid source B.
    """

    source_file_hash = file_sha256(source_path)
    source_hash_fields = _source_file_hash_fields(input_name)
    result_hashes: dict[str, str] = {}
    for field in source_hash_fields:
        value = result.get(field)
        if value is None:
            continue
        if not _is_sha256(value):
            raise FormalCommonIdentityError(
                f"{input_name} receipt {field} is invalid"
            )
        result_hashes[field] = cast(str, value)
        if value != source_file_hash:
            raise FormalCommonIdentityError(
                f"{input_name} receipt {field} does not match source file"
            )
    if not result_hashes:
        raise FormalCommonIdentityError(
            f"{input_name} receipt source file hash is missing"
        )

    binding: dict[str, object] = {
        "source_file_hash": source_file_hash,
        "result_source_file_hashes": result_hashes,
    }
    if common_clock is not None and input_name == "causal_non_cash_portfolio_ledger":
        expected_portfolio = {
            "portfolio_clock_manifest": common_clock.get("path"),
            "portfolio_clock_file_hash": common_clock.get("file_hash"),
            "portfolio_clock_id": common_clock.get("clock_id"),
            "portfolio_clock_manifest_hash": common_clock.get("clock_manifest_hash"),
            "portfolio_clock_activation_trading_day": common_clock.get(
                "activation_trading_day"
            ),
            "portfolio_clock_policy_hash": common_clock.get("policy_hash"),
            "portfolio_clock_universe_hash": common_clock.get("universe_hash"),
            "portfolio_clock_scope": "cumulative_paper_portfolio_state",
        }
        for field, expected in expected_portfolio.items():
            if result.get(field) != expected:
                raise FormalCommonIdentityError(
                    f"{input_name} receipt {field} does not match common portfolio clock"
                )
        binding["portfolio_clock_binding"] = expected_portfolio

    if daily_rule_lineage is not None and input_name == "formal_rule_champion_snapshot_history":
        expected_rule = {
            "clock_id": daily_rule_lineage.get("clock_id"),
            "clock_manifest_hash": daily_rule_lineage.get("clock_manifest_hash"),
            "activation_trading_day": daily_rule_lineage.get("activation_trading_day"),
            "universe_hash": daily_rule_lineage.get("universe_hash"),
            "source_window_hash": daily_rule_lineage.get("source_window_hash"),
        }
        if daily_rule_lineage.get("policy_hash") is not None:
            expected_rule["policy_hash"] = daily_rule_lineage.get("policy_hash")
        for field, expected in expected_rule.items():
            if result.get(field) != expected:
                raise FormalCommonIdentityError(
                    f"{input_name} receipt {field} does not match daily Rule lineage"
                )
        binding["daily_rule_binding"] = expected_rule
    return binding


def _source_file_hash_fields(input_name: str) -> tuple[str, ...]:
    if input_name == "causal_non_cash_portfolio_ledger":
        return (
            "source_file_hash",
            "file_hash",
            "manifest_file_hash",
            "formal_manifest_file_hash",
            "publication_file_hash",
        )
    if input_name == "formal_rule_champion_snapshot_history":
        return (
            "source_file_hash",
            "file_hash",
            "formal_manifest_file_hash",
            "manifest_file_hash",
            "publication_file_hash",
        )
    return (
        "source_file_hash",
        "file_hash",
        "sidecar_file_hash",
        "manifest_file_hash",
        "publication_file_hash",
    )


def _source_path_from_result(result: Mapping[str, object]) -> object:
    for field in (
        "formal_manifest_path",
        "manifest_path",
        "sidecar_path",
        "publication_path",
        "path",
    ):
        value = result.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _producer_consumer_verified(result: Mapping[str, object]) -> bool:
    return (
        result.get("consumer_verified") is True
        or result.get("formal_consumer_verified") is True
        or result.get("prospective_consumer_verified") is True
    )


def _entries(payload: Mapping[str, object]) -> dict[str, dict[str, object]]:
    value = payload.get("entries")
    if not isinstance(value, Mapping):
        raise FormalCommonIdentityError("common identity entries are missing")
    result: dict[str, dict[str, object]] = {}
    for environment_name in FORMAL_PATH_ENV_NAMES:
        entry = value.get(environment_name)
        if not isinstance(entry, Mapping):
            raise FormalCommonIdentityError(
                f"common identity entry missing:{environment_name}"
            )
        result[environment_name] = {str(key): item for key, item in entry.items()}
    return result


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise FormalCommonIdentityError(f"{field} must be an object")
    return {str(key): item for key, item in value.items()}


def _validate_identity_hash(payload: Mapping[str, object]) -> None:
    supplied = payload.get("identity_hash")
    body = dict(payload)
    body.pop("identity_hash", None)
    if not _is_sha256(supplied) or _payload_hash(body) != supplied:
        raise FormalCommonIdentityError("common identity hash mismatch")


def _required_sha256(value: object, field: str) -> str:
    if not _is_sha256(value):
        raise FormalCommonIdentityError(f"{field} must be sha256")
    return cast(str, value)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _payload_hash(value: object) -> str:
    return _bytes_hash(canonical_json(value).encode("utf-8"))


def _bytes_hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _aware_datetime(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise FormalCommonIdentityError(f"{field} must be ISO datetime") from error
    else:
        raise FormalCommonIdentityError(f"{field} must be timezone-aware datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FormalCommonIdentityError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _resolved_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return str(Path(value).expanduser().resolve())


def _safe_error(error: Exception) -> str:
    return " ".join(str(error).split())[:240] or type(error).__name__


__all__ = [
    "FORMAL_COMMON_IDENTITY_SCHEMA_VERSION",
    "FORMAL_COMMON_IDENTITY_VERSION",
    "FormalCommonIdentityError",
    "build_formal_common_identity_manifest",
    "read_formal_common_identity_manifest",
    "write_immutable_formal_common_identity_manifest",
]
