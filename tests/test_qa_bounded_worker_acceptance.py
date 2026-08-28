from __future__ import annotations

import pytest

from scripts import qa_bounded_worker_acceptance as probe


def test_bounded_worker_acceptance_proves_retry_cancel_and_single_writer() -> None:
    report = probe.measure_bounded_worker_acceptance(
        max_workers=2,
        max_in_flight=4,
        max_retries=1,
        cancel_after=3,
    )

    assert report["status"] == "measured"
    assert all(report["checks"].values())
    assert report["read_only"] is True
    assert report["write_attempted"] is False
    assert report["production_worker_enabled"] is False
    assert report["parallelism_enabled"] is False
    assert report["synthetic_parallelism_enabled"] is True
    assert report["observed_worker_count"] == 2
    assert report["single_writer_required"] is True

    full = report["scenarios"]["full_completion"]
    assert full["duplicate_input_ids"] == ["task-normal-3"]
    assert full["retry_count"] == 1
    assert full["failed_ids"] == ["task-permanent-failure"]
    assert "task-normal-3" in full["committed_ids"]
    assert full["worker_write_attempts"] == 0
    assert full["max_observed_in_flight"] <= 4

    cancellation = report["scenarios"]["cooperative_cancellation"]
    assert cancellation["cancellation_requested"] is True
    assert cancellation["cancelled_ids"]
    assert cancellation["discarded_after_cancel_count"] >= 0
    assert cancellation["worker_write_attempts"] == 0
    assert cancellation["max_observed_in_flight"] <= 4


def test_bounded_worker_acceptance_rejects_unbounded_options() -> None:
    with pytest.raises(ValueError, match="max_workers"):
        probe.measure_bounded_worker_acceptance(max_workers=9)
    with pytest.raises(ValueError, match="max_in_flight"):
        probe.measure_bounded_worker_acceptance(max_in_flight=33)
    with pytest.raises(ValueError, match="max_retries"):
        probe.measure_bounded_worker_acceptance(max_retries=6)
    with pytest.raises(ValueError, match="cancel_after"):
        probe.measure_bounded_worker_acceptance(cancel_after=0)
