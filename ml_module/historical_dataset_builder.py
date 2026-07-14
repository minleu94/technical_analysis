"""Deterministic first-build assembly for causal historical ML datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from typing import Mapping

from ml_module.dataset_manifest import MLDatasetField, MLDatasetManifestV2
from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY, FeatureRegistry
from ml_module.historical_contracts import (
    HistoricalDatasetRow,
    HistoricalFeatureRow,
    HistoricalLabelRow,
)
from ml_module.historical_feature_builder import HistoricalFeatureBuilder
from ml_module.label_registry import CORE_LONG_HISTORY_LABEL_REGISTRY, LabelRegistry


@dataclass(frozen=True)
class HistoricalDatasetBuildResult:
    rows: tuple[HistoricalDatasetRow, ...]
    content_hash: str | None
    manifest: MLDatasetManifestV2 | None
    accepted_diagnostics: dict[str, int]
    excluded_diagnostics: dict[str, int]
    formal_oos_allowed: bool
    shadow_only: bool = True
    production_action_allowed: bool = False


class HistoricalDatasetBuilder:
    """Joins canonical T-1 features only to labels mature by training_as_of."""

    def __init__(
        self,
        *,
        feature_registry: FeatureRegistry = CORE_LONG_HISTORY_FEATURE_REGISTRY,
        label_registry: LabelRegistry = CORE_LONG_HISTORY_LABEL_REGISTRY,
    ) -> None:
        self.feature_registry = feature_registry
        self.label_registry = label_registry
        self._feature_loader = HistoricalFeatureBuilder(feature_registry)

    def build(
        self,
        *,
        feature_rows: tuple[HistoricalFeatureRow, ...],
        labels: tuple[HistoricalLabelRow, ...],
        training_as_of: str,
        dataset_id: str,
        created_at: str,
        source_fingerprints: Mapping[str, str],
    ) -> HistoricalDatasetBuildResult:
        expected_labels = tuple(spec.label_id for spec in self.label_registry.specs)
        label_lookup: dict[tuple[str, str], dict[str, HistoricalLabelRow]] = {}
        for label in labels:
            label_lookup.setdefault((label.symbol, label.decision_date), {})[label.label_id] = label
        accepted: list[HistoricalDatasetRow] = []
        unavailable_label_count = 0
        future_decision_count = 0
        for feature in sorted(feature_rows, key=lambda row: (row.decision_date, row.symbol)):
            self._feature_loader.load(feature)
            if date.fromisoformat(feature.decision_date[:10]) > date.fromisoformat(training_as_of[:10]):
                future_decision_count += 1
                continue
            by_id = label_lookup.get((feature.symbol, feature.decision_date), {})
            selected = tuple(by_id[label_id] for label_id in expected_labels if label_id in by_id)
            if (
                len(selected) != len(expected_labels)
                or any(not label.is_fit_eligible(training_as_of=training_as_of) for label in selected)
            ):
                unavailable_label_count += 1
                continue
            accepted.append(HistoricalDatasetRow(feature=feature, labels=selected))
        excluded = {}
        if unavailable_label_count:
            excluded["immature_or_unavailable_label"] = unavailable_label_count
        if future_decision_count:
            excluded["future_decision_row"] = future_decision_count
        rows = tuple(accepted)
        accepted_diagnostics = {"accepted": len(rows)} if rows else {}
        degraded_row_count = sum(
            any(label.quality != "clean" for label in row.labels) for row in rows
        )
        if degraded_row_count:
            accepted_diagnostics["degraded_corporate_action_rows"] = degraded_row_count
        if not rows:
            return HistoricalDatasetBuildResult(
                rows=(), content_hash=None, manifest=None,
                accepted_diagnostics=accepted_diagnostics, excluded_diagnostics=excluded,
                formal_oos_allowed=False,
            )
        content_hash = _content_hash(rows)
        corporate_action_coverage = (
            "research_only_degraded"
            if any(label.quality != "clean" for row in rows for label in row.labels)
            else "clean_official_or_observed"
        )
        manifest = MLDatasetManifestV2.create(
            dataset_id=dataset_id,
            created_at=created_at,
            decision_date_start=min(row.feature.decision_date for row in rows),
            decision_date_end=max(row.feature.decision_date for row in rows),
            row_count=len(rows),
            features=tuple(
                MLDatasetField(
                    name=spec.feature_id, dtype=spec.dtype,
                    source_id=f"core.{spec.family}", available_date_required=True,
                )
                for spec in self.feature_registry.specs
            ),
            labels=tuple(
                MLDatasetField(
                    name=spec.label_id, dtype=spec.dtype,
                    source_id="historical_label", available_date_required=True,
                )
                for spec in self.label_registry.specs
            ),
            feature_registry_hash=self.feature_registry.registry_hash,
            label_registry_hash=self.label_registry.registry_hash,
            universe_policy_id="historical-listed-with-observed-history-v1",
            decision_timing="decision_t_uses_previous_trading_day",
            split_policy="expanding_purged_walk_forward_trading_calendar",
            source_fingerprints=source_fingerprints,
            accepted_diagnostics=accepted_diagnostics,
            excluded_diagnostics=excluded,
            corporate_action_coverage=corporate_action_coverage,
            broker_eligibility="excluded_separate_addon",
            fundamental_eligibility="ineligible_pending_pit_repair",
            content_hash=content_hash,
        )
        return HistoricalDatasetBuildResult(
            rows=rows, content_hash=content_hash, manifest=manifest,
            accepted_diagnostics=accepted_diagnostics, excluded_diagnostics=excluded,
            formal_oos_allowed=corporate_action_coverage == "clean_official_or_observed",
        )


def _content_hash(rows: tuple[HistoricalDatasetRow, ...]) -> str:
    payload = [
        {
            "symbol": row.feature.symbol,
            "decision_date": row.feature.decision_date,
            "feature_as_of_date": row.feature.feature_as_of_date,
            "feature_available_date": row.feature.available_date,
            "features": list(row.feature.values),
            "labels": [
                {
                    "label_id": label.label_id,
                    "value": label.value,
                    "horizon_end_date": label.horizon_end_date,
                    "available_date": label.available_date,
                    "quality": label.quality,
                }
                for label in row.labels
            ],
        }
        for row in rows
    ]
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"
