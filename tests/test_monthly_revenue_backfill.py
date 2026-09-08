from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date

import data_module.monthly_revenue_backfill as backfill_module
from data_module.fundamental_schema import apply_fundamental_schema
from data_module.monthly_revenue_backfill import (
    apply_mops_snapshot_monthly_revenue_backfill,
    apply_monthly_revenue_backfill,
    plan_mops_snapshot_monthly_revenue_backfill,
    plan_monthly_revenue_backfill,
)


def _write_revenue_csv(raw_dir, stock_code: str = "2330") -> None:
    raw_dir.mkdir()
    (raw_dir / f"{stock_code}_monthly_revenue.csv").write_text(
        "date,stock_id,country,revenue,revenue_month,revenue_year\n"
        f"2026-06-01,{stock_code},Taiwan,1000000000,5,2026\n",
        encoding="utf-8",
    )


def _write_availability_csv(path) -> None:
    path.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version,"
        "availability_contract_version,evidence_class,source_hash,revision,parent_revision\n"
        "2330,2026-05,2026-05-31,2026-06-10,2026-06-11,"
        "manual.twse_monthly_revenue_announcement_log,announcement-log-2026-06-16,"
        "formal-availability.v2,official_announcement,sha256:"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,1,\n",
        encoding="utf-8",
    )


def _write_mops_snapshot_csv(path, *, fetched_at: str = "2026-06-10T08:00:00Z") -> None:
    path.write_text(
        "market,period,stock_code,company_name,current_month_revenue,"
        "previous_month_revenue,previous_year_month_revenue,mom_pct,yoy_pct,"
        "cumulative_revenue,previous_year_cumulative_revenue,cumulative_yoy_pct,"
        "note,fetched_at,source,source_version\n"
        "twse,2026-05,2330,台積電,320000000000,300000000000,250000000000,"
        "6.67,28.0,1500000000000,1200000000000,25.0,,"
        f"{fetched_at},mops.monthly_revenue_static_snapshot,"
        "mops-static-2026-06-16\n",
        encoding="utf-8-sig",
    )


def _scope_key_digest(keys: set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()


def _write_scope_manifest(
    path,
    *,
    candidate_file,
    accepted_file,
    accepted_keys: set[str],
    excluded_keys: list[str],
) -> None:
    candidate_bytes = candidate_file.read_bytes()
    accepted_bytes = accepted_file.read_bytes()
    candidate_key_set = accepted_keys | set(excluded_keys)
    path.write_text(
        json.dumps(
            {
                "candidate_file": str(candidate_file),
                "candidate_rows": len(candidate_key_set),
                "mapping_rows": len(accepted_keys),
                "accepted_rows": len(accepted_keys),
                "excluded_rows": len(excluded_keys),
                "excluded_keys": excluded_keys,
                "candidate_file_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
                "accepted_file_sha256": hashlib.sha256(accepted_bytes).hexdigest(),
                "candidate_key_sha256": _scope_key_digest(candidate_key_set),
                "accepted_key_sha256": _scope_key_digest(accepted_keys),
                "excluded_key_sha256": _scope_key_digest(set(excluded_keys)),
            }
        ),
        encoding="utf-8",
    )


def test_plan_monthly_revenue_backfill_requires_governed_mapping(tmp_path) -> None:
    raw_dir = tmp_path / "financial_data"
    _write_revenue_csv(raw_dir)
    availability_file = tmp_path / "missing_monthly_revenue_availability.csv"

    plan = plan_monthly_revenue_backfill(
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version="financial-data-csv-monthly-revenue-v1",
    )

    assert plan.records == ()
    assert plan.ready_for_apply is False
    assert plan.diagnostics[0].code == "fundamental_availability.mapping_file_missing"


def test_plan_monthly_revenue_backfill_builds_records_from_mapping(tmp_path) -> None:
    raw_dir = tmp_path / "financial_data"
    _write_revenue_csv(raw_dir)
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)

    plan = plan_monthly_revenue_backfill(
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version="financial-data-csv-monthly-revenue-v1",
    )

    assert plan.ready_for_apply is True
    assert plan.raw_row_count == 1
    assert len(plan.records) == 1
    record = plan.records[0]
    assert record.stock_code == "2330"
    assert record.period == "2026-05"
    assert record.available_date == date(2026, 6, 11)
    assert record.source_version == "financial-data-csv-monthly-revenue-v1"
    assert plan.diagnostics == ()


def test_plan_mops_snapshot_monthly_revenue_backfill_preserves_mops_source(
    tmp_path,
) -> None:
    snapshot_file = tmp_path / "mops_snapshot.csv"
    _write_mops_snapshot_csv(snapshot_file)
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)

    plan = plan_mops_snapshot_monthly_revenue_backfill(
        snapshot_file=snapshot_file,
        availability_file=availability_file,
        source_version="mops-static-snapshot-monthly-revenue-2026-06-16",
    )

    assert plan.ready_for_apply is True
    assert plan.raw_row_count == 1
    assert len(plan.records) == 1
    record = plan.records[0]
    assert record.stock_code == "2330"
    assert record.period == "2026-05"
    assert record.revenue == 320000000000
    assert record.source == "mops.monthly_revenue_static_snapshot"
    assert record.source_version == (
        "mops-static-snapshot-monthly-revenue-2026-06-16"
        "|snapshot=mops-static-2026-06-16"
    )
    assert plan.diagnostics == ()


def test_plan_mops_snapshot_blocks_partial_mapping_and_keeps_full_denominator(tmp_path) -> None:
    snapshot_file = tmp_path / "mops_snapshot.csv"
    _write_mops_snapshot_csv(snapshot_file)
    with snapshot_file.open("a", encoding="utf-8") as handle:
        handle.write(
            "twse,2026-05,2317,鴻海,100,90,80,1.0,2.0,500,450,3.0,,"
            "2026-06-11T00:00:00Z,mops.monthly_revenue_static_snapshot,"
            "mops-static-twse-2026-05-sha256-"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        )
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)

    plan = plan_mops_snapshot_monthly_revenue_backfill(
        snapshot_file=snapshot_file,
        availability_file=availability_file,
        source_version="mops-static-snapshot-monthly-revenue-2026-06-16",
    )

    assert plan.raw_row_count == 2
    assert plan.snapshot_unmatched_mapping_count == 1
    assert len(plan.records) == 1
    assert plan.ready_for_apply is False
    assert any(
        diagnostic.code == "fundamental_availability.snapshot_mapping_incomplete"
        for diagnostic in plan.diagnostics
    )


def test_plan_mops_snapshot_accepts_explicit_partial_scope_manifest(tmp_path) -> None:
    snapshot_file = tmp_path / "accepted_scope.csv"
    _write_mops_snapshot_csv(snapshot_file)
    candidate_file = tmp_path / "full_candidate.csv"
    candidate_file.write_bytes(snapshot_file.read_bytes())
    with candidate_file.open("a", encoding="utf-8") as handle:
        handle.write(
            "twse,2026-05,2317,鴻海,100,90,80,1.0,2.0,500,450,3.0,,"
            "2026-06-11T00:00:00Z,mops.monthly_revenue_static_snapshot,"
            "mops-static-twse-2026-05-sha256-"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        )
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)
    manifest_file = tmp_path / "scope_manifest.json"
    _write_scope_manifest(
        manifest_file,
        candidate_file=candidate_file,
        accepted_file=snapshot_file,
        accepted_keys={"2330|2026-05"},
        excluded_keys=["2317|2026-05"],
    )

    plan = plan_mops_snapshot_monthly_revenue_backfill(
        snapshot_file=snapshot_file,
        availability_file=availability_file,
        source_version="mops-static-snapshot-monthly-revenue-2026-06-16",
        scope_manifest_file=manifest_file,
    )

    assert plan.ready_for_apply is True
    assert plan.snapshot_scope == "partial"
    assert plan.full_snapshot_row_count == 2
    assert plan.excluded_snapshot_row_count == 1
    assert plan.raw_row_count == 1
    assert len(plan.records) == 1
    assert plan.diagnostics == ()


def test_plan_mops_snapshot_rejects_scope_source_hash_or_key_drift(tmp_path) -> None:
    snapshot_file = tmp_path / "accepted_scope.csv"
    _write_mops_snapshot_csv(snapshot_file)
    candidate_file = tmp_path / "full_candidate.csv"
    candidate_file.write_bytes(snapshot_file.read_bytes())
    with candidate_file.open("a", encoding="utf-8") as handle:
        handle.write(
            "twse,2026-05,2317,鴻海,100,90,80,1.0,2.0,500,450,3.0,,"
            "2026-06-11T00:00:00Z,mops.monthly_revenue_static_snapshot,"
            "mops-static-twse-2026-05-sha256-"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        )
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)
    manifest_file = tmp_path / "scope_manifest.json"
    _write_scope_manifest(
        manifest_file,
        candidate_file=candidate_file,
        accepted_file=snapshot_file,
        accepted_keys={"2330|2026-05"},
        excluded_keys=["2317|2026-05"],
    )
    snapshot_file.write_text(
        snapshot_file.read_text(encoding="utf-8-sig")
        + "\n",
        encoding="utf-8-sig",
    )

    plan = plan_mops_snapshot_monthly_revenue_backfill(
        snapshot_file=snapshot_file,
        availability_file=availability_file,
        source_version="mops-static-snapshot-monthly-revenue-2026-06-16",
        scope_manifest_file=manifest_file,
    )

    assert plan.ready_for_apply is False
    assert any(
        diagnostic.code
        == "fundamental_revenue.snapshot_scope_manifest_invalid"
        for diagnostic in plan.diagnostics
    )


def test_plan_mops_snapshot_rejects_inconsistent_partial_scope_manifest(tmp_path) -> None:
    snapshot_file = tmp_path / "accepted_scope.csv"
    _write_mops_snapshot_csv(snapshot_file)
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)
    manifest_file = tmp_path / "scope_manifest.json"
    manifest_file.write_text(
        '{"candidate_rows": 2, "accepted_rows": 2, "excluded_rows": 0, '
        '"excluded_keys": []}',
        encoding="utf-8",
    )

    plan = plan_mops_snapshot_monthly_revenue_backfill(
        snapshot_file=snapshot_file,
        availability_file=availability_file,
        source_version="mops-static-snapshot-monthly-revenue-2026-06-16",
        scope_manifest_file=manifest_file,
    )

    assert plan.ready_for_apply is False
    assert any(
        diagnostic.code
        == "fundamental_revenue.snapshot_scope_manifest_invalid"
        for diagnostic in plan.diagnostics
    )


def test_plan_mops_snapshot_rejects_mapping_earlier_than_capture_session(tmp_path) -> None:
    snapshot_file = tmp_path / "mops_snapshot.csv"
    _write_mops_snapshot_csv(snapshot_file, fetched_at="2026-06-16T00:00:00Z")
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)

    plan = plan_mops_snapshot_monthly_revenue_backfill(
        snapshot_file=snapshot_file,
        availability_file=availability_file,
        source_version="mops-static-snapshot-monthly-revenue-2026-06-16",
    )

    assert plan.raw_row_count == 1
    assert len(plan.records) == 1
    assert plan.ready_for_apply is False
    assert any(
        diagnostic.code
        == "fundamental_availability.snapshot_capture_after_available_date"
        for diagnostic in plan.diagnostics
    )


def test_plan_mops_snapshot_rejects_missing_source_lineage(tmp_path) -> None:
    snapshot_file = tmp_path / "mops_snapshot.csv"
    _write_mops_snapshot_csv(snapshot_file)
    snapshot_file.write_text(
        snapshot_file.read_text(encoding="utf-8-sig").replace(
            "mops-static-2026-06-16", ""
        ),
        encoding="utf-8-sig",
    )


    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)

    plan = plan_mops_snapshot_monthly_revenue_backfill(
        snapshot_file=snapshot_file,
        availability_file=availability_file,
        source_version="mops-static-snapshot-monthly-revenue-2026-06-16",
    )

    assert plan.raw_row_count == 1
    assert plan.snapshot_invalid_row_count == 1
    assert plan.records == ()
    assert plan.ready_for_apply is False
    assert plan.diagnostics[0].code == "fundamental_revenue.snapshot_invalid_row"


def test_apply_monthly_revenue_backfill_inserts_records_and_backs_up_db(tmp_path) -> None:
    raw_dir = tmp_path / "financial_data"
    _write_revenue_csv(raw_dir)
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)
    db_file = tmp_path / "twstock.db"
    backup_dir = tmp_path / "backup"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)

    result = apply_monthly_revenue_backfill(
        db_file=db_file,
        backup_dir=backup_dir,
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version="financial-data-csv-monthly-revenue-v1",
    )

    assert result.applied is True
    assert result.inserted_count == 1
    assert result.backup_file is not None
    assert result.backup_file.exists()
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT stock_code, period, as_of_date, announced_date, available_date,
                   revenue, source, source_version, quality
            FROM fundamental_monthly_revenues
            """
        ).fetchall()
    assert rows == [
        (
            "2330",
            "2026-05",
            "2026-05-31",
            "2026-06-10",
            "2026-06-11",
            "1000000000",
            "financial_data.monthly_revenue_csv",
            "financial-data-csv-monthly-revenue-v1",
            "observed",
        )
    ]


def test_apply_mops_snapshot_preserves_prior_source_version(tmp_path) -> None:
    snapshot_file = tmp_path / "mops_snapshot.csv"
    _write_mops_snapshot_csv(snapshot_file)
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2330",
                "2026-05",
                "2026-05-31",
                "2026-06-10",
                "2026-06-11",
                "900",
                "mops.monthly_revenue_static_snapshot",
                "prior-capture-2026-06-11",
                "observed",
            ),
        )

    result = apply_mops_snapshot_monthly_revenue_backfill(
        db_file=db_file,
        backup_dir=tmp_path / "backup",
        snapshot_file=snapshot_file,
        availability_file=availability_file,
        source_version="capture-2026-06-11",
    )

    assert result.applied is True
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            "SELECT revenue, source_version FROM fundamental_monthly_revenues "
            "ORDER BY source_version"
        ).fetchall()
    assert len(rows) == 2
    assert {row[0] for row in rows} == {"900", "320000000000"}
    assert any(row[1] == "prior-capture-2026-06-11" for row in rows)


def test_apply_monthly_revenue_backfill_refuses_diagnostics(tmp_path) -> None:
    raw_dir = tmp_path / "financial_data"
    _write_revenue_csv(raw_dir)
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)

    result = apply_monthly_revenue_backfill(
        db_file=db_file,
        backup_dir=tmp_path / "backup",
        raw_dir=raw_dir,
        availability_file=tmp_path / "missing.csv",
        source_version="financial-data-csv-monthly-revenue-v1",
    )

    assert result.applied is False
    assert result.inserted_count == 0
    assert result.backup_file is None
    with sqlite3.connect(db_file) as conn:
        count = conn.execute("SELECT COUNT(*) FROM fundamental_monthly_revenues").fetchone()[0]
    assert count == 0


def test_monthly_revenue_backup_captures_committed_wal_state(tmp_path) -> None:
    db_file = tmp_path / "twstock.db"
    backup_dir = tmp_path / "task_backup"
    writer = sqlite3.connect(db_file)
    try:
        conn = writer
        apply_fundamental_schema(conn)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2330",
                "2026-05",
                "2026-05-31",
                "2026-06-10",
                "2026-06-11",
                "100",
                "fixture",
                "wal-v1",
                "observed",
            ),
        )
        conn.commit()
        wal_file = db_file.with_name(f"{db_file.name}-wal")
        assert wal_file.exists()
        assert wal_file.stat().st_size > 0

        backup_file = backfill_module._create_consistent_sqlite_backup(
            db_file,
            backup_dir,
            label="wal-test",
        )

        assert backup_file is not None
        verification = sqlite3.connect(backup_file)
        try:
            assert verification.execute(
                "SELECT revenue FROM fundamental_monthly_revenues"
            ).fetchone() == ("100",)
            assert verification.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            verification.close()
    finally:
        writer.close()


def test_monthly_revenue_apply_rolls_back_transaction_without_restoring_whole_db(
    tmp_path,
    monkeypatch,
) -> None:
    raw_dir = tmp_path / "financial_data"
    _write_revenue_csv(raw_dir)
    availability_file = tmp_path / "monthly_revenue_availability.csv"
    _write_availability_csv(availability_file)
    db_file = tmp_path / "twstock.db"
    backup_dir = tmp_path / "task_backup"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        conn.execute("CREATE TABLE unrelated_state (value TEXT NOT NULL)")
        conn.execute("INSERT INTO unrelated_state(value) VALUES ('keep')")

    def _fail_after_partial_insert(conn, records):
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            )
            VALUES ('2330', '2026-05', '2026-05-31', '2026-06-10',
                    '2026-06-11', '999', 'fixture', 'partial-failure', 'observed')
            """
        )
        raise RuntimeError("injected writer failure")

    monkeypatch.setattr(
        backfill_module,
        "_insert_monthly_revenue_records",
        _fail_after_partial_insert,
    )
    real_backup = backfill_module._create_consistent_sqlite_backup

    def _backup_then_commit_after_backup(*args, **kwargs):
        backup_file = real_backup(*args, **kwargs)
        with sqlite3.connect(db_file) as concurrent:
            concurrent.execute(
                "INSERT INTO unrelated_state(value) VALUES ('after-backup')"
            )
        return backup_file

    monkeypatch.setattr(
        backfill_module,
        "_create_consistent_sqlite_backup",
        _backup_then_commit_after_backup,
    )

    try:
        apply_monthly_revenue_backfill(
            db_file=db_file,
            backup_dir=backup_dir,
            raw_dir=raw_dir,
            availability_file=availability_file,
            source_version="financial-data-csv-monthly-revenue-v1",
        )
    except RuntimeError as exc:
        assert str(exc) == "injected writer failure"
    else:
        raise AssertionError("injected writer failure was not raised")

    with sqlite3.connect(db_file) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM fundamental_monthly_revenues"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT value FROM unrelated_state"
        ).fetchone() == ("keep",)
        assert [
            row[0]
            for row in conn.execute(
                "SELECT value FROM unrelated_state ORDER BY rowid"
            ).fetchall()
        ] == ["keep", "after-backup"]
    assert len(list(backup_dir.glob("*.db"))) == 1
