"""Tests for the guarded technical-indicator production canary."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from pathlib import Path

from scripts import qa_technical_indicator_production_canary as canary


def _production_fixture(tmp_path: Path) -> tuple[Path, Path]:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    (data_root / "sqlite").mkdir(parents=True)
    (data_root / "technical_analysis").mkdir()
    output_root.mkdir()
    with sqlite3.connect(data_root / "sqlite" / "twstock.db") as connection:
        connection.execute(
            "CREATE TABLE daily_prices (date TEXT, stock_id TEXT, close REAL)"
        )
        connection.execute(
            "CREATE TABLE technical_indicators (date TEXT, stock_id TEXT, sma REAL)"
        )
        connection.execute(
            "INSERT INTO daily_prices VALUES ('2026-08-28', '2330', 100)"
        )
    return data_root, output_root


def test_canary_preview_is_read_only_and_requires_confirmation(tmp_path, monkeypatch):
    data_root, output_root = _production_fixture(tmp_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("preview must not invoke UpdateService")

    monkeypatch.setattr(
        canary.UpdateService,
        "calculate_technical_indicators",
        fail_if_called,
    )
    report = canary.execute_production_canary(
        data_root=data_root,
        output_root=output_root,
        protected_roots=(tmp_path,),
        stock_id="2330",
        expected_latest_date="2026-08-28",
    )

    assert report["status"] == "confirmation_required"
    assert report["production_write_attempted"] is False
    assert report["production_sqlite_write_attempted"] is False
    assert report["writes_allowed"] is False
    assert not (data_root / "sqlite" / "backups").exists()


def test_canary_confirmation_and_storage_guards(tmp_path, monkeypatch):
    data_root, output_root = _production_fixture(tmp_path)
    report = canary.execute_production_canary(
        data_root=data_root,
        output_root=output_root,
        protected_roots=(tmp_path,),
        stock_id="2330",
        expected_latest_date="2026-08-28",
        confirm=True,
        owner_approval="wrong-owner-token",
        no_concurrent_writer_ack=canary.NO_CONCURRENT_WRITER_TOKEN,
    )

    assert report["status"] == "blocked"
    assert report["blocker"] == "owner_approval_token_required"
    assert not (data_root / "sqlite" / "backups").exists()
    monkeypatch.setattr(
        canary.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=1000, used=950, free=50),
    )

    report = canary.execute_production_canary(
        data_root=data_root,
        output_root=output_root,
        protected_roots=(tmp_path,),
        stock_id="2330",
        expected_latest_date="2026-08-28",
        owner_approval=canary.OWNER_APPROVAL_TOKEN,
        no_concurrent_writer_ack=canary.NO_CONCURRENT_WRITER_TOKEN,
        confirm=True,
        minimum_free_space_bytes=100,
    )

    assert report["status"] == "blocked"
    assert report["blocker"] == "production_canary_storage_preflight_blocked"
    assert report["storage_preflight"]["free_bytes"] == 50
    assert report["storage_preflight"]["within_minimum_free_space"] is False
    assert not (data_root / "sqlite" / "backups").exists()


def test_canary_post_state_validation_requires_parent_only_writer_contract():
    service_result = {
        "success": True,
        "technical_process_pool": {
            "status": "completed",
            "parent_single_writer": True,
            "worker_writes": False,
            "sqlite_worker_writes": False,
            "parent_written_stock_count": 1,
            "parent_write_failed_count": 0,
        },
    }
    state = {
        "db_quick_check": "ok",
        "daily_stock_max_date": "2026-08-28",
        "technical_stock_row_count": 1,
        "indicator_file_exists": True,
    }

    accepted = canary._validate_post_state(
        service_result=service_result,
        pre_state={},
        post_state=state,
        expected_latest_date="2026-08-28",
    )
    assert accepted["ok"] is True

    rejected_result = {
        **service_result,
        "technical_process_pool": {
            **service_result["technical_process_pool"],
            "worker_writes": True,
        },
    }
    rejected = canary._validate_post_state(
        service_result=rejected_result,
        pre_state={},
        post_state=state,
        expected_latest_date="2026-08-28",
    )
    assert rejected["ok"] is False
    assert rejected["checks"]["pool_worker_writes_false"] is False


def test_canary_main_rejects_report_inside_protected_root(tmp_path, capsys):
    data_root, output_root = _production_fixture(tmp_path)
    output_path = tmp_path / "protected-report.json"
    code = canary.main(
        [
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            "--protected-root",
            str(tmp_path),
            "--stock-id",
            "2330",
            "--expected-latest-date",
            "2026-08-28",
            "--output-json",
            str(output_path),
        ]
    )

    assert code == 2
    assert "output_json_inside_protected_root" in capsys.readouterr().err
    assert not output_path.exists()


def test_canary_contract_is_valid_readiness_artifact():
    payload = {
        "schema_version": canary.CANARY_SCHEMA_VERSION,
        "status": "measured",
        "production_write_attempted": True,
        "production_sqlite_write_attempted": True,
        "single_writer_verified": True,
        "parent_single_writer": True,
        "worker_writes": False,
        "sqlite_worker_writes": False,
        "network_enabled": False,
        "broker_enabled": False,
        "selenium_invocations": 0,
        "validation": {"ok": True},
        "rollback": {"available": True, "succeeded": None},
    }
    from scripts.inspect_program_readiness import _valid_technical_production_canary

    assert _valid_technical_production_canary(payload) is True
