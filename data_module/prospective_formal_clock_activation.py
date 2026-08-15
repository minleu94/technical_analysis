"""Immutable activation contract for the prospective formal simulation clock.

PFS-07 freezes the candidate, calibration/evaluation identities and the three
controlled input paths before a future trading day is allowed to start.  The
module is deliberately side-effect-light: it only reads the already validated
PFS-06 readiness report and input files, and writes create-only JSON when the
caller explicitly asks for it.  It never reads the HMAC secret, changes Windows
environment variables, starts a watcher, or launches Direct/OOC.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from data_module.prospective_calibration_policy import (
    ProspectiveCalibrationPolicy,
    validate_policy_against_clock,
)
from data_module.prospective_capture_readiness import (
    PROSPECTIVE_CAPTURE_READINESS_DEFERRED_SCHEMA_VERSION,
    PROSPECTIVE_CAPTURE_READINESS_SCHEMA_VERSION,
)
from data_module.prospective_formal_clock import (
    ProspectiveFormalClock,
    canonical_json,
    file_sha256,
    payload_hash,
)


PROSPECTIVE_CLOCK_ACTIVATION_SCHEMA_VERSION = (
    "prospective-formal-clock-activation.v1"
)
PROSPECTIVE_DAILY_CAPTURE_SCHEMA_VERSION = (
    "prospective-formal-daily-capture-activation.v1"
)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
CONTROLLED_PATH_ENV_NAMES = (
    "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
    "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
    "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
)
CONTROLLED_STORE_ID_ENV_NAME = "RULE_CHAMPION_CONTROLLED_STORE_ID"
CONTROLLED_HMAC_KEY_ENV_NAME = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
CAPTURE_INPUT_TO_ENV = {
    "causal_simulated_portfolio_ledger": CONTROLLED_PATH_ENV_NAMES[0],
    "prospective_rule_champion_history": CONTROLLED_PATH_ENV_NAMES[1],
    "prospective_pit_sector_membership": CONTROLLED_PATH_ENV_NAMES[2],
}
DAILY_CAPTURE_SEQUENCE = (
    "pit_publication",
    "rule_champion_snapshot",
    "t_minus_one_portfolio_transition",
    "frozen_candidate_inference",
    "readiness_heartbeat",
)

_ACTIVATION_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "mode",
        "owner_decision_id",
        "owner_activation_id",
        "owner_activation_timestamp",
        "clock_id",
        "clock_manifest_hash",
        "activation_trading_day",
        "decision_timezone",
        "decision_time",
        "candidate_training_cutoff",
        "candidate_model_hash",
        "candidate_feature_manifest_hash",
        "calibration_policy_hash",
        "evaluation_policy_hash",
        "policy_hash",
        "universe_hash",
        "source_policy_hash",
        "seed_state_hash",
        "readiness_hash",
        "readiness_status",
        "controlled_paths",
        "controlled_store_id",
        "hmac_secret_store_configured",
        "rebuild_requested",
        "heavy_rebuild_launch_allowed",
        "formal_oos_allowed",
        "production_blend_alpha_bp",
        "promotion_eligible",
        "broker_order_allowed",
        "historical_backfill_claimed",
        "real_money",
        "broker_execution",
        "manifest_hash",
    }
)
_CONTROLLED_PATH_FIELDS = frozenset({"path", "path_hash", "file_hash"})
_DEFERRED_CONTROLLED_PATH_FIELDS = frozenset(
    {"deferred", "path", "path_hash", "file_hash"}
)
_DAILY_CAPTURE_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "mode",
        "capture_only",
        "clock_id",
        "clock_manifest_hash",
        "activation_manifest_hash",
        "owner_activation_id",
        "capture_id",
        "capture_date",
        "decision_timestamp",
        "started_at",
        "decision_timezone",
        "controlled_path_env_names",
        "controlled_store_id",
        "scheduled_sequence",
        "completed_steps",
        "failed_steps",
        "late_or_backfill",
        "same_day_advice_used",
        "future_teacher_target_used",
        "direct_ooc_invocation_count",
        "heavy_rebuild_launch_allowed",
        "formal_oos_allowed",
        "production_blend_alpha_bp",
        "promotion_eligible",
        "broker_order_allowed",
        "elapsed_day_credit",
        "formal_credit",
        "secret_values_emitted",
        "record_hash",
    }
)


class ProspectiveClockActivationError(ValueError):
    """PFS-07 activation／daily capture contract 不符合安全邊界。"""


@dataclass(frozen=True)
class ProspectiveClockActivation:
    """通過 validation 的 immutable activation identity。"""

    payload: Mapping[str, object]
    activation_manifest_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", dict(self.payload))

    @property
    def clock_id(self) -> str:
        return str(self.payload["clock_id"])

    @property
    def activation_trading_day(self) -> date:
        return date.fromisoformat(str(self.payload["activation_trading_day"]))

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


def build_prospective_clock_activation_manifest(
    *,
    clock: ProspectiveFormalClock,
    calibration_policy: ProspectiveCalibrationPolicy,
    readiness_report: Mapping[str, object],
    controlled_paths: Mapping[str, Path | None],
    controlled_store_id: str,
    hmac_secret_store_configured: bool,
    owner_activation_id: str,
    owner_activation_timestamp: datetime,
    now: datetime,
    rebuild_requested: bool = False,
) -> dict[str, object]:
    """建立 activation manifest，不變更 clock、不啟動任何程序。

    ``controlled_paths`` 必須是目前 PFS-06 ready report 中的三個絕對檔案；
    會重新計算 path／file hash，避免 readiness 後路徑內容悄悄漂移。
    ``hmac_secret_store_configured`` 僅是受控 secret store 的布林旗標，
    並不接受或保存 secret value。
    """

    _validate_now(now)
    if not isinstance(clock, ProspectiveFormalClock):
        raise ProspectiveClockActivationError("validated prospective clock is required")
    if not isinstance(calibration_policy, ProspectiveCalibrationPolicy):
        raise ProspectiveClockActivationError(
            "validated prospective calibration policy is required"
        )
    try:
        validate_policy_against_clock(calibration_policy, clock)
    except Exception as error:
        raise ProspectiveClockActivationError(
            f"calibration policy is not bound to clock: {error}"
        ) from error
    readiness_hash, readiness_inputs = _validate_readiness_report(
        readiness_report,
        clock=clock,
        calibration_policy=calibration_policy,
        now=now,
    )
    activation_timestamp = _parse_aware_datetime(
        owner_activation_timestamp, "owner_activation_timestamp"
    )
    now_aware = _parse_now(now)
    if activation_timestamp > now_aware:
        raise ProspectiveClockActivationError(
            "owner_activation_timestamp cannot be in the future"
        )
    if activation_timestamp <= clock.owner_decision_timestamp:
        raise ProspectiveClockActivationError(
            "owner_activation_timestamp must follow owner_decision_timestamp"
        )
    if clock.activation_trading_day <= activation_timestamp.astimezone(
        TAIPEI_TIMEZONE
    ).date():
        raise ProspectiveClockActivationError(
            "activation_trading_day must remain after owner activation date"
        )
    activation_paths = _build_controlled_paths(
        controlled_paths,
        readiness_inputs=readiness_inputs,
    )
    inputs_deferred = all(
        item.get("state") == "deferred" for item in readiness_inputs.values()
    )
    owner_id = _required_text(owner_activation_id, "owner_activation_id")
    store_id = _required_text(controlled_store_id, "controlled_store_id")
    if hmac_secret_store_configured is not True:
        raise ProspectiveClockActivationError(
            "controlled HMAC secret store must be configured before activation"
        )
    if rebuild_requested is not False:
        raise ProspectiveClockActivationError(
            "PFS-07 activation cannot request a Direct/OOC rebuild"
        )

    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_CLOCK_ACTIVATION_SCHEMA_VERSION,
        "status": "scheduled",
        "mode": "prospective_formal_simulation",
        "owner_decision_id": str(clock.payload["owner_decision_id"]),
        "owner_activation_id": owner_id,
        "owner_activation_timestamp": activation_timestamp.isoformat(),
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "activation_trading_day": clock.activation_trading_day.isoformat(),
        "decision_timezone": "Asia/Taipei",
        "decision_time": str(clock.payload["decision_time"]),
        "candidate_training_cutoff": str(clock.payload["candidate_training_cutoff"]),
        "candidate_model_hash": str(clock.payload["candidate_model_hash"]),
        "candidate_feature_manifest_hash": str(
            clock.payload["candidate_feature_manifest_hash"]
        ),
        "calibration_policy_hash": calibration_policy.policy_hash,
        "evaluation_policy_hash": str(clock.payload["evaluation_policy_hash"]),
        "policy_hash": str(clock.payload["policy_hash"]),
        "universe_hash": str(clock.payload["universe_hash"]),
        "source_policy_hash": str(clock.payload["source_policy_hash"]),
        "seed_state_hash": _seed_state_hash(clock),
        "readiness_hash": readiness_hash,
        "readiness_status": (
            "inputs_deferred_until_activation"
            if inputs_deferred
            else "ready_for_future_activation"
        ),
        "controlled_paths": activation_paths,
        "controlled_store_id": store_id,
        "hmac_secret_store_configured": True,
        "rebuild_requested": False,
        "heavy_rebuild_launch_allowed": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "historical_backfill_claimed": False,
        "real_money": False,
        "broker_execution": False,
    }
    manifest = {**body, "manifest_hash": payload_hash(body)}
    validate_prospective_clock_activation_manifest(
        manifest,
        clock=clock,
        calibration_policy=calibration_policy,
        readiness_report=readiness_report,
        now=now,
    )
    return manifest


def validate_prospective_clock_activation_manifest(
    manifest: Mapping[str, object],
    *,
    clock: ProspectiveFormalClock,
    calibration_policy: ProspectiveCalibrationPolicy,
    readiness_report: Mapping[str, object],
    now: datetime,
) -> ProspectiveClockActivation:
    """重新驗證 activation manifest 與所有 frozen identities。"""

    if set(manifest) != _ACTIVATION_FIELDS:
        raise ProspectiveClockActivationError("activation manifest fields are invalid")
    if manifest.get("schema_version") != PROSPECTIVE_CLOCK_ACTIVATION_SCHEMA_VERSION:
        raise ProspectiveClockActivationError("activation schema_version is invalid")
    if manifest.get("status") != "scheduled":
        raise ProspectiveClockActivationError("activation status must be scheduled")
    if manifest.get("mode") != "prospective_formal_simulation":
        raise ProspectiveClockActivationError("activation mode is invalid")
    if manifest.get("clock_id") != clock.clock_id:
        raise ProspectiveClockActivationError("activation clock_id mismatch")
    if manifest.get("clock_manifest_hash") != clock.manifest_hash:
        raise ProspectiveClockActivationError("activation clock_manifest_hash mismatch")
    try:
        validate_policy_against_clock(calibration_policy, clock)
    except Exception as error:
        raise ProspectiveClockActivationError(
            f"calibration policy is not bound to clock: {error}"
        ) from error
    if manifest.get("calibration_policy_hash") != calibration_policy.policy_hash:
        raise ProspectiveClockActivationError("activation calibration_policy_hash mismatch")
    for field_name in (
        "candidate_model_hash",
        "candidate_feature_manifest_hash",
        "evaluation_policy_hash",
        "policy_hash",
        "universe_hash",
        "source_policy_hash",
        "seed_state_hash",
        "readiness_hash",
        "clock_manifest_hash",
    ):
        _required_hash(manifest.get(field_name), field_name)
    for field_name, expected in (
        ("owner_decision_id", clock.payload["owner_decision_id"]),
        ("activation_trading_day", clock.activation_trading_day.isoformat()),
        ("decision_timezone", "Asia/Taipei"),
        ("decision_time", clock.payload["decision_time"]),
        ("candidate_training_cutoff", clock.payload["candidate_training_cutoff"]),
        ("candidate_model_hash", clock.payload["candidate_model_hash"]),
        (
            "candidate_feature_manifest_hash",
            clock.payload["candidate_feature_manifest_hash"],
        ),
        ("evaluation_policy_hash", clock.payload["evaluation_policy_hash"]),
        ("policy_hash", clock.payload["policy_hash"]),
        ("universe_hash", clock.payload["universe_hash"]),
        ("source_policy_hash", clock.payload["source_policy_hash"]),
        ("seed_state_hash", _seed_state_hash(clock)),
    ):
        if manifest.get(field_name) != expected:
            raise ProspectiveClockActivationError(
                f"activation {field_name} does not match frozen clock"
            )
    activation_timestamp = _parse_aware_datetime(
        manifest.get("owner_activation_timestamp"), "owner_activation_timestamp"
    )
    now_aware = _parse_now(now)
    if activation_timestamp > now_aware:
        raise ProspectiveClockActivationError(
            "owner_activation_timestamp cannot be in the future"
        )
    if activation_timestamp <= clock.owner_decision_timestamp:
        raise ProspectiveClockActivationError(
            "owner_activation_timestamp must follow owner_decision_timestamp"
        )
    if clock.activation_trading_day <= activation_timestamp.astimezone(
        TAIPEI_TIMEZONE
    ).date():
        raise ProspectiveClockActivationError(
            "activation_trading_day must remain after owner activation date"
        )
    _required_text(manifest.get("owner_activation_id"), "owner_activation_id")
    _required_text(manifest.get("controlled_store_id"), "controlled_store_id")
    if manifest.get("hmac_secret_store_configured") is not True:
        raise ProspectiveClockActivationError(
            "controlled HMAC secret store must be configured"
        )
    readiness_status = manifest.get("readiness_status")
    if readiness_status not in {
        "ready_for_future_activation",
        "inputs_deferred_until_activation",
    }:
        raise ProspectiveClockActivationError(
            "activation readiness_status is invalid"
        )
    if readiness_status == "inputs_deferred_until_activation":
        controlled_entries = manifest.get("controlled_paths")
        if not isinstance(controlled_entries, Mapping):
            raise ProspectiveClockActivationError(
                "deferred activation controlled_paths are invalid"
            )
        if any(
            not isinstance(entry, Mapping)
            or entry.get("deferred") is not True
            for entry in controlled_entries.values()
        ):
            raise ProspectiveClockActivationError(
                "deferred activation paths must remain deferred"
            )
    for field_name, expected in (
        ("rebuild_requested", False),
        ("heavy_rebuild_launch_allowed", False),
        ("formal_oos_allowed", False),
        ("production_blend_alpha_bp", 0),
        ("promotion_eligible", False),
        ("broker_order_allowed", False),
        ("historical_backfill_claimed", False),
        ("real_money", False),
        ("broker_execution", False),
    ):
        if manifest.get(field_name) is not expected if isinstance(expected, bool) else manifest.get(field_name) != expected:
            raise ProspectiveClockActivationError(
                f"activation {field_name} is unsafe"
            )
    readiness_hash, readiness_inputs = _validate_readiness_report(
        readiness_report,
        clock=clock,
        calibration_policy=calibration_policy,
        now=now,
    )
    if manifest.get("readiness_hash") != readiness_hash:
        raise ProspectiveClockActivationError("activation readiness_hash mismatch")
    controlled = manifest.get("controlled_paths")
    if not isinstance(controlled, Mapping):
        raise ProspectiveClockActivationError("activation controlled_paths must be an object")
    _validate_controlled_path_entries(controlled, readiness_inputs=readiness_inputs)
    supplied_hash = _required_hash(manifest.get("manifest_hash"), "manifest_hash")
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if payload_hash(body) != supplied_hash:
        raise ProspectiveClockActivationError("activation manifest hash mismatch")
    return ProspectiveClockActivation(payload=dict(manifest), activation_manifest_hash=supplied_hash)


def write_immutable_clock_activation_manifest(
    output_path: Path,
    manifest: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存 activation manifest。"""

    _validate_manifest_hash_shape(manifest, label="activation manifest")
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveClockActivationError(
            "activation output parent directory must already exist"
        )
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(manifest)).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveClockActivationError(
            "activation output already exists"
        ) from error
    return file_sha256(output)


def build_daily_capture_activation_record(
    *,
    activation: ProspectiveClockActivation,
    capture_date: str,
    decision_timestamp: str,
    started_at: datetime,
    now: datetime,
) -> dict[str, object]:
    """建立低 CPU daily capture 的 create-only 啟動紀錄。

    這是「開始蒐證」紀錄，不是完成或 elapsed-day credit；當日 steps 必須
    另外以 append-only evidence 保存，不能隔日補寫到此 record。
    """

    if not isinstance(activation, ProspectiveClockActivation):
        raise ProspectiveClockActivationError("validated activation is required")
    _validate_now(now)
    started = _parse_aware_datetime(started_at, "started_at")
    now_aware = _parse_now(now)
    if started > now_aware:
        raise ProspectiveClockActivationError("started_at cannot be in the future")
    capture_day = _parse_date(capture_date, "capture_date")
    if capture_day < activation.activation_trading_day:
        raise ProspectiveClockActivationError("capture_date precedes activation")
    now_day = now_aware.astimezone(TAIPEI_TIMEZONE).date()
    if capture_day > now_day:
        raise ProspectiveClockActivationError("capture_date cannot be in the future")
    if started.astimezone(TAIPEI_TIMEZONE).date() != capture_day:
        raise ProspectiveClockActivationError("started_at date does not match capture_date")
    decision = _parse_taipei_timestamp(decision_timestamp, "decision_timestamp")
    if decision.date() != capture_day:
        raise ProspectiveClockActivationError(
            "decision_timestamp date does not match capture_date"
        )
    if decision > now_aware.astimezone(TAIPEI_TIMEZONE):
        raise ProspectiveClockActivationError("decision_timestamp is after now")
    expected_time = _clock_decision_time(activation.payload)
    if decision.timetz().replace(tzinfo=None) != expected_time:
        raise ProspectiveClockActivationError(
            "decision_timestamp does not match clock decision_time"
        )
    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_DAILY_CAPTURE_SCHEMA_VERSION,
        "status": "started",
        "mode": "prospective_formal_simulation",
        "capture_only": True,
        "clock_id": activation.clock_id,
        "clock_manifest_hash": str(activation.payload["clock_manifest_hash"]),
        "activation_manifest_hash": activation.activation_manifest_hash,
        "owner_activation_id": str(activation.payload["owner_activation_id"]),
        "capture_id": f"{activation.clock_id}:{capture_day.isoformat()}",
        "capture_date": capture_day.isoformat(),
        "decision_timestamp": decision.isoformat(),
        "started_at": started.astimezone(TAIPEI_TIMEZONE).isoformat(),
        "decision_timezone": "Asia/Taipei",
        "controlled_path_env_names": list(CONTROLLED_PATH_ENV_NAMES),
        "controlled_store_id": str(activation.payload["controlled_store_id"]),
        "scheduled_sequence": list(DAILY_CAPTURE_SEQUENCE),
        "completed_steps": [],
        "failed_steps": [],
        "late_or_backfill": False,
        "same_day_advice_used": False,
        "future_teacher_target_used": False,
        "direct_ooc_invocation_count": 0,
        "heavy_rebuild_launch_allowed": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "elapsed_day_credit": 0,
        "formal_credit": 0,
        "secret_values_emitted": False,
    }
    record = {**body, "record_hash": payload_hash(body)}
    validate_daily_capture_activation_record(
        record,
        activation=activation,
        now=now,
    )
    return record


def validate_daily_capture_activation_record(
    record: Mapping[str, object],
    *,
    activation: ProspectiveClockActivation,
    now: datetime,
) -> None:
    """驗證 daily capture 啟動紀錄仍綁定同一 activation identity。"""

    if set(record) != _DAILY_CAPTURE_FIELDS:
        raise ProspectiveClockActivationError("daily capture record fields are invalid")
    if record.get("schema_version") != PROSPECTIVE_DAILY_CAPTURE_SCHEMA_VERSION:
        raise ProspectiveClockActivationError("daily capture schema_version is invalid")
    if record.get("status") != "started" or record.get("capture_only") is not True:
        raise ProspectiveClockActivationError("daily capture record status is invalid")
    if record.get("clock_id") != activation.clock_id:
        raise ProspectiveClockActivationError("daily capture clock_id mismatch")
    if record.get("activation_manifest_hash") != activation.activation_manifest_hash:
        raise ProspectiveClockActivationError("daily capture activation hash mismatch")
    if record.get("clock_manifest_hash") != activation.payload["clock_manifest_hash"]:
        raise ProspectiveClockActivationError("daily capture clock hash mismatch")
    if record.get("owner_activation_id") != activation.payload["owner_activation_id"]:
        raise ProspectiveClockActivationError("daily capture owner activation mismatch")
    if record.get("controlled_store_id") != activation.payload["controlled_store_id"]:
        raise ProspectiveClockActivationError("daily capture store identity mismatch")
    if record.get("controlled_path_env_names") != list(CONTROLLED_PATH_ENV_NAMES):
        raise ProspectiveClockActivationError("daily capture controlled path list is invalid")
    _parse_date(record.get("capture_date"), "capture_date")
    _parse_taipei_timestamp(record.get("decision_timestamp"), "decision_timestamp")
    _parse_aware_datetime(record.get("started_at"), "started_at")
    for field_name, expected in (
        ("scheduled_sequence", list(DAILY_CAPTURE_SEQUENCE)),
        ("completed_steps", []),
        ("failed_steps", []),
        ("late_or_backfill", False),
        ("same_day_advice_used", False),
        ("future_teacher_target_used", False),
        ("direct_ooc_invocation_count", 0),
        ("heavy_rebuild_launch_allowed", False),
        ("formal_oos_allowed", False),
        ("production_blend_alpha_bp", 0),
        ("promotion_eligible", False),
        ("broker_order_allowed", False),
        ("elapsed_day_credit", 0),
        ("formal_credit", 0),
        ("secret_values_emitted", False),
    ):
        if record.get(field_name) is not expected if isinstance(expected, bool) else record.get(field_name) != expected:
            raise ProspectiveClockActivationError(
                f"daily capture {field_name} is unsafe"
            )
    supplied_hash = _required_hash(record.get("record_hash"), "record_hash")
    body = dict(record)
    body.pop("record_hash", None)
    if payload_hash(body) != supplied_hash:
        raise ProspectiveClockActivationError("daily capture record hash mismatch")
    _validate_daily_time_boundary(record, activation=activation, now=now)


def write_immutable_daily_capture_activation_record(
    output_path: Path,
    record: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存 daily capture start record。"""

    _validate_manifest_hash_shape(record, label="daily capture record", hash_field="record_hash")
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveClockActivationError(
            "daily capture output parent directory must already exist"
        )
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(record)).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveClockActivationError(
            "daily capture output already exists"
        ) from error
    return file_sha256(output)


def _validate_readiness_report(
    report: Mapping[str, object],
    *,
    clock: ProspectiveFormalClock,
    calibration_policy: ProspectiveCalibrationPolicy,
    now: datetime,
) -> tuple[str, dict[str, Mapping[str, object]]]:
    expected_fields = {
        "schema_version", "status", "mode", "clock_id", "clock_manifest_hash",
        "calibration_policy_hash", "decision_timestamp", "active_clock", "inputs",
        "capture_only", "heavy_rebuild_guard", "formal_oos_allowed",
        "production_blend_alpha_bp", "promotion_eligible", "broker_order_allowed",
        "secret_values_emitted", "readiness_hash",
    }
    schema_version = report.get("schema_version")
    deferred = schema_version == PROSPECTIVE_CAPTURE_READINESS_DEFERRED_SCHEMA_VERSION
    if deferred:
        expected_fields.add("input_collection_phase")
    if set(report) != expected_fields:
        raise ProspectiveClockActivationError("readiness report fields are invalid")
    if schema_version not in {
        PROSPECTIVE_CAPTURE_READINESS_SCHEMA_VERSION,
        PROSPECTIVE_CAPTURE_READINESS_DEFERRED_SCHEMA_VERSION,
    }:
        raise ProspectiveClockActivationError("readiness report schema_version is invalid")
    if report.get("status") != "ready_for_future_activation":
        raise ProspectiveClockActivationError("prospective inputs are not ready")
    for field_name, expected in (
        ("mode", "prospective_formal_simulation"),
        ("clock_id", clock.clock_id),
        ("clock_manifest_hash", clock.manifest_hash),
        ("calibration_policy_hash", calibration_policy.policy_hash),
        ("active_clock", False),
        ("capture_only", True),
        ("formal_oos_allowed", False),
        ("production_blend_alpha_bp", 0),
        ("promotion_eligible", False),
        ("broker_order_allowed", False),
        ("secret_values_emitted", False),
    ):
        if report.get(field_name) is not expected if isinstance(expected, bool) else report.get(field_name) != expected:
            raise ProspectiveClockActivationError(
                f"readiness report {field_name} is unsafe"
            )
    if deferred and report.get("input_collection_phase") != "deferred_until_activation":
        raise ProspectiveClockActivationError(
            "deferred readiness input_collection_phase is invalid"
        )
    if not deferred and report.get("input_collection_phase", "validated") != "validated":
        raise ProspectiveClockActivationError(
            "readiness input_collection_phase is invalid"
        )
    decision = _parse_taipei_timestamp(
        report.get("decision_timestamp"), "readiness decision_timestamp"
    )
    if deferred:
        expected_decision = datetime.combine(
            clock.activation_trading_day,
            _clock_decision_time(clock.payload),
            tzinfo=TAIPEI_TIMEZONE,
        )
        if decision != expected_decision:
            raise ProspectiveClockActivationError(
                "deferred readiness decision_timestamp does not match activation"
            )
    elif decision > _parse_now(now).astimezone(TAIPEI_TIMEZONE):
        raise ProspectiveClockActivationError("readiness decision_timestamp is after now")
    guard = report.get("heavy_rebuild_guard")
    if not isinstance(guard, Mapping):
        raise ProspectiveClockActivationError("readiness heavy_rebuild_guard is invalid")
    for field_name, expected in (
        ("heavy_rebuild_launch_allowed", False),
        ("owner_confirmation_required_for_heavy_rebuild", True),
        ("owner_confirmation_received", False),
        ("direct_ooc_invocation_count", 0),
    ):
        if guard.get(field_name) is not expected if isinstance(expected, bool) else guard.get(field_name) != expected:
            raise ProspectiveClockActivationError(
                f"readiness heavy guard {field_name} is unsafe"
            )
    inputs = report.get("inputs")
    if not isinstance(inputs, Sequence) or isinstance(inputs, (str, bytes)):
        raise ProspectiveClockActivationError("readiness inputs must be an array")
    by_name: dict[str, Mapping[str, object]] = {}
    for item in inputs:
        if not isinstance(item, Mapping):
            raise ProspectiveClockActivationError("readiness input is invalid")
        name = _required_text(item.get("input"), "readiness input")
        if name in by_name or name not in CAPTURE_INPUT_TO_ENV:
            raise ProspectiveClockActivationError("readiness input set is invalid")
        if deferred:
            if set(item) != {
                "input",
                "state",
                "reason",
                "controlled_path_env_name",
                "formal_consumer_compatible",
            }:
                raise ProspectiveClockActivationError(
                    f"deferred readiness input {name} fields are invalid"
                )
            if item.get("state") != "deferred":
                raise ProspectiveClockActivationError(
                    f"deferred readiness input {name} is not deferred"
                )
            if item.get("controlled_path_env_name") != CAPTURE_INPUT_TO_ENV[name]:
                raise ProspectiveClockActivationError(
                    f"deferred readiness input {name} env name is invalid"
                )
            if item.get("formal_consumer_compatible") is not False:
                raise ProspectiveClockActivationError(
                    f"deferred readiness input {name} cannot be formal compatible"
                )
        else:
            if item.get("state") != "ready":
                raise ProspectiveClockActivationError(f"readiness input {name} is not ready")
            _required_text(item.get("path"), f"readiness {name} path")
            _required_hash(item.get("file_hash"), f"readiness {name} file_hash")
        by_name[name] = item
    if set(by_name) != set(CAPTURE_INPUT_TO_ENV):
        raise ProspectiveClockActivationError("readiness must contain all three inputs")
    supplied_hash = _required_hash(report.get("readiness_hash"), "readiness_hash")
    body = dict(report)
    body.pop("readiness_hash", None)
    if payload_hash(body) != supplied_hash:
        raise ProspectiveClockActivationError("readiness report hash mismatch")
    return supplied_hash, by_name


def _build_controlled_paths(
    paths: Mapping[str, Path | None],
    *,
    readiness_inputs: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    if set(paths) != set(CONTROLLED_PATH_ENV_NAMES):
        raise ProspectiveClockActivationError(
            "controlled_paths must contain exactly the three formal path env names"
        )
    if all(item.get("state") == "deferred" for item in readiness_inputs.values()):
        if any(value is not None for value in paths.values()):
            raise ProspectiveClockActivationError(
                "deferred readiness cannot bind concrete input paths"
            )
        return {
            env_name: {
                "deferred": True,
                "path": None,
                "path_hash": None,
                "file_hash": None,
            }
            for env_name in CONTROLLED_PATH_ENV_NAMES
        }
    result: dict[str, object] = {}
    for env_name in CONTROLLED_PATH_ENV_NAMES:
        path = paths.get(env_name)
        if not isinstance(path, Path):
            raise ProspectiveClockActivationError(f"controlled path {env_name} is invalid")
        if not path.is_absolute():
            raise ProspectiveClockActivationError(
                f"controlled path {env_name} must be absolute"
            )
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise ProspectiveClockActivationError(
                f"controlled path {env_name} must be an existing file"
            )
        input_name = next(name for name, item in CAPTURE_INPUT_TO_ENV.items() if item == env_name)
        readiness_item = readiness_inputs[input_name]
        readiness_path = Path(_required_text(readiness_item.get("path"), f"readiness {input_name} path")).expanduser().resolve()
        if resolved != readiness_path:
            raise ProspectiveClockActivationError(
                f"controlled path {env_name} differs from readiness path"
            )
        current_file_hash = file_sha256(resolved)
        if current_file_hash != readiness_item.get("file_hash"):
            raise ProspectiveClockActivationError(
                f"controlled path {env_name} file changed after readiness"
            )
        result[env_name] = {
            "path": str(resolved),
            "path_hash": payload_hash({"env_name": env_name, "path": str(resolved)}),
            "file_hash": current_file_hash,
        }
    return result


def _validate_controlled_path_entries(
    entries: Mapping[str, object],
    *,
    readiness_inputs: Mapping[str, Mapping[str, object]],
) -> None:
    if set(entries) != set(CONTROLLED_PATH_ENV_NAMES):
        raise ProspectiveClockActivationError("activation controlled path names are invalid")
    deferred_entries = all(
        isinstance(item, Mapping) and item.get("state") == "deferred"
        for item in readiness_inputs.values()
    )
    if deferred_entries:
        for env_name in CONTROLLED_PATH_ENV_NAMES:
            entry = entries.get(env_name)
            if not isinstance(entry, Mapping) or set(entry) != _DEFERRED_CONTROLLED_PATH_FIELDS:
                raise ProspectiveClockActivationError(
                    f"deferred controlled path {env_name} fields are invalid"
                )
            if (
                entry.get("deferred") is not True
                or entry.get("path") is not None
                or entry.get("path_hash") is not None
                or entry.get("file_hash") is not None
            ):
                raise ProspectiveClockActivationError(
                    f"deferred controlled path {env_name} is unsafe"
                )
        return
    normalized_paths: dict[str, Path] = {}
    for env_name in CONTROLLED_PATH_ENV_NAMES:
        entry = entries.get(env_name)
        if not isinstance(entry, Mapping):
            raise ProspectiveClockActivationError(
                f"controlled path {env_name} must be an object"
            )
        normalized_paths[env_name] = Path(
            _required_text(entry.get("path"), f"controlled path {env_name}")
        )
    expected = _build_controlled_paths(
        normalized_paths,
        readiness_inputs=readiness_inputs,
    )
    if canonical_json(entries) != canonical_json(expected):
        raise ProspectiveClockActivationError("activation controlled path custody mismatch")
    for env_name, entry in entries.items():
        if not isinstance(entry, Mapping) or set(entry) != _CONTROLLED_PATH_FIELDS:
            raise ProspectiveClockActivationError(f"controlled path {env_name} fields are invalid")


def _validate_daily_time_boundary(
    record: Mapping[str, object],
    *,
    activation: ProspectiveClockActivation,
    now: datetime,
) -> None:
    capture_day = _parse_date(record.get("capture_date"), "capture_date")
    if capture_day < activation.activation_trading_day:
        raise ProspectiveClockActivationError("daily capture date precedes activation")
    now_taipei = _parse_now(now).astimezone(TAIPEI_TIMEZONE)
    if capture_day > now_taipei.date():
        raise ProspectiveClockActivationError("daily capture date is in the future")
    started = _parse_aware_datetime(record.get("started_at"), "started_at")
    if started > _parse_now(now):
        raise ProspectiveClockActivationError("daily capture started_at is in the future")
    decision = _parse_taipei_timestamp(record.get("decision_timestamp"), "decision_timestamp")
    if decision.date() != capture_day or decision > now_taipei:
        raise ProspectiveClockActivationError("daily capture decision boundary is invalid")
    if decision.timetz().replace(tzinfo=None) != _clock_decision_time(activation.payload):
        raise ProspectiveClockActivationError("daily capture decision_time mismatch")


def _validate_manifest_hash_shape(
    value: Mapping[str, object],
    *,
    label: str,
    hash_field: str = "manifest_hash",
) -> None:
    supplied = _required_hash(value.get(hash_field), hash_field)
    body = dict(value)
    body.pop(hash_field, None)
    if payload_hash(body) != supplied:
        raise ProspectiveClockActivationError(f"{label} hash mismatch")


def _seed_state_hash(clock: ProspectiveFormalClock) -> str:
    seed = clock.payload.get("seed_state")
    if not isinstance(seed, Mapping):
        raise ProspectiveClockActivationError("clock seed_state is invalid")
    state_hash = seed.get("state_hash")
    return _required_hash(state_hash, "seed_state_hash")


def _clock_decision_time(payload: Mapping[str, object]) -> time:
    value = payload.get("decision_time")
    if not isinstance(value, str):
        raise ProspectiveClockActivationError("clock decision_time is invalid")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as error:
        raise ProspectiveClockActivationError("clock decision_time is invalid") from error
    if parsed.tzinfo is not None:
        raise ProspectiveClockActivationError("clock decision_time must not contain timezone")
    return parsed


def _parse_taipei_timestamp(value: object, field_name: str) -> datetime:
    parsed = _parse_aware_datetime(value, field_name)
    return parsed.astimezone(TAIPEI_TIMEZONE)


def _parse_aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ProspectiveClockActivationError(f"{field_name} is invalid") from error
    else:
        raise ProspectiveClockActivationError(f"{field_name} must include timezone")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectiveClockActivationError(f"{field_name} must include timezone")
    return parsed


def _parse_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise ProspectiveClockActivationError(f"{field_name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ProspectiveClockActivationError(f"{field_name} is invalid") from error
    if parsed.isoformat() != value:
        raise ProspectiveClockActivationError(f"{field_name} must use YYYY-MM-DD")
    return parsed


def _parse_now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveClockActivationError("now must include timezone")
    return value


def _validate_now(value: datetime) -> None:
    _parse_now(value)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveClockActivationError(f"{field_name} must be non-empty text")
    return value.strip()


def _required_hash(value: object, field_name: str) -> str:
    text = _required_text(value, field_name)
    if len(text) != 71 or not text.startswith("sha256:") or any(
        char not in "0123456789abcdef" for char in text[7:]
    ):
        raise ProspectiveClockActivationError(f"{field_name} must be sha256")
    return text
