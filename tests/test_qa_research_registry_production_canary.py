from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app_module.research_run_repository import ResearchRunRepository
from scripts.qa_research_registry_production_canary import (
    NO_CONCURRENT_WRITER_TOKEN,
    OWNER_APPROVAL_TOKEN,
    execute_production_registry_canary,
    inspect_production_registry,
)


def _create_registry(tmp_path: Path) -> tuple[Path, Path]:
    output_root = tmp_path / "output"
    registry = output_root / "research_runs" / "research_runs.db"
    ResearchRunRepository(SimpleNamespace(research_run_db_file=registry))
    return output_root, registry


def _kwargs(output_root: Path, registry: Path, **extra):
    return {
        "registry_path": registry,
        "output_root": output_root,
        "protected_roots": [output_root.parent],
        **extra,
    }


def test_registry_canary_defaults_to_read_only_confirmation_required(tmp_path: Path) -> None:
    output_root, registry = _create_registry(tmp_path)
    before = registry.read_bytes()

    report = execute_production_registry_canary(**_kwargs(output_root, registry))

    assert report["status"] == "confirmation_required"
    assert report["production_write_attempted"] is False
    assert report["side_effect_free"] is True
    assert report["backup"] is None
    assert registry.read_bytes() == before


def test_registry_canary_requires_owner_and_writer_ack_before_write(tmp_path: Path) -> None:
    output_root, registry = _create_registry(tmp_path)
    before = registry.read_bytes()

    report = execute_production_registry_canary(
        **_kwargs(
            output_root,
            registry,
            confirm=True,
            owner_approval=OWNER_APPROVAL_TOKEN,
        )
    )

    assert report["status"] == "blocked"
    assert report["blocker"] == "no_concurrent_writer_ack_required"
    assert report["production_write_attempted"] is False
    assert registry.read_bytes() == before


def test_registry_canary_proves_real_transaction_and_rollback(tmp_path: Path) -> None:
    output_root, registry = _create_registry(tmp_path)
    before = registry.read_bytes()
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()

    report = execute_production_registry_canary(
        **_kwargs(
            output_root,
            registry,
            backup_root=backup_root,
            confirm=True,
            owner_approval=OWNER_APPROVAL_TOKEN,
            no_concurrent_writer_ack=NO_CONCURRENT_WRITER_TOKEN,
        )
    )

    assert report["status"] == "measured"
    assert report["production_write_attempted"] is True
    assert report["production_sqlite_write_attempted"] is True
    assert report["writes_allowed"] is True
    assert report["durable_change_detected"] is False
    assert report["rollback"]["succeeded"] is True
    assert report["validation"]["ok"] is True
    assert report["validation"]["insert_visible_before_rollback"] is True
    assert report["validation"]["rolled_back_row_absent"] is True
    assert report["validation"]["row_count_unchanged"] is True
    assert report["validation"]["registry_content_unchanged"] is True
    assert report["backup"]["retained"] is False
    assert registry.read_bytes() == before
    assert inspect_production_registry(registry)["row_count"] == 0
    assert not list(backup_root.iterdir())


def test_registry_canary_rejects_noncanonical_registry_path(tmp_path: Path) -> None:
    output_root, registry = _create_registry(tmp_path)
    other_registry = tmp_path / "other.db"

    report = execute_production_registry_canary(
        **_kwargs(output_root, other_registry),
    )

    assert report["status"] == "blocked"
    assert report["blocker"] == "registry_path_must_match_output_root_research_registry"
    assert not other_registry.exists()


def test_registry_canary_blocks_incomplete_schema(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    registry = output_root / "research_runs" / "research_runs.db"
    registry.parent.mkdir(parents=True)
    registry.write_bytes(b"not sqlite")

    report = execute_production_registry_canary(
        **_kwargs(output_root, registry),
    )

    assert report["status"] == "blocked"
    assert report["blocker"] == "registry_schema_version_mismatch"
    assert report["production_write_attempted"] is False
