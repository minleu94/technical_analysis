"""執行配置型 ML Production Co-pilot 的每日 fail-closed promotion 評估。

本腳本只寫入 OUTPUT_ROOT 下的 append-only sidecar、promotion artifact 與
latest status。缺少、無效或未授權的證據一律原子回退為 alpha=0，不會改寫
來源資料庫、投組狀態或模型產物。
"""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml_module.allocation_validation import (
    ALPHA_LANES,
    AllocationFoldEvidence,
    AllocationPromotionEvidence,
    AllocationPromotionEvaluator,
    AlphaLaneEvidence,
    PromotionAuthorizationVerification,
    PromotionAuthorizationVerifier,
)
from data_module.official_trading_calendar import OfficialTradingCalendar
from runtime.promotion_authority_secret_store import (
    DEFAULT_CUSTODY_ID,
    DEFAULT_ISSUER_ID,
    PromotionAuthoritySecretStore,
)


TASK_NAME = "baldr-ml-allocation-copilot-daily"
TAIPEI = ZoneInfo("Asia/Taipei")
SCHEMA_VERSION = "ml-allocation-copilot.v1"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    encoded = _canonical_json(payload).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _with_hash(
    payload: Mapping[str, object],
    *,
    field_name: str,
) -> dict[str, object]:
    result = dict(payload)
    result[field_name] = _payload_hash(result)
    return result


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json_mapping(path: Path, *, label: str) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} 必須是 JSON object")
    return value


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} 必須是 object")
    return value


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise TypeError(f"{label} 必須是 array")
    return value


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} 必須是 integer")
    return value


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{label} 必須是非空字串")
    return value


def _load_evidence(payload: Mapping[str, object]) -> AllocationPromotionEvidence:
    source = payload.get("promotion_evidence", payload)
    body = _mapping(source, label="promotion_evidence")
    lanes: list[AlphaLaneEvidence] = []
    for lane_index, lane_value in enumerate(
        _sequence(body.get("lanes"), label="promotion_evidence.lanes")
    ):
        lane = _mapping(lane_value, label=f"lanes[{lane_index}]")
        folds = tuple(
            AllocationFoldEvidence(
                fold_id=_text(
                    _mapping(row, label="fold").get("fold_id"),
                    label="fold_id",
                ),
                after_cost_excess_vs_rule_bp=_integer(
                    _mapping(row, label="fold").get(
                        "after_cost_excess_vs_rule_bp"
                    ),
                    label="after_cost_excess_vs_rule_bp",
                ),
            )
            for row in _sequence(lane.get("folds"), label="folds")
        )
        replay_hash_pairs_list: list[tuple[str, str]] = []
        for pair in _sequence(
            lane.get("replay_hash_pairs"),
            label="replay_hash_pairs",
        ):
            pair_values = _sequence(pair, label="replay_hash_pair")
            if len(pair_values) != 2:
                raise ValueError("replay_hash_pair 必須恰有兩個 hash")
            replay_hash_pairs_list.append(
                (
                    _text(
                        pair_values[0],
                        label="expected_replay_hash",
                    ),
                    _text(
                        pair_values[1],
                        label="actual_replay_hash",
                    ),
                )
            )
        replay_hash_pairs = tuple(replay_hash_pairs_list)
        lanes.append(
            AlphaLaneEvidence(
                alpha_bp=_integer(lane.get("alpha_bp"), label="alpha_bp"),
                pit_violation_count=_integer(
                    lane.get("pit_violation_count"),
                    label="pit_violation_count",
                ),
                future_prefix_violation_count=_integer(
                    lane.get("future_prefix_violation_count"),
                    label="future_prefix_violation_count",
                ),
                constraint_violation_count=_integer(
                    lane.get("constraint_violation_count"),
                    label="constraint_violation_count",
                ),
                replay_hash_pairs=replay_hash_pairs,
                folds=folds,
                bootstrap_lower_bound_bp=_integer(
                    lane.get("bootstrap_lower_bound_bp"),
                    label="bootstrap_lower_bound_bp",
                ),
                calibration_ece_bp=_integer(
                    lane.get("calibration_ece_bp"),
                    label="calibration_ece_bp",
                ),
                calibrated_brier_bp=_integer(
                    lane.get("calibrated_brier_bp"),
                    label="calibrated_brier_bp",
                ),
                uncalibrated_brier_bp=_integer(
                    lane.get("uncalibrated_brier_bp"),
                    label="uncalibrated_brier_bp",
                ),
                psi_bp=_integer(lane.get("psi_bp"), label="psi_bp"),
                core_coverage_bp=_integer(
                    lane.get("core_coverage_bp"),
                    label="core_coverage_bp",
                ),
                enriched_coverage_bp=_integer(
                    lane.get("enriched_coverage_bp"),
                    label="enriched_coverage_bp",
                ),
                feasible_fill_coverage_bp=_integer(
                    lane.get("feasible_fill_coverage_bp"),
                    label="feasible_fill_coverage_bp",
                ),
                mdd_worsening_vs_rule_bp=_integer(
                    lane.get("mdd_worsening_vs_rule_bp"),
                    label="mdd_worsening_vs_rule_bp",
                ),
                cvar_worsening_vs_rule_bp=_integer(
                    lane.get("cvar_worsening_vs_rule_bp"),
                    label="cvar_worsening_vs_rule_bp",
                ),
                weekly_turnover_bp=_integer(
                    lane.get("weekly_turnover_bp"),
                    label="weekly_turnover_bp",
                ),
                turnover_increment_vs_rule_bp=_integer(
                    lane.get("turnover_increment_vs_rule_bp"),
                    label="turnover_increment_vs_rule_bp",
                ),
                shadow_observed_days=_integer(
                    lane.get("shadow_observed_days"),
                    label="shadow_observed_days",
                ),
            )
        )
    return AllocationPromotionEvidence(
        experiment_id=_text(
            body.get("experiment_id"),
            label="experiment_id",
        ),
        model_id=_text(body.get("model_id"), label="model_id"),
        dataset_id=_text(body.get("dataset_id"), label="dataset_id"),
        model_artifact_hash=_text(
            body.get("model_artifact_hash"),
            label="model_artifact_hash",
        ),
        dataset_identity_hash=_text(
            body.get("dataset_identity_hash"),
            label="dataset_identity_hash",
        ),
        dataset_manifest_file_hash=_text(
            body.get("dataset_manifest_file_hash"),
            label="dataset_manifest_file_hash",
        ),
        oof_bundle_hash=_text(
            body.get("oof_bundle_hash"),
            label="oof_bundle_hash",
        ),
        shadow_evidence_hash=_text(
            body.get("shadow_evidence_hash"),
            label="shadow_evidence_hash",
        ),
        lanes=tuple(lanes),
    )


def _parse_decision_at(
    value: str | None,
    *,
    now: datetime | None = None,
) -> datetime:
    if value is None:
        current = now or datetime.now(TAIPEI)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now 必須包含時區")
        local_now = current.astimezone(TAIPEI)
        candidate = datetime.combine(
            local_now.date(),
            time(8, 30),
            tzinfo=TAIPEI,
        )
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--decision-at 必須包含時區")
    local = parsed.astimezone(TAIPEI)
    if local.timetz().replace(tzinfo=None) != time(8, 30):
        raise ValueError("--decision-at 必須對應 Asia/Taipei 08:30")
    return local


def _unevaluated_payload(
    *,
    policy_hash: str,
    blocker: str,
) -> dict[str, object]:
    return {
        "schema_version": "ml-allocation-promotion.v1",
        "evidence_hash": None,
        "policy_hash": policy_hash,
        "alpha_lanes": [
            {
                "alpha_bp": alpha_bp,
                "promotion_candidate": alpha_bp != 0,
                "evaluated": False,
                "passed": False,
                "winning_fold_count": 0,
                "failed_reasons": [blocker],
                "threshold_evidence": None,
            }
            for alpha_bp in ALPHA_LANES
        ],
        "eligible_alpha_bp": 0,
        "selected_alpha_bp": 0,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "authorization_artifact_id": None,
        "failed_reasons": [blocker],
    }


def _evaluate(
    *,
    decision_at: datetime,
    evidence_path: Path | None,
    authorization_path: Path | None,
    registry_revision_path: Path | None,
    model_artifact_path: Path | None,
    dataset_manifest_path: Path | None,
    oof_bundle_path: Path | None,
    shadow_evidence_path: Path | None,
    evaluator: AllocationPromotionEvaluator,
    authorization_verifier: PromotionAuthorizationVerifier | None,
) -> tuple[dict[str, object], dict[str, object]]:
    source: dict[str, object] = {
        "promotion_evidence_path": (
            str(evidence_path.resolve()) if evidence_path is not None else None
        ),
        "promotion_authorization_path": (
            str(authorization_path.resolve())
            if authorization_path is not None
            else None
        ),
        "promotion_registry_revision_path": (
            str(registry_revision_path.resolve())
            if registry_revision_path is not None
            else None
        ),
        "promotion_model_artifact_path": (
            str(model_artifact_path.resolve())
            if model_artifact_path is not None
            else None
        ),
        "promotion_dataset_manifest_path": (
            str(dataset_manifest_path.resolve())
            if dataset_manifest_path is not None
            else None
        ),
        "promotion_oof_bundle_path": (
            str(oof_bundle_path.resolve())
            if oof_bundle_path is not None
            else None
        ),
        "promotion_shadow_evidence_path": (
            str(shadow_evidence_path.resolve())
            if shadow_evidence_path is not None
            else None
        ),
        "promotion_evidence_hash": None,
        "promotion_authorization_artifact_id": None,
        "promotion_authorization_verified": False,
        "promotion_authorization_verification_blockers": [],
        "promotion_authorization_custody_hash": None,
    }
    if evidence_path is None:
        return (
            _unevaluated_payload(
                policy_hash=evaluator.policy_hash,
                blocker="promotion_evidence_missing",
            ),
            source,
        )
    if not evidence_path.is_file():
        return (
            _unevaluated_payload(
                policy_hash=evaluator.policy_hash,
                blocker="promotion_evidence_file_missing",
            ),
            source,
        )

    try:
        evidence_payload = _read_json_mapping(
            evidence_path,
            label="promotion_evidence",
        )
        evidence = _load_evidence(evidence_payload)
        source["promotion_evidence_hash"] = evidence.evidence_hash
        verification: PromotionAuthorizationVerification | None = None
        if authorization_path is not None:
            custody_paths = (
                registry_revision_path,
                model_artifact_path,
                dataset_manifest_path,
                oof_bundle_path,
                shadow_evidence_path,
            )
            if authorization_verifier is None:
                verification = PromotionAuthorizationVerification(
                    decision_at=decision_at.isoformat(timespec="seconds"),
                    passed=False,
                    blockers=("promotion_authority_trust_not_configured",),
                )
            elif any(path is None for path in custody_paths):
                verification = PromotionAuthorizationVerification(
                    decision_at=decision_at.isoformat(timespec="seconds"),
                    passed=False,
                    blockers=("promotion_custody_paths_incomplete",),
                )
            else:
                assert registry_revision_path is not None
                assert model_artifact_path is not None
                assert dataset_manifest_path is not None
                assert oof_bundle_path is not None
                assert shadow_evidence_path is not None
                verification = authorization_verifier.verify_files(
                    decision_at=decision_at,
                    evidence_path=evidence_path,
                    authorization_path=authorization_path,
                    registry_revision_path=registry_revision_path,
                    model_artifact_path=model_artifact_path,
                    dataset_manifest_path=dataset_manifest_path,
                    oof_bundle_path=oof_bundle_path,
                    shadow_evidence_path=shadow_evidence_path,
                    expected_policy_hash=evaluator.policy_hash,
                )
            source["promotion_authorization_verification_blockers"] = list(
                verification.blockers
            )
            source["promotion_authorization_custody_hash"] = (
                verification.custody_hash
            )
            source["promotion_authorization_verified"] = verification.passed
            if verification.authorization is not None:
                source["promotion_authorization_artifact_id"] = (
                    verification.authorization.artifact_id
                )
        result = evaluator.evaluate(
            evidence,
            authorization_verification=verification,
        ).to_dict()
        result["alpha_lanes"] = [
            {**_mapping(lane, label="alpha_lane"), "evaluated": True}
            for lane in _sequence(result["alpha_lanes"], label="alpha_lanes")
        ]
        return result, source
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        blocker = f"promotion_evidence_invalid:{type(exc).__name__}"
        source["validation_error"] = str(exc)
        return (
            _unevaluated_payload(
                policy_hash=evaluator.policy_hash,
                blocker=blocker,
            ),
            source,
        )


def run(
    *,
    output_root: Path,
    decision_at: datetime,
    evidence_path: Path | None,
    authorization_path: Path | None,
    calendar: OfficialTradingCalendar | None = None,
    registry_revision_path: Path | None = None,
    model_artifact_path: Path | None = None,
    dataset_manifest_path: Path | None = None,
    oof_bundle_path: Path | None = None,
    shadow_evidence_path: Path | None = None,
    trusted_issuer_keys: Mapping[str, bytes] | None = None,
    trusted_custody_roots: Sequence[Path] = (),
    trusted_custody_id: str | None = None,
) -> dict[str, object]:
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("decision_at 必須包含時區")
    decision_at = decision_at.astimezone(TAIPEI)
    if decision_at.timetz().replace(tzinfo=None) != time(8, 30):
        raise ValueError("decision_at 必須對應 Asia/Taipei 08:30")

    run_root = output_root / "scheduled" / "ml_allocation_copilot"
    calendar_service = calendar or OfficialTradingCalendar()
    try:
        is_trading_day, calendar_reason = (
            calendar_service.is_official_trading_day(decision_at.date())
        )
    except Exception as exc:  # noqa: BLE001 - 排程必須將日曆異常持久化
        is_trading_day = None
        calendar_reason = f"calendar_exception:{type(exc).__name__}"

    if is_trading_day is not True:
        blocker = (
            f"non_trading_day:{calendar_reason}"
            if is_trading_day is False
            else f"trading_calendar_unknown:{calendar_reason}"
        )
        blocked_base: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "task": TASK_NAME,
            "status": (
                "skipped_non_trading_day"
                if is_trading_day is False
                else "degraded_calendar_unknown"
            ),
            "operation_mode": "not_run",
            "evidence_state": (
                "official_market_closed"
                if is_trading_day is False
                else "calendar_evidence_unavailable"
            ),
            "decision_at": decision_at.isoformat(timespec="seconds"),
            "trading_calendar_validated": is_trading_day is False,
            "trading_calendar_is_open": is_trading_day,
            "trading_calendar_reason": calendar_reason,
            "selected_alpha_bp": 0,
            "production_blend_alpha_bp": 0,
            "formal_oos_allowed": False,
            "alpha_lanes": [],
            "failed_reasons": [blocker],
            "artifact_hash": None,
            "artifact_path": None,
            "sidecar_record_hash": None,
            "sidecar_path": None,
            "writes_source_database": False,
            "changes_portfolio_state": False,
            "broker_execution": False,
        }
        blocked = _with_hash(blocked_base, field_name="status_hash")
        _atomic_write_json(run_root / "latest_status.json", blocked)
        return blocked

    evaluator = AllocationPromotionEvaluator()
    authorization_verifier: PromotionAuthorizationVerifier | None = None
    if (
        trusted_issuer_keys
        and trusted_custody_roots
        and trusted_custody_id is not None
    ):
        authorization_verifier = PromotionAuthorizationVerifier(
            trusted_issuer_keys=trusted_issuer_keys,
            trusted_custody_roots=trusted_custody_roots,
            custody_id=trusted_custody_id,
        )
    promotion, source = _evaluate(
        decision_at=decision_at,
        evidence_path=evidence_path,
        authorization_path=authorization_path,
        registry_revision_path=registry_revision_path,
        model_artifact_path=model_artifact_path,
        dataset_manifest_path=dataset_manifest_path,
        oof_bundle_path=oof_bundle_path,
        shadow_evidence_path=shadow_evidence_path,
        evaluator=evaluator,
        authorization_verifier=authorization_verifier,
    )
    selected_alpha_bp = _integer(
        promotion["selected_alpha_bp"],
        label="selected_alpha_bp",
    )
    formal_oos_allowed = promotion["formal_oos_allowed"] is True
    if selected_alpha_bp != 0 and not formal_oos_allowed:
        raise ValueError("非正式 OOS 狀態不得輸出非零 alpha")

    decision_at_text = decision_at.isoformat(timespec="seconds")
    decision_key = decision_at.strftime("%Y%m%d")

    artifact_base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "promotion_evaluation",
        "task": TASK_NAME,
        "decision_at": decision_at_text,
        "promotion": promotion,
        "source": source,
        "safety_boundary": {
            "writes_source_database": False,
            "changes_portfolio_state": False,
            "broker_execution": False,
        },
    }
    artifact = _with_hash(artifact_base, field_name="artifact_hash")
    artifact_hash = _text(artifact["artifact_hash"], label="artifact_hash")
    artifact_path = (
        run_root
        / "artifacts"
        / f"{decision_key}_{artifact_hash[7:23]}_promotion.json"
    )

    sidecar_base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "daily_shadow_lane_observation",
        "task": TASK_NAME,
        "decision_at": decision_at_text,
        "artifact_hash": artifact_hash,
        "selected_alpha_bp": selected_alpha_bp,
        "formal_oos_allowed": formal_oos_allowed,
        "alpha_lanes": promotion["alpha_lanes"],
        "failed_reasons": promotion["failed_reasons"],
    }
    sidecar = _with_hash(sidecar_base, field_name="sidecar_record_hash")
    sidecar_hash = _text(
        sidecar["sidecar_record_hash"],
        label="sidecar_record_hash",
    )
    sidecar_path = (
        run_root
        / "sidecar"
        / f"{decision_key}_{sidecar_hash[7:23]}_shadow.json"
    )

    operation_mode = (
        "ml_blend_authorized" if formal_oos_allowed else "rule_only"
    )
    latest_base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "task": TASK_NAME,
        "status": (
            "passed_ml_blend"
            if formal_oos_allowed
            else "passed_rule_only"
        ),
        "operation_mode": operation_mode,
        "evidence_state": (
            "promotion_authorized"
            if formal_oos_allowed
            else "insufficient_evidence"
        ),
        "decision_at": decision_at_text,
        "trading_calendar_validated": True,
        "trading_calendar_is_open": True,
        "trading_calendar_reason": calendar_reason,
        "selected_alpha_bp": selected_alpha_bp,
        "production_blend_alpha_bp": selected_alpha_bp,
        "formal_oos_allowed": formal_oos_allowed,
        "alpha_lanes": promotion["alpha_lanes"],
        "failed_reasons": promotion["failed_reasons"],
        "artifact_hash": artifact_hash,
        "artifact_path": str(artifact_path.resolve()),
        "sidecar_record_hash": sidecar_hash,
        "sidecar_path": str(sidecar_path.resolve()),
        "writes_source_database": False,
        "changes_portfolio_state": False,
        "broker_execution": False,
    }
    latest = _with_hash(latest_base, field_name="status_hash")

    _atomic_write_json(artifact_path, artifact)
    _atomic_write_json(sidecar_path, sidecar)
    _atomic_write_json(run_root / "latest_status.json", latest)
    return latest


def _trusted_issuer_keys_from_environment() -> dict[str, bytes]:
    raw = os.environ.get("BALDR_PROMOTION_TRUSTED_ISSUER_KEYS_JSON")
    if raw is None or not raw.strip():
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError(
            "BALDR_PROMOTION_TRUSTED_ISSUER_KEYS_JSON 必須是 JSON object"
        )
    result: dict[str, bytes] = {}
    for raw_issuer_id, raw_key in payload.items():
        issuer_id = _text(raw_issuer_id, label="trusted issuer id")
        key_text = _text(raw_key, label=f"trusted issuer key:{issuer_id}")
        if not key_text.startswith("hex:"):
            raise ValueError("trusted issuer key 必須使用 hex: 編碼")
        try:
            key = bytes.fromhex(key_text[4:])
        except ValueError as exc:
            raise ValueError("trusted issuer key 不是有效 hex") from exc
        if len(key) < 32:
            raise ValueError("trusted issuer key 至少需要 32 bytes")
        result[issuer_id] = key
    return result


def _trusted_custody_roots_from_environment() -> tuple[Path, ...]:
    raw = os.environ.get("BALDR_PROMOTION_CUSTODY_ROOTS")
    if raw is None or not raw.strip():
        return ()
    return tuple(Path(value) for value in raw.split(os.pathsep) if value.strip())


def _promotion_trust_configuration(
    *,
    output_root: Path,
) -> tuple[dict[str, bytes], tuple[Path, ...], str | None]:
    """Load explicit trust plus an optional user-DPAPI deployment identity.

    The consumer never creates a key.  First-run initialization belongs to the
    independent Promotion Authority task.  Once that task has provisioned the
    DPAPI file, the consumer can verify its signatures without exposing the
    HMAC key through environment variables or command-line arguments.
    """

    keys = _trusted_issuer_keys_from_environment()
    roots = _trusted_custody_roots_from_environment()
    custody_id = os.environ.get("BALDR_PROMOTION_CUSTODY_ID")
    configured_path = os.environ.get(
        "BALDR_PROMOTION_AUTHORITY_SECRET_FILE"
    )
    default_path = (
        output_root
        / "release_v4"
        / "ml_promotion_authority"
        / "authority_secret.dpapi.json"
    )
    secret_path = (
        Path(configured_path)
        if configured_path is not None and configured_path.strip()
        else default_path
    )
    if not secret_path.exists():
        if configured_path is not None and configured_path.strip():
            raise ValueError(
                "configured Promotion Authority DPAPI secret does not exist"
            )
        return keys, roots, custody_id

    issuer_id = os.environ.get(
        "BALDR_PROMOTION_AUTHORITY_ISSUER_ID",
        DEFAULT_ISSUER_ID,
    )
    expected_custody_id = os.environ.get(
        "BALDR_PROMOTION_AUTHORITY_CUSTODY_ID",
        DEFAULT_CUSTODY_ID,
    )
    secret = PromotionAuthoritySecretStore(
        secret_path,
        issuer_id=issuer_id,
        custody_id=expected_custody_id,
    ).load()
    existing = keys.get(secret.issuer_id)
    if existing is not None and existing != secret.signing_key:
        raise ValueError("Promotion Authority issuer key conflicts with env trust")
    keys[secret.issuer_id] = secret.signing_key
    if not roots:
        roots = ((output_root / "release_v4").resolve(),)
    if custody_id is None or not custody_id.strip():
        custody_id = secret.custody_id
    elif custody_id.strip() != secret.custody_id:
        raise ValueError("Promotion Authority custody id conflicts with env trust")
    return keys, roots, custody_id


def _configure_standard_streams_utf8() -> None:
    """讓 Windows 排程器的 legacy code page 也能安全輸出稽核文字。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "執行配置型 ML Production Co-pilot 每日 promotion 評估；"
            "證據不足時維持 alpha=0。"
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(
            os.environ.get(
                "OUTPUT_ROOT",
                "D:/Min/Python/Project/FA_Data/output",
            )
        ),
    )
    parser.add_argument(
        "--decision-at",
        help="含時區 ISO timestamp；必須對應 Asia/Taipei 08:30。",
    )
    parser.add_argument("--promotion-evidence", type=Path)
    parser.add_argument("--promotion-authorization", type=Path)
    parser.add_argument("--promotion-registry-revision", type=Path)
    parser.add_argument("--promotion-model-artifact", type=Path)
    parser.add_argument("--promotion-dataset-manifest", type=Path)
    parser.add_argument("--promotion-oof-bundle", type=Path)
    parser.add_argument("--promotion-shadow-evidence", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_standard_streams_utf8()
    args = build_parser().parse_args(argv)
    try:
        trusted_keys, trusted_roots, trusted_custody_id = (
            _promotion_trust_configuration(output_root=args.output_root)
        )
        payload = run(
            output_root=args.output_root,
            decision_at=_parse_decision_at(args.decision_at),
            evidence_path=args.promotion_evidence,
            authorization_path=args.promotion_authorization,
            registry_revision_path=args.promotion_registry_revision,
            model_artifact_path=args.promotion_model_artifact,
            dataset_manifest_path=args.promotion_dataset_manifest,
            oof_bundle_path=args.promotion_oof_bundle,
            shadow_evidence_path=args.promotion_shadow_evidence,
            trusted_issuer_keys=trusted_keys,
            trusted_custody_roots=trusted_roots,
            trusted_custody_id=trusted_custody_id,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "task": TASK_NAME,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if str(payload["status"]).startswith(("passed_", "skipped_")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
