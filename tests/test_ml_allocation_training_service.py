from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
from io import BytesIO
import json
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pytest

from ml_module.allocation_contracts import (
    AllocationTargets,
    AllocationWeightContract,
    CausalPortfolioState,
    PITFeatureValue,
    PortfolioMLDatasetRow,
)
from ml_module.allocation_training_service import (
    AllocationHorizonLabel,
    AllocationTrainingSample,
    AllocationTrainingService,
    FeaturePackDefinition,
    _largest_remainder_weights,
    _observed_family_ids,
    _pack_matrix,
)
from ml_module.purged_walk_forward import MLTimeWindowRow, PurgedWalkForwardFold


_TAIPEI = ZoneInfo("Asia/Taipei")
_HASH = "sha256:" + ("a" * 64)
_SOURCE_HASH = "sha256:" + ("b" * 64)
_FEATURE_HASH = "sha256:" + ("c" * 64)
_MANIFEST_FILE_HASH = "sha256:" + ("d" * 64)


def test_pack_matrix_preallocation_preserves_values_and_missing_masks() -> None:
    samples = (_sample(0), _sample(1))
    pack = FeaturePackDefinition(
        pack_id="price",
        feature_ids=("return_20d_bp", "volume_rank_bp"),
    )

    ridge = _pack_matrix(
        samples,
        pack=pack,
        algorithm="ridge_logistic",
    )
    hgb = _pack_matrix(
        samples,
        pack=pack,
        algorithm="hist_gradient_boosting",
    )

    assert ridge.shape == (2, 2)
    assert np.isnan(ridge[0, 0])
    assert ridge[0, 1] == 0.0
    assert tuple(ridge[1]) == (-70.0, 137.0)
    assert hgb.shape == (2, 4)
    assert np.isnan(hgb[0, 0])
    assert tuple(hgb[0, 1:]) == (0.0, 1.0, 0.0)
    assert tuple(hgb[1]) == (-70.0, 137.0, 0.0, 0.0)


def test_zero_coverage_family_receives_zero_explanation_weight(
    samples: tuple[AllocationTrainingSample, ...],
) -> None:
    packs = (
        FeaturePackDefinition(
            pack_id="price",
            feature_ids=("return_20d_bp", "volume_rank_bp"),
        ),
        FeaturePackDefinition(
            pack_id="corporate_microstructure",
            feature_ids=("trading_restriction_flag",),
        ),
    )

    assert _observed_family_ids(
        samples=samples,
        packs=packs,
    ) == frozenset({"price"})
    weights = _largest_remainder_weights(
        {
            "price": Decimal("0"),
            "corporate_microstructure": Decimal("0"),
        },
        eligible_family_ids=frozenset({"price"}),
    )

    assert weights == (
        ("corporate_microstructure", 0),
        ("price", 10_000),
    )


def _sample(index: int) -> AllocationTrainingSample:
    decision_date = date(2025, 1, 1) + timedelta(days=index)
    symbol = f"{1000 + index:04d}"
    decision_at = datetime.combine(
        decision_date, time(8, 30), tzinfo=_TAIPEI
    ).isoformat()
    feature_date = decision_date - timedelta(days=1)
    first_feature_missing = index % 11 == 0
    features = (
        PITFeatureValue(
            feature_id="return_20d_bp",
            family_id="price",
            source_id="daily_prices",
            value_int=None if first_feature_missing else ((index % 17) - 8) * 10,
            scale=1,
            event_at=feature_date.isoformat(),
            available_at=f"{feature_date.isoformat()}T16:00:00+08:00",
            revision_id=f"price-r{index}",
            quality="missing" if first_feature_missing else "observed",
            content_hash=_FEATURE_HASH,
            observed=not first_feature_missing,
        ),
        PITFeatureValue(
            feature_id="volume_rank_bp",
            family_id="price",
            source_id="daily_prices",
            value_int=(index * 137) % 10_001,
            scale=1,
            event_at=feature_date.isoformat(),
            available_at=f"{feature_date.isoformat()}T16:00:00+08:00",
            revision_id=f"volume-r{index}",
            quality="observed",
            content_hash=_FEATURE_HASH,
            observed=True,
        ),
    )
    target_weight = 1_000 if index % 3 else 1_500
    target = AllocationWeightContract(
        positions_bp=((symbol, target_weight),),
        cash_bp=10_000 - target_weight,
    )
    targets = AllocationTargets(
        decision_date=decision_date.isoformat(),
        horizon_end_date=(decision_date + timedelta(days=20)).isoformat(),
        available_at=(
            f"{(decision_date + timedelta(days=21)).isoformat()}"
            "T18:00:00+08:00"
        ),
        target_weights=target,
        delta_weights_bp=((symbol, target_weight),),
        risk_contributions_bp=((symbol, target_weight),),
        risky_budget_bp=target_weight,
        cash_bp=10_000 - target_weight,
        rebalance_worthwhile=index % 2 == 0,
    )
    row = PortfolioMLDatasetRow(
        row_id=f"row-{index:03d}",
        decision_at=decision_at,
        symbol=symbol,
        features=features,
        missing_family_ids=("price",) if first_feature_missing else (),
        portfolio_state=CausalPortfolioState.create(
            as_of_date=feature_date.isoformat(),
            weights=AllocationWeightContract(positions_bp=(), cash_bp=10_000),
            weekly_turnover_used_bp=0,
        ),
        dataset_identity_hash=_HASH,
        feature_registry_hash=_HASH,
        source_manifest_hashes=(("daily_prices", _SOURCE_HASH),),
        targets=targets,
    )
    horizon_labels = tuple(
        AllocationHorizonLabel(
            horizon_trading_days=horizon,
            horizon_end_date=(decision_date + timedelta(days=horizon)).isoformat(),
            available_at=(
                f"{(decision_date + timedelta(days=horizon + 1)).isoformat()}"
                "T18:00:00+08:00"
            ),
            benchmark_excess_return_bp=(
                (index % 13) * 12 - 60 + (horizon // 5)
            ),
            sector_excess_return_bp=(
                None
                if index % 5 == 0
                else (index % 11) * 9 - 45 + (horizon // 10)
            ),
            sector_excess_observed=index % 5 != 0,
            sector_excess_missing_reason=(
                "pit_sector_benchmark_unavailable"
                if index % 5 == 0
                else None
            ),
            downside_observed=index % 2 == 0,
            mae_bp=(index * 31 + horizon) % 1_500,
            mfe_bp=(index * 47 + horizon) % 2_000,
            realized_volatility_bp=(index * 17 + horizon) % 900,
            max_drawdown_bp=(index * 29 + horizon) % 1_700,
            tail_loss_bp=(index * 23 + horizon) % 1_200,
            fill_feasible_observed=index % 3 != 0,
        )
        for horizon in (5, 10, 20, 60)
    )
    return AllocationTrainingSample(row=row, horizon_labels=horizon_labels)


@pytest.fixture(scope="module")
def samples() -> tuple[AllocationTrainingSample, ...]:
    return tuple(_sample(index) for index in range(163))


def _window_row(sample: AllocationTrainingSample) -> MLTimeWindowRow:
    label_end = max(
        label.horizon_end_date for label in sample.horizon_labels
    )
    return MLTimeWindowRow(
        row_id=sample.row.row_id,
        decision_date=sample.row.decision_at[:10],
        label_end_date=label_end,
    )


@pytest.fixture(scope="module")
def folds(
    samples: tuple[AllocationTrainingSample, ...],
) -> tuple[PurgedWalkForwardFold, ...]:
    windows = tuple(_window_row(sample) for sample in samples)
    definitions = (
        (19, 80, 85),
        (45, 106, 111),
        (71, 132, 137),
        (97, 158, 163),
    )
    result = []
    for fold_index, (train_end, test_start, test_end) in enumerate(
        definitions, start=1
    ):
        test_rows = windows[test_start:test_end]
        result.append(
            PurgedWalkForwardFold(
                fold_id=f"fold-{fold_index:03d}",
                train_rows=windows[:train_end],
                test_rows=test_rows,
                test_start=test_rows[0].decision_date,
                test_end=test_rows[-1].decision_date,
                purge_days=60,
                embargo_days=5,
            )
        )
    return tuple(result)


@pytest.fixture(scope="module")
def training_result(
    samples: tuple[AllocationTrainingSample, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
):
    return AllocationTrainingService(
        random_state=7,
        hgb_max_iter=6,
    ).fit(
        dataset_id="all-field-enriched-v4-test",
        dataset_manifest_file_hash=_MANIFEST_FILE_HASH,
        samples=samples,
        feature_packs=(
            FeaturePackDefinition(
                pack_id="price",
                feature_ids=("return_20d_bp", "volume_rank_bp"),
            ),
        ),
        folds=folds,
        training_as_of="2026-12-31T23:59:59+08:00",
    )


def test_base_experts_are_complete_oof_and_fold_local(
    training_result,
) -> None:
    assert len(training_result.outer_fold_ids) == 4
    assert len(training_result.base_oof_predictions) == 4 * 5 * 4 * 2
    assert {
        prediction.horizon_trading_days
        for prediction in training_result.base_oof_predictions
    } == {5, 10, 20, 60}
    assert {
        prediction.algorithm
        for prediction in training_result.base_oof_predictions
    } == {"ridge_logistic", "hist_gradient_boosting"}

    for audit in training_result.expert_fold_audits:
        assert audit.model_fit_row_ids == audit.preprocessor_fit_row_ids
        assert audit.model_fit_row_ids == audit.calibrator_fit_row_ids
        assert set(audit.model_fit_row_ids).isdisjoint(audit.test_row_ids)
        if audit.algorithm == "hist_gradient_boosting":
            assert (
                audit.preprocessing_strategy
                == "native_nan_plus_explicit_missing_mask"
            )
        else:
            assert (
                audit.preprocessing_strategy
                == "head_local_median_indicator_then_standard_scale"
            )
        assert tuple(
            head_id for head_id, _ in audit.head_fit_row_ids
        ) == (
            "expected_excess_return_bp",
            "expected_sector_excess_return_bp",
            "predicted_mae_bp",
            "predicted_mfe_bp",
            "predicted_realized_volatility_bp",
            "predicted_max_drawdown_bp",
            "predicted_tail_loss_bp",
            "downside_probability_bp",
            "fill_feasibility_probability_bp",
        )
        assert all(
            set(row_ids).isdisjoint(audit.test_row_ids)
            for _, row_ids in audit.head_fit_row_ids
        )
    for prediction in training_result.base_oof_predictions:
        assert isinstance(prediction.expected_excess_return_bp, int)
        assert isinstance(prediction.downside_probability_bp, int)
        assert isinstance(prediction.predicted_mae_bp, int)
        assert isinstance(prediction.predicted_mfe_bp, int)
        assert isinstance(prediction.predicted_realized_volatility_bp, int)
        assert isinstance(prediction.predicted_max_drawdown_bp, int)
        assert isinstance(prediction.predicted_tail_loss_bp, int)
        assert isinstance(
            prediction.fill_feasibility_probability_bp,
            int,
        )


def test_fit_row_custody_reuses_equal_tuples_without_changing_audit(
    training_result,
) -> None:
    for fold_id in training_result.outer_fold_ids:
        fold_audits = tuple(
            audit
            for audit in training_result.expert_fold_audits
            if audit.fold_id == fold_id
        )
        shared = fold_audits[0].model_fit_row_ids
        assert all(
            audit.model_fit_row_ids is shared
            and audit.preprocessor_fit_row_ids is shared
            and audit.calibrator_fit_row_ids is shared
            for audit in fold_audits
        )
        for audit in fold_audits:
            assert all(
                not row_ids
                or head_id == "expected_sector_excess_return_bp"
                or row_ids is shared
                for head_id, row_ids in audit.head_fit_row_ids
            )

    artifact = joblib.load(BytesIO(training_result.artifact_bytes))
    fit_row_ids = tuple(
        model_payload["fit_row_ids"]
        for model_payload in artifact["base_models"].values()
    )
    assert all(row_ids is fit_row_ids[0] for row_ids in fit_row_ids)


def test_meta_allocator_uses_only_prior_base_oof_rows(
    training_result,
    samples: tuple[AllocationTrainingSample, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
) -> None:
    sample_by_id = {sample.row.row_id: sample for sample in samples}
    test_start_by_fold = {
        fold.fold_id: datetime.fromisoformat(
            f"{fold.test_start}T08:30:00+08:00"
        )
        for fold in folds
    }
    assert len(training_result.meta_oof_predictions) == 15
    assert {
        prediction.fold_id
        for prediction in training_result.meta_oof_predictions
    } == {"fold-002", "fold-003", "fold-004"}
    for prediction in training_result.meta_oof_predictions:
        assert prediction.fold_id not in prediction.fit_fold_ids
        assert prediction.row_id not in prediction.fit_row_ids
        assert isinstance(prediction.target_weight_bp, int)
        assert isinstance(prediction.delta_weight_bp, int)
        assert isinstance(prediction.risk_contribution_bp, int)
        assert isinstance(prediction.cash_bp, int)
        assert isinstance(prediction.rebalance_worthwhile, bool)
        for fit_row_id in prediction.fit_row_ids:
            targets = sample_by_id[fit_row_id].row.targets
            assert targets is not None
            assert (
                datetime.fromisoformat(targets.available_at)
                <= test_start_by_fold[prediction.fold_id]
            )


def test_training_artifact_is_json_auditable_and_cannot_enable_alpha(
    training_result,
) -> None:
    assert training_result.production_alpha_bp == 0
    assert training_result.production_action_allowed is False
    assert training_result.artifact_hash.startswith("sha256:")
    assert training_result.replay_hash.startswith("sha256:")
    assert sum(
        weight for _, weight in training_result.feature_family_weights_bp
    ) == 10_000
    assert training_result.feature_family_weights_bp == (("price", 10_000),)

    audit = training_result.audit_payload()
    assert audit["schema_version"] == "allocation-training-audit-v3"
    assert audit["dataset_identity_hash"] == _HASH
    assert audit["dataset_manifest_file_hash"] == _MANIFEST_FILE_HASH
    assert audit["artifact_hash"] == training_result.artifact_hash
    assert audit["replay_hash"] == training_result.replay_hash
    compact_expert = audit["expert_fold_audits"][0]
    assert "model_fit_row_ids" not in compact_expert
    assert compact_expert["model_fit_rows"]["count"] > 0
    assert compact_expert["model_fit_rows"]["ordered_sha256"].startswith(
        "sha256:"
    )
    compact_meta = audit["meta_fold_audits"][0]
    assert "fit_row_ids" not in compact_meta
    assert compact_meta["fit_rows"]["ordered_sha256"].startswith("sha256:")
    compact_prediction = audit["meta_oof_predictions"][0]
    assert "fit_row_ids" not in compact_prediction
    assert compact_prediction["fit_rows"]["count"] > 0
    assert compact_prediction["fit_rows"]["ordered_sha256"].startswith(
        "sha256:"
    )
    canonical_prediction = training_result.meta_oof_predictions[0]
    encoded_fit_rows = json.dumps(
        list(canonical_prediction.fit_row_ids),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    expected_custody_hash = (
        f"sha256:{hashlib.sha256(encoded_fit_rows).hexdigest()}"
    )
    assert compact_prediction["fit_rows"] == {
        "count": len(canonical_prediction.fit_row_ids),
        "ordered_sha256": expected_custody_hash,
    }
    compact_prediction_fold = next(
        fold
        for fold in audit["meta_fold_audits"]
        if fold["fold_id"] == canonical_prediction.fold_id
    )
    assert compact_prediction_fold["fit_rows"] == compact_prediction["fit_rows"]
    json.dumps(audit, ensure_ascii=False)

    artifact = joblib.load(BytesIO(training_result.artifact_bytes))
    assert artifact["artifact_schema_version"] == "allocation-model-artifact-v3"
    assert artifact["dataset_identity_hash"] == _HASH
    assert artifact["dataset_manifest_file_hash"] == _MANIFEST_FILE_HASH
    assert artifact["expert_vector_width"] == 19
    assert tuple(artifact["expert_head_ids"]) == (
        "expected_excess_return_bp",
        "expected_sector_excess_return_bp",
        "predicted_mae_bp",
        "predicted_mfe_bp",
        "predicted_realized_volatility_bp",
        "predicted_max_drawdown_bp",
        "predicted_tail_loss_bp",
        "downside_probability_bp",
        "fill_feasibility_probability_bp",
    )
    assert artifact["production_alpha_bp"] == 0
    assert artifact["production_action_allowed"] is False
    assert set(artifact["expert_keys"]) == {
        f"price|h{horizon}|{algorithm}"
        for horizon in (5, 10, 20, 60)
        for algorithm in ("ridge_logistic", "hist_gradient_boosting")
    }
    for model_payload in artifact["base_models"].values():
        assert set(model_payload["regression_models"]) == {
            "expected_excess_return_bp",
            "expected_sector_excess_return_bp",
            "predicted_mae_bp",
            "predicted_mfe_bp",
            "predicted_realized_volatility_bp",
            "predicted_max_drawdown_bp",
            "predicted_tail_loss_bp",
        }
        assert set(model_payload["classification_models"]) == {
            "downside_probability_bp",
            "fill_feasibility_probability_bp",
        }


def test_replay_and_artifact_hashes_are_deterministic(
    samples: tuple[AllocationTrainingSample, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
    training_result,
) -> None:
    rerun = AllocationTrainingService(
        random_state=7,
        hgb_max_iter=6,
    ).fit(
        dataset_id="all-field-enriched-v4-test",
        dataset_manifest_file_hash=_MANIFEST_FILE_HASH,
        samples=samples,
        feature_packs=(
            FeaturePackDefinition(
                pack_id="price",
                feature_ids=("return_20d_bp", "volume_rank_bp"),
            ),
        ),
        folds=folds,
        training_as_of="2026-12-31T23:59:59+08:00",
    )
    assert rerun.replay_hash == training_result.replay_hash
    assert rerun.artifact_hash == training_result.artifact_hash


@pytest.mark.parametrize(
    "algorithm",
    ("ridge_logistic", "hist_gradient_boosting"),
)
def test_sector_excess_head_is_explicitly_masked_without_pit_labels(
    samples: tuple[AllocationTrainingSample, ...],
    algorithm: str,
) -> None:
    subset = tuple(
        replace(
            sample,
            horizon_labels=tuple(
                replace(
                    label,
                    sector_excess_return_bp=None,
                    sector_excess_observed=False,
                    sector_excess_missing_reason=(
                        "pit_sector_benchmark_unavailable"
                    ),
                )
                for label in sample.horizon_labels
            ),
        )
        for sample in samples[:12]
    )
    matrix = np.asarray(
        [[index, index % 3] for index in range(len(subset))],
        dtype=float,
    )
    payload = AllocationTrainingService(
        random_state=7,
        hgb_max_iter=2,
    )._fit_expert_head_models(
        algorithm=algorithm,
        x=matrix,
        samples=subset,
        horizon=20,
    )

    sector_head = "expected_sector_excess_return_bp"
    assert payload["regression_models"][sector_head] is None
    assert payload["head_fit_row_ids"][sector_head] == ()
    assert (
        payload["head_missing_reasons"][sector_head]
        == "pit_sector_benchmark_labels_unavailable"
    )


def test_rejects_less_than_four_outer_folds(
    samples: tuple[AllocationTrainingSample, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
) -> None:
    with pytest.raises(ValueError, match="at least four outer folds"):
        AllocationTrainingService(hgb_max_iter=2).fit(
            dataset_id="too-few-folds",
            dataset_manifest_file_hash=_MANIFEST_FILE_HASH,
            samples=samples,
            feature_packs=(
                FeaturePackDefinition(
                    pack_id="price",
                    feature_ids=("return_20d_bp", "volume_rank_bp"),
                ),
            ),
            folds=folds[:3],
            training_as_of="2026-12-31T23:59:59+08:00",
        )


def test_rejects_declared_purge_when_actual_decision_date_gap_is_short(
    samples: tuple[AllocationTrainingSample, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
) -> None:
    poisoned = replace(
        folds[0],
        train_rows=tuple(
            (*folds[0].train_rows, _window_row(samples[79]))
        ),
    )
    with pytest.raises(ValueError, match="actual purge"):
        AllocationTrainingService(
            random_state=7,
            hgb_max_iter=2,
        ).fit(
            dataset_id="declared-purge-poison",
            dataset_manifest_file_hash=_MANIFEST_FILE_HASH,
            samples=samples,
            feature_packs=(
                FeaturePackDefinition(
                    pack_id="price",
                    feature_ids=("return_20d_bp", "volume_rank_bp"),
                ),
            ),
            folds=(poisoned, *folds[1:]),
            training_as_of="2026-12-31T23:59:59+08:00",
        )


def test_rejects_non_expanding_outer_train_windows(
    samples: tuple[AllocationTrainingSample, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
) -> None:
    non_expanding = replace(
        folds[1],
        train_rows=folds[1].train_rows[1:],
    )
    with pytest.raises(ValueError, match="expanding window"):
        AllocationTrainingService(
            random_state=7,
            hgb_max_iter=2,
        ).fit(
            dataset_id="non-expanding-poison",
            dataset_manifest_file_hash=_MANIFEST_FILE_HASH,
            samples=samples,
            feature_packs=(
                FeaturePackDefinition(
                    pack_id="price",
                    feature_ids=("return_20d_bp", "volume_rank_bp"),
                ),
            ),
            folds=(folds[0], non_expanding, *folds[2:]),
            training_as_of="2026-12-31T23:59:59+08:00",
        )


def test_rejects_outer_test_row_overlap(
    samples: tuple[AllocationTrainingSample, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
) -> None:
    duplicate = replace(folds[1], test_rows=folds[0].test_rows)
    with pytest.raises(ValueError, match="only one outer test fold"):
        AllocationTrainingService(hgb_max_iter=2).fit(
            dataset_id="overlapping-oof",
            dataset_manifest_file_hash=_MANIFEST_FILE_HASH,
            samples=samples,
            feature_packs=(
                FeaturePackDefinition(
                    pack_id="price",
                    feature_ids=("return_20d_bp", "volume_rank_bp"),
                ),
            ),
            folds=(folds[0], duplicate, folds[2], folds[3]),
            training_as_of="2026-12-31T23:59:59+08:00",
        )


def test_rejects_label_that_is_not_available_by_training_cutoff(
    samples: tuple[AllocationTrainingSample, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
) -> None:
    poisoned_labels = (
        replace(
            samples[0].horizon_labels[0],
            available_at="2028-01-01T18:00:00+08:00",
        ),
        *samples[0].horizon_labels[1:],
    )
    poisoned = (
        replace(samples[0], horizon_labels=poisoned_labels),
        *samples[1:],
    )
    with pytest.raises(ValueError, match="availability exceeds training_as_of"):
        AllocationTrainingService(hgb_max_iter=2).fit(
            dataset_id="future-label",
            dataset_manifest_file_hash=_MANIFEST_FILE_HASH,
            samples=poisoned,
            feature_packs=(
                FeaturePackDefinition(
                    pack_id="price",
                    feature_ids=("return_20d_bp", "volume_rank_bp"),
                ),
            ),
            folds=folds,
            training_as_of="2026-12-31T23:59:59+08:00",
        )


def test_rejects_train_label_unavailable_at_fold_test_start(
    samples: tuple[AllocationTrainingSample, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
) -> None:
    fold_test_start = folds[0].test_start
    poisoned_labels = (
        replace(
            samples[0].horizon_labels[0],
            available_at=f"{fold_test_start}T08:31:00+08:00",
        ),
        *samples[0].horizon_labels[1:],
    )
    poisoned = (
        replace(samples[0], horizon_labels=poisoned_labels),
        *samples[1:],
    )
    with pytest.raises(
        ValueError, match="horizon label was unavailable at test start"
    ):
        AllocationTrainingService(hgb_max_iter=2).fit(
            dataset_id="fold-future-label",
            dataset_manifest_file_hash=_MANIFEST_FILE_HASH,
            samples=poisoned,
            feature_packs=(
                FeaturePackDefinition(
                    pack_id="price",
                    feature_ids=("return_20d_bp", "volume_rank_bp"),
                ),
            ),
            folds=folds,
            training_as_of="2026-12-31T23:59:59+08:00",
        )


def test_rejects_meta_fit_when_prior_oof_targets_are_not_mature(
    samples: tuple[AllocationTrainingSample, ...],
    folds: tuple[PurgedWalkForwardFold, ...],
) -> None:
    poisoned = list(samples)
    for index in range(80, 85):
        targets = poisoned[index].row.targets
        assert targets is not None
        future_targets = replace(
            targets,
            available_at=f"{folds[1].test_start}T08:31:00+08:00",
        )
        poisoned[index] = replace(
            poisoned[index],
            row=replace(poisoned[index].row, targets=future_targets),
        )
    with pytest.raises(
        ValueError,
        match="no matured prior OOF AllocationTargets",
    ):
        AllocationTrainingService(hgb_max_iter=2).fit(
            dataset_id="meta-future-label",
            dataset_manifest_file_hash=_MANIFEST_FILE_HASH,
            samples=tuple(poisoned),
            feature_packs=(
                FeaturePackDefinition(
                    pack_id="price",
                    feature_ids=("return_20d_bp", "volume_rank_bp"),
                ),
            ),
            folds=folds,
            training_as_of="2026-12-31T23:59:59+08:00",
        )
