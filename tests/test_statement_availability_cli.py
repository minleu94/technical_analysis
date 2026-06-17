from __future__ import annotations

from scripts.validate_statement_availability import main


def test_statement_availability_cli_exits_zero_for_valid_mapping(tmp_path, capsys):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text(
        "stock_code,statement_type,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,income_statement,2024-Q1,2024-03-31,,2026-06-17,"
        "manual.retroactive_statement_baseline_mapping,statement-retroactive-baseline-2026-06-17\n",
        encoding="utf-8-sig",
    )

    assert main(["--path", str(mapping_file)]) == 0
    assert "valid: true" in capsys.readouterr().out


def test_statement_availability_cli_exits_nonzero_for_invalid_mapping(tmp_path, capsys):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text("stock_code,period\n2330,2024-Q1\n", encoding="utf-8")

    assert main(["--path", str(mapping_file)]) == 1
    assert "valid: false" in capsys.readouterr().out
