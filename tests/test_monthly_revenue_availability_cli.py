from scripts.validate_monthly_revenue_availability import main


def test_monthly_revenue_availability_cli_exits_zero_for_valid_mapping(tmp_path, capsys):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2026-05,2026-05-31,2026-06-10,2026-06-11,"
        "manual.twse_monthly_revenue_announcement_log,announcement-log-2026-06-16\n",
        encoding="utf-8-sig",
    )

    assert main(["--path", str(mapping_file)]) == 0
    assert "valid: true" in capsys.readouterr().out


def test_monthly_revenue_availability_cli_exits_nonzero_for_invalid_mapping(tmp_path, capsys):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text("stock_code,period\n2330,2026-05\n", encoding="utf-8")

    assert main(["--path", str(mapping_file)]) == 1
    assert "valid: false" in capsys.readouterr().out
