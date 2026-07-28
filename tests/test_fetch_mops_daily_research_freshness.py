from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_module.mops_ezsearch_statement_availability import (
    MOPS_MARKETS,
    MOPS_STATEMENT_ITEMS,
)
from scripts.fetch_mops_daily_research_freshness import main


def _fixture(path: Path) -> None:
    payload = [
        {
            "market": market,
            "announcement_item": item,
            "rows": [],
            "response_sha256": "a" * 64,
            "source_status": "success",
        }
        for market in MOPS_MARKETS
        for item in MOPS_STATEMENT_ITEMS
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_offline_fixture_mode_executes_without_live_name_error(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    _fixture(fixture_path)

    exit_code = main(
        [
            "--start-date",
            "2026-07-27",
            "--end-date",
            "2026-07-27",
            "--output-root",
            str(tmp_path / "output"),
            "--fixture-file",
            str(fixture_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "output" / "latest_sanitized_projection.json").is_file()


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--confirm-live-readonly"],
        ["--live", "--confirm-live-readonly", "--fixture-file", "fixture.json"],
        ["--timeout-seconds", "0"],
        ["--prior-artifact", "prior.json"],
    ],
)
def test_incompatible_or_invalid_cli_flags_fail_closed(
    tmp_path: Path,
    extra_args: list[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--start-date",
                "2026-07-27",
                "--end-date",
                "2026-07-27",
                "--output-root",
                str(tmp_path / "output"),
                *extra_args,
            ]
        )

    assert exc_info.value.code == 2
