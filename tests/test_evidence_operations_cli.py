from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from app_module.decision_quality_dtos import DecisionQualityItem, DecisionQualityReview
from app_module.decision_quality_repository import DecisionQualityRepository
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


def test_weekly_review_cli_save_history_and_list_history(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence-ops-cli.db"

    saved = subprocess.run(
        [
            sys.executable,
            "scripts/build_evidence_operations_weekly_review.py",
            "--start-date",
            "2026-07-06",
            "--end-date",
            "2026-07-12",
            "--db-path",
            str(db_path),
            "--save-history",
            "--json-output",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert saved.returncode == 0, saved.stderr
    saved_payload = json.loads(saved.stdout)
    assert saved_payload["history_record"]["period_end"] == "2026-07-12"
    assert saved_payload["history_record"]["production_scheduler_allowed"] is False
    assert saved_payload["write_performed"] is True

    listed = subprocess.run(
        [
            sys.executable,
            "scripts/build_evidence_operations_weekly_review.py",
            "--start-date",
            "2026-07-06",
            "--end-date",
            "2026-07-12",
            "--db-path",
            str(db_path),
            "--list-history",
            "--json-output",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert listed.returncode == 0, listed.stderr
    listed_payload = json.loads(listed.stdout)
    assert len(listed_payload["history_records"]) == 1
    assert listed_payload["history_records"][0]["period_start"] == "2026-07-06"
    assert listed_payload["history_records"][0]["payload_json"]["status"] == saved_payload["status"]


def test_list_history_missing_database_is_diagnostic_and_never_creates_it(tmp_path: Path) -> None:
    db_path = tmp_path / "missing" / "history.db"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_evidence_operations_weekly_review.py",
            "--start-date",
            "2026-07-06",
            "--end-date",
            "2026-07-12",
            "--db-path",
            str(db_path),
            "--list-history",
            "--json-output",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["history_records"] == []
    assert payload["diagnostics"] == ["evidence_operations_history_db_missing"]
    assert payload["write_performed"] is False
    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_list_history_missing_table_is_diagnostic_and_does_not_create_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "history-without-table.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE unrelated_table (value TEXT NOT NULL)")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_evidence_operations_weekly_review.py",
            "--start-date",
            "2026-07-06",
            "--end-date",
            "2026-07-12",
            "--db-path",
            str(db_path),
            "--list-history",
            "--json-output",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["history_records"] == []
    assert payload["diagnostics"] == ["evidence_operations_history_table_missing"]
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
    assert tables == {"unrelated_table"}
    assert indexes == set()


def test_confirmed_action_owner_is_persisted_and_traceable_in_history_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence-ops-cli.db"
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = db_path
    repository = DecisionQualityRepository(config)
    repository.save_review(
        DecisionQualityReview(
            review_id="dqr-weekly",
            review_hash="sha256:dqr-weekly",
            review_period_start="2026-07-06",
            review_period_end="2026-07-12",
            review_type="weekly",
            review_status="needs_review",
        ),
        items=[
            DecisionQualityItem(
                item_id="dqi-weekly",
                review_id="dqr-weekly",
                item_type="trade_without_source_trace",
                status="open",
            )
        ],
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_evidence_operations_weekly_review.py",
            "--start-date",
            "2026-07-06",
            "--end-date",
            "2026-07-12",
            "--db-path",
            str(db_path),
            "--confirm-action-items",
            "--save-history",
            "--action-owner",
            "weekly-reviewer",
            "--json-output",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["action_item_plan"]["action_items_created"] == 1
    assert payload["history_record"]["payload_json"]["action_owner"] == "weekly-reviewer"
    assert payload["history_record"]["payload_json"]["action_item_plan"]["planned_action_items"][0]["owner"] == "weekly-reviewer"
    assert repository.list_action_items(review_id="dqr-weekly")[0].owner == "weekly-reviewer"


def test_production_like_db_is_rejected_without_escape_hatch(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    production_like_db = data_root / "sqlite" / "twstock.db"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_evidence_operations_weekly_review.py",
            "--start-date",
            "2026-07-06",
            "--end-date",
            "2026-07-12",
            "--data-root",
            str(data_root),
            "--db-path",
            str(production_like_db),
            "--save-history",
            "--json-output",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 2
    assert "production-like DB" in completed.stderr
    assert not production_like_db.exists()

    help_output = subprocess.run(
        [sys.executable, "scripts/build_evidence_operations_weekly_review.py", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert help_output.returncode == 0
    assert "--allow-production-like-db" not in help_output.stdout


def test_data_root_override_cannot_bypass_configured_production_db_guard(tmp_path: Path) -> None:
    configured_production_root = tmp_path / "configured-production"
    overridden_qa_root = tmp_path / "overridden-qa"
    production_like_db = configured_production_root / "sqlite" / "twstock.db"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_evidence_operations_weekly_review.py",
            "--start-date",
            "2026-07-06",
            "--end-date",
            "2026-07-12",
            "--data-root",
            str(overridden_qa_root),
            "--db-path",
            str(production_like_db),
            "--save-history",
            "--json-output",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "DATA_ROOT": str(configured_production_root),
            "OUTPUT_ROOT": str(tmp_path / "output"),
            "PYTHONIOENCODING": "utf-8",
        },
        check=False,
    )

    assert completed.returncode == 2
    assert "production-like DB" in completed.stderr
    assert not production_like_db.exists()
