from __future__ import annotations

from datetime import date
from decimal import Decimal

from data_module.fundamental_statement_availability_sources import (
    StatementAvailabilityOverride,
)
from data_module.fundamental_statement_data import parse_statement_rows
from decision_module.factors.factor_dtos import FactorQuality


def test_parse_statement_rows_requires_explicit_available_date():
    result = parse_statement_rows(
        [
            {
                "date": "2024-03-31",
                "stock_id": "2330",
                "type": "EPS",
                "value": "2.30",
                "origin_name": "基本每股盈餘（元）",
            }
        ],
        statement_type="income_statement",
        available_dates={},
        source_version="financial-data-income-statement-v1",
    )

    assert result.records == ()
    assert result.diagnostics[0].code == "fundamental_availability.missing_available_date"


def test_parse_statement_rows_builds_normalized_item_with_available_date():
    result = parse_statement_rows(
        [
            {
                "date": "2024-03-31",
                "stock_id": "2330",
                "type": "EPS",
                "value": "2.30",
                "origin_name": "基本每股盈餘（元）",
            }
        ],
        statement_type="income_statement",
        available_dates={
            ("2330", "income_statement", "2024-Q1"): StatementAvailabilityOverride(
                stock_code="2330",
                statement_type="income_statement",
                period="2024-Q1",
                as_of_date=date(2024, 3, 31),
                announced_date=date(2024, 5, 10),
                available_date=date(2024, 5, 11),
                quality=FactorQuality.OBSERVED,
                source="manual.statement_available_date_mapping",
                source_version="statement-availability-2026-06-17",
            )
        },
        source_version="financial-data-income-statement-v1",
    )

    assert result.diagnostics == ()
    assert len(result.records) == 1
    record = result.records[0]
    assert record.stock_code == "2330"
    assert record.statement_type == "income_statement"
    assert record.period == "2024-Q1"
    assert record.as_of_date == date(2024, 3, 31)
    assert record.announced_date == date(2024, 5, 10)
    assert record.available_date == date(2024, 5, 11)
    assert record.item_code == "EPS"
    assert record.item_name == "基本每股盈餘（元）"
    assert record.value == Decimal("2.30")
    assert record.source == "financial_data.income_statement_csv"
    assert record.source_version == "financial-data-income-statement-v1"
    assert record.quality == FactorQuality.OBSERVED


def test_parse_statement_rows_reports_invalid_decimal():
    result = parse_statement_rows(
        [
            {
                "date": "2024-03-31",
                "stock_id": "2330",
                "type": "EPS",
                "value": "not-a-number",
                "origin_name": "基本每股盈餘（元）",
            }
        ],
        statement_type="income_statement",
        available_dates={
            ("2330", "income_statement", "2024-Q1"): date(2024, 5, 11)
        },
        source_version="financial-data-income-statement-v1",
    )

    assert result.records == ()
    assert result.diagnostics[0].code == "fundamental_statement.invalid_value"
