import json
import subprocess
import sys
from pathlib import Path


def test_workbench_prototype_cli_outputs_sample_json() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v2_workbench_prototype.py",
            "--sample",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    payload = json.loads(result.stdout)

    assert payload["source_mode"] == "sample_only"
    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["access_boundary"]["production_scheduler_allowed"] is False
    assert payload["review_items"]


def test_workbench_prototype_cli_outputs_markdown_boundary_text() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v2_workbench_prototype.py",
            "--sample",
            "--format",
            "markdown",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert "# V2.0 Unified Decision Workbench Prototype" in result.stdout
    assert "production_scheduler_allowed: `false`" in result.stdout
    assert "不是交易建議" in result.stdout


def test_workbench_prototype_cli_reads_replay_summary_as_simulated_input(tmp_path: Path) -> None:
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(
        json.dumps(
            {
                "replay_mode": "historical_replay",
                "source_label": "simulated_scheduler",
                "start_date": "2026-01-06",
                "end_date": "2026-07-06",
                "totals": {"days": 118, "events_seen": 118056, "outcomes_created": 472224},
                "final_outcome_summary": {"missing_benchmark": 0, "missing_industry_benchmark": 378491},
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v2_workbench_prototype.py",
            "--sample",
            "--format",
            "json",
            "--replay-summary-json",
            str(replay_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    payload = json.loads(result.stdout)
    evidence_ids = {item["item_id"] for item in payload["evidence_summary"]}

    assert payload["source_mode"] == "sample_plus_historical_replay"
    assert "historical_replay" in evidence_ids
    assert any("simulated_scheduler" in warning for warning in payload["warnings"])


def test_workbench_prototype_cli_markdown_includes_replay_diagnostics(tmp_path: Path) -> None:
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(
        json.dumps(
            {
                "replay_mode": "historical_replay",
                "source_label": "simulated_scheduler",
                "totals": {"days": 118, "events_seen": 118056, "outcomes_created": 472224},
                "final_outcome_summary": {
                    "ready": 380736,
                    "pending_insufficient_future_data": 91488,
                    "missing_benchmark": 0,
                    "missing_industry_benchmark": 378491,
                },
                "days": [{"diagnostics": ["source_missing_screening_matrix"]}],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v2_workbench_prototype.py",
            "--sample",
            "--format",
            "markdown",
            "--replay-summary-json",
            str(replay_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert "diagnostics:" in result.stdout
    assert "simulated_scheduler" in result.stdout
    assert "source_gap:source_missing_screening_matrix" in result.stdout
    assert "benchmark_coverage:covered=472224,total=472224,missing=0" in result.stdout
    assert "pending_future_data:91488" in result.stdout


def test_workbench_prototype_cli_writes_requested_output_only(tmp_path: Path) -> None:
    output_path = tmp_path / "workbench.json"
    untouched_db = tmp_path / "evidence.db"

    subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v2_workbench_prototype.py",
            "--sample",
            "--format",
            "json",
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert output_path.exists()
    assert not untouched_db.exists()


def test_workbench_prototype_cli_reads_controlled_db_path_without_sample(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing" / "evidence.db"
    record_path = tmp_path / "multi-day.md"
    record_path.write_text(
        "\n".join(
            [
                "| Date | Data update status | Source coverage status | Dry-run pipeline status | Working-copy confirm smoke status | Events seen | Events inserted in working copy | Outcomes created in working copy | Summary groups | Warnings count | Blocking gaps | Dashboard review completed | Human reviewer notes | Decision |",
                "|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v2_workbench_prototype.py",
            "--db-path",
            str(missing_db),
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(tmp_path / "output"),
            "--decision-date",
            "2026-07-06",
            "--multi-day-record-path",
            str(record_path),
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(result.stdout)

    assert payload["source_mode"] == "read_only_sources"
    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["access_boundary"]["production_scheduler_allowed"] is False
    assert any("decision_desk_snapshot_db_missing" in warning for warning in payload["warnings"])
    assert not missing_db.exists()


def test_workbench_prototype_cli_requires_sample_or_db_path() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v2_workbench_prototype.py",
            "--format",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 2
    assert "--db-path" in result.stderr
