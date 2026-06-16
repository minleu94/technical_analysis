from datetime import date
from decimal import Decimal

from data_module.fundamental_data import parse_monthly_revenue_rows
from decision_module.factors.factor_dtos import FactorQuality


def test_parse_monthly_revenue_rows_requires_explicit_available_date():
    rows = [
        {
            "date": "2026-06-10",
            "stock_id": "2330",
            "country": "Taiwan",
            "revenue": "1000000000",
            "revenue_month": "5",
            "revenue_year": "2026",
        }
    ]

    result = parse_monthly_revenue_rows(
        rows,
        available_dates={},
        source_version="financial-data-csv-preflight-v1",
    )

    assert result.records == ()
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "fundamental_availability.missing_available_date"
    assert result.diagnostics[0].stock_code == "2330"


def test_parse_monthly_revenue_rows_builds_normalized_record_with_available_date():
    rows = [
        {
            "date": "2026-06-10",
            "stock_id": "2330",
            "country": "Taiwan",
            "revenue": "1000000000",
            "revenue_month": "5",
            "revenue_year": "2026",
        }
    ]

    result = parse_monthly_revenue_rows(
        rows,
        available_dates={("2330", "2026-05"): date(2026, 6, 10)},
        source_version="financial-data-csv-preflight-v1",
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.stock_code == "2330"
    assert record.period == "2026-05"
    assert record.as_of_date == date(2026, 5, 31)
    assert record.raw_date == date(2026, 6, 10)
    assert record.announced_date is None
    assert record.available_date == date(2026, 6, 10)
    assert record.revenue == Decimal("1000000000")
    assert record.source == "financial_data.monthly_revenue_csv"
    assert record.source_version == "financial-data-csv-preflight-v1"
    assert record.quality == FactorQuality.DEGRADED
    assert result.diagnostics[0].code == "fundamental_availability.missing_announced_date"


def test_parse_monthly_revenue_rows_reports_invalid_decimal_without_record():
    rows = [
        {
            "date": "2026-06-10",
            "stock_id": "2330",
            "country": "Taiwan",
            "revenue": "not-a-number",
            "revenue_month": "5",
            "revenue_year": "2026",
        }
    ]

    result = parse_monthly_revenue_rows(
        rows,
        available_dates={("2330", "2026-05"): date(2026, 6, 10)},
        source_version="financial-data-csv-preflight-v1",
    )

    assert result.records == ()
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "fundamental_revenue.invalid_revenue"
