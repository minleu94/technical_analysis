from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_evidence_rehearsal.py"


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source_db = tmp_path / "source-fixture.db"
    source_db.write_bytes(b"read-only-fixture")
    working_copy_db = tmp_path / "working-copy" / "rehearsal.db"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps(
            {
                "scenario_id": "cli-fixture",
                "decision_date": "2026-07-12",
                "tier": "engineering_fixture",
            }
        ),
        encoding="utf-8",
    )
    replay_summary = tmp_path / "replay-summary.json"
    replay_summary.write_text(
        json.dumps(
            {
                "replay_run_id": "hre-cli-fixture",
                "available_date": "2026-07-12",
                "days": [{"decision_date": "2026-07-12"}],
            }
        ),
        encoding="utf-8",
    )
    return source_db, working_copy_db, scenario, replay_summary


def _run_cli(
    *,
    source_db: Path,
    working_copy_db: Path,
    scenario: Path,
    replay_summary: Path,
    output_root: Path,
    inject_failure: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--scenario",
        str(scenario),
        "--source-db",
        str(source_db),
        "--working-copy-db",
        str(working_copy_db),
        "--replay-summary",
        str(replay_summary),
        "--output-root",
        str(output_root),
    ]
    if inject_failure is not None:
        command.extend(("--inject-failure", inject_failure))
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


def test_cli_defaults_to_dry_read_only_and_writes_only_report_package(tmp_path: Path) -> None:
    source_db, working_copy_db, scenario, replay_summary = _write_inputs(tmp_path)
    original_source = source_db.read_bytes()
    output_root = tmp_path / "reports"

    completed = _run_cli(
        source_db=source_db,
        working_copy_db=working_copy_db,
        scenario=scenario,
        replay_summary=replay_summary,
        output_root=output_root,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads((output_root / "rehearsal-report.json").read_text(encoding="utf-8"))
    handoff = json.loads((output_root / "forward-handoff.json").read_text(encoding="utf-8"))
    assert (output_root / "rehearsal-report.md").is_file()
    assert report["execution"] == {
        "advice_invoked": False,
        "broker_invoked": False,
        "db_write_performed": False,
        "mode": "dry_read_only",
        "promotion_invoked": False,
        "scheduler_invoked": False,
        "source_db_opened": False,
        "working_copy_created": False,
    }
    assert report["scenario"]["production_actions_allowed"] is False
    assert source_db.read_bytes() == original_source
    assert not working_copy_db.exists()
    assert handoff["status"] == "forward_handoff_pending"
    assert handoff["production_actions_allowed"] is False


def test_cli_rejects_same_source_and_working_copy(tmp_path: Path) -> None:
    source_db, _, scenario, replay_summary = _write_inputs(tmp_path)

    completed = _run_cli(
        source_db=source_db,
        working_copy_db=source_db,
        scenario=scenario,
        replay_summary=replay_summary,
        output_root=tmp_path / "out",
    )

    assert completed.returncode != 0
    assert "working-copy DB must differ" in completed.stderr


@pytest.mark.parametrize("unsafe_name", ("production.db", "prod.db"))
def test_cli_rejects_production_like_target(tmp_path: Path, unsafe_name: str) -> None:
    source_db, _, scenario, replay_summary = _write_inputs(tmp_path)

    completed = _run_cli(
        source_db=source_db,
        working_copy_db=tmp_path / unsafe_name,
        scenario=scenario,
        replay_summary=replay_summary,
        output_root=tmp_path / "out",
    )

    assert completed.returncode != 0
    assert "production-like" in completed.stderr
    assert not (tmp_path / unsafe_name).exists()


@pytest.mark.parametrize(
    ("inject_failure", "expected_blocker"),
    (
        ("missing_day", "missing_required_adapter_output:source"),
        ("source_outage", "adapter_failure:source:source_outage"),
        ("future_available_date", "future_available_date:source-data"),
        ("schema_missing", "missing_field:source-data:source_version"),
        ("immature_label", "immature_label:ml-shadow"),
    ),
)
def test_cli_failure_injections_are_deterministic_and_do_not_touch_working_copy(
    tmp_path: Path,
    inject_failure: str,
    expected_blocker: str,
) -> None:
    source_db, working_copy_db, scenario, replay_summary = _write_inputs(tmp_path)
    output_root = tmp_path / inject_failure

    completed = _run_cli(
        source_db=source_db,
        working_copy_db=working_copy_db,
        scenario=scenario,
        replay_summary=replay_summary,
        output_root=output_root,
        inject_failure=inject_failure,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads((output_root / "rehearsal-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "degraded"
    assert report["injection"] == {
        "blocker": expected_blocker,
        "name": inject_failure,
        "status": "degraded",
    }
    assert expected_blocker in report["blockers"]
    assert report["execution"]["db_write_performed"] is False
    assert report["execution"]["scheduler_invoked"] is False
    assert not working_copy_db.exists()
