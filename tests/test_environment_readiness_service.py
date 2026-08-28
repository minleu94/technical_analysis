from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import app_module.runtime_services.environment_readiness_service as readiness_module
from app_module.runtime_services.environment_readiness_service import (
    EnvironmentReadinessService,
)


def test_environment_readiness_reports_existing_paths_without_writing(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    (data_root / "logs").mkdir(parents=True)
    (output_root / "research_runs").mkdir(parents=True)
    registry = output_root / "research_runs" / "research_runs.db"
    registry.write_bytes(b"placeholder")

    snapshot = EnvironmentReadinessService(
        data_root,
        output_root,
        now_provider=lambda: datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc),
    ).get_snapshot()

    assert snapshot.overall_state == "ready"
    assert snapshot.side_effect_free is True
    assert snapshot.write_probe == "os.access_plus_existing_handle"
    assert {item.key: item.status for item in snapshot.paths} == {
        "data_root": "ready",
        "output_root": "ready",
        "log_root": "ready",
        "research_registry": "ready",
    }
    assert snapshot.observed_at.tzinfo == timezone.utc


def test_environment_readiness_does_not_create_missing_paths(tmp_path: Path) -> None:
    data_root = tmp_path / "missing-data"
    output_root = tmp_path / "missing-output"

    snapshot = EnvironmentReadinessService(data_root, output_root).get_snapshot()

    assert snapshot.overall_state == "unavailable"
    assert not data_root.exists()
    assert not output_root.exists()
    statuses = {item.key: item for item in snapshot.paths}
    assert statuses["data_root"].status == "unavailable"
    assert statuses["data_root"].diagnostic == "data_root_not_created"
    assert statuses["output_root"].status == "ready_to_create"
    assert statuses["output_root"].diagnostic == "output_root_not_created"


def test_environment_readiness_exposes_write_boundary_without_probe_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    (data_root / "logs").mkdir(parents=True)
    (output_root / "research_runs").mkdir(parents=True)

    real_access = readiness_module._access

    def fake_access(path: Path, mode: int) -> bool:
        if mode == readiness_module.os.W_OK and path in {output_root, data_root / "logs"}:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(readiness_module, "_access", fake_access)

    snapshot = EnvironmentReadinessService(data_root, output_root).get_snapshot()

    assert snapshot.overall_state == "attention"
    statuses = {item.key: item for item in snapshot.paths}
    assert statuses["output_root"].status == "attention"
    assert statuses["output_root"].diagnostic == "output_root_not_writable"
    assert statuses["log_root"].status == "attention"
    assert statuses["log_root"].diagnostic == "log_root_not_writable"
    assert not (output_root / "research_runs" / "research_runs.db").exists()


def test_environment_readiness_downgrades_existing_write_handle_denial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    logs = data_root / "logs"
    (output_root / "research_runs").mkdir(parents=True)
    logs.mkdir(parents=True)
    (logs / "config.log").write_text("existing\n", encoding="utf-8")
    (output_root / "research_runs" / "research_runs.db").write_bytes(b"db")

    monkeypatch.setattr(
        readiness_module,
        "_probe_existing_write_handle",
        lambda path: (False, f"{path.name}_write_handle_denied:PermissionError"),
    )

    snapshot = EnvironmentReadinessService(data_root, output_root).get_snapshot()

    assert snapshot.overall_state == "attention"
    statuses = {item.key: item for item in snapshot.paths}
    assert statuses["log_root"].status == "attention"
    assert statuses["log_root"].diagnostic == "config.log_write_handle_denied:PermissionError"
    assert statuses["research_registry"].status == "attention"
    assert statuses["research_registry"].diagnostic == "research_runs.db_write_handle_denied:PermissionError"
    assert snapshot.write_probe == "os.access_plus_existing_handle"


def test_environment_write_probe_requires_confirmation_and_does_not_write(tmp_path: Path) -> None:
    data_root = tmp_path / "formal-data"
    output_root = tmp_path / "formal-output"
    probe_root = tmp_path / "staging"
    data_root.mkdir()
    output_root.mkdir()
    probe_root.mkdir()

    service = EnvironmentReadinessService(data_root, output_root)

    result = service.run_write_probe(probe_root)

    assert result.status == "confirmation_required"
    assert result.side_effect_free is True
    assert result.write_probe == "not_run"
    assert not list(probe_root.iterdir())


def test_environment_write_probe_passes_and_cleans_ephemeral_artifacts(tmp_path: Path) -> None:
    data_root = tmp_path / "formal-data"
    output_root = tmp_path / "formal-output"
    probe_root = tmp_path / "staging"
    data_root.mkdir()
    output_root.mkdir()
    probe_root.mkdir()

    service = EnvironmentReadinessService(data_root, output_root)

    result = service.run_write_probe(probe_root, confirm=True)

    assert result.status == "passed"
    assert result.file_write_succeeded is True
    assert result.sqlite_write_succeeded is True
    assert result.cleanup_succeeded is True
    assert result.side_effect_free is False
    assert result.write_probe == "actual_ephemeral"
    assert not list(probe_root.iterdir())


def test_environment_write_probe_blocks_formal_roots(tmp_path: Path) -> None:
    data_root = tmp_path / "formal-data"
    output_root = tmp_path / "formal-output"
    data_root.mkdir()
    output_root.mkdir()

    service = EnvironmentReadinessService(data_root, output_root)

    result = service.run_write_probe(output_root, confirm=True)

    assert result.status == "blocked"
    assert result.side_effect_free is True
    assert result.write_probe == "not_run"
    assert "正式" in result.diagnostic
