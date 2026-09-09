"""Formal 三項受控路徑的唯讀 attestation 與原子 handoff 計畫。

這個模組把目前程序實際採用的 Windows registry／process environment 來源、
三項 Formal consumer readback，以及未來 owner 可審核的設定更新方案放在同一
份 hash-bound 計畫中。它不尋找最新檔案、不複製 candidate、不改 registry 或
受控路徑，也不讀出 HMAC secret。只有所有路徑、clock identity、producer
receipt 與三個 consumer 都已由 owner 明確提供且重驗成功，後續受控操作才
可能套用；本模組本身永遠只產生 read-only plan。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import os
from pathlib import Path
from typing import Any, cast

from data_module.formal_daily_input_producer import (
    DailyFormalInputPaths,
    _readback_explicit_formal_sources,
)
from data_module.prospective_activation_environment import (
    CONTROLLED_HMAC_KEY_ENV_NAME,
    CONTROLLED_STORE_ID_ENV_NAME,
    FORMAL_PATH_ENV_NAMES,
    build_prospective_activation_environment_preflight,
)
from data_module.prospective_formal_clock import (
    canonical_json,
    file_sha256,
    load_clock_manifest,
    load_clock_manifest_for_capture,
    payload_hash,
)
from runtime.controlled_environment import windows_effective_environment_value


FORMAL_CONTROLLED_HANDOFF_SCHEMA_VERSION = "formal-controlled-handoff-plan.v1"
FORMAL_CONTROLLED_HANDOFF_VERSION = "formal-controlled-handoff-readback.v1"


class FormalControlledHandoffError(ValueError):
    """受控 Formal handoff 計畫無法形成。"""


def build_formal_controlled_handoff_plan(
    *,
    market_db: Path,
    training_as_of: str,
    output_root: Path,
    development_output_root: Path,
    now: datetime | None = None,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    registry: object | None = None,
    proposed_paths: Mapping[str, Path | str | None] | None = None,
    proposed_clock_manifest: Path | None = None,
    proposed_identity_manifest: Path | None = None,
) -> dict[str, object]:
    """建立目前受控設定 attestation 與明確 proposed handoff 計畫。

    ``proposed_paths`` 必須由呼叫端逐項傳入三個完整 environment name；若未
    傳入，計畫會明確停在 ``proposed_paths_not_supplied``，絕不從任何 output
    root 猜選檔案。``proposed_identity_manifest`` 是 producer 共同產出的
    immutable identity evidence；它必須列出每個 environment name 的 path
    hash、file hash、clock id 與 clock manifest hash，避免只用目錄名稱綁定。
    """

    observed = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc),
        "now",
    )
    market_path = market_db.expanduser().resolve()
    output_path = output_root.expanduser().resolve()
    development_path = development_output_root.expanduser().resolve()
    env_report = build_prospective_activation_environment_preflight(
        environment=environment,
        platform_name=platform_name,
        registry=registry,
    )
    runtime_attestation = _build_runtime_attestation(
        env_report,
        environment=environment,
        platform_name=platform_name,
        registry=registry,
    )
    current_paths = _paths_from_environment_report(env_report)
    current_readback, current_readback_blockers = _readback_sources(
        current_paths,
        market_db=market_path,
        output_root=output_path,
        development_output_root=development_path,
        training_as_of=training_as_of,
    )

    proposed = _build_proposed_projection(
        proposed_paths=proposed_paths,
        proposed_clock_manifest=proposed_clock_manifest,
        proposed_identity_manifest=proposed_identity_manifest,
        market_db=market_path,
        output_root=output_path,
        development_output_root=development_path,
        training_as_of=training_as_of,
        now=observed,
    )

    # The current configuration is retained as diagnostic evidence and as the
    # rollback target.  Its stale/missing inputs must not veto a complete,
    # explicitly supplied proposed bundle; otherwise repairing the old path
    # could never become possible.  Only proposed bundle blockers and custody
    # runtime blockers control whether this plan can proceed to root review.
    blockers = list(cast(list[str], proposed["blockers"]))
    blockers.extend(_runtime_blockers(runtime_attestation))
    apply_gate = {
        "allowed": False,
        "writes_performed": False,
        "automatic_path_discovery": False,
        "partial_update_allowed": False,
        "requires_root_review_of_this_plan": True,
        "requirements": [
            "official source custody for the proposed activation trading day and a new owner-approved prospective clock",
            "one explicit proposed path for each of the three BALDR_ML_FORMAL_* variables",
            "one immutable producer identity manifest matching all three paths",
            "each exact formal consumer readback reports formal_ready=true and formal_consumer_compatible=true",
            "all three producer identity entries match the fixed cumulative portfolio clock_id and clock_manifest_hash; any daily Rule clock is carried only as separate lineage",
            "controlled store identity remains unchanged and HMAC store is configured",
            "fresh post-update readiness readback confirms 3/3 before any Formal OOS credit",
        ],
    }
    rollback = _build_rollback_plan(env_report)
    body: dict[str, object] = {
        "schema_version": FORMAL_CONTROLLED_HANDOFF_SCHEMA_VERSION,
        "handoff_version": FORMAL_CONTROLLED_HANDOFF_VERSION,
        "status": "ready_for_root_review" if not blockers else "blocked",
        "observed_at": observed.isoformat(),
        "training_as_of": training_as_of,
        "runtime_attestation": runtime_attestation,
        "current_controlled_configuration": {
            "environment_report_hash": env_report.get("preflight_hash"),
            "formal_paths": env_report.get("formal_paths"),
            "consumer_readback": current_readback,
            "consumer_blockers": current_readback_blockers,
            "formal_ready_count": sum(
                1
                for value in current_readback.values()
                if value.get("formal_ready") is True
                and value.get("formal_consumer_compatible") is True
            ),
        },
        "proposed_controlled_configuration": proposed,
        "clock_identity_contract": {
            "common_scope": "cumulative_portfolio_state",
            "common_clock_is_fixed_across_natural_days": True,
            "daily_rule_clock_scope": "natural_day_rule_source_version",
            "daily_rule_clock_must_not_replace_common_clock": True,
            "universe_policy": (
                "all three identity entries bind the common portfolio policy/universe "
                "when supplied; a daily Rule universe change is versioned by its own "
                "effective trading day and remains lineage only"
            ),
        },
        "apply_gate": apply_gate,
        "atomic_update_plan": {
            "operation": "single owner-controlled update of all three explicit formal path values",
            "ordering": [
                "capture current effective path strings and file hashes in this plan",
                "publish all three immutable inputs and matching producer identity evidence",
                "re-run the exact three consumer readbacks against the proposed paths",
                "review this concrete plan and approve the complete set as one operation",
                "update all three controlled values without changing HMAC or store identity",
                "run a fresh preflight and 3/3 readiness readback before activation credit",
            ],
            "no_candidate_copy": True,
            "no_latest_file_guess": True,
            "no_formal_credit_on_partial": True,
        },
        "rollback": rollback,
        "safety": {
            "read_only": True,
            "writes_formal_controlled_paths": False,
            "writes_windows_environment": False,
            "writes_market_database": False,
            "broker_order_allowed": False,
            "formal_oos_allowed": False,
            "historical_backfill_claimed": False,
            "secret_values_emitted": False,
        },
    }
    return {**body, "plan_hash": payload_hash(body)}


def write_immutable_formal_controlled_handoff_plan(
    output_path: Path,
    plan: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存 handoff plan。"""

    _validate_plan_hash(plan)
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise FormalControlledHandoffError("handoff plan output parent must exist")
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(plan)).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise FormalControlledHandoffError(
            "handoff plan output already exists"
        ) from error
    return file_sha256(output)


def _readback_sources(
    paths: Mapping[str, Path | None],
    *,
    market_db: Path,
    output_root: Path,
    development_output_root: Path,
    training_as_of: str,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    formal_paths = DailyFormalInputPaths(
        output_root=output_root,
        development_output_root=development_output_root,
        market_db=market_db,
        formal_ledger_path=paths.get(FORMAL_PATH_ENV_NAMES[0]),
        formal_rule_history_path=paths.get(FORMAL_PATH_ENV_NAMES[1]),
        formal_sector_path=paths.get(FORMAL_PATH_ENV_NAMES[2]),
    )
    try:
        results, blockers = _readback_explicit_formal_sources(
            formal_paths,
            training_as_of=training_as_of,
        )
    except Exception as error:  # noqa: BLE001 - preserve machine blocker
        return {}, [f"formal_consumer_readback_failed:{_safe_error(error)}"]
    return results, blockers


def _build_proposed_projection(
    *,
    proposed_paths: Mapping[str, Path | str | None] | None,
    proposed_clock_manifest: Path | None,
    proposed_identity_manifest: Path | None,
    market_db: Path,
    output_root: Path,
    development_output_root: Path,
    training_as_of: str,
    now: datetime,
) -> dict[str, object]:
    blockers: list[str] = []
    path_values = {
        name: (proposed_paths or {}).get(name)
        for name in FORMAL_PATH_ENV_NAMES
    }
    supplied_count = sum(value is not None for value in path_values.values())
    if supplied_count == 0:
        blockers.append("proposed_paths_not_supplied")
    elif supplied_count != len(FORMAL_PATH_ENV_NAMES):
        blockers.append("proposed_paths_partial")

    resolved_paths: dict[str, Path | None] = {}
    path_projection: dict[str, dict[str, object]] = {}
    for name, value in path_values.items():
        if value is None:
            resolved_paths[name] = None
            path_projection[name] = {
                "path": None,
                "path_hash": None,
                "file_hash": None,
                "exists": False,
            }
            continue
        path = Path(value).expanduser().resolve()
        resolved_paths[name] = path
        path_hash = payload_hash({"env_name": name, "path": str(path)})
        file_hash = file_sha256(path) if path.is_file() else None
        path_projection[name] = {
            "path": str(path),
            "path_hash": path_hash,
            "file_hash": file_hash,
            "exists": path.is_file(),
        }
        if not path.is_absolute():
            blockers.append(f"{name}:proposed_path_not_absolute")
        if not path.is_file():
            blockers.append(f"{name}:proposed_file_missing")

    readback: dict[str, dict[str, object]] = {}
    readback_blockers: list[str] = []
    # Run the exact consumer readback even when one proposed file is missing.
    # The resulting per-input evidence distinguishes a real, valid Rule
    # publication from the missing causal/PIT sources instead of hiding that
    # fact behind a single path blocker.
    if supplied_count == len(FORMAL_PATH_ENV_NAMES):
        readback, readback_blockers = _readback_sources(
            resolved_paths,
            market_db=market_db,
            output_root=output_root,
            development_output_root=development_output_root,
            training_as_of=training_as_of,
        )
        blockers.extend(readback_blockers)
        for input_name, result in readback.items():
            if not (
                result.get("formal_ready") is True
                and result.get("formal_consumer_compatible") is True
            ):
                blockers.append(
                    f"{input_name}:proposed_consumer_not_formal_ready"
                )

    clock_projection: dict[str, object] = {
        "path": None,
        "file_hash": None,
        "clock_id": None,
        "clock_manifest_hash": None,
        "policy_hash": None,
        "universe_hash": None,
    }
    if proposed_clock_manifest is None:
        blockers.append("proposed_clock_manifest_not_supplied")
    else:
        clock_path = proposed_clock_manifest.expanduser().resolve()
        clock_projection["path"] = str(clock_path)
        clock_projection["file_hash"] = (
            file_sha256(clock_path) if clock_path.is_file() else None
        )
        if not clock_path.is_file():
            blockers.append("proposed_clock_manifest_missing")
        else:
            try:
                try:
                    # Before activation the proposed clock is still a planned
                    # future artifact; after activation the capture loader
                    # supplies the elapsed-day boundary.  A handoff plan must
                    # support both natural phases without treating a future
                    # clock as an invalid source.
                    clock = load_clock_manifest(clock_path, now=now)
                except Exception:
                    clock = load_clock_manifest_for_capture(clock_path, now=now)
                clock_payload = getattr(clock, "payload", {})
                if not isinstance(clock_payload, Mapping):
                    clock_payload = {}
                clock_projection.update(
                    {
                        "clock_id": clock.clock_id,
                        "clock_manifest_hash": clock.manifest_hash,
                        "activation_trading_day": clock.activation_trading_day.isoformat(),
                        "policy_hash": clock_payload.get("policy_hash"),
                        "universe_hash": clock_payload.get("universe_hash"),
                    }
                )
            except Exception as error:  # noqa: BLE001
                blockers.append(
                    "proposed_clock_manifest_invalid:" + _safe_error(error)
                )

    identity_projection: dict[str, object] = {
        "path": None,
        "file_hash": None,
        "status": "missing",
        "entries": {},
    }
    if proposed_identity_manifest is None:
        blockers.append("proposed_identity_manifest_not_supplied")
    else:
        identity_path = proposed_identity_manifest.expanduser().resolve()
        identity_projection["path"] = str(identity_path)
        identity_projection["file_hash"] = (
            file_sha256(identity_path) if identity_path.is_file() else None
        )
        if not identity_path.is_file():
            blockers.append("proposed_identity_manifest_missing")
        else:
            try:
                raw = _read_json_object(identity_path)
                entries = _identity_entries(raw)
                identity_projection["entries"] = entries
                identity_projection["status"] = "valid_shape"
                identity_projection["common_clock_scope"] = "cumulative_portfolio_state"
                identity_projection["daily_rule_lineage"] = raw.get(
                    "daily_rule_lineage"
                )
                # A producer-created common identity is a stronger contract
                # than a hand-authored entries object.  Re-run its exact
                # receipt and three-consumer readback here, against the same
                # proposed paths, before allowing the plan to be reviewed.
                if raw.get("schema_version") == (
                    "formal-common-identity-manifest.v1"
                ):
                    from data_module.formal_common_identity import (  # noqa: PLC0415
                        read_formal_common_identity_manifest,
                    )

                    if any(value is None for value in resolved_paths.values()):
                        raise FormalControlledHandoffError(
                            "common identity source paths are incomplete"
                        )
                    if proposed_clock_manifest is None:
                        raise FormalControlledHandoffError(
                            "common identity portfolio clock is missing"
                        )
                    producer_readback = read_formal_common_identity_manifest(
                        identity_path,
                        source_paths=cast(dict[str, Path], {
                            FORMAL_PATH_ENV_NAMES[0]: resolved_paths[FORMAL_PATH_ENV_NAMES[0]],
                            FORMAL_PATH_ENV_NAMES[1]: resolved_paths[FORMAL_PATH_ENV_NAMES[1]],
                            FORMAL_PATH_ENV_NAMES[2]: resolved_paths[FORMAL_PATH_ENV_NAMES[2]],
                        }),
                        portfolio_clock_manifest=proposed_clock_manifest,
                        market_db=market_db,
                        output_root=output_root,
                        development_output_root=development_output_root,
                        training_as_of=training_as_of,
                        observed=now,
                        verify_consumers=True,
                    )
                    identity_projection["status"] = "producer_and_consumer_verified"
                    identity_projection["producer_readback_verified"] = True
                    identity_projection["identity_hash"] = producer_readback.get(
                        "identity_hash"
                    )
                else:
                    identity_projection["producer_readback_verified"] = False
                blockers.extend(
                    _validate_identity_entries(
                        entries,
                        path_projection=path_projection,
                        clock_projection=clock_projection,
                        identity_payload=raw,
                    )
                )
            except Exception as error:  # noqa: BLE001
                blockers.append(
                    "proposed_identity_manifest_invalid:" + _safe_error(error)
                )

    return {
        "explicit_paths_required": True,
        "paths": path_projection,
        "consumer_readback": readback,
        "consumer_blockers": readback_blockers,
        "clock": clock_projection,
        "identity_evidence": identity_projection,
        "blockers": sorted(set(blockers)),
    }


def _build_runtime_attestation(
    env_report: Mapping[str, object],
    *,
    environment: Mapping[str, str] | None,
    platform_name: str | None,
    registry: object | None,
) -> dict[str, object]:
    effective_environment = os.environ if environment is None else environment
    platform = platform_name or os.name
    raw_paths = env_report.get("formal_paths")
    formal_paths = raw_paths if isinstance(raw_paths, Mapping) else {}
    sources: dict[str, dict[str, object]] = {}
    for name in FORMAL_PATH_ENV_NAMES:
        entry = formal_paths.get(name)
        entry_map = entry if isinstance(entry, Mapping) else {}
        process_value = effective_environment.get(name)
        registry_value = windows_effective_environment_value(
            name,
            platform_name=platform,
            registry=registry,
        )
        process_resolved = None
        if isinstance(process_value, str) and process_value.strip():
            process_resolved = str(Path(process_value.strip()).expanduser().resolve())
        sources[name] = {
            "effective_source": entry_map.get("source", "unknown"),
            "process_environment_configured": process_resolved is not None,
            "process_environment_path_matches_effective": (
                process_resolved is not None
                and process_resolved == entry_map.get("path")
            ),
            "windows_registry_configured": registry_value is not None,
            "effective_path": entry_map.get("path"),
            "effective_file_hash": entry_map.get("file_hash"),
        }
    controlled_store = env_report.get("controlled_store")
    hmac_store = env_report.get("hmac_secret_store")
    store_map = controlled_store if isinstance(controlled_store, Mapping) else {}
    hmac_map = hmac_store if isinstance(hmac_store, Mapping) else {}
    return {
        "method": "prospective_activation_environment_preflight_plus_process_registry_source_check",
        "preflight_hash": env_report.get("preflight_hash"),
        "platform": platform,
        "formal_paths": sources,
        "controlled_store": {
            "configured": store_map.get("configured") is True,
            "source": store_map.get("source", "unknown"),
            "identity_hash": store_map.get("identity_hash"),
            "value_emitted": False,
        },
        "hmac_secret_store": {
            "configured": hmac_map.get("configured") is True,
            "source": hmac_map.get("source", "unknown"),
            "secret_emitted": False,
        },
        "read_only": True,
        "environment_mutated": False,
    }


def _paths_from_environment_report(
    report: Mapping[str, object],
) -> dict[str, Path | None]:
    raw = report.get("formal_paths")
    paths: dict[str, Path | None] = {}
    for name in FORMAL_PATH_ENV_NAMES:
        entry = raw.get(name) if isinstance(raw, Mapping) else None
        value = entry.get("path") if isinstance(entry, Mapping) else None
        paths[name] = Path(value) if isinstance(value, str) and value else None
    return paths


def _runtime_blockers(attestation: Mapping[str, object]) -> list[str]:
    blockers: list[str] = []
    formal_paths = attestation.get("formal_paths")
    if isinstance(formal_paths, Mapping):
        for name in FORMAL_PATH_ENV_NAMES:
            entry = formal_paths.get(name)
            if not isinstance(entry, Mapping):
                blockers.append(f"runtime_attestation_missing:{name}")
                continue
            if entry.get("effective_source") not in {
                "process_environment",
                "windows_user_or_system_registry",
            }:
                blockers.append(
                    f"runtime_attestation_uncontrolled_source:{name}"
                )
    controlled_store = attestation.get("controlled_store")
    if not isinstance(controlled_store, Mapping) or controlled_store.get(
        "configured"
    ) is not True:
        blockers.append(f"{CONTROLLED_STORE_ID_ENV_NAME}:missing")
    hmac_store = attestation.get("hmac_secret_store")
    if not isinstance(hmac_store, Mapping) or hmac_store.get("configured") is not True:
        blockers.append(f"{CONTROLLED_HMAC_KEY_ENV_NAME}:missing")
    return blockers


def _build_rollback_plan(report: Mapping[str, object]) -> dict[str, object]:
    raw = report.get("formal_paths")
    current: dict[str, dict[str, object]] = {}
    for name in FORMAL_PATH_ENV_NAMES:
        entry = raw.get(name) if isinstance(raw, Mapping) else None
        value = entry if isinstance(entry, Mapping) else {}
        current[name] = {
            "restore_path": value.get("path"),
            "restore_file_hash": value.get("file_hash"),
            "source": value.get("source"),
        }
    return {
        "trigger": "post-update preflight or any exact consumer readback mismatch",
        "saved_current_configuration": current,
        "steps": [
            "stop the formal activation/readiness consumer before any credit",
            "restore all three saved path values as one controlled operation",
            "re-run the environment preflight and exact three consumer readback",
            "retain the new immutable candidates and all receipts for diagnosis; do not delete or overwrite them",
            "keep formal_oos_allowed=false until a later complete handoff passes",
        ],
        "rollback_writes_performed_by_this_plan": False,
    }


def _identity_entries(raw: Mapping[str, object]) -> dict[str, dict[str, object]]:
    value = raw.get("entries", raw.get("formal_paths"))
    if not isinstance(value, Mapping):
        raise FormalControlledHandoffError(
            "identity manifest entries/formal_paths must be an object"
        )
    result: dict[str, dict[str, object]] = {}
    for name in FORMAL_PATH_ENV_NAMES:
        entry = value.get(name)
        if not isinstance(entry, Mapping):
            raise FormalControlledHandoffError(
                f"identity manifest entry missing: {name}"
            )
        result[name] = dict(entry)
    return result


def _validate_identity_entries(
    entries: Mapping[str, Mapping[str, object]],
    *,
    path_projection: Mapping[str, Mapping[str, object]],
    clock_projection: Mapping[str, object],
    identity_payload: Mapping[str, object] | None = None,
) -> list[str]:
    blockers: list[str] = []
    expected_clock_id = clock_projection.get("clock_id")
    expected_clock_hash = clock_projection.get("clock_manifest_hash")
    if not isinstance(expected_clock_id, str) or not isinstance(
        expected_clock_hash, str
    ):
        return ["proposed_identity_clock_not_verified"]
    expected_policy = clock_projection.get("policy_hash")
    expected_universe = clock_projection.get("universe_hash")
    blockers.extend(
        _validate_daily_rule_lineage(
            (identity_payload or {}).get("daily_rule_lineage"),
            portfolio_activation=clock_projection.get("activation_trading_day"),
        )
    )
    for name in FORMAL_PATH_ENV_NAMES:
        entry = entries.get(name, {})
        expected_path = path_projection.get(name, {})
        if entry.get("path_hash") != expected_path.get("path_hash"):
            blockers.append(f"{name}:identity_path_hash_mismatch")
        if entry.get("file_hash") != expected_path.get("file_hash"):
            blockers.append(f"{name}:identity_file_hash_mismatch")
        if entry.get("clock_id") != expected_clock_id:
            blockers.append(f"{name}:identity_clock_id_mismatch")
        if entry.get("clock_manifest_hash") != expected_clock_hash:
            blockers.append(
                f"{name}:identity_clock_manifest_hash_mismatch"
            )
        # New identity manifests make the common policy/universe explicit.
        # Keep old manifests readable when they have no such fields, while
        # rejecting a partial or conflicting common identity as soon as a
        # producer starts emitting it.
        for field, expected in (
            ("policy_hash", expected_policy),
            ("universe_hash", expected_universe),
            ("portfolio_policy_hash", expected_policy),
            ("portfolio_universe_hash", expected_universe),
        ):
            if field not in entry:
                continue
            if not isinstance(expected, str) or entry.get(field) != expected:
                blockers.append(f"{name}:identity_{field}_mismatch")
        if entry.get("clock_scope") not in (None, "cumulative_portfolio_state"):
            blockers.append(f"{name}:identity_clock_scope_mismatch")
    return blockers


def _validate_daily_rule_lineage(
    value: object,
    *,
    portfolio_activation: object,
) -> list[str]:
    """驗證 daily Rule 版本證據，但不把它提升為 common clock。"""

    if value is None:
        return []
    if not isinstance(value, Mapping):
        return ["daily_rule_lineage_must_be_object"]
    blockers: list[str] = []
    for field in ("clock_id", "clock_manifest_hash", "activation_trading_day", "universe_hash"):
        if not isinstance(value.get(field), str) or not str(value.get(field)).strip():
            blockers.append(f"daily_rule_lineage_{field}_missing")
    for field in ("clock_manifest_hash", "universe_hash", "source_window_hash"):
        if field in value:
            text = value.get(field)
            if not isinstance(text, str) or not text.startswith("sha256:") or len(text) != 71:
                blockers.append(f"daily_rule_lineage_{field}_invalid")
    activation = value.get("activation_trading_day")
    if isinstance(activation, str) and isinstance(portfolio_activation, str):
        try:
            if date.fromisoformat(activation) < date.fromisoformat(portfolio_activation):
                blockers.append("daily_rule_lineage_activation_precedes_portfolio")
        except ValueError:
            blockers.append("daily_rule_lineage_activation_invalid")
    return blockers


def _read_json_object(path: Path) -> dict[str, object]:
    import json

    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise FormalControlledHandoffError("identity manifest root must be an object")
    return raw


def _aware_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise FormalControlledHandoffError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise FormalControlledHandoffError(f"{field_name} must include a timezone")
    return value.astimezone(timezone.utc)


def _safe_error(error: Exception) -> str:
    return " ".join(str(error).split())[:240] or type(error).__name__


def _validate_plan_hash(plan: Mapping[str, object]) -> None:
    if plan.get("schema_version") != FORMAL_CONTROLLED_HANDOFF_SCHEMA_VERSION:
        raise FormalControlledHandoffError("handoff plan schema_version is invalid")
    supplied = plan.get("plan_hash")
    if not isinstance(supplied, str) or not supplied.startswith("sha256:"):
        raise FormalControlledHandoffError("handoff plan hash is invalid")
    body = dict(plan)
    body.pop("plan_hash", None)
    if payload_hash(body) != supplied:
        raise FormalControlledHandoffError("handoff plan hash mismatch")


__all__ = [
    "FORMAL_CONTROLLED_HANDOFF_SCHEMA_VERSION",
    "FORMAL_CONTROLLED_HANDOFF_VERSION",
    "FormalControlledHandoffError",
    "build_formal_controlled_handoff_plan",
    "write_immutable_formal_controlled_handoff_plan",
]
