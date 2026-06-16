from datetime import date
from decimal import Decimal

from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy
from decision_module.factors.factor_gate import FactorGate
from decision_module.factors.fundamental_adapters import (
    FundamentalObservation,
    build_revenue_yoy_factor,
)


def test_revenue_yoy_factor_preserves_available_date_contract():
    observation = FundamentalObservation(
        stock_code="2330",
        period="2026-05",
        as_of_date=date(2026, 5, 31),
        announced_date=date(2026, 6, 10),
        available_date=date(2026, 6, 10),
        value=Decimal("12.34"),
        source="financial_data.monthly_revenue_csv",
        source_version="fundamental-source-inventory-2026-06-16",
        quality=FactorQuality.OBSERVED,
    )

    result = build_revenue_yoy_factor(observation)

    assert not result.diagnostics
    assert len(result.records) == 1
    record = result.records[0]
    assert record.factor_name == "fundamental.revenue_yoy"
    assert record.stock_code == "2330"
    assert record.as_of_date == date(2026, 5, 31)
    assert record.available_date == date(2026, 6, 10)
    assert record.value == Decimal("12.34")
    assert record.score_bp is None
    assert record.quality == FactorQuality.OBSERVED
    assert record.missing_policy == MissingPolicy.SKIP
    assert record.source_version == "fundamental-source-inventory-2026-06-16"
    assert record.metadata["period"] == "2026-05"
    assert record.metadata["announced_date"] == date(2026, 6, 10)
    assert record.metadata["source"] == "financial_data.monthly_revenue_csv"


def test_revenue_yoy_factor_reports_missing_available_date_without_record():
    observation = FundamentalObservation(
        stock_code="2330",
        period="2026-05",
        as_of_date=date(2026, 5, 31),
        announced_date=None,
        available_date=None,
        value=Decimal("12.34"),
        source="financial_data.monthly_revenue_csv",
        source_version="fundamental-source-inventory-2026-06-16",
        quality=FactorQuality.DEGRADED,
    )

    result = build_revenue_yoy_factor(observation)

    assert result.records == ()
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "fundamental.missing_available_date"
    assert result.diagnostics[0].factor_name == "fundamental.revenue_yoy"
    assert result.diagnostics[0].stock_code == "2330"


def test_revenue_yoy_factor_gate_skips_future_available_date():
    observation = FundamentalObservation(
        stock_code="2330",
        period="2026-05",
        as_of_date=date(2026, 5, 31),
        announced_date=date(2026, 6, 20),
        available_date=date(2026, 6, 20),
        value=Decimal("12.34"),
        source="financial_data.monthly_revenue_csv",
        source_version="fundamental-source-inventory-2026-06-16",
        quality=FactorQuality.OBSERVED,
    )

    build_result = build_revenue_yoy_factor(observation)
    gate_result = FactorGate().validate_for_decision(
        build_result.records,
        decision_date=date(2026, 6, 14),
    )

    assert gate_result.accepted == ()
    assert len(gate_result.skipped) == 1
    assert gate_result.diagnostics[0].code == "factor.skipped_lookahead"
