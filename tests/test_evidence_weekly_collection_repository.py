from __future__ import annotations

from pathlib import Path
import sqlite3

from app_module.evidence_weekly_collection_repository import EvidenceWeeklyCollectionRepository


def _create_source_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE source_marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO source_marker (value) VALUES ('source data')")


def test_save_pending_is_idempotent_and_never_modifies_source_database(tmp_path: Path) -> None:
    source_db_path = tmp_path / "twstock.db"
    _create_source_database(source_db_path)
    source_bytes_before = source_db_path.read_bytes()
    repository = EvidenceWeeklyCollectionRepository(source_db_path)

    first = repository.save_pending(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
    )
    second = repository.save_pending(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
    )

    assert first.collection_id == second.collection_id
    assert first.status == "pending_human_review"
    assert source_db_path.read_bytes() == source_bytes_before


def test_save_failed_preserves_error_details_and_is_retrievable(tmp_path: Path) -> None:
    source_db_path = tmp_path / "twstock.db"
    _create_source_database(source_db_path)
    repository = EvidenceWeeklyCollectionRepository(source_db_path)

    saved = repository.save_failed(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
        error=ValueError("source format is invalid"),
    )

    assert saved.status == "collection_failed"
    assert saved.error_type == "ValueError"
    assert saved.error_message == "source format is invalid"
    assert repository.get_by_identity(saved.collection_id) == saved
