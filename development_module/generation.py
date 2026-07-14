"""Fresh, development-only Terra V0 dataset generation from core source snapshots."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from data_module.ml_historical_snapshot_provider import HistoricalRawSnapshot
from development_module.contracts import DevelopmentDatasetManifest, DevelopmentGenerationRequest
from development_module.source_adapter import CoreSourceSnapshot
from development_module.universe import ConservativeObservedHistoryUniverse
from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.historical_contracts import HistoricalDatasetRow, HistoricalFeatureRow, HistoricalLabelRow
from ml_module.historical_feature_builder import HistoricalFeatureBuilder
from ml_module.historical_label_builder import HistoricalLabelBuilder
from ml_module.label_registry import CORE_LONG_HISTORY_LABEL_REGISTRY


@dataclass(frozen=True)
class DevelopmentGenerationResult:
    """Rows intentionally split so evaluation labels can never enter fit input."""

    fit_rows: tuple[HistoricalDatasetRow, ...]
    evaluation_rows: tuple[HistoricalDatasetRow, ...]
    manifest: DevelopmentDatasetManifest


class TerraDevelopmentDatasetGenerator:
    """Builds T-1 features and fresh research labels without a formal-OOS path."""

    def __init__(self, snapshot: CoreSourceSnapshot) -> None:
        self._snapshot = snapshot
        self._feature_builder = HistoricalFeatureBuilder()
        self._label_builder = HistoricalLabelBuilder()

    def generate(self, request: DevelopmentGenerationRequest) -> DevelopmentGenerationResult:
        _validate_request_dates(request)
        decision_dates = self._decision_dates(request)
        features, universe_diagnostics, skipped = self._feature_rows(decision_dates, request)
        labels_result = self._label_builder.build(
            feature_rows=features,
            prices=self._snapshot.prices,
            market=self._snapshot.market,
            label_as_of=request.evaluation_as_of,
            corporate_action_by_row={},
            mode="research",
        )
        rows = _join_rows(features, labels_result.labels)
        fit_rows = tuple(
            row for row in rows
            if row.feature.decision_date.startswith("2025-")
            and all(label.is_fit_eligible(training_as_of=request.training_as_of) for label in row.labels)
        )
        evaluation_rows = tuple(
            row for row in rows
            if row.feature.decision_date.startswith("2026-")
            and all(label.is_fit_eligible(training_as_of=request.evaluation_as_of) for label in row.labels)
        )
        excluded = Counter(universe_diagnostics)
        excluded.update(labels_result.excluded_diagnostics)
        excluded.update(skipped)
        excluded["non_2025_or_2026_row"] += sum(
            not row.feature.decision_date.startswith(("2025-", "2026-")) for row in rows
        )
        accepted = {
            "feature_rows": len(features),
            "fresh_label_rows": len(labels_result.labels),
            "development_fit_rows": len(fit_rows),
            "evaluation_only_rows": len(evaluation_rows),
            "corporate_coverage_missing": 1,
        }
        content_hash = _content_hash(fit_rows, evaluation_rows)
        manifest_without_hash = {
            "generation_id": request.generation_id,
            "dataset_id": f"terra-development-v0:{request.generation_id}",
            "feature_registry_hash": CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
            "label_registry_hash": CORE_LONG_HISTORY_LABEL_REGISTRY.registry_hash,
            "source_fingerprints": dict(self._snapshot.source_fingerprints),
            "decision_date_start": request.decision_date_start,
            "decision_date_end": request.decision_date_end,
            "training_as_of": request.training_as_of,
            "evaluation_as_of": request.evaluation_as_of,
            "fit_row_count": len(fit_rows),
            "evaluation_row_count": len(evaluation_rows),
            "accepted_diagnostics": dict(sorted(accepted.items())),
            "excluded_diagnostics": dict(sorted(excluded.items())),
            "content_hash": content_hash,
            "dataset_status": "research_only_degraded",
            "universe_policy_id": "conservative_observed_history",
            "minimum_observed_history_days": request.minimum_observed_history_days,
            "selected_universe_symbol_count": len({row.symbol for row in features}),
            "corporate_action_coverage": "research_only_degraded",
            "corporate_action_blockers": list(labels_result.blockers),
            "new_holdout_start": request.new_holdout_start,
            "usage_decision_sha256": request.usage_decision_sha256,
        }
        manifest_hash = DevelopmentDatasetManifest.canonical_sha256(manifest_without_hash)
        manifest = DevelopmentDatasetManifest(
            dataset_status="research_only_degraded",
            generation_id=request.generation_id,
            dataset_id=f"terra-development-v0:{request.generation_id}",
            feature_registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
            label_registry_hash=CORE_LONG_HISTORY_LABEL_REGISTRY.registry_hash,
            source_fingerprints=tuple(sorted(self._snapshot.source_fingerprints.items())),
            decision_date_start=request.decision_date_start,
            decision_date_end=request.decision_date_end,
            training_as_of=request.training_as_of,
            evaluation_as_of=request.evaluation_as_of,
            fit_row_count=len(fit_rows),
            evaluation_row_count=len(evaluation_rows),
            accepted_diagnostics=tuple(sorted(accepted.items())),
            excluded_diagnostics=tuple(sorted(excluded.items())),
            content_hash=content_hash,
            manifest_hash=manifest_hash,
            universe_policy_id="conservative_observed_history",
            minimum_observed_history_days=request.minimum_observed_history_days,
            selected_universe_symbol_count=len({row.symbol for row in features}),
            corporate_action_coverage="research_only_degraded",
            corporate_action_blockers=labels_result.blockers,
            new_holdout_start=request.new_holdout_start,
            usage_decision_sha256=request.usage_decision_sha256,
        )
        return DevelopmentGenerationResult(
            fit_rows=fit_rows,
            evaluation_rows=evaluation_rows,
            manifest=manifest,
        )

    def _decision_dates(self, request: DevelopmentGenerationRequest) -> tuple[str, ...]:
        dates = tuple(
            sorted(
                {
                    row.trading_date
                    for row in self._snapshot.market
                    if row.close_value is not None
                    and request.decision_date_start <= row.trading_date <= request.decision_date_end
                    and row.trading_date <= request.evaluation_as_of
                }
            )
        )
        return dates[:request.max_decision_dates] if request.max_decision_dates else dates

    def _feature_rows(
        self,
        decision_dates: Iterable[str],
        request: DevelopmentGenerationRequest,
    ) -> tuple[tuple[HistoricalFeatureRow, ...], dict[str, int], dict[str, int]]:
        all_rows: list[HistoricalFeatureRow] = []
        diagnostics: Counter[str] = Counter()
        skipped: Counter[str] = Counter()
        market_dates = tuple(sorted({row.trading_date for row in self._snapshot.market if row.close_value is not None}))
        universe = ConservativeObservedHistoryUniverse(request.minimum_observed_history_days)
        for decision_date in decision_dates:
            prior_dates = tuple(value for value in market_dates if value < decision_date)
            if not prior_dates:
                skipped["no_t_minus_1_market_date"] += 1
                continue
            selected_symbols, universe_result = universe.select(
                self._snapshot.prices,
                decision_date=decision_date,
            )
            diagnostics.update(universe_result)
            if not selected_symbols:
                skipped["empty_conservative_observed_history_universe"] += 1
                continue
            feature_as_of = prior_dates[-1]
            raw_snapshot = HistoricalRawSnapshot(
                decision_date=decision_date,
                feature_as_of_date=feature_as_of,
                prices=self._snapshot.prices,
                technicals=self._snapshot.technicals,
                market=self._snapshot.market,
                industries=self._snapshot.industries,
                source_fingerprint=DevelopmentDatasetManifest.canonical_sha256(
                    dict(self._snapshot.source_fingerprints)
                ),
                query_count=0,
            )
            rows = self._feature_builder.compute(raw_snapshot, industry_index_name_by_symbol={})
            all_rows.extend(row for row in rows if row.symbol in selected_symbols)
        return tuple(all_rows), dict(diagnostics), dict(skipped)


def _join_rows(
    features: tuple[HistoricalFeatureRow, ...], labels: tuple[HistoricalLabelRow, ...]
) -> tuple[HistoricalDatasetRow, ...]:
    expected_ids = tuple(spec.label_id for spec in CORE_LONG_HISTORY_LABEL_REGISTRY.specs)
    by_key: dict[tuple[str, str], dict[str, HistoricalLabelRow]] = {}
    for label in labels:
        by_key.setdefault((label.symbol, label.decision_date), {})[label.label_id] = label
    result: list[HistoricalDatasetRow] = []
    for feature in features:
        matches = by_key.get((feature.symbol, feature.decision_date), {})
        if all(label_id in matches for label_id in expected_ids):
            result.append(HistoricalDatasetRow(
                feature=feature,
                labels=tuple(matches[label_id] for label_id in expected_ids),
            ))
    return tuple(result)


def _content_hash(
    fit_rows: tuple[HistoricalDatasetRow, ...], evaluation_rows: tuple[HistoricalDatasetRow, ...]
) -> str:
    def row_payload(row: HistoricalDatasetRow) -> dict[str, object]:
        return {
            "symbol": row.feature.symbol,
            "decision_date": row.feature.decision_date,
            "feature_as_of_date": row.feature.feature_as_of_date,
            "available_date": row.feature.available_date,
            "values": list(row.feature.values),
            "labels": [
                {
                    "id": label.label_id,
                    "value": label.value,
                    "horizon_end_date": label.horizon_end_date,
                    "available_date": label.available_date,
                    "quality": label.quality,
                }
                for label in row.labels
            ],
        }
    return DevelopmentDatasetManifest.canonical_sha256({
        "fit_rows": [row_payload(row) for row in fit_rows],
        "evaluation_rows": [row_payload(row) for row in evaluation_rows],
    })


def _validate_request_dates(request: DevelopmentGenerationRequest) -> None:
    values = (
        request.decision_date_start,
        request.decision_date_end,
        request.training_as_of,
        request.evaluation_as_of,
    )
    for value in values:
        date.fromisoformat(value[:10])
    if request.decision_date_start > request.decision_date_end:
        raise ValueError("decision date range is invalid")
    if request.training_as_of > request.evaluation_as_of:
        raise ValueError("training_as_of must not exceed evaluation_as_of")
    date.fromisoformat(request.new_holdout_start[:10])
    if request.decision_date_end >= request.new_holdout_start:
        raise ValueError("decision date range must end before the new holdout start")
