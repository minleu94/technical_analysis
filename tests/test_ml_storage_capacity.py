from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from data_module.ml_storage_capacity import (
    BYTES_PER_GIB,
    MLStorageCapacityBudget,
    StorageCapacityExceededError,
    evaluate_capacity,
    preflight_capacity,
)
from data_module import portfolio_ml_direct_numeric_store as direct_store
from scripts.scheduled import run_ml_direct_chain_maintenance as direct_runner
from scripts.scheduled import run_ml_raw_pit_refresh as raw_runner


def test_capacity_budget_reports_three_independent_limits() -> None:
    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=35 * BYTES_PER_GIB,
        temporary_peak_bytes_budget=40 * BYTES_PER_GIB,
        safety_reserve_bytes=100 * BYTES_PER_GIB,
    )

    assert budget.as_dict() == {
        "persistent_new_bytes_budget": 35 * BYTES_PER_GIB,
        "temporary_peak_bytes_budget": 40 * BYTES_PER_GIB,
        "safety_reserve_bytes": 100 * BYTES_PER_GIB,
        "persistent_storage_budget_bytes": 35 * BYTES_PER_GIB,
        "temporary_storage_budget_bytes": 40 * BYTES_PER_GIB,
    }


def test_capacity_evaluation_requires_budget_plus_reserve_headroom() -> None:
    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=300,
        temporary_peak_bytes_budget=200,
        safety_reserve_bytes=100,
    )
    result = evaluate_capacity(
        budget=budget,
        usage={"probe_path": "fixture", "total_bytes": 1_000, "used_bytes": 0, "free_bytes": 599},
        persistent_new_bytes_estimate=300,
        temporary_peak_bytes_observed=200,
        stage="fixture",
    )

    assert result.required_free_bytes == 600
    assert result.within_persistent_budget is True
    assert result.within_temporary_budget is True
    assert result.within_safety_reserve is True
    assert result.within_headroom is False
    assert result.within_budget is False
    assert "required_free_headroom_unavailable" in result.blockers


def test_preflight_fails_closed_without_writing_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=300,
        temporary_peak_bytes_budget=200,
        safety_reserve_bytes=100,
    )
    monkeypatch.setattr(
        "data_module.ml_storage_capacity.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=1_000, used=0, free=599),
    )

    with pytest.raises(StorageCapacityExceededError) as raised:
        preflight_capacity(
            probe_path=output_root,
            budget=budget,
            stage="fixture_before_year",
            persistent_new_bytes_estimate=300,
            temporary_peak_bytes_observed=200,
        )

    assert raised.value.preflight["stage"] == "fixture_before_year"
    assert raised.value.preflight["within_budget"] is False
    assert not tuple(output_root.iterdir())


def test_directory_size_does_not_follow_symlink_target(tmp_path: Path) -> None:
    target = tmp_path / "target.bin"
    target.write_bytes(b"x" * 17)
    link = tmp_path / "link.bin"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this fixture")

    from data_module.ml_storage_capacity import directory_size_bytes

    assert directory_size_bytes(link) == 0


def test_incomplete_checkpoint_keeps_capacity_failure_for_resume(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    capacity = {
        "stage": "year_2024_checkpoint",
        "within_budget": False,
        "blockers": ["required_free_headroom_unavailable"],
    }

    direct_store._write_incomplete_checkpoint(
        checkpoint_path=checkpoint_path,
        run_id="run-1",
        raw_manifest_hash="sha256:" + "a" * 64,
        completed={2023: {"year": 2023, "manifest_hash": "sha256:" + "b" * 64}},
        peak_temporary_bytes=42,
        capacity_preflight=capacity,
        failure={"error_type": "StorageCapacityExceededError"},
    )

    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert payload["complete"] is False
    assert payload["completed_years"] == [
        {"year": 2023, "manifest_hash": "sha256:" + "b" * 64}
    ]
    assert payload["capacity_preflight"] == capacity
    assert payload["failure"]["error_type"] == "StorageCapacityExceededError"


def test_direct_chain_parser_defaults_and_command_forward_direct_budget() -> None:
    args = direct_runner._parser().parse_args([])

    assert args.temporary_storage_budget_bytes == (
        direct_runner._DEFAULT_DIRECT_TEMPORARY_STORAGE_BUDGET_BYTES
    )
    assert args.persistent_storage_budget_bytes == (
        direct_runner._DEFAULT_DIRECT_PERSISTENT_STORAGE_BUDGET_BYTES
    )


def test_scheduled_capacity_helpers_keep_legacy_threshold_compatible() -> None:
    direct_args = SimpleNamespace(
        minimum_free_space_bytes=20,
        persistent_storage_budget_bytes=300,
        temporary_storage_budget_bytes=200,
        safety_reserve_bytes=None,
    )
    raw_args = SimpleNamespace(
        minimum_free_space_bytes=20,
        persistent_storage_budget_bytes=300,
        temporary_storage_budget_bytes=200,
        safety_reserve_bytes=None,
    )

    assert direct_runner._capacity_budget_from_args(direct_args).as_dict()[
        "safety_reserve_bytes"
    ] == 20
    assert raw_runner._capacity_budget_from_args(raw_args).as_dict()[
        "temporary_storage_budget_bytes"
    ] == 200
