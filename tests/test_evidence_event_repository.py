from __future__ import annotations

import sqlite3
from pathlib import Path

from data_module.config import TWStockConfig
from data_module.evidence_event_migration import (
    apply_evidence_event_schema_migration,
    generate_evidence_event_schema_copy_dry_run_report,
)
from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEvent,
    EvidenceEventType,
    EvidenceOutcome,
    EvidenceOutcomeStatus,
)
from app_module.evidence_event_repository import EvidenceEventRepository


def _config(tmp_path: Path) -> TWStockConfig:
    return TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")


def _event(event_hash: str = "hash-a", *, reasons: tuple[str, ...] = ("rs_breakout",)) -> EvidenceEvent:
    return EvidenceEvent(
        event_id="event-a",
        event_hash=event_hash,
        event_date="2026-06-01",
        decision_date="2026-06-01",
        symbol="2330",
        event_type=EvidenceEventType.RECOMMENDATION_INCLUDED,
        event_family="recommendation",
        source_type="recommendation_result",
        source_id="rec-001",
        source_snapshot_id="snapshot-001",
        reason_codes=reasons,
        data_quality=EvidenceDataQuality.OBSERVED,
        warnings=(),
        as_of_date="2026-06-01",
        available_date="2026-06-01",
        source_version="test",
        benchmark_id="TAIEX",
        industry_benchmark_id="半導體類指數",
        metadata={"return_basis": "close_to_close_event_date"},
    )


def test_evidence_schema_working_copy_dry_run_does_not_modify_source_db(tmp_path):
    source_db = tmp_path / "source.db"
    working_copy = tmp_path / "working.db"
    with sqlite3.connect(source_db) as conn:
        conn.execute("CREATE TABLE daily_prices (日期 TEXT, 證券代號 TEXT)")

    report = generate_evidence_event_schema_copy_dry_run_report(source_db, working_copy)

    with sqlite3.connect(source_db) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "daily_prices" in tables
    assert "evidence_events" not in tables
    assert report.existing_tables_preserved is True
    assert "evidence_events" in report.created_tables
    assert working_copy.exists()


def test_repository_insert_event_is_idempotent_by_event_hash(tmp_path):
    config = _config(tmp_path)
    repo = EvidenceEventRepository(config)

    first = repo.insert_event(_event())
    duplicate = repo.insert_event(_event())
    rows = repo.list_events()

    assert first.event_id == duplicate.event_id
    assert len(rows) == 1
    assert rows[0].event_hash == "hash-a"


def test_repository_keeps_different_reason_hash_as_distinct_event(tmp_path):
    config = _config(tmp_path)
    repo = EvidenceEventRepository(config)

    first = repo.insert_event(_event("hash-a", reasons=("rs_breakout",)))
    second = repo.insert_event(_event("hash-b", reasons=("liquidity_ok",)))

    rows = repo.list_events(symbol="2330", event_type=EvidenceEventType.RECOMMENDATION_INCLUDED)
    assert [row.event_id for row in rows] == [first.event_id, second.event_id]
    assert rows[0].reason_codes == ("rs_breakout",)
    assert rows[1].reason_codes == ("liquidity_ok",)


def test_repository_upserts_and_lists_outcomes(tmp_path):
    config = _config(tmp_path)
    repo = EvidenceEventRepository(config)
    event = repo.insert_event(_event())
    outcome = EvidenceOutcome(
        outcome_id="outcome-a",
        event_id=event.event_id,
        window_days=5,
        outcome_status=EvidenceOutcomeStatus.PENDING,
        data_quality=EvidenceDataQuality.MISSING,
        warnings=("insufficient_future_data",),
        metadata={"return_basis": "close_to_close_event_date"},
    )

    repo.upsert_outcome(outcome)
    updated = repo.upsert_outcome(
        EvidenceOutcome(
            outcome_id="outcome-b",
            event_id=event.event_id,
            window_days=5,
            outcome_status=EvidenceOutcomeStatus.READY,
            data_quality=EvidenceDataQuality.OBSERVED,
            event_price_date="2026-06-01",
            event_close="100",
            outcome_price_date="2026-06-08",
            outcome_close="110",
            forward_return_bp=1000,
            warnings=(),
            metadata={"return_basis": "close_to_close_event_date"},
        )
    )

    rows = repo.list_outcomes(event_id=event.event_id)
    assert len(rows) == 1
    assert rows[0].outcome_id == updated.outcome_id
    assert rows[0].outcome_status == EvidenceOutcomeStatus.READY
    assert rows[0].forward_return_bp == 1000


def test_apply_migration_requires_existing_db_and_creates_backup(tmp_path):
    db_file = tmp_path / "formal.db"
    backup_dir = tmp_path / "backup"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE daily_prices (日期 TEXT, 證券代號 TEXT)")

    result = apply_evidence_event_schema_migration(db_file, backup_dir=backup_dir)

    assert result.applied is True
    assert result.backup_file is not None
    assert result.backup_file.exists()
    with sqlite3.connect(db_file) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"evidence_events", "evidence_outcomes"}.issubset(tables)
