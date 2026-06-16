from __future__ import annotations

import csv

from scripts import fetch_finmind_monthly_revenue_create_time


def test_finmind_create_time_cli_writes_candidate_rows_and_groups(tmp_path, monkeypatch) -> None:
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "2330_monthly_revenue.csv").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        fetch_finmind_monthly_revenue_create_time,
        "load_finmind_token",
        lambda token_file=None: "secret-token",
    )
    monkeypatch.setattr(
        fetch_finmind_monthly_revenue_create_time,
        "fetch_finmind_monthly_revenue_rows",
        lambda stock_code, start_date, end_date, token: [
            {
                "stock_id": stock_code,
                "date": "2026-04-01",
                "revenue_year": 2026,
                "revenue_month": 4,
                "revenue": 195211000,
                "create_time": "2026-05-08",
            }
        ],
    )

    output_dir = tmp_path / "out"
    exit_code = fetch_finmind_monthly_revenue_create_time.main(
        [
            "--start-date",
            "2026-04-01",
            "--end-date",
            "2026-05-31",
            "--raw-dir",
            str(raw_dir),
            "--output-dir",
            str(output_dir),
            "--max-requests-per-hour",
            "0",
            "--fetch-date",
            "2026-06-16",
        ]
    )

    assert exit_code == 0
    rows_path = output_dir / "finmind_monthly_revenue_create_time_2026-06-16.csv"
    groups_path = output_dir / "finmind_create_time_groups_2026-06-16.csv"
    assert rows_path.exists()
    assert groups_path.exists()
    rows = list(csv.DictReader(rows_path.open(encoding="utf-8-sig")))
    groups = list(csv.DictReader(groups_path.open(encoding="utf-8-sig")))
    assert rows[0]["stock_code"] == "2330"
    assert rows[0]["source"] == "finmind.monthly_revenue_create_time"
    assert groups[0]["stock_codes"] == "2330"
