from datetime import date
from decimal import Decimal

from data_module.valuation_data import (
    build_valuation_observations,
    calculate_industry_percentiles_bp,
)
from decision_module.factors.factor_dtos import FactorQuality


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
