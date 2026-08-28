from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_module.update_status_history import (
    UPDATE_STATUS_HISTORY_SCHEMA,
    append_update_status_history,
    build_update_status_history_record,
    read_update_status_history,
)


def _payload(*, status: str = "passed", run_id: str = "run-1") -> dict:
    return {
        "task": "baldr-data-update-quick-daily",
        "status": status,
        "run_id": run_id,
        "started_at": "2026-08-28T08:30:00+08:00",
        "completed_at": "2026-08-28T09:00:00+08:00",
        "start_date": "2026-08-17",
        "end_date": "2026-08-28",
        "steps": [
            {"name": "download", "status": "passed", "message": "ok", "result": {"rows": 2}},
            {"name": "sync", "status": "failed", "message": "db unavailable"},
        ],
        "warnings": ["one warning"],
        "errors": ["one error"],
    }


def test_build_history_record_is_bounded_and_hash_bound() -> None:
    record = build_update_status_history_record(
        _payload(), captured_at="2026-08-28T09:00:01+08:00"
    )

    assert record["schema_version"] == UPDATE_STATUS_HISTORY_SCHEMA
    assert record["record_type"] == "data_update_attempt"
    assert record["run_id"] == "run-1"
    assert record["failed_step_count"] == 1
    assert record["warning_count"] == 1
    assert record["error_count"] == 1
    assert record["steps"][0] == {
        "name": "download",
        "status": "passed",
        "message": "ok",
    }
    assert len(record["record_id"]) == 28
    assert len(record["payload_sha256"]) == 64


def test_append_history_is_idempotent_and_readable(tmp_path: Path) -> None:
    path = tmp_path / "scheduled" / "history.jsonl"
    payload = _payload()
    first = append_update_status_history(
        path, payload, captured_at="2026-08-28T09:00:01+08:00"
    )
    second = append_update_status_history(
        path, payload, captured_at="2026-08-28T09:00:01+08:00"
    )

    assert first["appended"] is True
    assert second["appended"] is False
    assert second["duplicate"] is True
    result = read_update_status_history(path)
    assert result["status"] == "current"
    assert result["record_count"] == 1
    assert result["latest"]["run_id"] == "run-1"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_read_history_reports_missing_and_invalid_without_inventing_records(tmp_path: Path) -> None:
    missing = read_update_status_history(tmp_path / "missing.jsonl")
    assert missing["status"] == "missing"
    assert missing["record_count"] == 0

    invalid_path = tmp_path / "invalid.jsonl"
    invalid_path.write_text(
        json.dumps({"schema_version": "other", "run_id": "run-x"}) + "\n",
        encoding="utf-8",
    )
    invalid = read_update_status_history(invalid_path)
    assert invalid["status"] == "invalid"
    assert invalid["record_count"] == 0
    assert any("schema_mismatch" in item for item in invalid["diagnostics"])

    with pytest.raises(ValueError, match="history artifact is invalid"):
        append_update_status_history(invalid_path, _payload())


def test_history_requires_run_identity() -> None:
    with pytest.raises(ValueError, match="requires run_id"):
        build_update_status_history_record({"status": "passed"})
