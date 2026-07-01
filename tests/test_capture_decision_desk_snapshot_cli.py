from __future__ import annotations

import json
import subprocess
import sys

from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from data_module.config import TWStockConfig


def _config(tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _run(tmp_path, *args):
    config = _config(tmp_path)
    command = [
        sys.executable,
        "scripts/capture_decision_desk_snapshot.py",
        "--decision-date",
        "2026-06-30",
        "--db-path",
        str(config.db_file),
        "--data-root",
        str(config.data_root),
        "--output-root",
        str(config.output_root),
        "--json-output",
        *args,
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout), config


def test_dry_run_does_not_write_snapshot(tmp_path):
    summary, config = _run(tmp_path, "--dry-run")

    assert summary["dry_run"] is True
    assert summary["saved"] is False
    assert DecisionDeskSnapshotRepository(config).list_snapshots() == []


def test_confirm_writes_snapshot_and_duplicate_is_skipped(tmp_path):
    first, config = _run(tmp_path, "--confirm")
    second, _ = _run(tmp_path, "--confirm")

    assert first["dry_run"] is False
    assert first["saved"] is True
    assert second["skipped_duplicate"] is True
    assert len(DecisionDeskSnapshotRepository(config).list_snapshots()) == 1


def test_inspect_decision_desk_snapshots_cli_reports_latest(tmp_path):
    _, config = _run(tmp_path, "--confirm")
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_decision_desk_snapshots.py",
            "--db-path",
            str(config.db_file),
            "--json-output",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    assert summary["snapshots_count"] == 1
    assert summary["latest_decision_date"] == "2026-06-30"


def test_snapshot_clis_do_not_import_ui_modules():
    for path in (
        "scripts/capture_decision_desk_snapshot.py",
        "scripts/inspect_decision_desk_snapshots.py",
    ):
        text = open(path, encoding="utf-8").read()
        assert "ui_qt" not in text
