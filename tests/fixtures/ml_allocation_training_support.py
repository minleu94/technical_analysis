"""跨 ML allocation 測試共用的合成 sample 與 fold fixture。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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
)
from ml_module.purged_walk_forward import MLTimeWindowRow, PurgedWalkForwardFold


_TAIPEI = ZoneInfo("Asia/Taipei")
_HASH = "sha256:" + ("a" * 64)
_SOURCE_HASH = "sha256:" + ("b" * 64)
_FEATURE_HASH = "sha256:" + ("c" * 64)
_MANIFEST_FILE_HASH = "sha256:" + ("d" * 64)


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


__all__ = [
    "_MANIFEST_FILE_HASH",
    "_HASH",
    "_sample",
    "_window_row",
    "folds",
    "samples",
    "training_result",
]
