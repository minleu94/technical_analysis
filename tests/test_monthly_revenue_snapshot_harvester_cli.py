from __future__ import annotations

import csv
import io
import sys

from scripts import fetch_mops_monthly_revenue_snapshot


MOPS_SAMPLE_HTML = """
<html>
  <body>
    <div>出表日期：115/04/10</div>
    <table>
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
    </table>
  </body>
</html>
"""


def test_mops_snapshot_cli_writes_candidate_csv_and_raw_html(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        fetch_mops_monthly_revenue_snapshot,
        "fetch_mops_static_monthly_revenue_html",
        lambda *, market, period: MOPS_SAMPLE_HTML,
    )

    exit_code = fetch_mops_monthly_revenue_snapshot.main(
        [
            "--start-period",
            "2026-03",
            "--end-period",
            "2026-03",
            "--markets",
            "twse",
            "--output-dir",
            str(tmp_path),
            "--fetch-date",
            "2026-06-16",
        ]
    )

    assert exit_code == 0
    csv_path = tmp_path / "mops_monthly_revenue_snapshot_2026-03_2026-03_2026-06-16.csv"
    html_path = tmp_path / "raw_html" / "twse_2026-03.html"
    assert csv_path.exists()
    assert html_path.read_text(encoding="utf-8-sig") == MOPS_SAMPLE_HTML
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    assert rows[0]["stock_code"] == "2330"
    assert rows[0]["source"] == "mops.monthly_revenue_static_snapshot"
    assert "output_csv" in capsys.readouterr().out


def test_mops_snapshot_cli_does_not_crash_when_stdout_cannot_encode_chinese(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        fetch_mops_monthly_revenue_snapshot,
        "fetch_mops_static_monthly_revenue_html",
        lambda *, market, period: MOPS_SAMPLE_HTML,
    )
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)

    exit_code = fetch_mops_monthly_revenue_snapshot.main(
        [
            "--start-period",
            "2026-03",
            "--end-period",
            "2026-03",
            "--markets",
            "twse",
            "--output-dir",
            str(tmp_path),
            "--fetch-date",
            "2026-06-16",
        ]
    )

    assert exit_code == 0
