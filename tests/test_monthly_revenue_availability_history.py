from __future__ import annotations

from datetime import date

from data_module.monthly_revenue_availability_history import (
    build_historical_monthly_revenue_availability,
    load_pit_announcement_rows,
    load_official_rows_for_markets,
    parse_mops_monthly_revenue_html,
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


def test_build_history_rows_rejects_unreasonably_late_availability() -> None:
    result = build_historical_monthly_revenue_availability(
        official_rows_by_market={
            "twse": [
                {"資料年月": "2024-04", "公司代號": "2330", "出表日期": "2026-06-17"},
            ],
        },
        raw_periods={("2330", "2024-04")},
        start_period="2024-04",
        end_period="2024-04",
        markets=("twse",),
        fetch_date=date(2026, 6, 17),
    )

    assert result.rows == []
    assert result.missing_availability_count == 1
    assert result.diagnostics[0].code == (
        "monthly_revenue_availability.available_date_unreasonably_late"
    )


def test_parse_mops_html_uses_page_level_announcement_date() -> None:
    html = """
    <html><body>
      <div>出表日期：113/05/10</div>
      <table>
        <tr><th>公司代號</th><th>公司名稱</th><th>當月營收</th></tr>
        <tr><td>2330</td><td>台積電</td><td>236021112</td></tr>
        <tr><td>9935</td><td>慶豐富</td><td>321000</td></tr>
      </table>
    </body></html>
    """

    rows, diagnostics = parse_mops_monthly_revenue_html(
        html,
        market="twse",
        period="2024-04",
    )

    assert diagnostics == ()
    assert rows == [
        {"資料年月": "2024-04", "公司代號": "2330", "出表日期": "2024-05-10"},
        {"資料年月": "2024-04", "公司代號": "9935", "出表日期": "2024-05-10"},
    ]


def test_parse_mops_html_reports_missing_announcement_date() -> None:
    html = """
    <html><body>
      <table>
        <tr><th>公司代號</th><th>公司名稱</th><th>當月營收</th></tr>
        <tr><td>2330</td><td>台積電</td><td>236021112</td></tr>
      </table>
    </body></html>
    """

    rows, diagnostics = parse_mops_monthly_revenue_html(
        html,
        market="twse",
        period="2024-04",
    )

    assert rows == []
    assert diagnostics[0].code == "monthly_revenue_availability.mops_missing_announced_date"


def test_parse_mops_html_handles_multi_row_headers() -> None:
    html = """
    <html><body>
      <div>出表日期：115/06/17</div>
      <table>
        <tr><th colspan="2">&nbsp;</th><th colspan="5">營業收入</th></tr>
        <tr>
          <th>公司<br>代號</th><th>公司名稱</th><th>當月營收</th>
          <th>上月營收</th><th>去年當月營收</th>
        </tr>
        <tr align="right">
          <td align="center">2330</td><td align="left">台積電</td>
          <td nowrap>236,021,112</td><td nowrap>195,210,804</td>
          <td nowrap>147,899,735</td>
        </tr>
      </table>
    </body></html>
    """

    rows, diagnostics = parse_mops_monthly_revenue_html(
        html,
        market="twse",
        period="2024-04",
    )

    assert diagnostics == ()
    assert rows == [
        {"資料年月": "2024-04", "公司代號": "2330", "出表日期": "2026-06-17"}
    ]


def test_parse_mops_html_deduplicates_nested_company_rows() -> None:
    html = """
    <html><body>
      <div>出表日期：113/05/10</div>
      <table>
        <tr><td>
          <table>
            <tr><th>公司<br>代號</th><th>公司名稱</th></tr>
            <tr><td>2330</td><td>台積電</td></tr>
          </table>
        </td></tr>
      </table>
    </body></html>
    """

    rows, diagnostics = parse_mops_monthly_revenue_html(
        html,
        market="twse",
        period="2024-04",
    )

    assert diagnostics == ()
    assert rows == [
        {"資料年月": "2024-04", "公司代號": "2330", "出表日期": "2024-05-10"}
    ]


def test_load_official_rows_for_markets_reads_mops_static_reports(monkeypatch) -> None:
    html = """
    <html><body>
      <div>出表日期：113/05/10</div>
      <table>
        <tr><th>公司代號</th><th>公司名稱</th><th>當月營收</th></tr>
        <tr><td>2330</td><td>台積電</td><td>236021112</td></tr>
      </table>
    </body></html>
    """

    def fake_fetch(*, market: str, period: str) -> str:
        assert market == "twse"
        assert period == "2024-04"
        return html

    monkeypatch.setattr(
        "data_module.monthly_revenue_availability_history."
        "_fetch_mops_static_monthly_revenue_html",
        fake_fetch,
    )

    rows_by_market, diagnostics = load_official_rows_for_markets(
        markets=("twse",),
        mops_static=True,
        start_period="2024-04",
        end_period="2024-04",
    )

    assert diagnostics == ()
    assert rows_by_market["twse"] == [
        {
            "資料年月": "2024-04",
            "公司代號": "2330",
            "出表日期": "2024-05-10",
            "__availability_source": "mops.monthly_revenue_announcement",
            "__source_version_prefix": "mops-t05st10-ifrs",
        }
    ]


def test_load_pit_announcement_rows_accepts_chinese_column_names(tmp_path) -> None:
    pit_csv = tmp_path / "tej_monthly_revenue_pit.csv"
    pit_csv.write_text(
        "公司代號,資料年月,公告日\n"
        "2330,2024-04,2024-05-10\n"
        "3207,11304,113/05/10\n",
        encoding="utf-8-sig",
    )

    rows, diagnostics = load_pit_announcement_rows(
        pit_csv,
        source="tej.monthly_revenue_announcement_pit",
        source_version="tej-pit-export-2026-06-17",
    )

    assert diagnostics == ()
    assert rows == [
        {
            "資料年月": "2024-04",
            "公司代號": "2330",
            "出表日期": "2024-05-10",
            "__availability_source": "tej.monthly_revenue_announcement_pit",
            "__source_version": "tej-pit-export-2026-06-17",
        },
        {
            "資料年月": "2024-04",
            "公司代號": "3207",
            "出表日期": "2024-05-10",
            "__availability_source": "tej.monthly_revenue_announcement_pit",
            "__source_version": "tej-pit-export-2026-06-17",
        },
    ]


def test_load_pit_announcement_rows_reports_missing_source_version(tmp_path) -> None:
    pit_csv = tmp_path / "monthly_revenue_pit.csv"
    pit_csv.write_text(
        "stock_code,period,announced_date\n2330,2024-04,2024-05-10\n",
        encoding="utf-8",
    )

    rows, diagnostics = load_pit_announcement_rows(
        pit_csv,
        source="tej.monthly_revenue_announcement_pit",
        source_version="",
    )

    assert rows == []
    assert diagnostics[0].code == "monthly_revenue_availability.pit_missing_source_version"
