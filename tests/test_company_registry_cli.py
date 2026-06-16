from __future__ import annotations

import csv

from scripts.update_company_registry import main


def test_company_registry_cli_dry_run_does_not_write_output(tmp_path, capsys) -> None:
    output = tmp_path / "companies.csv"

    exit_code = main(
        [
            "--output",
            str(output),
            "--source-json-dir",
            str(_source_json_dir(tmp_path)),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert "ready_for_apply: true" in capsys.readouterr().out
    assert not output.exists()


def test_company_registry_cli_apply_requires_confirm(tmp_path) -> None:
    output = tmp_path / "companies.csv"

    assert (
        main(
            [
                "--output",
                str(output),
                "--source-json-dir",
                str(_source_json_dir(tmp_path)),
                "--apply",
            ]
        )
        == 2
    )


def test_company_registry_cli_apply_writes_after_confirm_and_backs_up(tmp_path) -> None:
    output = tmp_path / "companies.csv"
    output.write_text(
        "industry_category,stock_id,stock_name,type,date,download_time\n"
        "其他,9935,慶豐富,twse,2023-06-30,old\n",
        encoding="utf-8",
    )
    backup_dir = tmp_path / "backup"

    exit_code = main(
        [
            "--output",
            str(output),
            "--backup-dir",
            str(backup_dir),
            "--source-json-dir",
            str(_source_json_dir(tmp_path)),
            "--apply",
            "--confirm",
            "apply-company-registry",
        ]
    )

    assert exit_code == 0
    assert list(backup_dir.glob("companies_company_registry_*.csv"))
    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows == [
        {
            "industry_category": "居家生活",
            "stock_id": "9935",
            "stock_name": "慶豐富",
            "type": "twse",
            "date": "2026-06-15",
            "download_time": "2026-06-16 12:00:00",
        },
        {
            "industry_category": "電子零組件業",
            "stock_id": "3207",
            "stock_name": "耀勝",
            "type": "tpex",
            "date": "2026-06-16",
            "download_time": "2026-06-16 12:00:00",
        },
    ]


def _source_json_dir(tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir(exist_ok=True)
    (source_dir / "twse_listed.json").write_text(
        '[{"出表日期":"1150615","公司代號":"9935","公司簡稱":"慶豐富","產業別":"38"}]',
        encoding="utf-8",
    )
    (source_dir / "tpex_otc.json").write_text(
        '[{"Date":"1150616","SecuritiesCompanyCode":"3207",'
        '"CompanyAbbreviation":"耀勝","SecuritiesIndustryCode":"28"}]',
        encoding="utf-8",
    )
    (source_dir / "tpex_emerging.json").write_text("[]", encoding="utf-8")
    return source_dir
