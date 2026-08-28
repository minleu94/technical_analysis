from __future__ import annotations

import csv
import sqlite3

from data_module.fundamental_availability_sources import (
    MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
)

from app_module.update_service import UpdateService


def test_monthly_revenue_status_separates_imported_and_pit_available_periods(
    test_config,
    monkeypatch,
) -> None:
    with sqlite3.connect(test_config.db_file) as conn:
        conn.execute(
            """
            CREATE TABLE fundamental_monthly_revenues (
                stock_code TEXT NOT NULL,
                period TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                announced_date TEXT,
                available_date TEXT NOT NULL,
                revenue TEXT NOT NULL,
                source TEXT NOT NULL,
                source_version TEXT NOT NULL,
                quality TEXT NOT NULL,
                PRIMARY KEY (stock_code, period, source_version)
            )
            """
        )
        conn.executemany(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("2330", "2026-05", "2026-05-31", "2026-06-16", "2026-06-17", "100", "mops", "v1", "observed"),
                ("2330", "2026-06", "2026-06-30", "2026-07-14", "2026-07-15", "110", "mops", "v2", "observed"),
                ("2317", "2026-05", "2026-05-31", "2026-06-15", "2026-06-16", "90", "mops", "v1", "observed"),
                ("2317", "2026-06", "2026-06-30", "2026-07-13", "2026-07-14", "95", "mops", "v2", "observed"),
            ],
        )

    monkeypatch.setattr(
        "app_module.update_service._monthly_revenue_status_today",
        lambda: "2026-07-14",
        raising=False,
    )

    status = UpdateService(test_config)._monthly_revenue_status_from_sqlite()

    assert status["latest_period"] == "2026-06"
    assert status["latest_available_period"] == "2026-05"
    assert status["next_available_date"] == "2026-07-15"
    assert status["pending_period_count"] == 1


def test_monthly_revenue_status_marks_newer_snapshot_as_candidate(
    test_config,
    monkeypatch,
) -> None:
    with sqlite3.connect(test_config.db_file) as conn:
        conn.execute(
            """
            CREATE TABLE fundamental_monthly_revenues (
                stock_code TEXT NOT NULL,
                period TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                announced_date TEXT,
                available_date TEXT NOT NULL,
                revenue TEXT NOT NULL,
                source TEXT NOT NULL,
                source_version TEXT NOT NULL,
                quality TEXT NOT NULL,
                PRIMARY KEY (stock_code, period, source_version)
            )
            """
        )
        conn.execute(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2330", "2026-06", "2026-06-30", "2026-07-14", "2026-07-15", "110", "mops", "v2", "observed"),
        )

    snapshot_dir = test_config.output_root / "monthly_revenue_mops_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / "mops_monthly_revenue_snapshot_2026-07_2026-07_2026-08-28.csv"
    snapshot.write_text("market,period,stock_code\ntwse,2026-07,2330\n", encoding="utf-8")

    monkeypatch.setattr(
        "app_module.update_service._monthly_revenue_status_today",
        lambda: "2026-08-28",
        raising=False,
    )

    status = UpdateService(test_config)._monthly_revenue_status_from_sqlite()

    assert status["candidate_latest_period"] == "2026-07"
    assert status["candidate_fetch_date"] == "2026-08-28"
    assert status["status"] == "candidate_available"
    assert status["warnings"]


def test_monthly_revenue_status_projects_explicit_availability_candidate(
    test_config,
    monkeypatch,
) -> None:
    with sqlite3.connect(test_config.db_file) as conn:
        conn.execute(
            """
            CREATE TABLE fundamental_monthly_revenues (
                stock_code TEXT NOT NULL,
                period TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                announced_date TEXT,
                available_date TEXT NOT NULL,
                revenue TEXT NOT NULL,
                source TEXT NOT NULL,
                source_version TEXT NOT NULL,
                quality TEXT NOT NULL,
                PRIMARY KEY (stock_code, period, source_version)
            )
            """
        )
        conn.execute(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2330", "2026-06", "2026-06-30", "2026-07-14", "2026-07-15", "110", "mops", "v2", "observed"),
        )

    candidate = test_config.output_root / "monthly_revenue_availability_2026-07.csv"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "stock_code": "2330",
            "period": "2026-07",
            "as_of_date": "2026-07-31",
            "announced_date": "2026-08-17",
            "available_date": "2026-08-18",
            "source": "twse.monthly_revenue_announcement",
            "source_version": "twse-openapi-t187ap05-l-2026-08-28",
            "availability_contract_version": "formal-availability.v2",
            "evidence_class": "official_announcement",
            "source_hash": "sha256:" + "a" * 64,
            "revision": "1",
            "parent_revision": "",
        },
        {
            "stock_code": "2317",
            "period": "2026-07",
            "as_of_date": "2026-07-31",
            "announced_date": "2026-08-17",
            "available_date": "2026-08-18",
            "source": "twse.monthly_revenue_announcement",
            "source_version": "twse-openapi-t187ap05-l-2026-08-28",
            "availability_contract_version": "formal-availability.v2",
            "evidence_class": "official_announcement",
            "source_hash": "sha256:" + "b" * 64,
            "revision": "1",
            "parent_revision": "",
        },
    ]
    with candidate.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MONTHLY_REVENUE_AVAILABILITY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    monkeypatch.setattr(
        "app_module.update_service._monthly_revenue_status_today",
        lambda: "2026-08-28",
        raising=False,
    )

    status = UpdateService(
        test_config,
        monthly_revenue_availability_candidate_path=candidate,
    )._monthly_revenue_status_from_sqlite()

    assert status["availability_candidate_status"] == "ready_for_merge"
    assert status["availability_candidate_row_count"] == 2
    assert status["availability_candidate_latest_period"] == "2026-07"
    assert status["availability_candidate_latest_available_date"] == "2026-08-18"
    assert status["availability_candidate_added_count"] == 2
    assert status["availability_candidate_conflict_count"] == 0
    assert status["status"] == "candidate_available"
    assert any("公告日／可得日 mapping 候選" in item for item in status["warnings"])
