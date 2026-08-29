from __future__ import annotations

from scripts.backfill_fundamental_statement_items import main


def test_statement_backfill_cli_dry_run_reports_plan(tmp_path, capsys):
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "2330_income_statement.csv").write_text(
        "date,stock_id,type,value,origin_name\n"
        "2024-03-31,2330,EPS,2.30,基本每股盈餘（元）\n",
        encoding="utf-8-sig",
    )
    availability_file = tmp_path / "statement_availability.csv"
    availability_file.write_text(
        "stock_code,statement_type,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,income_statement,2024-Q1,2024-03-31,,2026-06-17,"
        "manual.retroactive_statement_baseline_mapping,statement-retroactive-baseline-2026-06-17\n",
        encoding="utf-8-sig",
    )

    exit_code = main(
        [
            "--raw-dir",
            str(raw_dir),
            "--availability-file",
            str(availability_file),
            "--statement-types",
            "income_statement",
            "--source-version",
            "financial-data-statements-v1",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "ready_for_apply: true" in output
    assert "normalized_record_count: 1" in output
    assert "diagnostics: 0" in output
    assert "quality_counts: degraded=1" in output


def test_statement_backfill_cli_combines_repeated_availability_files(tmp_path, capsys):
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "2330_income_statement.csv").write_text(
        "date,stock_id,type,value,origin_name\n"
        "2024-03-31,2330,EPS,2.30,基本每股盈餘（元）\n"
        "2024-06-30,2330,EPS,2.40,基本每股盈餘（元）\n",
        encoding="utf-8-sig",
    )
    first_file = tmp_path / "statement_availability_q1.csv"
    second_file = tmp_path / "statement_availability_q2.csv"
    header = (
        "stock_code,statement_type,period,as_of_date,announced_date,available_date,"
        "source,source_version\n"
    )
    first_file.write_text(
        header
        + "2330,income_statement,2024-Q1,2024-03-31,,2026-06-17,"
        "manual.retroactive_statement_baseline_mapping,statement-retroactive-baseline-2026-06-17\n",
        encoding="utf-8-sig",
    )
    second_file.write_text(
        header
        + "2330,income_statement,2024-Q2,2024-06-30,,2026-06-17,"
        "manual.retroactive_statement_baseline_mapping,statement-retroactive-baseline-2026-06-17\n",
        encoding="utf-8-sig",
    )

    exit_code = main(
        [
            "--raw-dir",
            str(raw_dir),
            "--availability-file",
            str(first_file),
            "--availability-file",
            str(second_file),
            "--statement-types",
            "income_statement",
            "--source-version",
            "financial-data-statements-v1",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "ready_for_apply: true" in output
    assert "availability_file_count: 2" in output
    assert "normalized_record_count: 2" in output
    assert "diagnostics: 0" in output
    assert "quality_counts: degraded=2" in output


def test_statement_backfill_cli_apply_requires_confirm(tmp_path, capsys):
    exit_code = main(["--apply"])

    assert exit_code == 2
    assert "requires --confirm apply-statement-items-backfill" in capsys.readouterr().out


def test_statement_backfill_cli_dry_run_bounds_missing_availability_output(tmp_path, capsys):
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "2330_income_statement.csv").write_text(
        "date,stock_id,type,value,origin_name\n"
        "2024-03-31,2330,EPS,2.30,基本每股盈餘（元）\n"
        "2024-06-30,2330,EPS,2.40,基本每股盈餘（元）\n",
        encoding="utf-8-sig",
    )
    availability_file = tmp_path / "statement_availability.csv"
    availability_file.write_text(
        "stock_code,statement_type,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,income_statement,2024-Q1,2024-03-31,,2026-06-17,"
        "manual.retroactive_statement_baseline_mapping,statement-retroactive-baseline-2026-06-17\n",
        encoding="utf-8-sig",
    )

    exit_code = main(
        [
            "--raw-dir",
            str(raw_dir),
            "--availability-file",
            str(availability_file),
            "--statement-types",
            "income_statement",
            "--source-version",
            "financial-data-statements-v1",
            "--dry-run",
        ]
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "normalized_record_count: 1" in output
    assert "diagnostics: 1" in output
    assert "missing_availability_count: 1" in output
    assert output.count("fundamental_availability.missing_available_date:") == 1
