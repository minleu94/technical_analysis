from datetime import date
from decimal import Decimal

from decision_module.factors.factor_dtos import FactorQuality
from decision_module.factors.valuation_policy import (
    VALUATION_PRESENTATION_POLICY_VERSION,
    ValuationBand,
    ValuationObservation,
    classify_relative_valuation,
    valuation_band_ui_label,
)


def test_classify_relative_valuation_uses_non_trading_band_names():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=1500,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = classify_relative_valuation(observation)

    assert [band.name for band in ValuationBand] == [
        "LOW_RELATIVE",
        "MID_RELATIVE",
        "HIGH_RELATIVE",
        "UNAVAILABLE",
    ]
    assert result.band == ValuationBand.LOW_RELATIVE
    assert result.policy_version == VALUATION_PRESENTATION_POLICY_VERSION
    assert result.metric_value == Decimal("18.5")
    assert result.diagnostics == ()


def test_classify_relative_valuation_mid_and_high_relative_bands():
    mid = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("22"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=5000,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )
    high = ValuationObservation(
        stock_code="2317",
        metric_name="pe",
        metric_value=Decimal("45"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=8500,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    assert classify_relative_valuation(mid).band == ValuationBand.MID_RELATIVE
    assert classify_relative_valuation(high).band == ValuationBand.HIGH_RELATIVE


def test_missing_industry_percentile_is_unavailable_not_neutral():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=None,
        quality=FactorQuality.DEGRADED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = classify_relative_valuation(observation)

    assert result.band == ValuationBand.UNAVAILABLE
    assert result.band != ValuationBand.MID_RELATIVE
    assert result.diagnostics[0].code == "valuation.missing_industry_percentile"


def test_invalid_percentile_is_unavailable():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=10001,
        quality=FactorQuality.DEGRADED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = classify_relative_valuation(observation)

    assert result.band == ValuationBand.UNAVAILABLE
    assert result.diagnostics[0].code == "valuation.invalid_industry_percentile"


def test_valuation_band_ui_labels_are_descriptive_not_actionable():
    assert valuation_band_ui_label(ValuationBand.LOW_RELATIVE) == "相對低估值區"
    assert valuation_band_ui_label(ValuationBand.MID_RELATIVE) == "中性估值區"
    assert valuation_band_ui_label(ValuationBand.HIGH_RELATIVE) == "相對高估值區"
    assert valuation_band_ui_label(ValuationBand.UNAVAILABLE) == "資料不足"


def test_policy_output_forbids_target_price_and_recommendation_fields():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=1500,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = classify_relative_valuation(observation)
    output = result.to_metadata()

    forbidden_fields = {
        "target_price",
        "fair_value",
        "upside_pct",
        "buy_signal",
        "sell_signal",
        "recommendation",
    }
    assert forbidden_fields.isdisjoint(output)
