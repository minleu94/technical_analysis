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


def test_two_repositories_share_an_idempotent_sidecar_migration(tmp_path: Path) -> None:
    source_db_path = tmp_path / "twstock.db"
    sidecar_path = tmp_path / "weekly-collection-sidecar.sqlite"
    _create_source_database(source_db_path)

    first_repository = EvidenceWeeklyCollectionRepository(source_db_path, sidecar_path=sidecar_path)
    second_repository = EvidenceWeeklyCollectionRepository(source_db_path, sidecar_path=sidecar_path)

    first = first_repository.save_pending(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
    )
    second = second_repository.save_pending(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
    )

    with sqlite3.connect(sidecar_path) as connection:
        version_count = connection.execute("SELECT COUNT(*) FROM sidecar_schema_version").fetchone()[0]
        collection_count = connection.execute("SELECT COUNT(*) FROM evidence_weekly_collections").fetchone()[0]

    assert first.collection_id == second.collection_id
    assert version_count == 1
    assert collection_count == 1


def test_save_failed_retries_idempotently_when_source_is_unreadable(tmp_path: Path) -> None:
    source_db_path = tmp_path / "unreadable-source"
    source_db_path.mkdir()
    repository = EvidenceWeeklyCollectionRepository(
        source_db_path,
        sidecar_path=tmp_path / "weekly-collection-sidecar.sqlite",
    )

    first = repository.save_failed(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
        error=ValueError("first collection failure"),
    )
    second = repository.save_failed(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
        error=RuntimeError("retry collection failure"),
    )

    assert first.collection_id == second.collection_id
    assert second.status == "collection_failed"
    assert second.source_hash.startswith("unavailable:sha256:")
    assert second.error_type == "RuntimeError"
    assert second.error_message == "retry collection failure"
    assert repository.get_by_identity(second.collection_id) == second


def test_all_sidecar_connections_are_closed_after_operations(tmp_path: Path, monkeypatch) -> None:
    source_db_path = tmp_path / "twstock.db"
    _create_source_database(source_db_path)
    connections: list[sqlite3.Connection] = []
    closed_connections: list[sqlite3.Connection] = []

    class TrackingConnection(sqlite3.Connection):
        def close(self) -> None:
            closed_connections.append(self)
            super().close()

    def tracking_connect(repository: EvidenceWeeklyCollectionRepository) -> sqlite3.Connection:
        connection = sqlite3.connect(repository.sidecar_path, factory=TrackingConnection)
        connections.append(connection)
        return connection

    monkeypatch.setattr(EvidenceWeeklyCollectionRepository, "_connect", tracking_connect)
    repository = EvidenceWeeklyCollectionRepository(source_db_path)
    saved = repository.save_pending(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
    )
    assert repository.get_by_identity(saved.collection_id) == saved

    assert connections
    assert closed_connections == connections
