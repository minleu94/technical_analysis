from __future__ import annotations

from datetime import date, timedelta
from dataclasses import replace
from io import BytesIO
import warnings

import joblib

from ml_module.historical_training_service import (
    HistoricalTrainingSample,
    HistoricalTrainingService,
)
from ml_module.purged_walk_forward import MLTimeWindowRow, PurgedWalkForwardSplitter


def _samples(count: int = 40) -> tuple[HistoricalTrainingSample, ...]:
    start = date(2024, 1, 1)
    rows = []
    for index in range(count):
        decision = start + timedelta(days=index)
        label_available = decision + timedelta(days=1)
        target = (index % 11 - 5) * 100
        rows.append(HistoricalTrainingSample(
            row_id=f"r{index:03d}", decision_date=decision.isoformat(),
            label_end_date=label_available.isoformat(),
            label_available_date=label_available.isoformat(),
            feature_values=(index, None if index % 7 == 0 else index % 5),
            return_target_bp=target, downside_target=int(target <= -500),
            rule_score_bp=(index % 9 - 4) * 100,
        ))
    return tuple(rows)


def _folds(samples: tuple[HistoricalTrainingSample, ...]):
    return PurgedWalkForwardSplitter(
        minimum_train_dates=12, test_date_count=6,
        purge_trading_days=1, embargo_trading_days=1,
    ).split(tuple(MLTimeWindowRow(
        row.row_id, row.decision_date, row.label_end_date
    ) for row in samples))


def test_training_uses_fold_only_preprocessing_and_freezes_both_model_families() -> None:
    samples = _samples()
    result = HistoricalTrainingService(random_state=7, hgb_max_iter=20).fit(
        dataset_id="research-degraded-2024", feature_names=("f1", "f2"),
        samples=samples, folds=_folds(samples), training_as_of="2024-12-31",
        blend_selection_label_cutoff="2024-12-31",
    )

    assert {audit.model_family for audit in result.fold_audits} == {
        "linear", "hist_gradient_boosting"
    }
    assert all(set(audit.preprocessor_fit_row_ids).isdisjoint(audit.test_row_ids)
               for audit in result.fold_audits)
    assert result.research_blend_policy.production_alpha_bp == 0
    assert result.research_blend_policy.research_alpha_bp in (0, 2500, 5000, 7500, 10000)
    assert result.research_blend_policy.max_selection_label_available_date <= "2024-12-31"
    assert result.selected_model_family in {"linear", "hist_gradient_boosting"}
    assert result.artifact_hash.startswith("sha256:")
    assert len(result.artifact_hash) == 71
    assert result.artifact_bytes


def test_rows_after_training_and_blend_cutoff_cannot_change_frozen_result() -> None:
    samples = _samples()
    future = tuple(
        HistoricalTrainingSample(
            row_id=f"future-{i}", decision_date=f"2025-01-{i + 1:02d}",
            label_end_date=f"2025-01-{i + 2:02d}",
            label_available_date=f"2025-01-{i + 2:02d}",
            feature_values=(999999, 999999), return_target_bp=999999,
            downside_target=i % 2, rule_score_bp=999999,
        ) for i in range(10)
    )
    service = HistoricalTrainingService(random_state=7, hgb_max_iter=20)
    kwargs = dict(dataset_id="research-degraded-2024", feature_names=("f1", "f2"),
                  training_as_of="2024-12-31", blend_selection_label_cutoff="2024-12-31")

    prefix = service.fit(samples=samples, folds=_folds(samples), **kwargs)
    extended_samples = (*samples, *future)
    extended = service.fit(samples=extended_samples, folds=_folds(extended_samples), **kwargs)

    assert extended.artifact_hash == prefix.artifact_hash
    assert extended.research_blend_policy == prefix.research_blend_policy
    assert extended.selected_model_family == prefix.selected_model_family


def test_all_missing_training_column_keeps_frozen_feature_shape_without_warning() -> None:
    samples = tuple(replace(row, feature_values=(row.feature_values[0], None)) for row in _samples())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = HistoricalTrainingService(random_state=7, hgb_max_iter=20).fit(
            dataset_id="all-missing-column", feature_names=("f1", "f2"),
            samples=samples, folds=_folds(samples), training_as_of="2024-12-31",
            blend_selection_label_cutoff="2024-12-31",
        )
    payload = joblib.load(BytesIO(result.artifact_bytes))
    transformed = payload["return_model"].named_steps["imputer"].transform([[1, None]])

    assert transformed.shape[1] == 2
    assert not [item for item in caught if "Skipping features" in str(item.message)]
