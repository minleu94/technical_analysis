from __future__ import annotations

from datetime import date

from data_module.fundamental_statement_availability_sources import (
    STATEMENT_AVAILABILITY_COLUMNS,
    load_statement_availability_overrides,
    load_statement_availability_overrides_csv,
)
from decision_module.factors.factor_dtos import FactorQuality


def test_load_statement_availability_overrides_preserves_announcement_contract():
    result = load_statement_availability_overrides(
        [
            {
                "stock_code": "2330",
                "statement_type": "income_statement",
                "period": "2024-Q1",
                "as_of_date": "2024-03-31",
                "announced_date": "2024-05-10",
                "available_date": "2024-05-11",
                "source": "manual.statement_available_date_mapping",
                "source_version": "statement-availability-2026-06-17",
            }
        ]
    )

    override = result.overrides[("2330", "income_statement", "2024-Q1")]

    assert override.stock_code == "2330"
    assert override.statement_type == "income_statement"
    assert override.period == "2024-Q1"
    assert override.as_of_date == date(2024, 3, 31)
    assert override.announced_date == date(2024, 5, 10)
    assert override.available_date == date(2024, 5, 11)
    assert override.quality == FactorQuality.OBSERVED
    assert result.diagnostics == ()


def test_load_statement_availability_overrides_degrades_retroactive_baseline():
    result = load_statement_availability_overrides(
        [
            {
                "stock_code": "2330",
                "statement_type": "income_statement",
                "period": "2024-Q1",
                "as_of_date": "2024-03-31",
                "announced_date": "",
                "available_date": "2026-06-17",
                "source": "manual.retroactive_statement_baseline_mapping",
                "source_version": "statement-retroactive-baseline-2026-06-17",
            }
        ]
    )

    override = result.overrides[("2330", "income_statement", "2024-Q1")]

    assert override.announced_date is None
    assert override.available_date == date(2026, 6, 17)
    assert override.quality == FactorQuality.DEGRADED
    assert result.diagnostics == ()


def test_load_statement_availability_overrides_rejects_raw_statement_source():
    result = load_statement_availability_overrides(
        [
            {
                "stock_code": "2330",
                "statement_type": "income_statement",
                "period": "2024-Q1",
                "as_of_date": "2024-03-31",
                "announced_date": "",
                "available_date": "2024-05-11",
                "source": "financial_data.income_statement_csv",
                "source_version": "raw-v1",
            }
        ]
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_statement_availability.raw_csv_not_available_source"


def test_load_statement_availability_overrides_csv_reads_governed_file(tmp_path):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text(
        ",".join(STATEMENT_AVAILABILITY_COLUMNS)
        + "\n"
        + (
            "2330,income_statement,2024-Q1,2024-03-31,2024-05-10,2024-05-11,"
            "manual.statement_available_date_mapping,statement-availability-2026-06-17\n"
        ),
        encoding="utf-8-sig",
    )

    result = load_statement_availability_overrides_csv(mapping_file)

    assert result.overrides[("2330", "income_statement", "2024-Q1")].available_date == date(
        2024, 5, 11
    )
    assert result.diagnostics == ()


def test_load_statement_availability_overrides_csv_reports_missing_file(tmp_path):
    result = load_statement_availability_overrides_csv(
        tmp_path / "missing_fundamental_statement_availability.csv"
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_statement_availability.mapping_file_missing"
