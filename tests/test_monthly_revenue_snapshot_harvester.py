from __future__ import annotations

from datetime import date

from data_module.monthly_revenue_snapshot_harvester import (
    build_mops_monthly_revenue_snapshot,
    parse_mops_monthly_revenue_snapshot_html,
)


MOPS_SAMPLE_HTML = """
<html>
  <body>
    <div>出表日期：115/04/10</div>
    <table>
      <tr><td>產業別</td><td>半導體業</td></tr>
      <tr>
        <th>公司代號</th><th>公司名稱</th><th>當月營收</th><th>上月營收</th>
        <th>去年當月營收</th><th>上月比較增減(%)</th><th>去年同月增減(%)</th>
        <th>當月累計營收</th><th>去年累計營收</th><th>前期比較增減(%)</th><th>備註</th>
      </tr>
      <tr>
        <td>2330</td><td>台積電</td><td>195,211,000</td><td>180,000,000</td>
        <td>160,000,000</td><td>8.45</td><td>22.00</td>
        <td>580,000,000</td><td>500,000,000</td><td>16.00</td><td></td>
      </tr>
      <tr>
        <td>合計</td><td></td><td>195,211,000</td>
      </tr>
    </table>
  </body>
</html>
"""


def test_parse_mops_snapshot_extracts_full_revenue_rows_without_available_date() -> None:
    rows, diagnostics = parse_mops_monthly_revenue_snapshot_html(
        MOPS_SAMPLE_HTML,
        market="twse",
        period="2026-03",
        fetched_at="2026-06-16T01:02:03Z",
        source_version="mops-static-2026-06-16",
    )

    assert diagnostics == ()
    assert len(rows) == 1
    row = rows[0]
    assert row["market"] == "twse"
    assert row["period"] == "2026-03"
    assert row["stock_code"] == "2330"
    assert row["company_name"] == "台積電"
    assert row["current_month_revenue"] == "195211000"
    assert row["previous_month_revenue"] == "180000000"
    assert row["previous_year_month_revenue"] == "160000000"
    assert row["mom_pct"] == "8.45"
    assert row["yoy_pct"] == "22.00"
    assert row["cumulative_revenue"] == "580000000"
    assert row["previous_year_cumulative_revenue"] == "500000000"
    assert row["cumulative_yoy_pct"] == "16.00"
    assert row["source"] == "mops.monthly_revenue_static_snapshot"
    assert "available_date" not in row


def test_parse_mops_snapshot_reports_diagnostic_when_headers_shift() -> None:
    html = "<html><body><table><tr><th>公司代號</th><th>公司名稱</th></tr><tr><td>2330</td><td>台積電</td></tr></table></body></html>"

    rows, diagnostics = parse_mops_monthly_revenue_snapshot_html(
        html,
        market="twse",
        period="2026-03",
        fetched_at="2026-06-16T01:02:03Z",
        source_version="mops-static-2026-06-16",
    )

    assert rows == []
    assert diagnostics
    assert diagnostics[0].code == "monthly_revenue_snapshot.mops_missing_required_columns"


def test_parse_mops_snapshot_deduplicates_repeated_company_rows() -> None:
    duplicated_html = MOPS_SAMPLE_HTML.replace(
        "</table>",
        """
      <tr>
        <td>2330</td><td>台積電</td><td>195,211,000</td><td>180,000,000</td>
        <td>160,000,000</td><td>8.45</td><td>22.00</td>
        <td>580,000,000</td><td>500,000,000</td><td>16.00</td><td></td>
      </tr>
    </table>
""",
    )

    rows, diagnostics = parse_mops_monthly_revenue_snapshot_html(
        duplicated_html,
        market="twse",
        period="2026-03",
        fetched_at="2026-06-16T01:02:03Z",
        source_version="mops-static-2026-06-16",
    )

    assert diagnostics == ()
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "2330"


def test_build_mops_snapshot_fetches_markets_and_periods_with_summary() -> None:
    calls: list[tuple[str, str]] = []
    sleeps: list[float] = []

    def fake_fetch(*, market: str, period: str) -> str:
        calls.append((market, period))
        return MOPS_SAMPLE_HTML

    result = build_mops_monthly_revenue_snapshot(
        start_period="2026-03",
        end_period="2026-04",
        markets=("twse",),
        fetch_date=date(2026, 6, 16),
        fetch_html=fake_fetch,
        sleep_seconds=0.25,
        sleep=sleeps.append,
    )

    assert calls == [("twse", "2026-03"), ("twse", "2026-04")]
    assert sleeps == [0.25]
    assert len(result.rows) == 2
    assert result.requested_periods == ("2026-03", "2026-04")
    assert result.fetched_periods == ("2026-03", "2026-04")
    assert "parsed_rows: 2" in result.to_markdown()
