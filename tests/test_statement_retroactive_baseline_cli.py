from __future__ import annotations

from data_module.fundamental_statement_availability_entrypoint import (
    validate_statement_availability_file,
)
from scripts.build_statement_retroactive_baseline_mapping import main


def test_statement_retroactive_baseline_cli_writes_valid_candidate(tmp_path, capsys):
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "2330_income_statement.csv").write_text(
        "date,stock_id,type,value,origin_name\n"
        "2024-03-31,2330,EPS,2.30,基本每股盈餘（元）\n"
        "2024-03-31,2330,Revenue,1000,營業收入\n"
        "2024-03-31,2330,EPS,2.30,基本每股盈餘（元）\n",
        encoding="utf-8-sig",
    )
    (raw_dir / "2330_balance_sheet.csv").write_text(
        "date,stock_id,type,value,origin_name\n"
        "2024-03-31,2330,Equity,10000,權益總計\n",
        encoding="utf-8-sig",
    )
    output = tmp_path / "statement_availability.csv"

    exit_code = main(
        [
            "--raw-dir",
            str(raw_dir),
            "--available-date",
            "2026-06-17",
            "--source-version",
            "statement-retroactive-baseline-2026-06-17",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    summary = capsys.readouterr().out
    assert "raw_row_count: 4" in summary
    assert "candidate_row_count: 2" in summary
    assert "duplicate_raw_period_rows: 2" in summary
    validation = validate_statement_availability_file(output)
    assert validation.valid is True
    assert validation.accepted_count == 2
    text = output.read_text(encoding="utf-8-sig")
    assert "manual.retroactive_statement_baseline_mapping" in text
    assert "2330,income_statement,2024-Q1,2024-03-31,,2026-06-17" in text


def test_statement_retroactive_baseline_cli_filters_statement_types(tmp_path, capsys):
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "2330_income_statement.csv").write_text(
        "date,stock_id,type,value,origin_name\n"
        "2024-03-31,2330,EPS,2.30,基本每股盈餘（元）\n",
        encoding="utf-8-sig",
    )
    (raw_dir / "2330_balance_sheet.csv").write_text(
        "date,stock_id,type,value,origin_name\n"
        "2024-03-31,2330,Equity,10000,權益總計\n",
        encoding="utf-8-sig",
    )

    exit_code = main(
        [
            "--raw-dir",
            str(raw_dir),
            "--statement-types",
            "income_statement",
            "--available-date",
            "2026-06-17",
            "--source-version",
            "statement-retroactive-baseline-2026-06-17",
        ]
    )

    assert exit_code == 0
    assert "candidate_row_count: 1" in capsys.readouterr().out
