from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path
import sys
from typing import Any

import pytest

from data_module import portfolio_ml_direct_numeric_store as direct_store
from data_module.ml_storage_capacity import StorageCapacityError
from data_module.portfolio_ml_direct_numeric_store import (
    PortfolioMLDirectNumericStoreBuilder,
)
from tests.test_ml_direct_numeric_shared_reuse import (
    _build_raw,
    _direct_request,
)


pytestmark = pytest.mark.usefixtures("synthetic_ml_capacity")


def _dependency_snapshot() -> tuple[dict[str, Any], str]:
    payload = direct_store._direct_computation_dependency_payload()
    return payload, direct_store._sha256_json(payload)


def _write_checkpoint(
    path: Path,
    *,
    dependencies: dict[str, Any],
    dependency_hash: str,
) -> None:
    direct_store._write_incomplete_checkpoint(
        checkpoint_path=path,
        run_id="run-1",
        raw_manifest_hash="sha256:" + "a" * 64,
        computation_dependency_hash=dependency_hash,
        computation_dependencies=dependencies,
        completed={},
        peak_temporary_bytes=0,
    )


def test_resume_requires_matching_dependency_snapshot(tmp_path: Path) -> None:
    dependencies, dependency_hash = _dependency_snapshot()
    checkpoint_path = tmp_path / "checkpoint.json"
    _write_checkpoint(
        checkpoint_path,
        dependencies=dependencies,
        dependency_hash=dependency_hash,
    )

    loaded = direct_store._load_checkpoint(
        path=checkpoint_path,
        run_id="run-1",
        raw_manifest_hash="sha256:" + "a" * 64,
        computation_dependency_hash=dependency_hash,
        computation_dependencies=dependencies,
    )
    assert loaded["computation_dependency_hash"] == dependency_hash
    assert loaded["computation_dependencies"] == dependencies

    changed = json.loads(json.dumps(dependencies))
    changed["files"][0]["sha256"] = "sha256:" + "b" * 64
    changed_hash = direct_store._sha256_json(changed)
    with pytest.raises(ValueError, match="computation dependency mismatch"):
        direct_store._load_checkpoint(
            path=checkpoint_path,
            run_id="run-1",
            raw_manifest_hash="sha256:" + "a" * 64,
            computation_dependency_hash=changed_hash,
            computation_dependencies=changed,
        )


def test_legacy_checkpoint_without_dependency_snapshot_fails_closed(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "legacy-checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "schema_version": direct_store.DIRECT_CHECKPOINT_SCHEMA_VERSION,
                "run_id": "run-1",
                "raw_manifest_hash": "sha256:" + "a" * 64,
                "completed_years": [],
                "peak_temporary_bytes": 0,
                "complete": False,
            }
        ),
        encoding="utf-8",
    )
    dependencies, dependency_hash = _dependency_snapshot()
    with pytest.raises(ValueError, match="dependency snapshot is missing"):
        direct_store._load_checkpoint(
            path=checkpoint_path,
            run_id="run-1",
            raw_manifest_hash="sha256:" + "a" * 64,
            computation_dependency_hash=dependency_hash,
            computation_dependencies=dependencies,
        )


def test_build_boundary_rejects_dependency_drift_after_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies, dependency_hash = _dependency_snapshot()
    changed = json.loads(json.dumps(dependencies))
    changed["files"][0]["sha256"] = "sha256:" + "c" * 64
    monkeypatch.setattr(
        direct_store,
        "_direct_computation_dependency_payload",
        lambda: changed,
    )
    with pytest.raises(
        RuntimeError,
        match="dependency drift detected at year_2020_built",
    ):
        direct_store._assert_direct_computation_dependencies_unchanged(
            expected_payload=dependencies,
            expected_hash=dependency_hash,
            stage="year_2020_built",
        )


def test_build_boundary_rejects_dependency_file_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "mid_build_dependency.py"
    source_path.write_text(
        "VALUE = 1\n\n"
        "def calculate(value: int) -> int:\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    old_file = direct_store._direct_dependency_file_identity(
        "tests/mid_build_dependency.py",
        source_path.resolve(),
    )
    expected_payload = {
        "schema_version": direct_store.DIRECT_COMPUTATION_DEPENDENCY_SCHEMA_VERSION,
        "source_hash_semantics": (
            "disk_bytes_snapshot_at_build_start;"
            "loaded_code_fingerprint_is_checked_separately"
        ),
        "files": [old_file],
    }
    expected_hash = direct_store._sha256_json(expected_payload)
    source_path.write_text(
        "VALUE = 1\n\n"
        "def calculate(value: int) -> int:\n"
        "    return value + 2\n",
        encoding="utf-8",
    )
    current_payload = {
        **expected_payload,
        "files": [
            direct_store._direct_dependency_file_identity(
                "tests/mid_build_dependency.py",
                source_path.resolve(),
            )
        ],
    }
    monkeypatch.setattr(
        direct_store,
        "_direct_computation_dependency_payload",
        lambda: current_payload,
    )
    with pytest.raises(
        RuntimeError,
        match="dependency drift detected at year_2020_built",
    ):
        direct_store._assert_direct_computation_dependencies_unchanged(
            expected_payload=expected_payload,
            expected_hash=expected_hash,
            stage="year_2020_built",
        )


def test_imported_old_module_is_rejected_when_source_changed(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "loaded_dependency.py"
    source_path.write_text(
        "VALUE = 1\n\n"
        "def calculate(value: int) -> int:\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    module_name = "_ml_direct_loaded_dependency_test"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        unchanged = direct_store._direct_dependency_file_identity(
            "tests/loaded_dependency.py",
            source_path.resolve(),
        )
        assert unchanged["loaded_code_matches_source"] is True
        source_path.write_text(
            "VALUE = 1\n\n"
            "def calculate(value: int) -> int:\n"
            "    return value + 2\n",
            encoding="utf-8",
        )
        with pytest.raises(
            RuntimeError,
            match="loaded code/constants do not match source",
        ):
            direct_store._direct_dependency_file_identity(
                "tests/loaded_dependency.py",
                source_path.resolve(),
            )
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.parametrize(
    "changed_source",
    (
        "VALUE = 2\n\n"
        "def calculate(value: int) -> int:\n"
        "    return value + 1\n",
        "VALUE = 1\n"
        "NEW_FLAG = 9\n\n"
        "def calculate(value: int) -> int:\n"
        "    return value + 1\n",
        "def calculate(value: int) -> int:\n"
        "    return value + 1\n",
    ),
    ids=("constant_changed", "constant_added", "constant_deleted"),
)
def test_imported_old_module_rejects_constant_add_or_delete(
    tmp_path: Path,
    changed_source: str,
) -> None:
    source_path = tmp_path / "constant_dependency.py"
    source_path.write_text(
        "VALUE = 1\n\n"
        "def calculate(value: int) -> int:\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    module_name = "_ml_direct_constant_dependency_test"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        unchanged = direct_store._direct_dependency_file_identity(
            "tests/constant_dependency.py",
            source_path.resolve(),
        )
        assert unchanged["loaded_code_matches_source"] is True
        source_path.write_text(changed_source, encoding="utf-8")
        with pytest.raises(
            RuntimeError,
            match="loaded code/constants do not match source",
        ):
            direct_store._direct_dependency_file_identity(
                "tests/constant_dependency.py",
                source_path.resolve(),
            )
    finally:
        sys.modules.pop(module_name, None)


def test_interrupted_builder_resume_reuses_custodied_year(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capacity interruption leaves a valid checkpoint for a real resume."""

    raw = _build_raw(tmp_path / "interrupted-source")
    request = replace(
        _direct_request(
            raw,
            output_root=tmp_path / "interrupted-direct",
            shared_root=tmp_path / "interrupted-shared",
        ),
        shared_numeric_store_root=None,
    )
    builder = PortfolioMLDirectNumericStoreBuilder()
    real_preflight = direct_store.preflight_capacity
    interrupted = False

    def interrupt_once(**kwargs: Any) -> Any:
        nonlocal interrupted
        result = real_preflight(**kwargs)
        if kwargs.get("stage") == "year_2022_checkpoint" and not interrupted:
            interrupted = True
            raise StorageCapacityError(
                "synthetic interruption after annual publication",
                preflight=result.as_dict(),
            )
        return result

    monkeypatch.setattr(direct_store, "preflight_capacity", interrupt_once)
    with pytest.raises(
        StorageCapacityError,
        match="synthetic interruption after annual publication",
    ):
        builder.build(request)
    assert interrupted

    run_directories = tuple((request.output_root / "runs").iterdir())
    assert len(run_directories) == 1
    checkpoint_path = run_directories[0] / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["complete"] is False
    assert checkpoint["completed_years"] == []
    assert isinstance(checkpoint["computation_dependencies"], dict)
    assert (run_directories[0] / "year=2022").is_dir()

    monkeypatch.setattr(direct_store, "preflight_capacity", real_preflight)
    resumed = builder.build(replace(request, resume=True))
    manifest = json.loads(resumed.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert [int(item["year"]) for item in manifest["years"]] == [
        2022,
        2023,
        2024,
    ]
    final_checkpoint = json.loads(
        checkpoint_path.read_text(encoding="utf-8")
    )
    assert final_checkpoint["complete"] is True
    assert final_checkpoint["computation_dependency_hash"] == manifest[
        "computation_dependency_hash"
    ]
