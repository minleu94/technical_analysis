from __future__ import annotations

import json

from data_module.fundamental_availability_entrypoint import (
    validate_monthly_revenue_availability_file,
)
from scripts.build_monthly_revenue_availability import main


def test_build_monthly_revenue_availability_cli_writes_valid_candidate(
    tmp_path, monkeypatch
) -> None:
    raw_dir = tmp_path / "financial_data"
    raw_dir.mkdir()
    (raw_dir / "2330_monthly_revenue.csv").write_text(
        "date,stock_id,country,revenue,revenue_month,revenue_year\n"
        "2026-06-01,2330,Taiwan,100,5,2026\n",
        encoding="utf-8",
    )
    source_json = tmp_path / "twse_monthly_revenue.json"
    source_json.write_text(
        json.dumps(
            [{"出表日期": "1150615", "資料年月": "11505", "公司代號": "2330"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "monthly_revenue_availability.csv"

    monkeypatch.setenv("DATA_ROOT", str(tmp_path))

    exit_code = main(
        [
            "--source-json",
            str(source_json),
            "--raw-dir",
            str(raw_dir),
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
    assert validation.source_versions == ("twse-openapi-t187ap05-p-2026-06-16",)
