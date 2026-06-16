from __future__ import annotations

import json

from data_module.fundamental_availability_entrypoint import (
    validate_monthly_revenue_availability_file,
)
from scripts.build_monthly_revenue_availability_history import main


def test_history_cli_summary_only_does_not_write_output(tmp_path, capsys, monkeypatch) -> None:
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "2330_monthly_revenue.csv").write_text(
        "date,stock_id,country,revenue,revenue_month,revenue_year\n"
        "2026-06-01,2330,Taiwan,100,5,2026\n",
        encoding="utf-8",
    )
    source_dir = tmp_path / "official"
    source_dir.mkdir()
    (source_dir / "twse.json").write_text(
        json.dumps(
            [{"資料年月": "11505", "公司代號": "2330", "出表日期": "1150615"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "candidate.csv"
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))

    exit_code = main(
        [
            "--start-period",
            "2026-05",
            "--end-period",
            "2026-05",
            "--markets",
            "twse",
            "--stock-code",
            "2330",
            "--raw-dir",
            str(raw_dir),
            "--source-json-dir",
            str(source_dir),
            "--fetch-date",
            "2026-06-16",
        ]
    )

    assert exit_code == 0
    assert output.exists() is False
    summary = capsys.readouterr().out
    assert "requested_periods: 1" in summary
    assert "matched_raw_monthly_revenue_rows: 1" in summary


def test_history_cli_writes_valid_candidate_when_output_is_specified(
    tmp_path, monkeypatch
) -> None:
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "3207_monthly_revenue.csv").write_text(
        "date,stock_id,country,revenue,revenue_month,revenue_year\n"
        "2026-06-01,3207,Taiwan,100,5,2026\n",
        encoding="utf-8",
    )
    source_dir = tmp_path / "official"
    source_dir.mkdir()
    (source_dir / "tpex.json").write_text(
        json.dumps(
            [{"資料年月": "11505", "公司代號": "3207", "出表日期": "1150616"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "candidate.csv"
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))

    exit_code = main(
        [
            "--start-period",
            "2026-05",
            "--end-period",
            "2026-05",
            "--markets",
            "tpex",
            "--raw-dir",
            str(raw_dir),
            "--source-json-dir",
            str(source_dir),
            "--output",
            str(output),
            "--fetch-date",
            "2026-06-16",
        ]
    )

    assert exit_code == 0
    validation = validate_monthly_revenue_availability_file(output)
    assert validation.valid is True
    assert validation.accepted_count == 1
    assert validation.source_versions == ("tpex-openapi-mopsfin-t187ap05-o-2026-06-16",)


def test_history_cli_writes_mops_html_candidate(tmp_path, monkeypatch) -> None:
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "2330_monthly_revenue.csv").write_text(
        "date,stock_id,country,revenue,revenue_month,revenue_year\n"
        "2024-05-01,2330,Taiwan,100,4,2024\n",
        encoding="utf-8",
    )
    html_dir = tmp_path / "mops"
    html_dir.mkdir()
    (html_dir / "twse_2024-04.html").write_text(
        """
        <html><body>
          <div>出表日期：113/05/10</div>
          <table>
            <tr><th>公司代號</th><th>公司名稱</th><th>當月營收</th></tr>
            <tr><td>2330</td><td>台積電</td><td>236021112</td></tr>
          </table>
        </body></html>
        """,
        encoding="utf-8",
    )
    output = tmp_path / "candidate.csv"
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))

    exit_code = main(
        [
            "--start-period",
            "2024-04",
            "--end-period",
            "2024-04",
            "--markets",
            "twse",
            "--raw-dir",
            str(raw_dir),
            "--mops-html-dir",
            str(html_dir),
            "--output",
            str(output),
            "--fetch-date",
            "2026-06-16",
        ]
    )

    assert exit_code == 0
    validation = validate_monthly_revenue_availability_file(output)
    assert validation.valid is True
    assert validation.accepted_count == 1
    assert validation.source_versions == ("mops-t05st10-ifrs-2026-06-16",)
