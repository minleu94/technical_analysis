from __future__ import annotations

from pathlib import Path

import pytest

from scripts import qa_broker_bounded_fetch_acceptance as probe


def test_broker_fetch_probe_requires_explicit_confirmation_without_writes(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "staging"
    protected_root = tmp_path / "protected"
    staging_root.mkdir()
    protected_root.mkdir()

    report = probe.measure_bounded_fetch_acceptance(
        staging_root=staging_root,
        protected_roots=(protected_root,),
    )

    assert report["status"] == "confirmation_required"
    assert report["staging_write_attempted"] is False
    assert report["production_write_attempted"] is False
    assert list(staging_root.iterdir()) == []


def test_broker_fetch_probe_rejects_staging_inside_protected_root(tmp_path: Path) -> None:
    protected_root = tmp_path / "protected"
    staging_root = protected_root / "staging"
    protected_root.mkdir()
    staging_root.mkdir()

    report = probe.measure_bounded_fetch_acceptance(
        staging_root=staging_root,
        protected_roots=(protected_root,),
        confirm_broker_fetch_probe=True,
    )

    assert report["status"] == "blocked"
    assert report["blocker"] == "staging_root_inside_protected_root"
    assert list(staging_root.iterdir()) == []


def test_broker_fetch_probe_measures_bounded_retry_rate_limit_and_single_writer(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "staging"
    protected_root = tmp_path / "protected"
    staging_root.mkdir()
    protected_root.mkdir()

    report = probe.measure_bounded_fetch_acceptance(
        staging_root=staging_root,
        protected_roots=(protected_root,),
        confirm_broker_fetch_probe=True,
        max_tasks=9,
        max_workers=2,
        max_in_flight=4,
        max_retries=1,
        rate_limit_seconds=0.001,
        response_delay_seconds=0.005,
    )

    assert report["status"] == "measured"
    assert report["network_enabled"] is False
    assert report["staging_fetch_pool_enabled"] is True
    assert report["production_fetch_pool_enabled"] is False
    assert report["staging_write_attempted"] is True
    assert report["production_write_attempted"] is False
    assert report["sqlite_write_attempted"] is False
    assert report["selenium_fallback_invocations"] == 0
    assert report["selenium_fallback_serialized"] is True
    assert report["worker_write_attempts"] == 0
    assert report["single_writer_required"] is True

    acceptance = report["bounded_fetch_acceptance"]
    assert all(acceptance["checks"].values())
    assert acceptance["retry_count"] == 1
    assert acceptance["duplicate_suppressed_count"] == 1
    assert acceptance["failed_ids"] == ["9200_9200|2026-06-12|amount"]
    assert acceptance["max_observed_in_flight"] <= 4
    assert acceptance["worker_thread_count"] >= 1
    assert acceptance["transport"]["max_active"] >= 1
    assert report["rows"]["written_record_count"] == 7
    assert report["cleanup_succeeded"] is True
    assert list(staging_root.iterdir()) == []


def test_broker_fetch_probe_requires_full_scenario_task_bound(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    protected_root = tmp_path / "protected"
    staging_root.mkdir()
    protected_root.mkdir()

    with pytest.raises(ValueError, match="max_tasks"):
        probe.measure_bounded_fetch_acceptance(
            staging_root=staging_root,
            protected_roots=(protected_root,),
            max_tasks=8,
        )
