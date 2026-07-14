from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_evidence_rehearsal.py"


def _seed_source(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE daily_prices (股票代碼 TEXT NOT NULL, 證券代號 TEXT NOT NULL, 日期 TEXT NOT NULL, 收盤價 TEXT)"
        )
        connection.execute(
            "INSERT INTO daily_prices VALUES ('2330', '2330', '20260712', '100')"
        )
    return path


def _run_cli(
    tmp_path: Path,
    *,
    scenario_decision_date: str = "2026-07-12",
    replay_decision_date: str = "2026-07-12",
    inject_failure: str | None = None,
    ml_evidence_root: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object], Path, Path]:
    source = _seed_source(tmp_path / "source.sqlite3")
    working_copy = tmp_path / "working" / "rehearsal.sqlite3"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps(
            {
                "scenario_id": "real-e2e-contract",
                "decision_date": scenario_decision_date,
                "tier": "engineering_fixture",
            }
        ),
        encoding="utf-8",
    )
    replay_summary = tmp_path / "replay-summary.json"
    replay_payload: dict[str, object] = {
        "replay_run_id": "hre-contract",
        "available_date": replay_decision_date,
        "days": [{"decision_date": replay_decision_date}],
    }
    if inject_failure == "future_available_date":
        replay_payload["p0_shadow_observations"] = [
            {
                "source_id": "institutional_flows",
                "symbol": "2330",
                "decision_date": scenario_decision_date,
                "available_date": scenario_decision_date,
                "source_version": "fixture-v1",
                "status": "observed",
                "diagnostics": [],
            }
        ]
    replay_summary.write_text(
        json.dumps(replay_payload),
        encoding="utf-8",
    )
    output = tmp_path / "reports"
    command = [
            sys.executable,
            str(SCRIPT),
            "--execution-mode",
            "working_copy_e2e",
            "--scenario",
            str(scenario),
            "--source-db",
            str(source),
            "--working-copy-db",
            str(working_copy),
            "--replay-summary",
            str(replay_summary),
            "--output-root",
            str(output),
        ]
    if inject_failure is not None:
        command.extend(("--inject-failure", inject_failure))
    if ml_evidence_root is not None:
        command.extend(("--ml-evidence-root", str(ml_evidence_root)))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads((output / "rehearsal-report.json").read_text(encoding="utf-8"))
    return completed, report, source, working_copy


def test_real_e2e_opens_source_read_only_and_reports_working_copy_facts(
    tmp_path: Path,
) -> None:
    completed, report, source, working_copy = _run_cli(tmp_path)
    before = source.read_bytes()

    assert completed.returncode == 0, completed.stderr
    assert report["contract_version"] == 2
    assert report["execution"]["mode"] == "working_copy_e2e"
    assert report["execution"]["source_db_opened"] is True
    assert report["execution"]["source_db_write_performed"] is False
    assert report["execution"]["working_copy_created"] is True
    assert report["execution"]["working_copy_write_performed"] is True
    assert report["execution"]["production_db_write_performed"] is False
    assert report["source_snapshot"]["schema_fingerprint"]
    assert report["semantic_fingerprint"]
    assert report["execution"]["service_call_facts"]["historical_replay"] is True
    assert report["execution"]["service_call_facts"]["p0_comparison"] is True
    assert report["execution"]["service_call_facts"]["evidence_rehearsal_service_run"] is True
    assert report["lineage"]["status"] == "incomplete"
    assert report["lineage"]["artifact_dag"]
    assert report["historical_replay_artifacts"]
    assert report["formal_product_closeout"] is False
    assert report["production_actions_allowed"] is False
    assert working_copy.is_file()
    assert source.read_bytes() == before


def test_cli_blocks_replay_day_after_scenario_decision_date(tmp_path: Path) -> None:
    completed, report, _, working_copy = _run_cli(
        tmp_path,
        scenario_decision_date="2026-07-12",
        replay_decision_date="2026-07-13",
    )

    assert completed.returncode == 2
    assert "scenario_replay_decision_date_mismatch" in report["blockers"]
    assert report["coverage_metrics"][0]["observed_count"] == 0
    assert not working_copy.exists()


def test_cli_allows_read_only_source_inside_configured_data_root(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "formal-data-root"
    source = _seed_source(data_root / "sqlite" / "twstock.sqlite3")
    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps(
            {
                "scenario_id": "formal-source-read-only",
                "decision_date": "2026-07-12",
                "tier": "engineering_fixture",
            }
        ),
        encoding="utf-8",
    )
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "replay_run_id": "hre-formal-source",
                "days": [{"decision_date": "2026-07-12"}],
            }
        ),
        encoding="utf-8",
    )
    working_copy = tmp_path / "working" / "copy.sqlite3"
    output = tmp_path / "reports"
    before = source.read_bytes()
    before_mtime = source.stat().st_mtime_ns

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--execution-mode",
            "working_copy_e2e",
            "--scenario",
            str(scenario),
            "--source-db",
            str(source),
            "--working-copy-db",
            str(working_copy),
            "--replay-summary",
            str(summary),
            "--output-root",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DATA_ROOT": str(data_root)},
    )

    assert completed.returncode == 0, completed.stderr
    assert source.read_bytes() == before
    assert source.stat().st_mtime_ns == before_mtime
    assert working_copy.is_file()


def test_semantic_fingerprint_is_stable_across_fresh_working_copies(
    tmp_path: Path,
) -> None:
    first_completed, first_report, _, _ = _run_cli(tmp_path / "first")
    second_completed, second_report, _, _ = _run_cli(tmp_path / "second")

    assert first_completed.returncode == second_completed.returncode == 0
    assert first_report["semantic_fingerprint"] == second_report["semantic_fingerprint"]
    assert (
        first_report["source_snapshot"]["schema_fingerprint"]
        == second_report["source_snapshot"]["schema_fingerprint"]
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        ("missing_day", "adapter_failure:replay:missing_trading_day:"),
        ("schema_missing", "adapter_failure:replay:schema_missing:daily_prices"),
        ("immature_label", "label_not_mature:ml-shadow"),
    ),
)
def test_cli_e2e_faults_flow_through_real_detectors(
    tmp_path: Path,
    failure: str,
    expected: str,
) -> None:
    completed, report, source, working_copy = _run_cli(
        tmp_path,
        inject_failure=failure,
    )

    assert completed.returncode == 0, completed.stderr
    assert any(expected in blocker for blocker in report["blockers"])
    assert report["injection"]["name"] == failure
    assert report["injection"]["detector"]
    assert source.is_file()
    assert working_copy.is_file()


def test_cli_ml_evidence_root_is_validated_instead_of_trusting_status(
    tmp_path: Path,
) -> None:
    from tests.test_evidence_rehearsal_ml_provider import _write_ml_input

    ml_root = tmp_path / "ml-evidence"
    _write_ml_input(ml_root)

    completed, report, _, _ = _run_cli(
        tmp_path / "run",
        ml_evidence_root=ml_root,
    )

    assert completed.returncode == 0, completed.stderr
    assert report["ml_shadow"]["status"] == "insufficient_sample"
    assert report["ml_shadow"]["immature_label_rows"] == 1
    assert "label_not_mature:ml-shadow" in report["blockers"]
