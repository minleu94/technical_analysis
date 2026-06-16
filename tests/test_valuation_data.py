from datetime import date
from decimal import Decimal

from data_module.valuation_data import (
    build_valuation_observations,
    calculate_industry_percentiles_bp,
)
from decision_module.factors.factor_dtos import FactorQuality
from decision_module.factors.valuation_adapters import build_relative_valuation_factor


def test_calculate_industry_percentiles_bp_uses_same_industry_universe():
    rows = [
        {"stock_code": "2330", "industry": "半導體", "metric_value": Decimal("18")},
        {"stock_code": "2303", "industry": "半導體", "metric_value": Decimal("22")},
        {"stock_code": "2454", "industry": "半導體", "metric_value": Decimal("30")},
        {"stock_code": "2317", "industry": "電子零組件", "metric_value": Decimal("12")},
    ]

    result = calculate_industry_percentiles_bp(rows)

    assert result[("2330", "半導體")] == 3333
    assert result[("2303", "半導體")] == 6667
    assert result[("2454", "半導體")] == 10000
    assert result[("2317", "電子零組件")] is None


def test_build_valuation_observations_preserves_contract():
    observations = build_valuation_observations(
        [
            {
                "stock_code": "2330",
                "as_of_date": "2026-06-15",
                "available_date": "2026-06-16",
                "metric_name": "pe",
                "metric_value": "18.5",
                "industry": "半導體",
                "industry_percentile_bp": "3333",
                "source": "daily_prices.pe",
                "source_version": "daily-price-pe-2026-06-16",
                "quality": "observed",
            }
        ]
    )

    assert observations.diagnostics == ()
    observation = observations.records[0]
    assert observation.stock_code == "2330"
    assert observation.metric_name == "pe"
    assert observation.metric_value == Decimal("18.5")
    assert observation.available_date == date(2026, 6, 16)
    assert observation.industry_percentile_bp == 3333
    assert observation.quality == FactorQuality.OBSERVED


def test_valuation_data_layer_feeds_existing_relative_band_adapter():
    observations = build_valuation_observations(
        [
            {
                "stock_code": "2330",
                "as_of_date": "2026-06-15",
                "available_date": "2026-06-16",
                "metric_name": "pe",
                "metric_value": "18.5",
                "industry": "半導體",
                "industry_percentile_bp": "1500",
                "source": "daily_prices.pe",
                "source_version": "daily-price-pe-2026-06-16",
                "quality": "observed",
            }
        ]
    )

    factor_result = build_relative_valuation_factor(observations.records[0])

    record = factor_result.records[0]
    assert record.factor_name == "valuation.pe.relative_band"
    assert record.metadata["policy_version"] == "valuation_presentation_policy_v1"
    assert record.metadata["metric_value"] == "18.5"


def test_valuation_data_layer_keeps_missing_percentile_diagnostic_only():
    observations = build_valuation_observations(
        [
            {
                "stock_code": "2330",
                "as_of_date": "2026-06-15",
                "available_date": "2026-06-16",
                "metric_name": "pe",
                "metric_value": "18.5",
                "industry": "半導體",
                "industry_percentile_bp": "",
                "source": "daily_prices.pe",
                "source_version": "daily-price-pe-2026-06-16",
                "quality": "degraded",
            }
        ]
    )

    factor_result = build_relative_valuation_factor(observations.records[0])

    assert factor_result.records == ()
    assert factor_result.diagnostics[0].code == "valuation.missing_industry_percentile"
