"""以純函式驗證系統執行藍圖 artifacts；不連線 DB、不訓練、不改 gate。"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping


_INPUT_NAMES = (
    "evidence_execution",
    "ml_split_and_pit",
    "dataset_model_prediction_identity",
    "dashboard_visibility",
    "broker_latency",
    "formal_boundaries",
    "external_pending",
)
_DASHBOARD_SOURCES = frozenset(
    {
        "fundamental_monthly_revenues",
        "institutional_flows",
        "credit_transactions",
        "tdcc_shareholding",
        "broker_flows",
    }
)
_EXTERNAL_GATES = (
    "forward_evidence",
    "source_acceptance",
    "production_automation",
    "ml_promotion",
)


class BlueprintVerificationError(ValueError):
    """Artifact 不完整、矛盾或弱化安全真相。"""


def verify_system_execution_blueprint(input_root: str | Path) -> dict[str, object]:
    root = Path(input_root).expanduser().resolve()
    artifacts = {name: _load_mapping(root / f"{name}.json") for name in _INPUT_NAMES}
    _verify_evidence(artifacts["evidence_execution"])
    _verify_ml_split(artifacts["ml_split_and_pit"])
    _verify_identity(artifacts["dataset_model_prediction_identity"])
    _verify_dashboard(artifacts["dashboard_visibility"])
    _verify_latency(artifacts["broker_latency"])
    _verify_formal_boundaries(artifacts["formal_boundaries"])
    _verify_external_pending(artifacts["external_pending"])
    return {
        "evidence_execution": artifacts["evidence_execution"],
        "ml_split_and_pit": artifacts["ml_split_and_pit"],
        "dataset_model_prediction_identity": artifacts[
            "dataset_model_prediction_identity"
        ],
        "dashboard_visibility": artifacts["dashboard_visibility"],
        "broker_latency": artifacts["broker_latency"],
        "formal_boundaries": artifacts["formal_boundaries"],
        "external_pending": artifacts["external_pending"],
        "overall_engineering_status": (
            "engineering_integration_verified_external_gates_pending"
        ),
    }


def _load_mapping(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise BlueprintVerificationError(f"missing input artifact: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise BlueprintVerificationError(f"malformed input artifact: {path.name}") from error
    if not isinstance(payload, dict):
        raise BlueprintVerificationError(f"input artifact must be an object: {path.name}")
    return payload


def _verify_evidence(payload: Mapping[str, object]) -> None:
    if payload.get("status") != "engineering_real_e2e_complete":
        raise BlueprintVerificationError(
            "Evidence status must remain engineering_real_e2e_complete"
        )
    if (
        payload.get("source_db_opened") is not True
        or payload.get("source_db_write_performed") is not False
        or payload.get("working_copy_created") is not True
    ):
        raise BlueprintVerificationError("Evidence read-only/working-copy boundary failed")
    hashes = payload.get("artifact_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise BlueprintVerificationError("Evidence artifact hash is required")
    _verify_hashes(hashes, "Evidence")


def _verify_ml_split(payload: Mapping[str, object]) -> None:
    cutoff = date(2024, 12, 31)
    for field_name in (
        "training_end_date",
        "max_train_label_available_date",
        "max_blend_selection_label_available_date",
    ):
        try:
            value = date.fromisoformat(str(payload[field_name])[:10])
        except (KeyError, ValueError) as error:
            raise BlueprintVerificationError(f"invalid {field_name}") from error
        if value > cutoff:
            raise BlueprintVerificationError(
                f"{field_name} must be on or before 2024-12-31"
            )
    if payload.get("oos_start_date") != "2025-01-01" or payload.get(
        "oos_end_date"
    ) != "2025-12-31":
        raise BlueprintVerificationError("locked OOS must remain the 2025 calendar year")
    if payload.get("future_rows_excluded") is not True:
        raise BlueprintVerificationError("future rows must be excluded")
    if payload.get("immature_labels_excluded") is not True:
        raise BlueprintVerificationError("immature labels must be excluded")


def _verify_identity(payload: Mapping[str, object]) -> None:
    for field_name in ("dataset_id", "model_id"):
        if not isinstance(payload.get(field_name), str) or not payload[field_name]:
            raise BlueprintVerificationError(f"{field_name} is required")
    _verify_hashes(
        {
            "dataset_hash": payload.get("dataset_hash"),
            "model_hash": payload.get("model_hash"),
        },
        "dataset/model",
    )
    predictions = payload.get("prediction_ids")
    if not isinstance(predictions, list) or not predictions or any(
        not isinstance(item, str) or not item for item in predictions
    ):
        raise BlueprintVerificationError("prediction identity is required")
    if payload.get("shadow_only") is not True:
        raise BlueprintVerificationError("model prediction must remain shadow-only")


def _verify_dashboard(payload: Mapping[str, object]) -> None:
    missing = _DASHBOARD_SOURCES.difference(payload)
    if missing:
        raise BlueprintVerificationError(f"dashboard sources missing: {sorted(missing)}")
    for source_id in _DASHBOARD_SOURCES:
        status = payload[source_id]
        if not isinstance(status, dict):
            raise BlueprintVerificationError(f"dashboard status invalid: {source_id}")
        try:
            row_count = int(status["row_count"])
        except (KeyError, TypeError, ValueError) as error:
            raise BlueprintVerificationError(
                f"dashboard row_count invalid: {source_id}"
            ) from error
        quality = str(status.get("quality", "")).lower()
        if row_count == 0 and quality not in {"missing", "degraded"}:
            raise BlueprintVerificationError(
                f"zero-row dashboard source cannot be ready: {source_id}"
            )


def _verify_latency(payload: Mapping[str, object]) -> None:
    samples = payload.get("warm_samples_ms")
    if not isinstance(samples, list) or len(samples) < 20:
        raise BlueprintVerificationError("broker latency requires at least 20 warm samples")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0
        for value in samples
    ):
        raise BlueprintVerificationError("broker latency samples are invalid")
    warm_p95 = _required_nonnegative_number(payload, "warm_p95_ms")
    loading_state = _required_nonnegative_number(payload, "loading_state_ms")
    if warm_p95 >= 2000:
        raise BlueprintVerificationError("broker warm p95 must remain below 2000 ms")
    if loading_state >= 300:
        raise BlueprintVerificationError("UI loading state must appear within 300 ms")
    if payload.get("query_limit_pushed_down") is not True:
        raise BlueprintVerificationError("broker query limit must be pushed down")


def _verify_formal_boundaries(payload: Mapping[str, object]) -> None:
    if payload.get("production_blend_alpha_bp") != 0:
        raise BlueprintVerificationError("production blend alpha must remain zero")
    if payload.get("formal_rule_unchanged") is not True:
        raise BlueprintVerificationError("formal rule must remain unchanged")
    if payload.get("formal_score_changed") is not False:
        raise BlueprintVerificationError("formal score changed")
    if payload.get("production_action_allowed") is not False:
        raise BlueprintVerificationError("production action must remain disabled")
    if payload.get("formal_oos_allowed") is not False:
        raise BlueprintVerificationError("formal OOS must remain blocked")


def _verify_external_pending(payload: Mapping[str, object]) -> None:
    for gate in _EXTERNAL_GATES:
        if payload.get(gate) != "pending":
            raise BlueprintVerificationError(f"external gate must remain pending: {gate}")


def _verify_hashes(payload: Mapping[str, object], label: str) -> None:
    for artifact_id, raw_value in payload.items():
        value = str(raw_value)
        digest = value.removeprefix("sha256:")
        if (
            not artifact_id
            or not value.startswith("sha256:")
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise BlueprintVerificationError(f"{label} artifact hash is invalid")


def _required_nonnegative_number(
    payload: Mapping[str, object], field_name: str
) -> int | float:
    value = payload.get(field_name)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value < 0
    ):
        raise BlueprintVerificationError(f"{field_name} must be a non-negative number")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify system execution blueprint")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_system_execution_blueprint(args.input_root)
    except BlueprintVerificationError as error:
        print(json.dumps({"status": "verification_failed", "error": str(error)}))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "verified", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
