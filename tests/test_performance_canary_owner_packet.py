from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_module.performance_canary_owner_packet import (
    MAX_PERFORMANCE_OWNER_PACKET_BYTES,
    PERFORMANCE_CANARY_OWNER_PACKET_SCHEMA_VERSION,
    build_performance_canary_owner_packet,
    load_performance_canary_owner_packet,
    render_markdown,
    validate_output_path,
)
from scripts.build_performance_canary_owner_packet import main


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _artifacts(tmp_path: Path) -> dict[str, Path]:
    technical = _write(
        tmp_path / "technical.json",
        {
            "schema_version": "technical-indicator-production-canary.v1",
            "status": "confirmation_required",
            "stock_id": "2330",
            "expected_latest_date": "2026-08-28",
            "workers": 2,
            "max_in_flight": 2,
            "production_write_attempted": False,
            "production_sqlite_write_attempted": False,
            "production_worker_enabled": False,
            "rollback": {"available": False},
        },
    )
    worker = _write(
        tmp_path / "worker.json",
        {
            "schema_version": "technical-indicator-worker-recovery.v1",
            "status": "measured",
            "observed_worker_count": 2,
            "production_write_attempted": False,
            "production_sqlite_write_attempted": False,
            "checks": {
                "bounded_in_flight": True,
                "crash_recovery": True,
                "parent_single_writer": True,
                "no_production_write": True,
            },
        },
    )
    broker = _write(
        tmp_path / "broker.json",
        {
            "schema_version": "broker-performance-baseline.v2",
            "status": "measured",
            "production_write_attempted": False,
            "production_sqlite_write_attempted": False,
            "production_fetch_pool_enabled": False,
            "selenium_fallback_serialized": True,
            "selenium_fallback_invocations": 0,
            "single_writer_required": True,
            "bounded_fetch_acceptance": {
                "checks": {
                    "bounded_in_flight": True,
                    "parent_single_writer": True,
                    "worker_did_not_write": True,
                }
            },
        },
    )
    storage = _write(
        tmp_path / "storage.json",
        {
            "schema_version": "ml-direct-chain-maintenance-status.v1",
            "status": "blocked_insufficient_storage",
            "writes_source_database": False,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
            "storage_preflight": {
                "free_bytes": 6,
                "minimum_free_space_bytes": 20,
                "within_minimum_free_space": False,
                "probe_path": "D:/output/release_v4",
            },
        },
    )
    retention_payload = {
        "schema_version": "ml-storage-retention-inventory.v1",
        "status": "capacity_blocked",
        "disk": {"minimum_observed_free_bytes": 6, "within_minimum_free_space": False},
        "safety": {
            "automatic_delete_allowed": False,
            "deletion_attempted": False,
            "move_attempted": False,
        },
        "retention_candidates": [
            {
                "kind": "ml_run_review_candidate",
                "path": "D:/output/release_v4/run",
                "run_id": "allocation-ooc-test",
                "schema_version": "allocation-ooc-training.v5",
                "status": "complete",
                "size_bytes": 1024,
                "file_count": 2,
                "manual_review_required": True,
                "automatic_delete_allowed": False,
                "reversible_action": "owner_confirm_then_move_to_external_archive_or_delete",
            }
        ],
    }
    direct = _write(tmp_path / "retention_direct.json", retention_payload)
    ooc = _write(tmp_path / "retention_ooc.json", retention_payload)
    return {
        "technical_preview_path": technical,
        "worker_recovery_path": worker,
        "broker_canary_path": broker,
        "direct_storage_preflight_path": storage,
        "retention_direct_path": direct,
        "retention_ooc_path": ooc,
    }


def _build_packet(artifacts: dict[str, Path], **roles: str) -> dict:
    return build_performance_canary_owner_packet(
        technical_preview_path=artifacts["technical_preview_path"],
        worker_recovery_path=artifacts["worker_recovery_path"],
        broker_canary_path=artifacts["broker_canary_path"],
        direct_storage_preflight_path=artifacts["direct_storage_preflight_path"],
        retention_direct_path=artifacts["retention_direct_path"],
        retention_ooc_path=artifacts["retention_ooc_path"],
        **roles,
    )


def test_packet_is_bounded_and_non_authorizing(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)

    packet = _build_packet(artifacts)

    assert packet["schema_version"] == PERFORMANCE_CANARY_OWNER_PACKET_SCHEMA_VERSION
    assert packet["packet_status"] == "needs_named_owner_reviewer"
    assert packet["candidate_only"] is True
    assert packet["write_performed"] is False
    assert packet["destructive_action_performed"] is False
    assert packet["production_worker_enabled"] is False
    assert packet["production_fetch_pool_enabled"] is False
    assert packet["automatic_delete_allowed"] is False
    assert packet["direct_ooc_storage"]["within_minimum_free_space"] is False
    assert len(packet["review_records"]) == 4
    assert "Performance Canary Owner Review Packet" in render_markdown(packet)


def test_named_roles_only_change_handoff_status(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)

    packet = _build_packet(
        artifacts,
        owner_role="performance_owner",
        reviewer_role="independent_reviewer",
    )

    assert packet["packet_status"] == "ready_for_owner_review"
    assert packet["owner_role"] == "performance_owner"
    assert packet["reviewer_role"] == "independent_reviewer"
    assert packet["technical_production_canary"]["production_write_attempted"] is False


def test_packet_rejects_unsafe_production_artifact(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    payload = json.loads(artifacts["broker_canary_path"].read_text(encoding="utf-8"))
    payload["production_fetch_pool_enabled"] = True
    artifacts["broker_canary_path"].write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="production_fetch_pool_enabled"):
        _build_packet(artifacts)


def test_output_path_cannot_overwrite_input_or_leave_temp(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    with pytest.raises(ValueError, match="overwrite"):
        validate_output_path(artifacts["technical_preview_path"], input_paths=artifacts)
    outside = Path.cwd() / "performance-canary-packet-test.json"
    try:
        with pytest.raises(ValueError, match="OS TEMP"):
            validate_output_path(outside, input_paths=artifacts)
    finally:
        if outside.exists():
            outside.unlink()


def test_cli_writes_json_and_markdown(tmp_path: Path, capsys) -> None:
    artifacts = _artifacts(tmp_path)
    output_json = tmp_path / "packet.json"
    output_md = tmp_path / "packet.md"

    args = [
        "--technical-preview",
        str(artifacts["technical_preview_path"]),
        "--worker-recovery",
        str(artifacts["worker_recovery_path"]),
        "--broker-canary",
        str(artifacts["broker_canary_path"]),
        "--direct-storage-preflight",
        str(artifacts["direct_storage_preflight_path"]),
        "--retention-direct",
        str(artifacts["retention_direct_path"]),
        "--retention-ooc",
        str(artifacts["retention_ooc_path"]),
        "--output-json",
        str(output_json),
        "--markdown-output",
        str(output_md),
        "--json-output",
    ]

    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == PERFORMANCE_CANARY_OWNER_PACKET_SCHEMA_VERSION
    assert json.loads(output_json.read_text(encoding="utf-8"))["candidate_only"] is True
    assert "Review lanes" in output_md.read_text(encoding="utf-8")


def test_owner_packet_loader_preserves_non_authorizing_boundary(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    packet = _build_packet(artifacts)
    packet_path = _write(tmp_path / "packet.json", packet)

    loaded = load_performance_canary_owner_packet(packet_path)

    assert loaded["packet_status"] == "needs_named_owner_reviewer"
    assert loaded["candidate_only"] is True
    assert loaded["write_performed"] is False
    assert MAX_PERFORMANCE_OWNER_PACKET_BYTES >= packet_path.stat().st_size


def test_owner_packet_loader_rejects_authorizing_mutation(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    packet = _build_packet(artifacts)
    packet["production_fetch_pool_enabled"] = True
    packet_path = _write(tmp_path / "unsafe-packet.json", packet)

    with pytest.raises(ValueError, match="production_fetch_pool_enabled"):
        load_performance_canary_owner_packet(packet_path)
