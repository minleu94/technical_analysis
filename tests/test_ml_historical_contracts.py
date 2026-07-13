from __future__ import annotations

from datetime import date

import pytest

from ml_module.historical_contracts import (
    HistoricalDatasetRow,
    HistoricalFeatureRow,
    HistoricalLabelRow,
    HistoricalUniversePolicy,
)


def _feature_row(**overrides: object) -> HistoricalFeatureRow:
    values: dict[str, object] = {
        "symbol": "2330",
        "decision_date": "2024-06-03",
        "feature_as_of_date": "2024-05-31",
        "available_date": "2024-06-03",
        "values": (("return_20d_bp", 125),),
    }
    values.update(overrides)
    return HistoricalFeatureRow(**values)  # type: ignore[arg-type]


def _label_row(**overrides: object) -> HistoricalLabelRow:
    values: dict[str, object] = {
        "symbol": "2330",
        "decision_date": "2024-06-03",
        "label_id": "relative_return_20d_bp",
        "value": 300,
        "horizon_end_date": "2024-07-01",
        "available_date": "2024-07-01",
        "maturity_status": "ready",
        "quality": "research_only",
    }
    values.update(overrides)
    return HistoricalLabelRow(**values)  # type: ignore[arg-type]


def test_decision_timing_requires_feature_observation_before_decision_date() -> None:
    with pytest.raises(ValueError, match="feature_as_of_date.*before decision_date"):
        _feature_row(feature_as_of_date="2024-06-03")


def test_same_day_close_is_rejected_even_when_available_on_decision_date() -> None:
    with pytest.raises(ValueError, match="feature_as_of_date.*before decision_date"):
        _feature_row(
            feature_as_of_date="2024-06-03",
            available_date="2024-06-03",
        )


def test_future_available_feature_is_rejected() -> None:
    with pytest.raises(ValueError, match="available_date.*decision_date"):
        _feature_row(available_date="2024-06-04")


def test_label_fit_eligibility_requires_ready_and_available_by_training_cutoff() -> None:
    assert _label_row().is_fit_eligible(training_as_of="2024-07-01") is True
    assert _label_row().is_fit_eligible(training_as_of="2024-06-30") is False
    assert _label_row(maturity_status="pending", value=None).is_fit_eligible(
        training_as_of="2024-07-01"
    ) is False


def test_dataset_row_rejects_symbol_or_decision_date_mismatch() -> None:
    with pytest.raises(ValueError, match="same symbol and decision_date"):
        HistoricalDatasetRow(
            feature=_feature_row(),
            labels=(_label_row(symbol="2317"),),
        )


def test_historical_universe_is_built_from_decision_time_information() -> None:
    policy = HistoricalUniversePolicy(minimum_history_trading_days=60)

    assert policy.is_eligible(
        decision_date=date(2024, 6, 3),
        listing_date=date(2020, 1, 2),
        delisting_date=date(2024, 12, 31),
        observed_history_trading_days=60,
    ) is True
    assert policy.is_eligible(
        decision_date=date(2024, 6, 3),
        listing_date=date(2024, 6, 4),
        delisting_date=None,
        observed_history_trading_days=60,
    ) is False
    assert policy.is_eligible(
        decision_date=date(2024, 6, 3),
        listing_date=date(2020, 1, 2),
        delisting_date=date(2024, 5, 31),
        observed_history_trading_days=500,
    ) is False
