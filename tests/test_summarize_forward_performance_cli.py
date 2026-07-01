from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from tests.test_forward_performance_read_model import _event, _outcome, _repo


def _run_cli(db_path: Path, *args: str) -> dict[str, object]:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/summarize_forward_performance.py",
            "--db-path",
            str(db_path),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_cli_json_output_is_deterministic(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.insert_event(_event("evt-1", regime="Trend"))
    repo.upsert_outcome(_outcome("evt-1", window_days=5, forward_return_bp=100))

    first = _run_cli(repo.db_path, "--group-by", "event_type", "--window", "5", "--json-output")
    second = _run_cli(repo.db_path, "--group-by", "event_type", "--window", "5", "--json-output")

    assert first == second
    assert first["summary_count"] == 1
    summary = first["summaries"][0]  # type: ignore[index]
    assert summary["group_key"] == "recommendation_included"
    assert summary["sample_size"] == 1
    assert summary["positive_rate_bp"] == 10000


def test_cli_filters_and_groups_by_regime(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.insert_event(_event("evt-1", regime="Trend", sector="半導體"))
    repo.insert_event(_event("evt-2", regime="Range", sector="金融"))
    repo.upsert_outcome(_outcome("evt-1", forward_return_bp=100))
    repo.upsert_outcome(_outcome("evt-2", forward_return_bp=200))

    payload = _run_cli(repo.db_path, "--group-by", "regime", "--sector", "半導體")

    assert payload["summary_count"] == 1
    summary = payload["summaries"][0]  # type: ignore[index]
    assert summary["group_key"] == "Trend"
    assert summary["mean_forward_return_bp"] == 100


def test_cli_writes_csv_summary(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.insert_event(_event("evt-1"))
    repo.upsert_outcome(_outcome("evt-1", forward_return_bp=100))
    csv_path = tmp_path / "summary.csv"

    payload = _run_cli(repo.db_path, "--group-by", "score_percentile_bucket", "--csv-output", str(csv_path))

    assert payload["summary_count"] == 1
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "score_percentile_bucket" in csv_text
    assert "8001-10000" in csv_text


def test_cli_text_has_no_trading_language_or_ui_import() -> None:
    script_text = Path("scripts/summarize_forward_performance.py").read_text(encoding="utf-8").lower()

    assert "target price" not in script_text
    assert "fair price" not in script_text
    assert "high confidence" not in script_text
    assert "ui_qt" not in script_text
