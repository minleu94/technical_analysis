"""Run one-date ML shadow inference against explicit isolated paths."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.ml_shadow_projection_dtos import (
    MLShadowPredictionProjectionDTO,
    MLShadowProjectionDTO,
)
from ml_module.historical_contracts import HistoricalFeatureRow
from ml_module.historical_feature_builder import HistoricalFeatureBuilder
from ml_module.historical_run_report import HistoricalMLShadowRunReport
from ml_module.inference_contracts import ShadowInferenceRequest, ShadowInferenceResult
from ml_module.model_artifact_loader import (
    ArtifactCompatibilityExpectation,
    SafeShadowModelArtifactLoader,
)
from ml_module.model_lifecycle_registry import (
    ModelLifecycleEvent,
    ModelLifecycleRegistry,
    initialize_model_lifecycle_registry,
)
from ml_module.model_prediction_registries import (
    MLShadowPredictionRegistry,
    initialize_shadow_registry,
)
from ml_module.shadow_inference_service import OneDateShadowInferenceService
from ml_module.shadow_monitoring_service import ShadowModelMonitoringService


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        _validate_paths(
            shadow_root=args.shadow_root,
            output_root=args.output_root,
            prediction_registry=args.prediction_registry,
            lifecycle_registry=args.lifecycle_registry,
            data_root=args.data_root,
        )
        payload = _run(args)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid_request", "error": str(exc)}, ensure_ascii=False))
        return 2
    args.output_root.mkdir(parents=True, exist_ok=True)
    output = args.output_root / "ml-shadow-operation.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _run(args: argparse.Namespace) -> dict[str, Any]:
    initialize_shadow_registry(args.prediction_registry, data_root=args.data_root)
    initialize_model_lifecycle_registry(args.lifecycle_registry, data_root=args.data_root)
    prediction_registry = MLShadowPredictionRegistry(
        args.prediction_registry, data_root=args.data_root
    )
    lifecycle_registry = ModelLifecycleRegistry(args.lifecycle_registry, data_root=args.data_root)
    builder = HistoricalFeatureBuilder()
    feature_row = _feature_row(_read_json(args.feature_row))
    run_report = HistoricalMLShadowRunReport.from_dict(_read_json(args.run_report))
    source_versions_payload = _read_json(args.source_versions)
    source_versions = {str(key): str(value) for key, value in source_versions_payload.items()}
    artifact = SafeShadowModelArtifactLoader(data_root=args.data_root).load(
        args.model_root,
        expectation=ArtifactCompatibilityExpectation(
            expected_model_family=args.expected_model_family,
            expected_feature_registry_hash=builder.load_contract.registry_hash,
            expected_label_registry_hash=args.expected_label_registry_hash,
            expected_feature_schema=builder.load_contract.canonical_schema,
            installed_library_versions={"python": platform.python_version()},
        ),
    )
    current_lifecycle = lifecycle_registry.current_status(run_report.model_id)
    if current_lifecycle in {"disabled", "superseded"}:
        request = ShadowInferenceRequest(
            model_id=run_report.model_id,
            dataset_id=run_report.dataset_id,
            decision_date=feature_row.decision_date,
            feature_snapshot_hash="unavailable:lifecycle",
            feature_registry_hash=builder.load_contract.registry_hash,
            source_versions=source_versions,
            feature_max_available_date=feature_row.feature_as_of_date,
        )
        inference = ShadowInferenceResult.unavailable(
            request, blocker=f"lifecycle_{current_lifecycle}"
        )
    else:
        inference = OneDateShadowInferenceService(builder, prediction_registry).run_one_date(
            feature_row=feature_row,
            artifact=artifact,
            run_report=run_report,
            source_versions=source_versions,
            source_versions_hash=args.source_versions_hash,
            expected_builder_contract_hash=builder.load_contract.contract_hash,
            expected_builder_schema_hash=builder.load_contract.schema_hash,
        )
    lifecycle_action: dict[str, Any] | None = None
    if inference.status == "shadow_available":
        if lifecycle_registry.current_status(run_report.model_id) is None:
            lifecycle_registry.append(
                ModelLifecycleEvent(
                    event_id=_activation_event_id(run_report.model_id),
                    model_id=run_report.model_id,
                    event_type="activated_for_shadow",
                    created_at=f"{feature_row.decision_date}T00:00:00+00:00",
                    reason="explicit controlled shadow inference",
                )
            )
        if args.simulate_rollback_reason:
            lifecycle_action = asdict(
                ShadowModelMonitoringService(lifecycle_registry).simulate_rollback(
                    model_id=run_report.model_id,
                    dataset_id=run_report.dataset_id,
                    requested_at=f"{feature_row.decision_date}T23:59:59+00:00",
                    reason=args.simulate_rollback_reason,
                )
            )
    projection = _projection(inference)
    return {
        "inference": asdict(projection),
        "lifecycle_action": lifecycle_action,
        "evidence_mode": "controlled_contract_path",
        "validated_artifact_observed": artifact.status == "shadow_model_ready",
        "real_frozen_artifact_observed": False,
        "formal_rule_unchanged": True,
        "production_blend_alpha_bp": 0,
        "production_action_allowed": False,
        "auto_promotion_allowed": False,
        "auto_retrain_allowed": False,
        "production_scheduler_allowed": False,
    }


def _projection(result: ShadowInferenceResult) -> MLShadowProjectionDTO:
    rows = tuple(
        MLShadowPredictionProjectionDTO(
            prediction_id=row.prediction_id,
            symbol=row.symbol,
            return_prediction_bp=row.return_prediction_bp,
            ranking_score_bp=row.ranking_score_bp,
            downside_probability_bp=row.downside_probability_bp,
            uncertainty_bp=row.uncertainty_bp,
        )
        for row in result.predictions
    )
    return MLShadowProjectionDTO(
        decision_date=result.request.decision_date,
        model_id=result.request.model_id,
        dataset_id=result.request.dataset_id,
        status=result.status,
        predictions=rows,
        blockers=result.blockers,
    )


def _feature_row(payload: Mapping[str, Any]) -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        symbol=str(payload["symbol"]),
        decision_date=str(payload["decision_date"]),
        feature_as_of_date=str(payload["feature_as_of_date"]),
        available_date=str(payload["available_date"]),
        values=tuple((str(item[0]), None if item[1] is None else int(item[1])) for item in payload["values"]),
    )


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON object required: {path}")
    return payload


def _validate_paths(
    *,
    shadow_root: Path,
    output_root: Path,
    prediction_registry: Path,
    lifecycle_registry: Path,
    data_root: Path,
) -> None:
    shadow = shadow_root.resolve()
    formal = data_root.resolve()
    if not shadow_root.is_absolute() or shadow == formal or formal in shadow.parents:
        raise ValueError("explicit shadow root cannot be DATA_ROOT or a production descendant")
    for name, path in {
        "output_root": output_root,
        "prediction_registry": prediction_registry,
        "lifecycle_registry": lifecycle_registry,
    }.items():
        resolved = path.resolve()
        if not path.is_absolute() or (resolved != shadow and shadow not in resolved.parents):
            raise ValueError(f"{name} must be inside explicit shadow root")


def _activation_event_id(model_id: str) -> str:
    return f"activation:{hashlib.sha256(model_id.encode('utf-8')).hexdigest()}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shadow-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--prediction-registry", type=Path, required=True)
    parser.add_argument("--lifecycle-registry", type=Path, required=True)
    parser.add_argument("--feature-row", type=Path, required=True)
    parser.add_argument("--run-report", type=Path, required=True)
    parser.add_argument("--source-versions", type=Path, required=True)
    parser.add_argument("--source-versions-hash", required=True)
    parser.add_argument("--expected-model-family", required=True)
    parser.add_argument("--expected-label-registry-hash", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--simulate-rollback-reason")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
