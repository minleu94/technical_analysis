"""Prospective capture-only readiness and heavy-rebuild guard.

這個模組只做未來 clock 的唯讀 preflight：驗證 prospective calibration policy、
simulated ledger wrapper、clock-bound Rule history 與 PIT sidecar 是否同時存在。
它不啟動 Direct/OOC、不讀出 HMAC secret、不修改正式環境；即使 readiness 是
ready，``heavy_rebuild_launch_allowed`` 仍固定為 false，必須另走 owner
核准的 activation 流程。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from data_module.formal_simulated_portfolio_ledger import (
    SIMULATED_PORTFOLIO_LEDGER_SCHEMA_VERSION,
    SimulatedPortfolioLedgerError,
    SimulatedLedgerSummary,
    summarize_simulated_ledger,
)
from data_module.prospective_calibration_policy import (
    ProspectiveCalibrationPolicy,
    load_prospective_calibration_policy,
    validate_policy_against_clock,
)
from data_module.prospective_formal_clock import (
    ProspectiveFormalClock,
    canonical_json,
    file_sha256,
    load_clock_manifest,
    load_clock_manifest_for_capture,
    payload_hash,
)
from data_module.prospective_pit_sector_membership import (
    ProspectivePitSectorMembershipError,
    validate_prospective_pit_sector_membership,
)


PROSPECTIVE_CAPTURE_READINESS_SCHEMA_VERSION = (
    "prospective-formal-capture-readiness.v1"
)
PROSPECTIVE_CAPTURE_READINESS_DEFERRED_SCHEMA_VERSION = (
    "prospective-formal-capture-readiness-deferred.v1"
)
PROSPECTIVE_LEDGER_MANIFEST_SCHEMA_VERSION = (
    "prospective-formal-simulated-portfolio-ledger-manifest.v1"
)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")

_LEDGER_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "formal_source_only",
        "research_only",
        "formal_consumer_compatible",
        "promotion_eligible",
        "consumer_mode",
        "clock_id",
        "clock_manifest_hash",
        "sqlite_path",
        "sqlite_file_hash",
        "ledger_manifest_hash",
        "transition_chain_hash",
        "decision_date_count",
        "non_cash_state_day_count",
        "manifest_hash",
    }
)
_RULE_HISTORY_SCHEMA_VERSION = (
    "prospective-formal-rule-champion-snapshot-history.v1"
)
_RULE_SNAPSHOT_SCHEMA_VERSION = "RuleChampionSnapshot.v1"


class ProspectiveCaptureReadinessError(ValueError):
    """Prospective capture preflight 不符合安全契約。"""


def build_prospective_capture_readiness_report(
    *,
    clock_manifest_path: Path,
    calibration_policy_path: Path,
    decision_timestamp: str,
    pit_decision_timestamp: str | None = None,
    now: datetime,
    expected_symbols: Sequence[str],
    portfolio_ledger_manifest_path: Path | None = None,
    rule_history_path: Path | None = None,
    pit_sector_membership_path: Path | None = None,
    active_clock: bool = False,
    defer_until_activation: bool = False,
) -> dict[str, object]:
    """建立 read-only capture readiness report；不啟動任何重型程序。

    ``defer_until_activation`` 是 prospective clock 專用的 staging gate：它
    不把空 ledger、缺少 Rule history 或缺少 PIT sidecar 當成正式 ready，僅
    建立一份明確的「activation 後才收集」報告，讓未來 clock 能合法開始。
    Strict readiness（預設）仍要求三項 input 與 non-cash state 完整通過。
    """

    _validate_now(now)
    if defer_until_activation and active_clock:
        raise ProspectiveCaptureReadinessError(
            "deferred readiness cannot be requested for an active clock"
        )
    clock_loader = load_clock_manifest_for_capture if active_clock else load_clock_manifest
    try:
        clock = clock_loader(clock_manifest_path, now=now)
    except Exception as error:
        raise ProspectiveCaptureReadinessError(
            f"prospective clock is invalid: {error}"
        ) from error
    try:
        policy = load_prospective_calibration_policy(calibration_policy_path)
        validate_policy_against_clock(policy, clock)
    except Exception as error:
        raise ProspectiveCaptureReadinessError(
            f"prospective calibration policy is invalid: {error}"
        ) from error

    decision = _parse_taipei_timestamp(decision_timestamp, "decision_timestamp")
    pit_decision = (
        _parse_taipei_timestamp(pit_decision_timestamp, "pit_decision_timestamp")
        if pit_decision_timestamp is not None
        else _clock_boundary_timestamp(clock, "pit_decision_time")
    )
    expected = _normalize_symbols(expected_symbols)
    if defer_until_activation:
        expected_decision = _clock_boundary_timestamp(clock, "decision_time")
        if decision != expected_decision:
            raise ProspectiveCaptureReadinessError(
                "deferred readiness decision_timestamp must equal clock activation decision time"
            )
        expected_pit_decision = _clock_boundary_timestamp(clock, "pit_decision_time")
        if pit_decision != expected_pit_decision:
            raise ProspectiveCaptureReadinessError(
                "deferred readiness pit_decision_timestamp must equal clock activation PIT time"
            )
        inputs = _deferred_inputs()
    else:
        inputs = [
            _ledger_readiness(
                path=portfolio_ledger_manifest_path,
                clock=clock,
                now=now,
            ),
            _rule_history_readiness(
                path=rule_history_path,
                clock=clock,
                decision=decision,
                now=now,
            ),
            _pit_readiness(
                path=pit_sector_membership_path,
                clock=clock,
                decision=pit_decision,
                now=now,
                expected_symbols=expected,
            ),
        ]
    all_ready = all(item.get("state") == "ready" for item in inputs)
    schema_version = (
        PROSPECTIVE_CAPTURE_READINESS_DEFERRED_SCHEMA_VERSION
        if defer_until_activation
        else PROSPECTIVE_CAPTURE_READINESS_SCHEMA_VERSION
    )
    body: dict[str, object] = {
        "schema_version": schema_version,
        "status": (
            "ready_for_future_activation"
            if defer_until_activation or all_ready
            else "waiting_for_prospective_inputs"
        ),
        "mode": "prospective_formal_simulation",
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "calibration_policy_hash": policy.policy_hash,
        "decision_timestamp": decision.isoformat(),
        "pit_decision_timestamp": pit_decision.isoformat(),
        "active_clock": active_clock,
        "inputs": inputs,
        "capture_only": True,
        "heavy_rebuild_guard": {
            "heavy_rebuild_launch_allowed": False,
            "owner_confirmation_required_for_heavy_rebuild": True,
            "owner_confirmation_received": False,
            "direct_ooc_invocation_count": 0,
            "reason": "capture_only_preflight_never_launches_direct_or_ooc",
        },
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }
    if defer_until_activation:
        body["input_collection_phase"] = "deferred_until_activation"
    return {**body, "readiness_hash": _payload_hash(body)}


def _deferred_inputs() -> list[dict[str, object]]:
    """Return explicit post-activation collection placeholders.

    These rows are intentionally not ``ready`` and contain no path.  They are
    suitable only for scheduling a future clock; no formal consumer may use
    them as evidence.
    """

    return [
        {
            "input": "causal_simulated_portfolio_ledger",
            "state": "deferred",
            "reason": "collect_after_activation_first_non_cash_transition",
            "controlled_path_env_name": "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
            "formal_consumer_compatible": False,
        },
        {
            "input": "prospective_rule_champion_history",
            "state": "deferred",
            "reason": "collect_after_activation_controlled_store_snapshot",
            "controlled_path_env_name": "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
            "formal_consumer_compatible": False,
        },
        {
            "input": "prospective_pit_sector_membership",
            "state": "deferred",
            "reason": "collect_after_activation_licensed_publication",
            "controlled_path_env_name": "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
            "formal_consumer_compatible": False,
        },
    ]


def write_immutable_capture_readiness_report(
    output_path: Path,
    report: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存 readiness report。"""

    body = dict(report)
    supplied = _required_hash(body.get("readiness_hash"), "readiness_hash")
    without_hash = dict(body)
    without_hash.pop("readiness_hash", None)
    if _payload_hash(without_hash) != supplied:
        raise ProspectiveCaptureReadinessError("readiness hash mismatch")
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveCaptureReadinessError(
            "readiness output parent directory must already exist"
        )
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(body).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveCaptureReadinessError(
            "readiness output already exists"
        ) from error
    return file_sha256(output)


def _ledger_readiness(
    *,
    path: Path | None,
    clock: ProspectiveFormalClock,
    now: datetime,
) -> dict[str, object]:
    if path is None:
        return _missing("causal_simulated_portfolio_ledger", "ledger_manifest_path_unset")
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return _missing(
            "causal_simulated_portfolio_ledger",
            "ledger_manifest_path_is_not_a_file",
            resolved,
        )
    try:
        manifest = _read_canonical_object(resolved, "ledger manifest")
        if set(manifest) != _LEDGER_MANIFEST_FIELDS:
            raise ProspectiveCaptureReadinessError("ledger manifest fields are invalid")
        if manifest.get("schema_version") != PROSPECTIVE_LEDGER_MANIFEST_SCHEMA_VERSION:
            raise ProspectiveCaptureReadinessError("ledger manifest schema_version is invalid")
        for field_name, expected in (
            ("status", "complete"),
            ("formal_source_only", True),
            ("research_only", False),
            ("formal_consumer_compatible", True),
            ("promotion_eligible", False),
            ("consumer_mode", "prospective_formal_simulation"),
        ):
            if manifest.get(field_name) != expected:
                raise ProspectiveCaptureReadinessError(
                    f"ledger manifest {field_name} is invalid"
                )
        if manifest.get("clock_id") != clock.clock_id:
            raise ProspectiveCaptureReadinessError("ledger manifest clock_id mismatch")
        if manifest.get("clock_manifest_hash") != clock.manifest_hash:
            raise ProspectiveCaptureReadinessError(
                "ledger manifest clock_manifest_hash mismatch"
            )
        manifest_hash = _required_hash(manifest.get("manifest_hash"), "manifest_hash")
        body = dict(manifest)
        body.pop("manifest_hash", None)
        if _payload_hash(body) != manifest_hash:
            raise ProspectiveCaptureReadinessError("ledger manifest hash mismatch")
        sqlite_path = _resolve_relative_child(resolved, manifest.get("sqlite_path"))
        sqlite_file_hash = _required_hash(
            manifest.get("sqlite_file_hash"), "sqlite_file_hash"
        )
        ledger_identity = {
            "schema_version": PROSPECTIVE_LEDGER_MANIFEST_SCHEMA_VERSION,
            "clock_id": clock.clock_id,
            "clock_manifest_hash": clock.manifest_hash,
            "sqlite_path": str(manifest["sqlite_path"]),
            "sqlite_file_hash": sqlite_file_hash,
            "transition_chain_hash": _required_hash(
                manifest.get("transition_chain_hash"), "transition_chain_hash"
            ),
            "decision_date_count": _required_positive_int(
                manifest.get("decision_date_count"), "decision_date_count"
            ),
            "non_cash_state_day_count": _required_positive_int(
                manifest.get("non_cash_state_day_count"),
                "non_cash_state_day_count",
            ),
        }
        if manifest.get("ledger_manifest_hash") != _payload_hash(ledger_identity):
            raise ProspectiveCaptureReadinessError("ledger_manifest_hash mismatch")
        if file_sha256(sqlite_path) != sqlite_file_hash:
            raise ProspectiveCaptureReadinessError("ledger sqlite file hash mismatch")
        summary = summarize_simulated_ledger(sqlite_path, clock=clock)
        _validate_ledger_summary(summary, manifest, now=now)
        return {
            "input": "causal_simulated_portfolio_ledger",
            "state": "ready",
            "path": str(resolved),
            "file_hash": file_sha256(resolved),
            "sqlite_path": str(sqlite_path),
            "sqlite_file_hash": sqlite_file_hash,
            "ledger_manifest_hash": _required_hash(
                manifest.get("ledger_manifest_hash"), "ledger_manifest_hash"
            ),
            "transition_chain_hash": summary.transition_chain_hash,
            "decision_date_count": summary.decision_date_count,
            "non_cash_state_day_count": summary.non_cash_state_day_count,
            "formal_consumer_compatible": True,
        }
    except Exception as error:
        return _invalid("causal_simulated_portfolio_ledger", resolved, error)


def _rule_history_readiness(
    *,
    path: Path | None,
    clock: ProspectiveFormalClock,
    decision: datetime,
    now: datetime,
) -> dict[str, object]:
    if path is None:
        return _missing("prospective_rule_champion_history", "rule_history_path_unset")
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return _missing("prospective_rule_champion_history", "rule_history_path_is_not_a_file", resolved)
    try:
        manifest = _read_canonical_object(resolved, "Rule history manifest")
        _validate_rule_history_manifest(manifest, clock=clock, decision=decision, now=now)
        return {
            "input": "prospective_rule_champion_history",
            "state": "ready",
            "path": str(resolved),
            "file_hash": file_sha256(resolved),
            "manifest_hash": str(manifest["manifest_hash"]),
            "snapshot_count": _required_positive_int(
                manifest.get("snapshot_count"), "snapshot_count"
            ),
            "decision_date_count": len(cast(list[object], manifest["decision_dates"])),
            "hmac_attestation_present": True,
            "secret_values_emitted": False,
            "formal_consumer_compatible": True,
        }
    except Exception as error:
        return _invalid("prospective_rule_champion_history", resolved, error)


def _pit_readiness(
    *,
    path: Path | None,
    clock: ProspectiveFormalClock,
    decision: datetime,
    now: datetime,
    expected_symbols: Sequence[str],
) -> dict[str, object]:
    if path is None:
        return _missing("prospective_pit_sector_membership", "pit_sidecar_path_unset")
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return _missing("prospective_pit_sector_membership", "pit_sidecar_path_is_not_a_file", resolved)
    try:
        result = validate_prospective_pit_sector_membership(
            sidecar_path=resolved,
            clock=clock,
            decision_timestamp=decision.isoformat(),
            now=now,
            expected_symbols=expected_symbols,
        )
        return {
            "input": "prospective_pit_sector_membership",
            "state": "ready",
            "path": str(resolved),
            "file_hash": result.sidecar_file_hash,
            "canonical_hash": result.canonical_hash,
            "rows_hash": result.rows_hash,
            "row_count": result.row_count,
            "source_ids": list(result.source_ids),
            "formal_consumer_compatible": True,
        }
    except (OSError, ProspectivePitSectorMembershipError, ValueError) as error:
        return _invalid("prospective_pit_sector_membership", resolved, error)


def _validate_ledger_summary(
    summary: SimulatedLedgerSummary,
    manifest: Mapping[str, object],
    *,
    now: datetime,
) -> None:
    if summary.non_cash_state_day_count <= 0:
        raise ProspectiveCaptureReadinessError(
            "simulated ledger non_cash_state_day_count must be positive"
        )
    if manifest.get("transition_chain_hash") != summary.transition_chain_hash:
        raise ProspectiveCaptureReadinessError("ledger transition_chain_hash mismatch")
    if manifest.get("decision_date_count") != summary.decision_date_count:
        raise ProspectiveCaptureReadinessError("ledger decision_date_count mismatch")
    if manifest.get("non_cash_state_day_count") != summary.non_cash_state_day_count:
        raise ProspectiveCaptureReadinessError(
            "ledger non_cash_state_day_count mismatch"
        )
    today = now.astimezone(TAIPEI_TIMEZONE).date()
    if any(date.fromisoformat(item) > today for item in summary.decision_dates):
        raise ProspectiveCaptureReadinessError(
            "simulated ledger contains a decision date in the future"
        )


def _validate_rule_history_manifest(
    manifest: Mapping[str, object],
    *,
    clock: ProspectiveFormalClock,
    decision: datetime,
    now: datetime,
) -> None:
    if manifest.get("schema_version") != _RULE_HISTORY_SCHEMA_VERSION:
        raise ProspectiveCaptureReadinessError("Rule history schema_version is invalid")
    required = {
        "schema_version", "status", "formal_source_only", "research_only",
        "formal_consumer_compatible", "promotion_eligible", "rule_only_proof",
        "consumer_mode", "historical_backfill_claimed", "clock_id",
        "clock_manifest_hash", "activation_trading_day", "decision_timezone",
        "decision_time", "registered_store_id", "strategy_version", "policy_version",
        "score_configuration_hash", "universe_hash", "selection_capacity",
        "decision_dates", "snapshot_count", "snapshots", "manifest_hash",
    }
    if set(manifest) != required:
        raise ProspectiveCaptureReadinessError("Rule history manifest fields are invalid")
    for field_name, expected in (
        ("status", "complete"),
        ("formal_source_only", True),
        ("research_only", False),
        ("formal_consumer_compatible", True),
        ("promotion_eligible", False),
        ("rule_only_proof", "formal_rule_only"),
        ("consumer_mode", "prospective_formal_simulation"),
        ("historical_backfill_claimed", False),
        ("clock_id", clock.clock_id),
        ("clock_manifest_hash", clock.manifest_hash),
        ("activation_trading_day", clock.activation_trading_day.isoformat()),
        ("decision_timezone", "Asia/Taipei"),
        ("decision_time", str(clock.payload["decision_time"])),
    ):
        if manifest.get(field_name) != expected:
            raise ProspectiveCaptureReadinessError(
                f"Rule history {field_name} mismatch"
            )
    _required_text(manifest.get("registered_store_id"), "registered_store_id")
    _required_hash(manifest.get("score_configuration_hash"), "score_configuration_hash")
    _required_hash(manifest.get("universe_hash"), "universe_hash")
    dates = manifest.get("decision_dates")
    if not isinstance(dates, list) or not dates or dates != sorted(set(dates)):
        raise ProspectiveCaptureReadinessError("Rule history decision_dates are invalid")
    activation = clock.activation_trading_day.isoformat()
    if any(not isinstance(item, str) or item < activation for item in dates):
        raise ProspectiveCaptureReadinessError("Rule history contains preactivation dates")
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        raise ProspectiveCaptureReadinessError("Rule history snapshots are required")
    if manifest.get("snapshot_count") != len(snapshots):
        raise ProspectiveCaptureReadinessError("Rule history snapshot_count mismatch")
    now_taipei = now.astimezone(TAIPEI_TIMEZONE)
    if decision > now_taipei:
        raise ProspectiveCaptureReadinessError("decision timestamp is after now")
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            raise ProspectiveCaptureReadinessError("Rule history snapshot is invalid")
        if snapshot.get("schema_version") != _RULE_SNAPSHOT_SCHEMA_VERSION:
            raise ProspectiveCaptureReadinessError("Rule Champion snapshot schema is invalid")
        timestamp = _parse_taipei_timestamp(snapshot.get("decision_timestamp"), "snapshot.decision_timestamp")
        if timestamp > now_taipei or timestamp > decision:
            raise ProspectiveCaptureReadinessError("Rule snapshot timestamp is outside capture boundary")
        if timestamp.date().isoformat() not in dates:
            raise ProspectiveCaptureReadinessError("Rule snapshot date is not declared")
        _required_hash(snapshot.get("content_hash"), "snapshot.content_hash")
        rows = snapshot.get("decision_rows")
        if not isinstance(rows, list) or not rows:
            raise ProspectiveCaptureReadinessError("Rule snapshot decision_rows are required")
        ranks: list[int] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ProspectiveCaptureReadinessError("Rule decision row is invalid")
            ranks.append(_required_positive_int(row.get("rule_rank"), "rule_rank"))
            _required_hash(row.get("immutable_snapshot_hash"), "immutable_snapshot_hash")
            signature = row.get("attestation_signature")
            if not isinstance(signature, str) or not signature.startswith("hmac-sha256:"):
                raise ProspectiveCaptureReadinessError("Rule decision HMAC attestation is missing")
        if ranks != list(range(1, len(ranks) + 1)):
            raise ProspectiveCaptureReadinessError("Rule snapshot ranks are not contiguous")
    supplied = _required_hash(manifest.get("manifest_hash"), "manifest_hash")
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _payload_hash(body) != supplied:
        raise ProspectiveCaptureReadinessError("Rule history manifest hash mismatch")


def _read_canonical_object(path: Path, label: str) -> dict[str, object]:
    try:
        raw_text = path.read_text(encoding="utf-8")
        value: Any = json.loads(raw_text, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ProspectiveCaptureReadinessError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise ProspectiveCaptureReadinessError(f"{label} must be an object")
    if canonical_json(value) != raw_text:
        raise ProspectiveCaptureReadinessError(f"{label} must use canonical JSON")
    return value


def _resolve_relative_child(manifest_path: Path, value: object) -> Path:
    relative = _required_text(value, "sqlite_path").replace("\\", "/")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ProspectiveCaptureReadinessError(
            "sqlite_path must remain a relative child of the ledger manifest"
        )
    resolved = (manifest_path.parent / candidate).resolve()
    if not resolved.is_relative_to(manifest_path.parent.resolve()):
        raise ProspectiveCaptureReadinessError("sqlite_path escapes ledger custody")
    return resolved


def _missing(input_name: str, reason: str, path: Path | None = None) -> dict[str, object]:
    result: dict[str, object] = {"input": input_name, "state": "missing", "reason": reason}
    if path is not None:
        result["path"] = str(path)
    return result


def _invalid(input_name: str, path: Path, error: Exception) -> dict[str, object]:
    detail = str(error).splitlines()[0].strip()
    if len(detail) > 240:
        detail = detail[:237] + "..."
    return {
        "input": input_name,
        "state": "invalid",
        "path": str(path),
        "reason": "validation_failed",
        "error_type": type(error).__name__,
        "detail": detail,
    }


def _normalize_symbols(value: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ProspectiveCaptureReadinessError("expected_symbols must be a non-empty array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ProspectiveCaptureReadinessError("expected_symbols must contain text")
    normalized = tuple(item.strip() for item in value)
    if normalized != tuple(sorted(set(normalized))):
        raise ProspectiveCaptureReadinessError("expected_symbols must be sorted and unique")
    return normalized


def _parse_taipei_timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ProspectiveCaptureReadinessError(f"{field_name} must be timezone-aware ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProspectiveCaptureReadinessError(f"{field_name} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectiveCaptureReadinessError(f"{field_name} must include timezone")
    return parsed.astimezone(TAIPEI_TIMEZONE)


def _clock_decision_time(
    clock: ProspectiveFormalClock,
    field_name: str = "decision_time",
) -> time:
    value = clock.payload.get(field_name)
    if value is None and field_name == "pit_decision_time":
        value = clock.payload.get("decision_time")
    if not isinstance(value, str):
        raise ProspectiveCaptureReadinessError(f"clock {field_name} is invalid")
    try:
        parsed = datetime.strptime(value, "%H:%M:%S").time()
    except ValueError as error:
        raise ProspectiveCaptureReadinessError(
            f"clock {field_name} is invalid"
        ) from error
    return parsed


def _clock_boundary_timestamp(
    clock: ProspectiveFormalClock,
    field_name: str,
) -> datetime:
    return datetime.combine(
        clock.activation_trading_day,
        _clock_decision_time(clock, field_name),
        tzinfo=TAIPEI_TIMEZONE,
    )


def _validate_now(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveCaptureReadinessError("now must include timezone")


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveCaptureReadinessError(f"{field_name} must be non-empty text")
    return value.strip()


def _required_hash(value: object, field_name: str) -> str:
    text = _required_text(value, field_name)
    if len(text) != 71 or not text.startswith("sha256:") or any(
        char not in "0123456789abcdef" for char in text[7:]
    ):
        raise ProspectiveCaptureReadinessError(f"{field_name} must be sha256")
    return text


def _required_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProspectiveCaptureReadinessError(f"{field_name} must be positive")
    return value


def _payload_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
