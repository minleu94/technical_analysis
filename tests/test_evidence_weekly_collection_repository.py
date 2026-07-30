from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from app_module.evidence_weekly_collection_repository import EvidenceWeeklyCollectionRepository


def _create_source_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE source_marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO source_marker (value) VALUES ('source data')")


def test_save_observed_is_idempotent_and_never_modifies_source_database(
    tmp_path: Path,
) -> None:
    source_db_path = tmp_path / "twstock.db"
    _create_source_database(source_db_path)
    source_bytes_before = source_db_path.read_bytes()
    repository = EvidenceWeeklyCollectionRepository(source_db_path)

    first = repository.save_observed(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
    )
    second = repository.save_observed(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
    )
    compatibility_alias = repository.save_pending(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
    )

    assert first.collection_id == second.collection_id == compatibility_alias.collection_id
    assert first.status == second.status == compatibility_alias.status == "observed_automatic"
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

    first = first_repository.save_observed(
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


def test_schema_v2_migration_preserves_every_legacy_row_and_is_idempotent(
    tmp_path: Path,
) -> None:
    source_db_path = tmp_path / "twstock.db"
    sidecar_path = tmp_path / "weekly-collection-sidecar.sqlite"
    _create_source_database(source_db_path)
    source_bytes_before = source_db_path.read_bytes()
    with sqlite3.connect(sidecar_path) as connection:
        connection.execute(
            "CREATE TABLE sidecar_schema_version (version INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO sidecar_schema_version (version) VALUES (1)"
        )
        connection.execute(
            """
            CREATE TABLE evidence_weekly_collections (
                collection_id TEXT PRIMARY KEY,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('pending_human_review', 'collection_failed')
                ),
                payload_json TEXT NOT NULL,
                error_type TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO evidence_weekly_collections (
                collection_id, period_start, period_end, source_path,
                source_hash, status, payload_json, error_type,
                error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "ewc_legacy_observed",
                    "2026-07-06",
                    "2026-07-12",
                    str(source_db_path),
                    f"sha256:{'1' * 64}",
                    "pending_human_review",
                    '{"nested":{"value":"保留"},"status":"coverage_only"}',
                    "",
                    "",
                    "2026-07-13 01:02:03",
                ),
                (
                    "ewc_legacy_failed",
                    "2026-07-13",
                    "2026-07-19",
                    str(source_db_path),
                    f"sha256:{'2' * 64}",
                    "collection_failed",
                    '{"status":"collection_failed"}',
                    "ValueError",
                    "source unavailable",
                    "2026-07-20 04:05:06",
                ),
            ],
        )

    EvidenceWeeklyCollectionRepository(
        source_db_path,
        sidecar_path=sidecar_path,
    )
    EvidenceWeeklyCollectionRepository(
        source_db_path,
        sidecar_path=sidecar_path,
    )

    with sqlite3.connect(sidecar_path) as connection:
        version_rows = connection.execute(
            "SELECT version FROM sidecar_schema_version"
        ).fetchall()
        rows = connection.execute(
            """
            SELECT
                collection_id, period_start, period_end, source_path,
                source_hash, status, payload_json, error_type,
                error_message, created_at
            FROM evidence_weekly_collections
            ORDER BY collection_id
            """
        ).fetchall()
        schema_sql = str(
            connection.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'table' AND name = 'evidence_weekly_collections'
                """
            ).fetchone()[0]
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE evidence_weekly_collections
                SET status = 'pending_human_review'
                WHERE collection_id = 'ewc_legacy_observed'
                """
            )

    assert version_rows == [(2,)]
    assert rows == [
        (
            "ewc_legacy_failed",
            "2026-07-13",
            "2026-07-19",
            str(source_db_path),
            f"sha256:{'2' * 64}",
            "collection_failed",
            '{"status":"collection_failed"}',
            "ValueError",
            "source unavailable",
            "2026-07-20 04:05:06",
        ),
        (
            "ewc_legacy_observed",
            "2026-07-06",
            "2026-07-12",
            str(source_db_path),
            f"sha256:{'1' * 64}",
            "observed_automatic",
            '{"nested":{"value":"保留"},"status":"coverage_only"}',
            "",
            "",
            "2026-07-13 01:02:03",
        ),
    ]
    assert "observed_automatic" in schema_sql
    assert "pending_human_review" not in schema_sql
    assert source_db_path.read_bytes() == source_bytes_before


def test_schema_v2_migration_rolls_back_on_an_unknown_legacy_status(
    tmp_path: Path,
) -> None:
    source_db_path = tmp_path / "twstock.db"
    sidecar_path = tmp_path / "weekly-collection-sidecar.sqlite"
    _create_source_database(source_db_path)
    source_bytes_before = source_db_path.read_bytes()
    with sqlite3.connect(sidecar_path) as connection:
        connection.execute(
            "CREATE TABLE sidecar_schema_version (version INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO sidecar_schema_version (version) VALUES (1)"
        )
        connection.execute(
            """
            CREATE TABLE evidence_weekly_collections (
                collection_id TEXT PRIMARY KEY,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                error_type TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO evidence_weekly_collections (
                collection_id, period_start, period_end, source_path,
                source_hash, status, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ewc_unknown",
                "2026-07-06",
                "2026-07-12",
                str(source_db_path),
                f"sha256:{'3' * 64}",
                "manual_override",
                '{"preserve":true}',
            ),
        )

    with pytest.raises(
        RuntimeError,
        match="unsupported legacy weekly collection statuses: manual_override",
    ):
        EvidenceWeeklyCollectionRepository(
            source_db_path,
            sidecar_path=sidecar_path,
        )

    with sqlite3.connect(sidecar_path) as connection:
        version_rows = connection.execute(
            "SELECT version FROM sidecar_schema_version"
        ).fetchall()
        rows = connection.execute(
            """
            SELECT collection_id, status, payload_json
            FROM evidence_weekly_collections
            """
        ).fetchall()
        migration_table_count = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'evidence_weekly_collections_schema_v2_migration'
                """
            ).fetchone()[0]
        )

    assert version_rows == [(1,)]
    assert rows == [("ewc_unknown", "manual_override", '{"preserve":true}')]
    assert migration_table_count == 0
    assert source_db_path.read_bytes() == source_bytes_before


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
    saved = repository.save_observed(
        period_start="2026-07-06",
        period_end="2026-07-12",
        payload_json={"status": "coverage_only"},
    )
    assert repository.get_by_identity(saved.collection_id) == saved

    assert connections
    assert closed_connections == connections
