from datetime import date
from decimal import Decimal

from data_module.fundamental_data import MonthlyRevenueRecord
from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy
from decision_module.factors.fundamental_adapters import build_revenue_factor_pack


def _record(period: str, revenue: str, available_date: date) -> MonthlyRevenueRecord:
    year, month = [int(part) for part in period.split("-")]
    return MonthlyRevenueRecord(
        stock_code="2330",
        period=period,
        as_of_date=date(year, month, 28),
        raw_date=available_date,
        announced_date=available_date,
        available_date=available_date,
        revenue=Decimal(revenue),
        source="financial_data.monthly_revenue_csv",
        source_version="financial-data-csv-v1",
        quality=FactorQuality.OBSERVED,
    )


def test_build_revenue_factor_pack_emits_yoy_mom_trend_and_new_high():
    records = (
        _record("2025-04", "90", date(2025, 5, 10)),
        _record("2025-05", "100", date(2025, 6, 10)),
        _record("2026-03", "110", date(2026, 4, 10)),
        _record("2026-04", "120", date(2026, 5, 10)),
        _record("2026-05", "150", date(2026, 6, 10)),
    )

    result = build_revenue_factor_pack(records, stock_code="2330", decision_period="2026-05")

    by_name = {record.factor_name: record for record in result.records}
    assert by_name["fundamental.revenue_yoy"].value == Decimal("0.5")
    assert by_name["fundamental.revenue_mom"].value == Decimal("0.25")
    assert by_name["fundamental.revenue_3m_trend"].value == "up"
    assert by_name["fundamental.revenue_new_high"].value == 1
    for record in result.records:
        assert record.available_date == date(2026, 6, 10)
        assert record.missing_policy == MissingPolicy.SKIP
        assert record.score_bp is None
        assert record.source_version == "financial-data-csv-v1"
