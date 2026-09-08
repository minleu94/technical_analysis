from __future__ import annotations

import multiprocessing
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from data_module.ml_storage_capacity import (
    BYTES_PER_GIB,
    CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES,
    DEFAULT_HEAVY_PERSISTENT_NEW_BYTES_BUDGET,
    DEFAULT_HEAVY_TEMPORARY_PEAK_BYTES_BUDGET,
    HEAVY_CHAIN_LOCK_FILENAME,
    MLStorageCapacityBudget,
    SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET,
    SCHEDULED_REQUIRED_FREE_BYTES,
    SCHEDULED_SAFETY_RESERVE_BYTES,
    SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET,
    StorageCapacityExceededError,
    StorageCapacityPreflightError,
    acquire_heavy_chain_reservation,
    build_heavy_chain_reservation_handoff_environment,
    directory_size_bytes,
    evaluate_capacity,
    heavy_chain_capacity_budget,
    preflight_capacity,
    release_heavy_chain_reservation,
    resolve_heavy_chain_lock_path,
    resolve_heavy_chain_safety_reserve,
    scheduled_default_capacity_budget,
    validate_heavy_chain_reservation_handoff,
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


def test_preflight_applies_global_temporary_quota_across_filesystems(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    temp_a = tmp_path / "temp-a"
    temp_b = tmp_path / "temp-b"
    output_root.mkdir()
    temp_a.mkdir()
    temp_b.mkdir()
    (temp_a / "a.bin").write_bytes(b"a" * 600)
    (temp_b / "b.bin").write_bytes(b"b" * 600)

    def fake_identity(path: Path) -> str:
        text = str(path)
        if text.startswith(str(temp_b)):
            return "drive-b"
        return "drive-a"

    monkeypatch.setattr(
        "data_module.ml_storage_capacity._filesystem_identity",
        fake_identity,
    )
    monkeypatch.setattr(
        "data_module.ml_storage_capacity.filesystem_usage",
        lambda path: {
            "probe_path": str(path),
            "total_bytes": 10_000,
            "used_bytes": 1_000,
            "free_bytes": 9_000,
        },
    )
    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=100,
        temporary_peak_bytes_budget=1_000,
        safety_reserve_bytes=100,
    )

    with pytest.raises(StorageCapacityExceededError) as raised:
        preflight_capacity(
            probe_path=output_root,
            budget=budget,
            temporary_roots=(temp_a, temp_b),
            temporary_peak_bytes_observed=0,
            stage="cross-drive-total-temp",
        )

    assert "temporary_peak_bytes_budget_exceeded" in raised.value.preflight[
        "blockers"
    ]
    assert len(raised.value.preflight["filesystem_checks"]) == 2


def test_preflight_assigns_persistent_estimate_to_its_actual_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    persistent_root = tmp_path / "persistent"
    output_root.mkdir()
    persistent_root.mkdir()

    def fake_identity(path: Path) -> str:
        return "drive-b" if str(path).startswith(str(persistent_root)) else "drive-a"

    monkeypatch.setattr(
        "data_module.ml_storage_capacity._filesystem_identity",
        fake_identity,
    )
    monkeypatch.setattr(
        "data_module.ml_storage_capacity.filesystem_usage",
        lambda path: {
            "probe_path": str(path),
            "total_bytes": 10_000,
            "used_bytes": 1_000,
            "free_bytes": 9_000,
        },
    )
    result = preflight_capacity(
        probe_path=output_root,
        budget=MLStorageCapacityBudget(
            persistent_new_bytes_budget=100,
            temporary_peak_bytes_budget=100,
            safety_reserve_bytes=100,
        ),
        persistent_roots=(persistent_root,),
        persistent_new_bytes_estimate=100,
        temporary_peak_bytes_observed=0,
        stage="cross-drive-persistent-estimate",
    )

    assert result.within_budget is True
    assert len(result.filesystem_checks) == 2
    persistent_check = next(
        item
        for item in result.filesystem_checks
        if item["persistent_roots"]
    )
    assert persistent_check["persistent_new_bytes_budget"] == 100


def test_preflight_checks_three_filesystems_and_global_temp_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_root = tmp_path / "probe"
    output_root = tmp_path / "output"
    temp_root_a = tmp_path / "temp-a"
    temp_root_b = tmp_path / "temp-b"
    for root in (probe_root, output_root, temp_root_a, temp_root_b):
        root.mkdir()
    (temp_root_a / "a.bin").write_bytes(b"a" * 600)
    (temp_root_b / "b.bin").write_bytes(b"b" * 600)

    def fake_identity(path: Path) -> str:
        text = str(path)
        if text.startswith(str(temp_root_b)):
            return "drive-c"
        if text.startswith(str(output_root)) or text.startswith(str(temp_root_a)):
            return "drive-b"
        return "drive-a"

    monkeypatch.setattr(
        "data_module.ml_storage_capacity._filesystem_identity",
        fake_identity,
    )
    monkeypatch.setattr(
        "data_module.ml_storage_capacity.filesystem_usage",
        lambda path: {
            "probe_path": str(path),
            "total_bytes": 10_000,
            "used_bytes": 1_000,
            "free_bytes": 9_000,
        },
    )

    with pytest.raises(StorageCapacityExceededError) as raised:
        preflight_capacity(
            probe_path=probe_root,
            budget=MLStorageCapacityBudget(
                persistent_new_bytes_budget=100,
                temporary_peak_bytes_budget=1_000,
                safety_reserve_bytes=100,
            ),
            persistent_roots=(output_root,),
            persistent_new_bytes_estimate=100,
            temporary_roots=(temp_root_a, temp_root_b),
            temporary_peak_bytes_observed=0,
            stage="three-drive-global-temp",
        )

    assert "temporary_peak_bytes_budget_exceeded" in raised.value.preflight[
        "blockers"
    ]
    assert {
        item["filesystem_key"]
        for item in raised.value.preflight["filesystem_checks"]
    } == {"drive-a", "drive-b", "drive-c"}


def test_preflight_charges_persistent_estimate_on_destination_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    persistent_root = tmp_path / "persistent"
    output_root.mkdir()
    persistent_root.mkdir()

    def fake_identity(path: Path) -> str:
        return (
            "persistent-drive"
            if str(path).startswith(str(persistent_root))
            else "probe-drive"
        )

    def fake_usage(path: Path) -> dict[str, object]:
        key = fake_identity(path)
        free = 150 if key == "persistent-drive" else 10_000
        return {
            "probe_path": str(path),
            "total_bytes": 10_000,
            "used_bytes": 10_000 - free,
            "free_bytes": free,
        }

    monkeypatch.setattr(
        "data_module.ml_storage_capacity._filesystem_identity",
        fake_identity,
    )
    monkeypatch.setattr(
        "data_module.ml_storage_capacity.filesystem_usage",
        fake_usage,
    )
    with pytest.raises(StorageCapacityExceededError) as raised:
        preflight_capacity(
            probe_path=output_root,
            budget=MLStorageCapacityBudget(
                persistent_new_bytes_budget=100,
                temporary_peak_bytes_budget=100,
                safety_reserve_bytes=100,
            ),
            persistent_roots=(persistent_root,),
            persistent_new_bytes_estimate=100,
            temporary_peak_bytes_observed=0,
            stage="persistent-destination-headroom",
        )

    assert any(
        blocker.startswith("filesystem:persistent-drive:")
        for blocker in raised.value.preflight["blockers"]
    )


def test_production_lock_path_rejects_noncanonical_release_lock(
    tmp_path: Path,
) -> None:
    output = tmp_path / "release_v4" / "derived" / "run"
    canonical = output.parents[1] / HEAVY_CHAIN_LOCK_FILENAME
    assert resolve_heavy_chain_lock_path(output) == canonical.resolve()
    with pytest.raises(ValueError, match="canonical"):
        resolve_heavy_chain_lock_path(
            output,
            explicit_path=tmp_path / "other" / HEAVY_CHAIN_LOCK_FILENAME,
        )


def test_locked_recheck_observes_external_capacity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取得 reservation 後須以新的 filesystem 觀測重新判斷 headroom。"""

    output_root = tmp_path / "output"
    output_root.mkdir()
    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=100,
        temporary_peak_bytes_budget=100,
        safety_reserve_bytes=100,
    )
    usages = iter((1000, 250))

    def fake_usage(path: Path) -> dict[str, object]:
        free = next(usages)
        return {
            "probe_path": str(path),
            "total_bytes": 10_000,
            "used_bytes": 10_000 - free,
            "free_bytes": free,
        }

    monkeypatch.setattr(
        "data_module.ml_storage_capacity.filesystem_usage",
        fake_usage,
    )
    first = preflight_capacity(
        probe_path=output_root,
        budget=budget,
        persistent_new_bytes_estimate=100,
        temporary_peak_bytes_observed=100,
        stage="before-reservation",
    )
    assert first.within_budget is True
    reservation = acquire_heavy_chain_reservation(
        output_root / HEAVY_CHAIN_LOCK_FILENAME
    )
    assert reservation is not None
    try:
        with pytest.raises(StorageCapacityExceededError) as raised:
            preflight_capacity(
                probe_path=output_root,
                budget=budget,
                persistent_new_bytes_estimate=100,
                temporary_peak_bytes_observed=100,
                stage="after-reservation-recheck",
            )
        assert raised.value.preflight["stage"] == (
            "after-reservation-recheck"
        )
        assert "required_free_headroom_unavailable" in raised.value.preflight[
            "blockers"
        ]
    finally:
        release_heavy_chain_reservation(reservation)


def test_directory_size_does_not_follow_symlink_target(tmp_path: Path) -> None:
    target = tmp_path / "target.bin"
    target.write_bytes(b"x" * 17)
    link = tmp_path / "link.bin"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this fixture")

    assert directory_size_bytes(link) == 0


def test_directory_size_missing_path_is_zero(tmp_path: Path) -> None:
    assert directory_size_bytes(tmp_path / "not-created") == 0


def test_directory_size_permission_error_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "protected"
    root.mkdir()

    def deny_scandir(_path: object) -> object:
        raise PermissionError("fixture permission denied")

    monkeypatch.setattr("data_module.ml_storage_capacity.os.scandir", deny_scandir)

    with pytest.raises(StorageCapacityPreflightError) as raised:
        directory_size_bytes(root)

    assert raised.value.preflight == {
        "path": str(root),
        "error_type": "PermissionError",
    }


@pytest.mark.skipif(os.name != "nt", reason="requires a Windows junction")
def test_directory_size_skips_real_windows_junction(tmp_path: Path) -> None:
    target = tmp_path / "junction-target"
    target.mkdir()
    (target / "outside.bin").write_bytes(b"x" * 17)
    root = tmp_path / "scan-root"
    root.mkdir()
    junction = root / "junction"
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        diagnostic = f"{completed.stdout}\r\n{completed.stderr}".lower()
        if "syntax" in diagnostic or "filename" in diagnostic:
            raise AssertionError(f"mklink invocation was malformed: {diagnostic}")
        pytest.skip(f"junction creation unavailable: {completed.stderr}")

    assert junction.is_dir()
    assert directory_size_bytes(root) == 0


def test_scheduled_default_policy_keeps_two_hundred_gib_reserve() -> None:
    budget = scheduled_default_capacity_budget()

    assert budget.as_dict()["safety_reserve_bytes"] == SCHEDULED_SAFETY_RESERVE_BYTES
    assert budget.persistent_new_bytes_budget == SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET
    assert budget.temporary_peak_bytes_budget == SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET
    assert SCHEDULED_SAFETY_RESERVE_BYTES == 200 * BYTES_PER_GIB
    assert SCHEDULED_REQUIRED_FREE_BYTES == (
        200 * BYTES_PER_GIB
        + SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET
        + SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET
    )


def test_heavy_budget_defaults_and_low_reserve_are_explicit() -> None:
    budget = heavy_chain_capacity_budget()

    assert budget.persistent_new_bytes_budget == (
        DEFAULT_HEAVY_PERSISTENT_NEW_BYTES_BUDGET
    )
    assert budget.temporary_peak_bytes_budget == (
        DEFAULT_HEAVY_TEMPORARY_PEAK_BYTES_BUDGET
    )
    assert budget.safety_reserve_bytes == (
        CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES
    )
    with pytest.raises(ValueError, match="at least"):
        resolve_heavy_chain_safety_reserve(125 * BYTES_PER_GIB)


def test_unknown_estimates_are_explicit_capacity_blockers() -> None:
    result = evaluate_capacity(
        budget=MLStorageCapacityBudget(safety_reserve_bytes=10),
        usage={"probe_path": "fixture", "total_bytes": 100, "used_bytes": 0, "free_bytes": 100},
        persistent_new_bytes_estimate=None,
        temporary_peak_bytes_observed=None,
        stage="unknown-estimate",
    )

    assert result.within_budget is False
    assert result.persistent_new_bytes_estimate is None
    assert result.temporary_peak_bytes_observed is None
    assert result.blockers == (
        "persistent_new_bytes_estimate_unknown",
        "temporary_peak_bytes_estimate_unknown",
    )


def _hold_heavy_chain_reservation(
    lock_path: str,
    acquired: object,
    release: object,
) -> None:
    reservation = acquire_heavy_chain_reservation(Path(lock_path))
    acquired.set()  # type: ignore[attr-defined]
    if reservation is None:
        return
    try:
        release.wait(10)  # type: ignore[attr-defined]
    finally:
        release_heavy_chain_reservation(reservation)


def _exit_after_heavy_chain_reservation(
    lock_path: str,
    acquired: object,
) -> None:
    reservation = acquire_heavy_chain_reservation(Path(lock_path))
    acquired.set()  # type: ignore[attr-defined]
    os._exit(0 if reservation is not None else 3)


def test_heavy_chain_reservation_is_process_safe_and_recoverable(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    lock_path = tmp_path / HEAVY_CHAIN_LOCK_FILENAME
    acquired = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_heavy_chain_reservation,
        args=(str(lock_path), acquired, release),
    )
    process.start()
    try:
        assert acquired.wait(10)
        assert acquire_heavy_chain_reservation(lock_path) is None
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(10)
    assert process.exitcode == 0
    recovered = acquire_heavy_chain_reservation(lock_path)
    assert recovered is not None
    release_heavy_chain_reservation(recovered)
    # lock 檔是穩定 metadata；reservation lifecycle 由 OS handle 釋放控制，
    # 不靠 unlink。
    assert lock_path.is_file()


def test_heavy_chain_reservation_is_released_by_process_exit(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    lock_path = tmp_path / HEAVY_CHAIN_LOCK_FILENAME
    acquired = context.Event()
    process = context.Process(
        target=_exit_after_heavy_chain_reservation,
        args=(str(lock_path), acquired),
    )
    process.start()
    try:
        assert acquired.wait(10)
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(10)
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)
    assert process.exitcode == 0

    recovered = acquire_heavy_chain_reservation(lock_path)
    assert recovered is not None
    release_heavy_chain_reservation(recovered)


def test_heavy_chain_reservation_releases_after_failure(tmp_path: Path) -> None:
    lock_path = tmp_path / HEAVY_CHAIN_LOCK_FILENAME
    reservation = acquire_heavy_chain_reservation(lock_path)
    assert reservation is not None
    try:
        raise RuntimeError("simulated chain failure")
    except RuntimeError:
        pass
    finally:
        release_heavy_chain_reservation(reservation)

    recovered = acquire_heavy_chain_reservation(lock_path)
    assert recovered is not None
    release_heavy_chain_reservation(recovered)


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


def test_scheduled_capacity_helpers_reject_legacy_low_threshold() -> None:
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

    with pytest.raises(ValueError, match="at least"):
        direct_runner._capacity_budget_from_args(direct_args)
    with pytest.raises(ValueError, match="at least"):
        raw_runner._capacity_budget_from_args(raw_args)


def _run_handoff_child(
    lock_path: Path,
    environment: dict[str, str],
    source: str,
    *,
    reservation: object | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = dict(environment)
    environment["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (
            str(Path(__file__).resolve().parents[1]),
            environment.get("PYTHONPATH", ""),
        )
        if value
    )
    process = subprocess.Popen(
        [sys.executable, "-c", source, str(lock_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if reservation is not None:
        reservation.authorize_child(process.pid)  # type: ignore[attr-defined]
    stdout, stderr = process.communicate()
    return subprocess.CompletedProcess(
        process.args,
        process.returncode,
        stdout,
        stderr,
    )


def test_reservation_handoff_rejects_legacy_marker_and_unowned_payload(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / HEAVY_CHAIN_LOCK_FILENAME
    reservation = acquire_heavy_chain_reservation(lock_path)
    assert reservation is not None
    try:
        marker_environment = os.environ.copy()
        marker_environment["BALDR_ML_HEAVY_CHAIN_RESERVATION_HELD"] = "1"
        marker_result = _run_handoff_child(
            lock_path,
            marker_environment,
            """
from pathlib import Path
import sys
from data_module.ml_storage_capacity import (
    StorageCapacityError,
    validate_heavy_chain_reservation_handoff,
)
try:
    validate_heavy_chain_reservation_handoff(Path(sys.argv[1]))
except StorageCapacityError:
    raise SystemExit(0)
raise SystemExit(1)
""",
        )
        assert marker_result.returncode == 0, marker_result.stderr

        unowned_environment = os.environ.copy()
        unowned_environment["BALDR_ML_HEAVY_CHAIN_RESERVATION_HELD"] = json.dumps(
            {
                "schema_version": "ml-heavy-chain-reservation-handoff.v1",
                "lock_path": str(lock_path.resolve()),
                "owner_pid": os.getpid(),
                "parent_pid": os.getppid(),
                "owner_nonce": "x" * 48,
            },
            separators=(",", ":"),
        )
        unowned_result = _run_handoff_child(
            lock_path,
            unowned_environment,
            """
from pathlib import Path
import sys
from data_module.ml_storage_capacity import (
    StorageCapacityError,
    validate_heavy_chain_reservation_handoff,
)
try:
    validate_heavy_chain_reservation_handoff(Path(sys.argv[1]))
except StorageCapacityError:
    raise SystemExit(0)
raise SystemExit(1)
""",
        )
        assert unowned_result.returncode == 0, unowned_result.stderr
    finally:
        release_heavy_chain_reservation(reservation)


def test_reservation_handoff_accepts_real_parent_and_forwards_to_child(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / HEAVY_CHAIN_LOCK_FILENAME
    reservation = acquire_heavy_chain_reservation(lock_path)
    assert reservation is not None
    try:
        environment = build_heavy_chain_reservation_handoff_environment(
            reservation,
            environment=os.environ.copy(),
            parent_pid=os.getpid(),
        )
        result = _run_handoff_child(
            lock_path,
            environment,
            '''
import os
from pathlib import Path
import subprocess
import sys
from data_module.ml_storage_capacity import (
    authorize_heavy_chain_reservation_handoff_child,
    forward_heavy_chain_reservation_handoff_environment,
    validate_heavy_chain_reservation_handoff,
)
lock_path = Path(sys.argv[1])
handoff = validate_heavy_chain_reservation_handoff(lock_path)
assert handoff is not None
try:
    child_environment = forward_heavy_chain_reservation_handoff_environment(
        environment=os.environ
    )
    grandchild = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
from pathlib import Path
import sys
from data_module.ml_storage_capacity import validate_heavy_chain_reservation_handoff
lease = validate_heavy_chain_reservation_handoff(Path(sys.argv[1]))
assert lease is not None
lease.close()
""",
            str(lock_path),
        ],
        env=child_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    authorize_heavy_chain_reservation_handoff_child(
        grandchild.pid,
        environment=child_environment,
    )
    _stdout, _stderr = grandchild.communicate()
    raise SystemExit(grandchild.returncode)
finally:
    handoff.close()
''',
            reservation=reservation,
        )
        assert result.returncode == 0, result.stderr
    finally:
        release_heavy_chain_reservation(reservation)


def test_reservation_handoff_child_stops_after_owner_exit(tmp_path: Path) -> None:
    """owner 結束後 watchdog 必須停止仍持有舊 handoff 的 child。"""

    repository_root = Path(__file__).resolve().parents[1]
    lock_path = tmp_path / HEAVY_CHAIN_LOCK_FILENAME
    ready_path = tmp_path / "handoff-ready"
    child_pid_path = tmp_path / "handoff-child-pid"
    child_script = tmp_path / "handoff-child.py"
    parent_script = tmp_path / "handoff-parent.py"
    child_script.write_text(
        """
import os
from pathlib import Path
import sys
import time
from data_module.ml_storage_capacity import validate_heavy_chain_reservation_handoff

lease = validate_heavy_chain_reservation_handoff(Path(sys.argv[1]))
assert lease is not None
Path(os.environ["BALDR_HANDOFF_READY"]).write_text("ready", encoding="utf-8")
while True:
    time.sleep(0.05)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    parent_script.write_text(
        """
import os
from pathlib import Path
import subprocess
import sys
import time
from data_module.ml_storage_capacity import (
    acquire_heavy_chain_reservation,
    build_heavy_chain_reservation_handoff_environment,
)

lock_path = Path(sys.argv[1])
reservation = acquire_heavy_chain_reservation(lock_path)
assert reservation is not None
environment = build_heavy_chain_reservation_handoff_environment(
    reservation,
    environment=os.environ.copy(),
    parent_pid=os.getpid(),
)
child = subprocess.Popen(
    [sys.executable, os.environ["BALDR_HANDOFF_CHILD"], str(lock_path)],
    env=environment,
)
reservation.authorize_child(child.pid)
Path(os.environ["BALDR_HANDOFF_CHILD_PID"]).write_text(
    str(child.pid), encoding="utf-8"
)
deadline = time.monotonic() + 5
while time.monotonic() < deadline and not Path(
    os.environ["BALDR_HANDOFF_READY"]
).is_file():
    time.sleep(0.05)
os._exit(0)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "BALDR_HANDOFF_CHILD": str(child_script),
            "BALDR_HANDOFF_READY": str(ready_path),
            "BALDR_HANDOFF_CHILD_PID": str(child_pid_path),
            "PYTHONPATH": os.pathsep.join(
                value
                for value in (str(repository_root), environment.get("PYTHONPATH", ""))
                if value
            ),
        }
    )
    parent = subprocess.Popen(
        [sys.executable, str(parent_script), str(lock_path)],
        cwd=repository_root,
        env=environment,
    )
    try:
        assert parent.wait(timeout=10) == 0
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not child_pid_path.is_file():
            time.sleep(0.05)
        assert child_pid_path.is_file()
        actual_child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        # 以既有 child PID 觀察 owner 結束後 watchdog 的返回碼。
        import psutil

        observed = psutil.Process(actual_child_pid)
        assert ready_path.read_text(encoding="utf-8") == "ready"
        assert observed.wait(timeout=10) == 75
    finally:
        if parent.poll() is None:
            parent.terminate()
            parent.wait(timeout=5)


def test_owner_exit_keeps_child_gate_against_immediate_competitor(
    tmp_path: Path,
) -> None:
    """owner 突然結束時，持續寫入的 child gate 仍阻擋新 chain。"""

    repository_root = Path(__file__).resolve().parents[1]
    lock_path = tmp_path / HEAVY_CHAIN_LOCK_FILENAME
    ready_path = tmp_path / "gate-ready"
    owner_exit_path = tmp_path / "owner-exit"
    owner_pid_path = tmp_path / "gate-owner-pid"
    writing_path = tmp_path / "child-writing"
    result_path = tmp_path / "competitor-result"
    child_pid_path = tmp_path / "gate-child-pid"
    child_script = tmp_path / "gate-child.py"
    parent_script = tmp_path / "gate-parent.py"
    competitor_script = tmp_path / "gate-competitor.py"
    child_script.write_text(
        """
import os
from pathlib import Path
import sys
import time
import data_module.ml_storage_capacity as capacity

# 讓 assertion 有足夠窗口觀察「owner 已死、child 仍寫入」；正式
# production watchdog 仍維持 0.25 秒，不由此 fixture 改變。
capacity._HANDOFF_WATCHDOG_INTERVAL_SECONDS = 5.0
lease = capacity.validate_heavy_chain_reservation_handoff(Path(sys.argv[1]))
assert lease is not None
Path(os.environ["BALDR_GATE_READY"]).write_text("ready", encoding="utf-8")
while True:
    writing_path = Path(os.environ["BALDR_GATE_WRITING"])
    # Windows 讀取端可能短暫持有 target；以唯一 staging 並 bounded
    # 重試 replace，避免測試 heartbeat 自身製造假 child exit。
    writing_tmp = writing_path.with_name(
        f".{writing_path.name}.{os.getpid()}.tmp"
    )
    writing_tmp.write_text(str(time.time_ns()), encoding="utf-8")
    replaced = False
    for _ in range(100):
        try:
            os.replace(writing_tmp, writing_path)
            replaced = True
            break
        except PermissionError:
            time.sleep(0.001)
    if not replaced:
        raise RuntimeError("heartbeat replace remained locked")
    time.sleep(0.01)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    parent_script.write_text(
        """
import os
from pathlib import Path
import subprocess
import sys
import time
from data_module.ml_storage_capacity import (
    acquire_heavy_chain_reservation,
    build_heavy_chain_reservation_handoff_environment,
)

lock_path = Path(sys.argv[1])
reservation = acquire_heavy_chain_reservation(lock_path)
assert reservation is not None
Path(os.environ["BALDR_GATE_OWNER_PID"]).write_text(
    str(os.getpid()), encoding="utf-8"
)
environment = build_heavy_chain_reservation_handoff_environment(
    reservation,
    environment=os.environ.copy(),
    parent_pid=os.getpid(),
)
child = subprocess.Popen(
    [sys.executable, os.environ["BALDR_GATE_CHILD"], str(lock_path)],
    env=environment,
)
reservation.authorize_child(child.pid)
Path(os.environ["BALDR_GATE_CHILD_PID"]).write_text(
    str(child.pid), encoding="utf-8"
)
deadline = time.monotonic() + 5
while time.monotonic() < deadline and not Path(
    os.environ["BALDR_GATE_READY"]
).is_file():
    time.sleep(0.01)
assert Path(os.environ["BALDR_GATE_READY"]).is_file()
Path(os.environ["BALDR_GATE_OWNER_EXIT"]).write_text(
    str(time.time_ns()), encoding="utf-8"
)
os._exit(0)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    competitor_script.write_text(
        """
import json
import os
from pathlib import Path
import sys
import time
import psutil
import data_module.ml_storage_capacity as capacity

deadline = time.monotonic() + 5
while time.monotonic() < deadline and not Path(
    os.environ["BALDR_GATE_OWNER_EXIT"]
).is_file():
    time.sleep(0.005)
owner_exit_ns = int(Path(os.environ["BALDR_GATE_OWNER_EXIT"]).read_text())
owner_pid = int(Path(os.environ["BALDR_GATE_OWNER_PID"]).read_text())
# owner-exit marker 在 owner os._exit 前寫出；先等到真正的 owner PID
# 已終止，才能排除 canonical lock 仍由 owner 持有的假陽性。
while time.monotonic() < deadline and psutil.pid_exists(owner_pid):
    time.sleep(0.005)
owner_terminal = not psutil.pid_exists(owner_pid)

child_pid = int(Path(os.environ["BALDR_GATE_CHILD_PID"]).read_text())
heartbeat_after_owner_exit = False
heartbeat_deadline = time.monotonic() + 2
while time.monotonic() < heartbeat_deadline:
    try:
        heartbeat_after_owner_exit = (
            int(Path(os.environ["BALDR_GATE_WRITING"]).read_text()) >= owner_exit_ns
        )
    except (OSError, ValueError):
        heartbeat_after_owner_exit = False
    if heartbeat_after_owner_exit:
        break
    time.sleep(0.005)

# 蓄意移除 sidecar，並先用底層 lock API 驗證 canonical OS lock 已可取得；
# 接著 public acquire 仍須被 child 實際持有的 handoff gate 阻擋。
Path(str(Path(sys.argv[1])) + ".owner.json").unlink(missing_ok=True)
canonical_handle = None
canonical_deadline = time.monotonic() + 2
while time.monotonic() < canonical_deadline:
    canonical_handle = capacity._open_locked_file(Path(sys.argv[1]))
    if canonical_handle is not None:
        break
    time.sleep(0.005)
canonical_available = canonical_handle is not None
if canonical_handle is not None:
    capacity._unlock_handle(canonical_handle)
    canonical_handle.close()
child_alive_before_public = psutil.pid_exists(child_pid)
reservation = capacity.acquire_heavy_chain_reservation(Path(sys.argv[1]))
public_result = "acquired" if reservation is not None else "blocked"
if reservation is not None:
    capacity.release_heavy_chain_reservation(reservation)
Path(os.environ["BALDR_GATE_RESULT"]).write_text(
    json.dumps(
        {
            "owner_terminal": owner_terminal,
            "canonical_available": canonical_available,
            "child_alive_before_public": child_alive_before_public,
            "heartbeat_after_owner_exit": heartbeat_after_owner_exit,
            "public_result": public_result,
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "BALDR_GATE_CHILD": str(child_script),
            "BALDR_GATE_READY": str(ready_path),
            "BALDR_GATE_OWNER_EXIT": str(owner_exit_path),
            "BALDR_GATE_OWNER_PID": str(owner_pid_path),
            "BALDR_GATE_WRITING": str(writing_path),
            "BALDR_GATE_RESULT": str(result_path),
            "BALDR_GATE_CHILD_PID": str(child_pid_path),
            "PYTHONPATH": os.pathsep.join(
                value
                for value in (str(repository_root), environment.get("PYTHONPATH", ""))
                if value
            ),
        }
    )
    parent = subprocess.Popen(
        [sys.executable, str(parent_script), str(lock_path)],
        cwd=repository_root,
        env=environment,
    )
    competitor = subprocess.Popen(
        [sys.executable, str(competitor_script), str(lock_path)],
        cwd=repository_root,
        env=environment,
    )
    try:
        assert parent.wait(timeout=10) == 0
        assert competitor.wait(timeout=10) == 0
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not result_path.is_file():
            time.sleep(0.01)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result == {
            "canonical_available": True,
            "child_alive_before_public": True,
            "heartbeat_after_owner_exit": True,
            "owner_terminal": True,
            "public_result": "blocked",
        }
        assert writing_path.is_file()
        assert int(writing_path.read_text(encoding="utf-8")) >= int(
            owner_exit_path.read_text(encoding="utf-8")
        )
        # child gate eventually sees owner loss; only then may a new owner
        # recover the canonical reservation.
        import psutil

        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and not child_pid_path.is_file():
            time.sleep(0.01)
        assert child_pid_path.is_file()
        child = psutil.Process(int(child_pid_path.read_text(encoding="utf-8")))
        assert child.wait(timeout=12) == 75
        recovered = acquire_heavy_chain_reservation(lock_path)
        assert recovered is not None
        release_heavy_chain_reservation(recovered)
    finally:
        for process in (competitor, parent):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
