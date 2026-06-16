from datetime import date

from data_module.fundamental_availability_sources import (
    MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
    load_monthly_revenue_availability_overrides_csv,
    load_monthly_revenue_availability_overrides,
)
from decision_module.factors.factor_dtos import FactorQuality


def test_load_monthly_revenue_availability_overrides_preserves_announcement_contract():
    result = load_monthly_revenue_availability_overrides(
        [
            {
                "stock_code": "2330",
                "period": "2026-05",
                "as_of_date": "2026-05-31",
                "announced_date": "2026-06-10",
                "available_date": "2026-06-11",
                "source": "manual.twse_monthly_revenue_announcement_log",
                "source_version": "announcement-log-2026-06-16",
            }
        ]
    )

    override = result.overrides[("2330", "2026-05")]

    assert override.stock_code == "2330"
    assert override.period == "2026-05"
    assert override.as_of_date == date(2026, 5, 31)
    assert override.announced_date == date(2026, 6, 10)
    assert override.available_date == date(2026, 6, 11)
    assert override.quality == FactorQuality.OBSERVED
    assert override.source == "manual.twse_monthly_revenue_announcement_log"
    assert override.source_version == "announcement-log-2026-06-16"
    assert result.diagnostics == ()


def test_load_monthly_revenue_availability_overrides_degrades_missing_announcement():
    result = load_monthly_revenue_availability_overrides(
        [
            {
                "stock_code": "2330",
                "period": "2026-05",
                "as_of_date": "2026-05-31",
                "announced_date": "",
                "available_date": "2026-06-11",
                "source": "manual.available_date_mapping",
                "source_version": "announcement-log-2026-06-16",
            }
        ]
    )

    override = result.overrides[("2330", "2026-05")]

    assert override.announced_date is None
    assert override.available_date == date(2026, 6, 11)
    assert override.quality == FactorQuality.DEGRADED
    assert result.diagnostics[0].code == "fundamental_availability.missing_announced_date"


def test_load_monthly_revenue_availability_overrides_rejects_missing_available_date():
    result = load_monthly_revenue_availability_overrides(
        [
            {
                "stock_code": "2330",
                "period": "2026-05",
                "as_of_date": "2026-05-31",
                "announced_date": "2026-06-10",
                "available_date": "",
                "source": "manual.available_date_mapping",
                "source_version": "announcement-log-2026-06-16",
            }
        ]
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_availability.missing_available_date"


def test_load_monthly_revenue_availability_overrides_rejects_raw_csv_date_as_source():
    result = load_monthly_revenue_availability_overrides(
        [
            {
                "stock_code": "2330",
                "period": "2026-05",
                "as_of_date": "2026-05-31",
                "announced_date": "",
                "available_date": "2026-06-10",
                "source": "financial_data.monthly_revenue_csv",
                "source_version": "financial-data-csv-preflight-v1",
            }
        ]
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_availability.raw_csv_not_available_source"


def test_load_monthly_revenue_availability_overrides_csv_reads_governed_file(tmp_path):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        ",".join(MONTHLY_REVENUE_AVAILABILITY_COLUMNS)
        + "\n"
        + (
            "2330,2026-05,2026-05-31,2026-06-10,2026-06-11,"
            "manual.twse_monthly_revenue_announcement_log,announcement-log-2026-06-16\n"
        ),
        encoding="utf-8-sig",
    )

    result = load_monthly_revenue_availability_overrides_csv(mapping_file)

    override = result.overrides[("2330", "2026-05")]
    assert override.announced_date == date(2026, 6, 10)
    assert override.available_date == date(2026, 6, 11)
    assert override.quality == FactorQuality.OBSERVED
    assert result.diagnostics == ()


def test_load_monthly_revenue_availability_overrides_csv_reports_missing_file(tmp_path):
    result = load_monthly_revenue_availability_overrides_csv(
        tmp_path / "missing_monthly_revenue_availability.csv"
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_availability.mapping_file_missing"


def test_load_monthly_revenue_availability_overrides_csv_reports_missing_columns(tmp_path):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text("stock_code,period\n2330,2026-05\n", encoding="utf-8")

    result = load_monthly_revenue_availability_overrides_csv(mapping_file)

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_availability.mapping_missing_columns"
