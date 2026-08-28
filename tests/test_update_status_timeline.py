import json
from datetime import datetime, timezone
from pathlib import Path

from app_module.update_status_timeline import (
    UPDATE_STATUS_TIMELINE_SCHEMA,
    load_data_update_timeline,
)


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _update_payload(*, status: str = "passed", completed_at: str = "2026-08-28T09:00:00+08:00") -> dict:
    return {
        "status": status,
        "run_id": "run-1",
        "started_at": "2026-08-28T08:30:00+08:00",
        "completed_at": completed_at,
        "end_date": "2026-08-28",
        "steps": [
            {"name": "download", "status": "passed", "message": "ok"},
            {"name": "sync", "status": "passed", "message": "ok"},
        ],
    }


def test_timeline_projects_current_run_and_steps(tmp_path: Path) -> None:
    update = _write(tmp_path / "update.json", _update_payload())
    freshness = _write(
        tmp_path / "freshness.json",
        {"status": "passed", "checked_at": "2026-08-28T09:05:00+08:00"},
    )

    result = load_data_update_timeline(
        update_status_path=update,
        freshness_status_path=freshness,
        now=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
    )

    assert result["schema_version"] == UPDATE_STATUS_TIMELINE_SCHEMA
    assert result["status"] == "current"
    assert result["last_success_at"] == "2026-08-28T09:00:00+08:00"
    assert result["run_id"] == "run-1"
    assert result["step_count"] == 2
    assert result["failed_step_count"] == 0
    assert result["boundary"]["read_only"] is True
    assert result["boundary"]["writes_allowed"] is False


def test_timeline_does_not_claim_success_for_failed_or_future_run(tmp_path: Path) -> None:
    failed = _write(tmp_path / "failed.json", _update_payload(status="failed"))
    failed_result = load_data_update_timeline(
        update_status_path=failed,
        now=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
    )
    assert failed_result["status"] == "failed"
    assert failed_result["last_success_at"] is None

    future = _write(
        tmp_path / "future.json",
        _update_payload(completed_at="2026-08-29T09:00:00+08:00"),
    )
    future_result = load_data_update_timeline(
        update_status_path=future,
        now=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
    )
    assert future_result["status"] == "invalid"
    assert future_result["last_success_at"] is None
    assert any("timestamp_in_future" in item for item in future_result["diagnostics"])


def test_timeline_marks_old_run_stale_without_reusing_other_files(tmp_path: Path) -> None:
    update = _write(tmp_path / "update.json", _update_payload())
    result = load_data_update_timeline(
        update_status_path=update,
        freshness_status_path=tmp_path / "missing-freshness.json",
        tpex_status_path=tmp_path / "missing-tpex.json",
        now=datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc),
    )

    assert result["status"] == "stale"
    assert result["last_success_at"] == "2026-08-28T09:00:00+08:00"
    assert any("freshness_artifact_missing" in item for item in result["diagnostics"])
    assert any("tpex_artifact_missing" in item for item in result["diagnostics"])


def test_timeline_missing_and_invalid_are_fail_closed(tmp_path: Path) -> None:
    missing = load_data_update_timeline(
        update_status_path=tmp_path / "nope.json",
        now=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
    )
    assert missing["status"] == "missing"
    assert missing["last_success_at"] is None

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("[]", encoding="utf-8")
    invalid = load_data_update_timeline(
        update_status_path=invalid_path,
        now=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
    )
    assert invalid["status"] == "missing"
    assert any("update_artifact_root_not_object" in item for item in invalid["diagnostics"])
