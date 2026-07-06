from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from tests.test_evidence_pipeline_runner import _config, _seed_recommendation
from tests.test_evidence_pipeline_smoke import _seed_market_db


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/replay_historical_evidence_pipeline.py", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_replay_cli_defaults_to_dry_run_and_outputs_json(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config, days=3)
    _seed_recommendation(config, result_id="cli-rec")
    replay_db = tmp_path / "replay" / "historical.db"

    completed = _run(
        "--start-date",
        "2026-07-01",
        "--end-date",
        "2026-07-02",
        "--source-db-path",
        str(config.db_file),
        "--replay-db-path",
        str(replay_db),
        "--data-root",
        str(config.data_root),
        "--output-root",
        str(config.output_root),
        "--sources",
        "recommendation",
        "--windows",
        "1",
        "--json-output",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["dry_run"] is True
    assert payload["replay_mode"] == "historical_replay"
    assert payload["source_label"] == "simulated_scheduler"
    assert payload["outcome_mode"] == "final"
    assert payload["final_outcome_summary"]["dry_run"] is True
    assert payload["totals"]["days"] == 2
    assert payload["days"][0]["selected_recommendation_result_id"] == "cli-rec"


def test_replay_cli_rejects_same_source_and_replay_db(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config, days=1)

    completed = _run(
        "--start-date",
        "2026-07-01",
        "--end-date",
        "2026-07-01",
        "--source-db-path",
        str(config.db_file),
        "--replay-db-path",
        str(config.db_file),
        "--data-root",
        str(config.data_root),
        "--output-root",
        str(config.output_root),
    )

    assert completed.returncode != 0
    assert "replay DB must be separate" in completed.stderr


def test_replay_cli_writes_markdown_report(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config, days=2)
    _seed_recommendation(config, result_id="cli-rec")
    replay_db = tmp_path / "replay" / "historical.db"
    report_path = tmp_path / "report.md"

    completed = _run(
        "--start-date",
        "2026-07-01",
        "--end-date",
        "2026-07-01",
        "--source-db-path",
        str(config.db_file),
        "--replay-db-path",
        str(replay_db),
        "--data-root",
        str(config.data_root),
        "--output-root",
        str(config.output_root),
        "--sources",
        "recommendation",
        "--windows",
        "1",
        "--report-output",
        str(report_path),
    )

    assert completed.returncode == 0, completed.stderr
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "Historical Evidence Replay Report" in report_text
    assert "production scheduler" in report_text
