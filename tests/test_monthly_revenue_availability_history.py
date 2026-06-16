from __future__ import annotations

from datetime import date

from data_module.monthly_revenue_availability_history import (
    build_historical_monthly_revenue_availability,
    parse_announcement_date,
    parse_revenue_period,
)


def test_parse_revenue_period_accepts_roc_and_western_formats() -> None:
    assert parse_revenue_period("11505") == "2026-05"
    assert parse_revenue_period("115/05") == "2026-05"
    assert parse_revenue_period("2026-05") == "2026-05"
    assert parse_revenue_period("2026/05") == "2026-05"


def test_parse_announcement_date_accepts_roc_and_western_formats() -> None:
    assert parse_announcement_date("1150615") == date(2026, 6, 15)
    assert parse_announcement_date("115/06/15") == date(2026, 6, 15)
    assert parse_announcement_date("2026-06-15") == date(2026, 6, 15)
    assert parse_announcement_date("2026/06/15") == date(2026, 6, 15)


def test_build_history_rows_requires_announcement_date() -> None:
    result = build_historical_monthly_revenue_availability(
        official_rows_by_market={
            "twse": [
                {"資料年月": "11505", "公司代號": "2330", "出表日期": ""},
            ]
        },
        raw_periods={("2330", "2026-05")},
        start_period="2026-05",
        end_period="2026-05",
        markets=("twse",),
        fetch_date=date(2026, 6, 16),
    )

    assert result.rows == []
    assert result.missing_availability_count == 1
    assert result.diagnostics_by_source["twse"] == 1
    assert result.diagnostics[0].code == "monthly_revenue_availability.missing_announced_date"


def test_build_history_rows_keeps_twse_and_tpex_sources_distinct() -> None:
    result = build_historical_monthly_revenue_availability(
        official_rows_by_market={
            "twse": [
                {"資料年月": "11505", "公司代號": "2330", "出表日期": "1150615"},
            ],
            "tpex": [
                {"資料年月": "11505", "公司代號": "3207", "出表日期": "2026/06/16"},
            ],
        },
        raw_periods={("2330", "2026-05"), ("3207", "2026-05")},
        start_period="2026-05",
        end_period="2026-05",
        markets=("twse", "tpex"),
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
            "source_version": "twse-openapi-t187ap05-l-2026-06-16",
        },
        {
            "stock_code": "3207",
            "period": "2026-05",
            "as_of_date": "2026-05-31",
            "announced_date": "2026-06-16",
            "available_date": "2026-06-17",
            "source": "tpex.monthly_revenue_announcement",
            "source_version": "tpex-openapi-mopsfin-t187ap05-o-2026-06-16",
        },
    ]
    assert result.requested_periods == ("2026-05",)
    assert result.fetched_periods == ("2026-05",)
    assert result.matched_raw_monthly_revenue_rows == 2
    assert result.missing_availability_count == 0
    assert result.duplicate_mapping_rows == 0
