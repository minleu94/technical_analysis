from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app_module.research_run_repository import ResearchRunRepository
from scripts.inspect_research_registry_transaction import (
    inspect_registry_transaction,
)


def _create_registry(path: Path) -> None:
    ResearchRunRepository(SimpleNamespace(research_run_db_file=path))


def test_snapshot_probe_requires_confirmation_without_touching_source(tmp_path: Path) -> None:
    registry = tmp_path / "research_runs.db"
    _create_registry(registry)
    before = registry.read_bytes()

    report = inspect_registry_transaction(registry)

    assert report["status"] == "confirmation_required"
    assert report["write_probe"] == "not_run"
    assert report["formal_write_attempted"] is False
    assert registry.read_bytes() == before


def test_snapshot_probe_runs_transaction_only_in_temp_clone(tmp_path: Path) -> None:
    registry = tmp_path / "research_runs.db"
    _create_registry(registry)
    before = registry.read_bytes()

    report = inspect_registry_transaction(registry, confirm=True)

    assert report["status"] == "passed"
    assert report["write_probe"] == "formal_registry_read_only_snapshot_clone_transaction"
    assert report["formal_write_attempted"] is False
    assert report["writes_formal_registry"] is False
    assert report["source_unchanged"] is True
    assert report["cleanup_succeeded"] is True
    assert report["schema"]["schema_version"] == 2
    assert report["transaction"]["insert_visible_before_rollback"] is True
    assert report["transaction"]["rolled_back_row_absent"] is True
    assert report["transaction"]["row_count_unchanged"] is True
    assert report["transaction"]["quick_check_after"] == "ok"
    assert registry.read_bytes() == before


def test_snapshot_probe_fails_closed_for_wrong_schema(tmp_path: Path) -> None:
    registry = tmp_path / "wrong.db"
    registry.write_bytes(b"not a sqlite database")

    report = inspect_registry_transaction(registry, confirm=True)

    assert report["status"] == "failed"
    assert report["formal_write_attempted"] is False
    assert report["writes_formal_registry"] is False
    assert report["cleanup_succeeded"] is True
    assert report["diagnostics"]


def test_snapshot_probe_output_is_json_serializable(tmp_path: Path) -> None:
    registry = tmp_path / "research_runs.db"
    _create_registry(registry)

    report = inspect_registry_transaction(registry, confirm=True)

    json.dumps(report, ensure_ascii=False)
