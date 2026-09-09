from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from data_module.formal_operational_readiness import (
    SCHEDULE_CONTRACTS,
    TAIPEI,
    audit_formal_operational_readiness,
    file_sha256,
    inspect_formal_readiness_report,
    inspect_latest_pit_archive,
    inspect_persisted_status,
    inspect_schedule_contract,
    inspect_scheduler_registration,
    payload_hash,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _make_archive(
    tmp_path: Path,
    *,
    captured_at: datetime,
    target_date: date,
) -> Path:
    archive = tmp_path / "pit_candidate_archive" / target_date.isoformat() / "run-1"
    publication = archive / "pit-sector-membership-machine.json"
    receipt = archive / "receipt.json"
    archive.mkdir(parents=True, exist_ok=True)
    publication.write_bytes(b'{"rows":[{"symbol":"2330","sector_code":"01"}]}\n')
    receipt.write_bytes(b'{"status":"machine_verified_candidate"}\n')
    manifest = {
        "archive_id": "archive-1",
        "archived_at": captured_at.isoformat(),
        "captured_at": captured_at.isoformat(),
        "candidate_only": True,
        "consumer_verified_at_capture": True,
        "effective_from": target_date.isoformat(),
        "files": [
            {
                "archive_file_hash": file_sha256(publication),
                "relative_path": publication.name,
                "role": "publication",
            },
            {
                "archive_file_hash": file_sha256(receipt),
                "relative_path": receipt.name,
                "role": "receipt",
            },
        ],
        "formal_consumer_compatible": False,
        "row_count": 1,
        "source_ids": ["official:twse:t187ap03_L"],
    }
    manifest_path = archive / "archive_manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def _make_readiness_report(
    tmp_path: Path,
    *,
    created_at: datetime,
    machine_count: int = 1,
) -> Path:
    payload: dict[str, object] = {
        "schema_version": "ml-formal-input-readiness.v1",
        "created_at": created_at.isoformat(),
        "output_root": str(tmp_path),
        "training_as_of": created_at.isoformat(),
        "status": "waiting_for_formal_inputs",
        "ready_input_count": 0,
        "machine_verified_input_count": machine_count,
        "formal_consumer_compatible_count": 0,
        "input_count": 3,
        "formal_oos_allowed": False,
        "broker_order_allowed": False,
        "inputs": [
            {
                "input": "pit_sector_membership",
                "state": "machine_verified",
                "reason": "machine_verified_candidate_formal_owner_publication_pending",
            }
        ],
    }
    payload["readiness_hash"] = payload_hash(payload)
    path = tmp_path / "readiness.json"
    _write_json(path, payload)
    return path


def _registration_report(repo_root: Path, *, last_result: str = "0") -> dict[str, object]:
    tasks: list[dict[str, object]] = []
    for contract in SCHEDULE_CONTRACTS:
        tasks.append(
            {
                "name": contract["task_name"],
                "status": "available",
                "wrapper_status": "present",
                "wrapper_exists": (repo_root / contract["wrapper"]).is_file(),
                "action_matches_wrapper": True,
                "summary": {
                    "logon_mode": "Interactive only",
                    "run_only_if_user_is_logged_on": "Yes",
                    "stop_if_the_computer_switches_to_battery_power": "Yes",
                    "last_result": last_result,
                },
            }
        )
    return {
        "schema_version": "scheduled-task-registration.v1",
        "query_only": True,
        "tasks": tasks,
    }


def test_schedule_contract_is_dst_mapped_from_taipei_decision_window() -> None:
    now = datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
    rows = inspect_schedule_contract(target_date=date(2026, 9, 8), now=now)
    capture = next(item for item in rows if item["key"] == "pit_preopen_capture")
    formal = next(item for item in rows if item["key"] == "formal_input_producer")
    assert capture["expected_taipei_at"] == "2026-09-08T07:00:00+08:00"
    assert capture["expected_host_at"] == "2026-09-07T16:00:00-07:00"
    assert formal["expected_host_at"] == "2026-09-07T21:25:00-07:00"


def test_paper_eod_contract_uses_host_0600_and_dst_maps_to_taipei() -> None:
    now = datetime(2026, 9, 8, 18, 0, tzinfo=timezone.utc)
    summer_rows = inspect_schedule_contract(
        target_date=date(2026, 9, 8),
        now=now,
    )
    summer = next(item for item in summer_rows if item["key"] == "paper_eod_replay")
    assert summer["host_time"] == "06:00"
    assert summer["taipei_time"] == "21:00"
    assert summer["expected_host_at"] == "2026-09-08T06:00:00-07:00"
    assert summer["expected_taipei_at"] == "2026-09-08T21:00:00+08:00"

    winter_rows = inspect_schedule_contract(
        target_date=date(2026, 12, 8),
        now=now,
    )
    winter = next(item for item in winter_rows if item["key"] == "paper_eod_replay")
    assert winter["taipei_time"] == "22:00"
    assert winter["expected_host_at"] == "2026-12-08T06:00:00-08:00"
    assert winter["expected_taipei_at"] == "2026-12-08T22:00:00+08:00"


def test_paper_eod_readiness_waits_until_host_0600_window(
    tmp_path: Path,
) -> None:
    before = audit_formal_operational_readiness(
        publication_root=tmp_path / "before",
        now=datetime(2026, 9, 8, 12, 59, tzinfo=timezone.utc),
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert before["phase"] == "between_rule_close_and_paper_eod"
    assert "paper_eod_source_window_not_reached" in before["blockers"]
    assert before["windows"]["paper_eod_available_taipei"] == "21:00"

    after = audit_formal_operational_readiness(
        publication_root=tmp_path / "after",
        now=datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc),
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert after["phase"] == "paper_eod_or_later"
    assert "paper_eod_source_window_not_reached" not in after["blockers"]
    assert "paper_execution_terminal_receipt_missing" in after["blockers"]


def test_persisted_status_rejects_future_and_different_natural_day(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    now = datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
    _write_json(path, {"status": "ok", "observed_at": "2026-09-08T03:00:00+08:00"})
    future = inspect_persisted_status(
        path,
        target_date=date(2026, 9, 8),
        now=now,
        lane="pit",
    )
    assert future["state"] == "stale_or_invalid"
    assert "persistent_status_observed_in_future" in future["blockers"]

    _write_json(path, {"status": "ok", "observed_at": "2026-09-07T23:00:00+08:00"})
    stale = inspect_persisted_status(
        path,
        target_date=date(2026, 9, 8),
        now=now,
        lane="pit",
    )
    assert stale["state"] == "stale_or_invalid"
    assert "persistent_status_for_different_natural_day:2026-09-07" in stale["blockers"]


def test_persisted_status_preserves_current_producer_blockers_and_exit_code(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    now = datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
    _write_json(
        path,
        {
            "status": "blocked",
            "observed_at": now.isoformat(),
            "exit_code": 2,
            "blockers": ["formal_ledger_source_file_missing"],
        },
    )

    report = inspect_persisted_status(
        path,
        target_date=date(2026, 9, 8),
        now=now,
        lane="formal_input_producer",
    )

    assert report["state"] == "current"
    assert report["reported_blockers"] == ["formal_ledger_source_file_missing"]
    assert report["exit_code"] == 2


def test_pit_archive_rechecks_each_persisted_file_hash(tmp_path: Path) -> None:
    target = date(2026, 9, 8)
    captured = datetime(2026, 9, 7, 17, 29, tzinfo=timezone.utc)
    manifest = _make_archive(tmp_path, captured_at=captured, target_date=target)
    report = inspect_latest_pit_archive(
        tmp_path / "pit_candidate_archive",
        target_date=target,
        now=datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc),
    )
    assert report["state"] == "valid_candidate"
    assert report["row_count"] == 1

    publication = manifest.parent / "pit-sector-membership-machine.json"
    publication.write_bytes(b'{"rows":[{"symbol":"2330","sector_code":"99"}]}\n')
    tampered = inspect_latest_pit_archive(
        tmp_path / "pit_candidate_archive",
        target_date=target,
        now=datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc),
    )
    assert tampered["state"] == "invalid"
    assert any("pit_archive_candidates_invalid" in str(item) for item in tampered["blockers"])


def test_scheduler_registration_reports_conditions_and_nonzero_last_result(
    tmp_path: Path,
) -> None:
    path = tmp_path / "registration.json"
    _write_json(path, _registration_report(Path(__file__).resolve().parents[1], last_result="267011"))
    report = inspect_scheduler_registration(
        path,
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert report["state"] == "observed_with_blockers"
    assert "scheduler_task_last_result_nonzero:baldr-formal-input-producer-daily:267011" in report["blockers"]
    formal = next(
        item for item in report["tasks"] if item["task_name"] == "baldr-formal-input-producer-daily"
    )
    assert formal["condition_observed"] is True
    assert formal["credit_allowed"] is False


def test_missing_scheduler_registration_is_explicitly_unobserved() -> None:
    report = inspect_scheduler_registration(None, repo_root=Path.cwd())
    assert report["state"] == "not_supplied"
    assert report["credit_allowed"] is False
    assert report["blockers"] == ["scheduler_registration_query_not_supplied"]


def test_readiness_report_hash_tamper_is_rejected(tmp_path: Path) -> None:
    created = datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
    path = _make_readiness_report(tmp_path, created_at=created)
    valid = inspect_formal_readiness_report(
        path,
        target_date=date(2026, 9, 8),
        now=datetime(2026, 9, 7, 18, 1, tzinfo=timezone.utc),
    )
    assert valid["state"] == "current"
    assert valid["blockers"] == []

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["machine_verified_input_count"] = 3
    _write_json(path, payload)
    tampered = inspect_formal_readiness_report(
        path,
        target_date=date(2026, 9, 8),
        now=datetime(2026, 9, 7, 18, 1, tzinfo=timezone.utc),
    )
    assert tampered["state"] == "invalid"
    assert tampered["blockers"] == [
        "formal_readiness_report_invalid:FormalOperationalReadinessError"
    ]


def test_audit_before_windows_keeps_pit_candidate_and_zero_credit(tmp_path: Path) -> None:
    target = date(2026, 9, 8)
    now = datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
    _make_archive(
        tmp_path,
        captured_at=datetime(2026, 9, 7, 17, 29, tzinfo=timezone.utc),
        target_date=target,
    )
    readiness = _make_readiness_report(tmp_path, created_at=now)
    report = audit_formal_operational_readiness(
        publication_root=tmp_path,
        readiness_path=readiness,
        now=now,
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert report["target_taipei_date"] == "2026-09-08"
    assert report["phase"] == "before_pit_cutoff"
    assert report["status"] == "blocked_no_formal_credit"
    assert report["credit_decision"]["decision"] == "no_credit"
    assert report["safety"]["formal_oos_allowed"] is False
    assert report["safety"]["broker_order_allowed"] is False
    assert report["lanes"]["pit"]["archive"]["state"] == "valid_candidate"
    assert report["lanes"]["rule"]["status"] == "waiting_for_natural_window"
    assert "scheduler_registration_query_not_supplied" in report["blockers"]
    assert "rule_window_not_open" in report["blockers"]
    assert "paper_eod_source_window_not_reached" in report["blockers"]


def test_audit_exposes_login_battery_and_due_missed_run_without_credit(
    tmp_path: Path,
) -> None:
    target = date(2026, 9, 8)
    now = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)
    _make_archive(
        tmp_path,
        captured_at=datetime(2026, 9, 7, 17, 29, tzinfo=timezone.utc),
        target_date=target,
    )
    readiness = _make_readiness_report(tmp_path, created_at=now)
    registration = tmp_path / "registration.json"
    _write_json(
        registration,
        _registration_report(Path(__file__).resolve().parents[1]),
    )
    report = audit_formal_operational_readiness(
        publication_root=tmp_path,
        readiness_path=readiness,
        scheduler_registration_path=registration,
        now=now,
        repo_root=Path(__file__).resolve().parents[1],
    )
    blockers = [str(item) for item in report["blockers"]]
    assert "scheduler_task_requires_interactive_login:baldr-pit-sector-membership-preopen-capture-daily" in blockers
    assert "scheduler_task_battery_power_restricted:baldr-pit-sector-membership-preopen-capture-daily" in blockers
    assert "scheduler_task_due_last_run_unobserved:baldr-pit-sector-membership-preopen-capture-daily" in blockers
    assert report["credit_decision"]["decision"] == "no_credit"
    assert report["safety"]["formal_oos_allowed"] is False


def test_public_parser_has_no_clock_override_argument() -> None:
    from scripts.inspect_formal_operational_readiness import _parser

    with pytest.raises(SystemExit):
        _parser().parse_args(["--now", "2026-09-08T00:00:00+08:00"])
