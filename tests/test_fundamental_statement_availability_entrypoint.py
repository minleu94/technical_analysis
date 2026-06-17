from __future__ import annotations

from data_module.fundamental_statement_availability_entrypoint import (
    STATEMENT_ALLOWED_AVAILABILITY_SOURCES,
    validate_statement_availability_file,
)


def test_validate_statement_availability_file_accepts_governed_source(tmp_path):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text(
        "stock_code,statement_type,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,income_statement,2024-Q1,2024-03-31,2024-05-10,2024-05-11,"
        "manual.statement_available_date_mapping,statement-availability-2026-06-17\n",
        encoding="utf-8-sig",
    )

    result = validate_statement_availability_file(mapping_file)

    assert result.valid is True
    assert result.accepted_count == 1
    assert result.diagnostics == ()


def test_validate_statement_availability_file_accepts_retroactive_baseline(tmp_path):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text(
        "stock_code,statement_type,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,income_statement,2024-Q1,2024-03-31,,2026-06-17,"
        "manual.retroactive_statement_baseline_mapping,statement-retroactive-baseline-2026-06-17\n",
        encoding="utf-8-sig",
    )

    result = validate_statement_availability_file(mapping_file)

    assert result.valid is True
    assert result.accepted_count == 1
    assert result.diagnostics == ()


def test_validate_statement_availability_file_rejects_raw_csv_source(tmp_path):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text(
        "stock_code,statement_type,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,income_statement,2024-Q1,2024-03-31,,2024-05-11,"
        "financial_data.income_statement_csv,raw-v1\n",
        encoding="utf-8-sig",
    )

    result = validate_statement_availability_file(mapping_file)

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == (
        "fundamental_statement_availability.raw_csv_not_available_source"
    )


def test_validate_statement_availability_file_reports_missing_file(tmp_path):
    result = validate_statement_availability_file(
        tmp_path / "missing_fundamental_statement_availability.csv"
    )

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == "fundamental_statement_availability.mapping_file_missing"


def test_allowed_sources_include_statement_retroactive_baseline():
    assert (
        "manual.retroactive_statement_baseline_mapping"
        in STATEMENT_ALLOWED_AVAILABILITY_SOURCES
    )
