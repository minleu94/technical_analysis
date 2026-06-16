from datetime import date
from decimal import Decimal

from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy
from decision_module.factors.factor_gate import FactorGate
from decision_module.factors.valuation_adapters import build_relative_valuation_factor
from decision_module.factors.valuation_policy import ValuationBand, ValuationObservation


def test_valuation_adapter_preserves_factor_contract_and_policy_metadata():
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

    result = build_relative_valuation_factor(observation)

    assert result.diagnostics == ()
    assert len(result.records) == 1
    record = result.records[0]
    assert record.factor_name == "valuation.pe.relative_band"
    assert record.stock_code == "2330"
    assert record.as_of_date == date(2026, 6, 15)
    assert record.available_date == date(2026, 6, 16)
    assert record.quality == FactorQuality.OBSERVED
    assert record.missing_policy == MissingPolicy.SKIP
    assert record.source_version == "daily-price-pe-2026-06-16"
    assert record.score_bp is None
    assert record.value == ValuationBand.LOW_RELATIVE.value
    assert record.metadata["policy_version"] == "valuation_presentation_policy_v1"
    assert record.metadata["industry_percentile_bp"] == 1500
    assert record.metadata["metric_value"] == "18.5"


def test_valuation_adapter_diagnostic_only_when_percentile_missing():
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

    result = build_relative_valuation_factor(observation)

    assert result.records == ()
    assert result.diagnostics[0].code == "valuation.missing_industry_percentile"


def test_valuation_adapter_output_forbids_target_price_and_recommendations():
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

    result = build_relative_valuation_factor(observation)
    record = result.records[0]

    forbidden_fields = {
        "target_price",
        "fair_value",
        "upside_pct",
        "buy_signal",
        "sell_signal",
        "recommendation",
    }
    assert forbidden_fields.isdisjoint(record.metadata)


def test_valuation_factor_gate_skips_future_available_date():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 20),
        industry_percentile_bp=1500,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = build_relative_valuation_factor(observation)
    gate_result = FactorGate().validate_for_decision(
        result.records,
        decision_date=date(2026, 6, 16),
    )

    assert gate_result.accepted == ()
    assert len(gate_result.skipped) == 1
    assert gate_result.diagnostics[0].code == "factor.skipped_lookahead"
