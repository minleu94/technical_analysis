from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from data_module.config import TWStockConfig


def test_weekly_review_cli_outputs_json_without_enabling_scheduler(tmp_path: Path) -> None:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    db_path = tmp_path / "evidence-ops-cli.db"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_evidence_operations_weekly_review.py",
            "--start-date",
            "2026-06-24",
            "--end-date",
            "2026-06-30",
            "--db-path",
            str(db_path),
            "--data-root",
            str(config.data_root),
            "--output-root",
            str(config.output_root),
            "--json-output",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["manual_approval"]["production_scheduler_allowed"] is False
    assert payload["status"] in {"coverage_only", "needs_manual_review", "ready_for_weekly_closeout"}
    assert payload["write_performed"] is False


def test_weekly_review_cli_action_item_plan_dry_run_does_not_write(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence-ops-cli.db"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_evidence_operations_weekly_review.py",
            "--start-date",
            "2026-06-24",
            "--end-date",
            "2026-06-30",
            "--db-path",
            str(db_path),
            "--plan-action-items",
            "--json-output",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["action_item_plan"]["dry_run"] is True
    assert payload["action_item_plan"]["action_items_created"] == 0
    assert payload["write_performed"] is False
