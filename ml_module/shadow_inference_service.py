"""Controlled one-date shadow inference using the frozen B feature loader."""

from __future__ import annotations

from typing import Mapping

from ml_module.historical_contracts import HistoricalFeatureRow
from ml_module.historical_feature_builder import HistoricalFeatureBuilder
from ml_module.historical_run_report import HistoricalMLShadowRunReport
from ml_module.inference_contracts import (
    ShadowInferenceRequest,
    ShadowInferenceResult,
    ShadowPredictionIdentity,
    prediction_id_for,
)
from ml_module.model_artifact_loader import ShadowModelArtifactLoadResult
from ml_module.model_prediction_registries import (
    MLShadowPredictionRecord,
    MLShadowPredictionRegistry,
)


class OneDateShadowInferenceService:
    """Runs only an already-loaded controlled predictor; this service never fits."""

    def __init__(
        self,
        feature_builder: HistoricalFeatureBuilder,
        prediction_registry: MLShadowPredictionRegistry,
    ) -> None:
        self._feature_builder = feature_builder
        self._prediction_registry = prediction_registry

    def run_one_date(
        self,
        *,
        feature_row: HistoricalFeatureRow,
        artifact: ShadowModelArtifactLoadResult,
        run_report: HistoricalMLShadowRunReport,
        source_versions: Mapping[str, str],
        source_versions_hash: str,
        expected_builder_contract_hash: str,
        expected_builder_schema_hash: str,
    ) -> ShadowInferenceResult:
        fallback_request = self._request(
            feature_row=feature_row,
            model_id=run_report.model_id,
            dataset_id=run_report.dataset_id,
            source_versions=source_versions,
            snapshot_hash="unavailable:feature_snapshot",
        )
        if artifact.status != "shadow_model_ready" or artifact.manifest is None or artifact.model is None:
            blocker = artifact.blockers[0] if artifact.blockers else "unknown_artifact_failure"
            return ShadowInferenceResult.unavailable(
                fallback_request, blocker=f"artifact_unavailable:{blocker}"
            )
        manifest = artifact.manifest
        if (
            not run_report.shadow_only
            or run_report.production_eligible
            or run_report.production_action_allowed
            or run_report.model_id != manifest.model_id
            or run_report.dataset_id != manifest.dataset_id
            or run_report.run_id != manifest.created_run_id
        ):
            return ShadowInferenceResult.unavailable(
                fallback_request, blocker="historical_run_identity_mismatch"
            )

        contract = self._feature_builder.load_contract
        try:
            if contract.contract_hash != expected_builder_contract_hash:
                raise ValueError("feature builder contract hash mismatch")
            contract.validate(
                expected_registry_hash=manifest.feature_registry_hash,
                expected_canonical_schema=manifest.feature_schema,
                expected_schema_hash=expected_builder_schema_hash,
            )
        except ValueError:
            return ShadowInferenceResult.unavailable(
                fallback_request, blocker="feature_builder_contract_mismatch"
            )

        try:
            vector = self._feature_builder.load(feature_row)
        except ValueError:
            return ShadowInferenceResult.unavailable(
                fallback_request, blocker="feature_snapshot_invalid"
            )
        request = self._request(
            feature_row=feature_row,
            model_id=manifest.model_id,
            dataset_id=manifest.dataset_id,
            source_versions=source_versions,
            snapshot_hash=vector.snapshot_hash,
        )
        if vector.missing_feature_ids:
            return ShadowInferenceResult.unavailable(request, blocker="missing_feature_values")
        if (
            vector.registry_hash != manifest.feature_registry_hash
            or vector.schema_hash != contract.schema_hash
            or vector.feature_ids != contract.canonical_ids
            or vector.feature_dtypes != contract.canonical_dtypes
            or vector.feature_units != contract.canonical_units
        ):
            return ShadowInferenceResult.unavailable(request, blocker="feature_parity_mismatch")

        predictor = getattr(artifact.model, "predict_shadow_bp", None)
        if not callable(predictor):
            return ShadowInferenceResult.unavailable(
                request, blocker="controlled_predictor_contract_missing"
            )
        try:
            values = tuple(value for value in vector.values if value is not None)
            raw_prediction = predictor(values)
            prediction = ShadowPredictionIdentity(
                prediction_id=prediction_id_for(request, vector.symbol),
                symbol=vector.symbol,
                return_prediction_bp=raw_prediction[0],
                ranking_score_bp=raw_prediction[1],
                downside_probability_bp=raw_prediction[2],
                uncertainty_bp=raw_prediction[3],
            )
        except (IndexError, TypeError, ValueError):
            return ShadowInferenceResult.unavailable(request, blocker="prediction_output_invalid")

        record = MLShadowPredictionRecord(
            prediction_id=prediction.prediction_id,
            model_id=manifest.model_id,
            dataset_id=manifest.dataset_id,
            symbol=prediction.symbol,
            decision_date=feature_row.decision_date,
            available_date=feature_row.available_date,
            return_prediction_bp=prediction.return_prediction_bp,
            ranking_score=prediction.ranking_score_bp,
            downside_probability=prediction.downside_probability_bp,
            uncertainty_bp=prediction.uncertainty_bp,
            feature_snapshot_hash=vector.snapshot_hash,
            source_versions_hash=source_versions_hash,
        )
        try:
            self._prediction_registry.append(record)
        except ValueError:
            return ShadowInferenceResult.unavailable(
                request, blocker="prediction_registry_conflict"
            )
        return ShadowInferenceResult.available(request, predictions=(prediction,))

    def _request(
        self,
        *,
        feature_row: HistoricalFeatureRow,
        model_id: str,
        dataset_id: str,
        source_versions: Mapping[str, str],
        snapshot_hash: str,
    ) -> ShadowInferenceRequest:
        return ShadowInferenceRequest(
            model_id=model_id,
            dataset_id=dataset_id,
            decision_date=feature_row.decision_date,
            feature_snapshot_hash=snapshot_hash,
            feature_registry_hash=self._feature_builder.load_contract.registry_hash,
            source_versions=source_versions,
            feature_max_available_date=feature_row.feature_as_of_date,
        )
