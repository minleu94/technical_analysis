from __future__ import annotations

from datetime import date

from data_module.monthly_revenue_availability_builder import (
    build_monthly_revenue_availability_rows,
    load_raw_monthly_revenue_periods,
)


def test_build_monthly_revenue_availability_rows_uses_twse_publication_date() -> None:
    result = build_monthly_revenue_availability_rows(
        [
            {"出表日期": "1150615", "資料年月": "11505", "公司代號": "2330"},
            {"出表日期": "1150615", "資料年月": "11505", "公司代號": "1101"},
        ],
        raw_periods={("2330", "2026-05")},
        fetch_date=date(2026, 6, 16),
    )

    assert result.rows == [
        {
            "stock_code": "2330",
            "period": "2026-05",
            "as_of_date": "2026-05-31",
            "announced_date": "2026-06-15",
            "available_date": "2026-06-16",
            "source": "twse.monthly_revenue_announcement",
            "source_version": "twse-openapi-t187ap05-p-2026-06-16",
        }
    ]
    assert result.skipped_not_in_raw_count == 1
    assert result.diagnostics == ()


def test_build_monthly_revenue_availability_rows_reports_invalid_official_dates() -> None:
    result = build_monthly_revenue_availability_rows(
        [{"出表日期": "bad-date", "資料年月": "11505", "公司代號": "2330"}],
        raw_periods={("2330", "2026-05")},
        fetch_date=date(2026, 6, 16),
    )

    assert result.rows == []
    assert result.diagnostics == (
        "invalid official monthly revenue row; stock_code=2330; field=出表日期",
    )


def test_load_raw_monthly_revenue_periods_reads_local_csv_contract(tmp_path) -> None:
    revenue_file = tmp_path / "2330_monthly_revenue.csv"
    revenue_file.write_text(
        "date,stock_id,country,revenue,revenue_month,revenue_year\n"
        "2026-06-01,2330,Taiwan,100,5,2026\n",
        encoding="utf-8",
    )

    assert load_raw_monthly_revenue_periods(tmp_path) == {("2330", "2026-05")}
