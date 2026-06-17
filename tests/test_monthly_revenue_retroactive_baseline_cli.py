from __future__ import annotations

from data_module.fundamental_availability_entrypoint import (
    validate_monthly_revenue_availability_file,
)
from scripts.build_monthly_revenue_retroactive_baseline_mapping import main


def _write_snapshot(path) -> None:
    path.write_text(
        "market,period,stock_code,company_name,current_month_revenue,"
        "previous_month_revenue,previous_year_month_revenue,mom_pct,yoy_pct,"
        "cumulative_revenue,previous_year_cumulative_revenue,cumulative_yoy_pct,"
        "note,fetched_at,source,source_version\n"
        "twse,2024-04,2330,台積電,236021112,195211222,147900000,20.91,59.58,"
        "828665331,650000000,27.49,,2026-06-16T00:00:00Z,"
        "mops.monthly_revenue_static_snapshot,mops-static-2026-06-16\n"
        "twse,2024-04,2330,台積電,236021112,195211222,147900000,20.91,59.58,"
        "828665331,650000000,27.49,,2026-06-16T00:00:00Z,"
        "mops.monthly_revenue_static_snapshot,mops-static-2026-06-16\n"
        "tpex,2026-05,3207,耀勝,144081,120000,100000,20.07,44.08,"
        "600000,500000,20.0,,2026-06-16T00:00:00Z,"
        "mops.monthly_revenue_static_snapshot,mops-static-2026-06-16\n",
        encoding="utf-8-sig",
    )


def test_retroactive_baseline_cli_writes_valid_candidate_mapping(tmp_path, capsys):
    snapshot = tmp_path / "mops_snapshot.csv"
    output = tmp_path / "retroactive_mapping.csv"
    _write_snapshot(snapshot)

    exit_code = main(
        [
            "--snapshot-file",
            str(snapshot),
            "--available-date",
            "2026-06-17",
            "--source-version",
            "mops-retroactive-baseline-2026-06-17",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    summary = capsys.readouterr().out
    assert "snapshot_row_count: 3" in summary
    assert "candidate_row_count: 2" in summary
    assert "duplicate_snapshot_rows: 1" in summary

    validation = validate_monthly_revenue_availability_file(output)
    assert validation.valid is True
    assert validation.accepted_count == 2
    assert validation.source_versions == ("mops-retroactive-baseline-2026-06-17",)
    text = output.read_text(encoding="utf-8-sig")
    assert "manual.retroactive_baseline_mapping" in text
    assert "2330,2024-04,2024-04-30,,2026-06-17" in text


def test_retroactive_baseline_cli_summary_only_does_not_write_output(tmp_path, capsys):
    snapshot = tmp_path / "mops_snapshot.csv"
    _write_snapshot(snapshot)

    exit_code = main(
        [
            "--snapshot-file",
            str(snapshot),
            "--available-date",
            "2026-06-17",
            "--source-version",
            "mops-retroactive-baseline-2026-06-17",
        ]
    )

    assert exit_code == 0
    assert "candidate_row_count: 2" in capsys.readouterr().out
    assert not (tmp_path / "retroactive_mapping.csv").exists()


def test_retroactive_baseline_cli_filters_period_range(tmp_path, capsys):
    snapshot = tmp_path / "mops_snapshot.csv"
    output = tmp_path / "retroactive_mapping.csv"
    _write_snapshot(snapshot)

    exit_code = main(
        [
            "--snapshot-file",
            str(snapshot),
            "--start-period",
            "2014-04",
            "--end-period",
            "2026-04",
            "--available-date",
            "2026-06-17",
            "--source-version",
            "mops-retroactive-baseline-2026-06-17",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert "candidate_row_count: 1" in capsys.readouterr().out
    text = output.read_text(encoding="utf-8-sig")
    assert "2330,2024-04" in text
    assert "3207,2026-05" not in text
