"""Unit & Integration Tests for Gate 2 Data Governance Consolidation.

Tests:
1. Source Acceptance Governance (dossier diagnostics, fail-closed boundaries).
2. Data Quality Firewall (daily_prices anomalies with Decimal prices, market_indices degraded status).
3. PIT Safety Firewall & Provider Integration (no look-ahead bias, reason codes, rejection of future data on reading paths).
4. Approved Weekly History Projection (path security check, duplicate period check).
5. Scheduler Health Observability (ordering, status, write intent boundaries, path mapping fixtures).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import pytest
import pandas as pd

from data_module.data_quality_firewall import DataQualityFirewall, PITEvaluationResult
from data_module.fundamental_sqlite_provider import FundamentalSQLiteProvider
from data_module.gate2_manual_review_package import Gate2ManualReviewPackage
from data_module.scheduler_health_observability import SchedulerHealthService
from data_module.source_acceptance_governance import SourceAcceptanceDossier, SourceAcceptanceGovernance
from app_module.approved_weekly_history_projection import load_approved_weekly_history_projection, ApprovedWeeklyHistoryProjection


def test_source_acceptance_governance_fail_closed():
    governance = SourceAcceptanceGovernance()
    dossier = SourceAcceptanceDossier(
        source_id="test.source",
        source_owner_role="data_team",
        license_owner_role="legal",
        license_status="requires_review",
        license_scope="research_only",
        redistribution_policy="unverified",
        source_status="candidate",
        publication_time_policy="unverified",
        timezone="Asia/Taipei",
        available_date_policy="unverified",
        revision_policy="unverified",
        pit_coverage_window="unverified",
        coverage_numerator=0,
        coverage_denominator=100,
        missing_policy="fail_closed",
        row_conservation_counts={},
        quarantine_policy="quarantine_on_schema_error",
        quality_thresholds={"minimum_coverage_bp": 9500},
        downstream_use_cases=("research_backtest",),
        disable_conditions=("license_revoked",),
        rollback_reference="decision:test-ref",
        evidence_artifact_ids=(),
        downstream_eligibility="none",
    )
    diag = governance.diagnose_dossier(dossier)
    assert diag.status == "deferred"
    assert diag.downstream_eligibility == "none"
    assert diag.checklist_complete is False
    assert len(diag.active_blockers) > 0


def test_data_quality_firewall_daily_prices_decimal():
    firewall = DataQualityFirewall()

    # Create test dataframe with anomalies using Decimal-castable price strings
    df_test = pd.DataFrame([
        {"證券代號": "2330", "日期": "2026-07-21", "收盤價": "1000.0", "最高價": "1005.0", "最低價": "995.0"},
        {"證券代號": None, "日期": "2026-07-21", "收盤價": "50.0", "最高價": "51.0", "最低價": "49.0"}, # NULL stock code
        {"證券代號": "2330", "日期": "2026-07-21", "收盤價": "1000.0", "最高價": "1005.0", "最低價": "995.0"}, # Duplicate PK
        {"證券代號": "2317", "日期": "2026-07-19", "收盤價": "200.0", "最高價": "202.0", "最低價": "198.0"}, # Sunday date
        {"證券代號": "2454", "日期": "2026-07-21", "收盤價": "100.0", "最高價": "90.0", "最低價": "95.0"}, # High < Low
    ])

    report = firewall.inspect_daily_prices(df_test)
    assert report.total_records_checked == 5
    assert report.anomalies_found >= 3
    assert report.status in ("CRITICAL", "DEGRADED")

    anomaly_types = [a.anomaly_type for a in report.anomalies]
    assert "NULL_STOCK_CODE" in anomaly_types
    assert "DUPLICATE_PRIMARY_KEY" in anomaly_types
    assert "SUSPICIOUS_WEEKEND_DATE" in anomaly_types
    assert "INVALID_PRICE_BOUNDS" in anomaly_types


def test_data_quality_firewall_market_indices_degraded():
    firewall = DataQualityFirewall()

    # DataFrame missing canonical 指數名稱
    df_legacy = pd.DataFrame([
        {"日期": "2026-07-21", "收盤價": 23000.0, "收盤指數": 23000.0}
    ])

    status, desc, details = firewall.inspect_market_indices(df_legacy)
    assert status == "DEGRADED"
    assert "missing canonical" in desc or "missing index names" in desc


def test_pit_safety_evaluation_and_provider_integration(tmp_path: Path):
    firewall = DataQualityFirewall()

    # 1. Direct Firewall PIT Evaluation
    res_safe = firewall.evaluate_pit_availability(
        decision_date="2026-07-21",
        available_date="2026-07-20",
    )
    assert res_safe.is_usable is True
    assert res_safe.quality_status == "SAFE"

    res_future = firewall.evaluate_pit_availability(
        decision_date="2026-07-20",
        available_date="2026-07-21",
    )
    assert res_future.is_usable is False
    assert res_future.reason_code == "PIT_FUTURE_LOOK_AHEAD"

    res_missing_announcement = firewall.evaluate_pit_availability(
        decision_date="2026-07-21",
        available_date="2026-07-20",
        require_announced_date=True,
    )
    assert res_missing_announcement.is_usable is False
    assert res_missing_announcement.reason_code == "PIT_ANNOUNCED_DATE_MISSING"

    # 2. FundamentalSQLiteProvider Integration Test
    db_file = tmp_path / "test_fundamental.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE fundamental_monthly_revenues (
                stock_code TEXT, period TEXT, as_of_date TEXT, announced_date TEXT,
                available_date TEXT, revenue REAL, source TEXT, source_version TEXT, quality TEXT
            );
        """)
        # Insert one valid record plus three rows that must not enter a historical read.
        conn.execute("""
            INSERT INTO fundamental_monthly_revenues VALUES
            ('2330', '2026-06', '2026-06-30', '2026-07-10', '2026-07-10', 200000.0, 'twse', 'v1', 'observed'),
            ('2330', '2026-07', '2026-07-31', '2026-08-10', '2026-08-10', 220000.0, 'twse', 'v1', 'observed'),
            ('2330', '2026-05', '2026-05-31', NULL, '2026-07-09', 180000.0, 'twse', 'v1', 'observed'),
            ('2330', '2026-04', '2026-04-30', '2026-07-20', '2026-07-08', 170000.0, 'twse', 'v1', 'observed');
        """)

    provider = FundamentalSQLiteProvider(db_file, firewall=firewall)

    # Query with decision_date = 2026-07-15
    records = provider.load_monthly_revenues(stock_code="2330", decision_date=date(2026, 7, 15))
    assert len(records) == 1
    assert records[0].period == "2026-06"
    assert records[0].available_date == date(2026, 7, 10)


def test_approved_weekly_history_projection_path_security(tmp_path: Path):
    valid_payload = {
        "schema_version": "approved-weekly-history-projection.v1",
        "formal_credit_authorized": False,
        "records": [
            {
                "review_id": "rev_001",
                "review_hash": "hash_123",
                "period_start": "2026-07-06",
                "period_end": "2026-07-12",
                "owner_role": "portfolio_manager",
                "approved_at": "2026-07-12T18:00:00Z",
                "status": "approved_weekly_review",
            }
        ],
    }

    proj_file = tmp_path / "valid_proj.json"
    proj_file.write_text(json.dumps(valid_payload), encoding="utf-8")

    proj = load_approved_weekly_history_projection(proj_file)
    assert proj is not None
    assert len(proj.records) == 1

    with pytest.raises(ValueError, match="不得位於正式 SQLite 資料庫目錄中"):
        load_approved_weekly_history_projection("D:/Min/Python/Project/FA_Data/sqlite/projection.json")


def test_approved_weekly_history_projection_duplicate_period(tmp_path: Path):
    dup_payload = {
        "schema_version": "approved-weekly-history-projection.v1",
        "formal_credit_authorized": False,
        "records": [
            {
                "review_id": "rev_001",
                "review_hash": "hash_123",
                "period_start": "2026-07-06",
                "period_end": "2026-07-12",
                "owner_role": "portfolio_manager",
                "approved_at": "2026-07-12T18:00:00Z",
                "status": "approved_weekly_review",
            },
            {
                "review_id": "rev_002",
                "review_hash": "hash_456",
                "period_start": "2026-07-06",
                "period_end": "2026-07-12",
                "owner_role": "portfolio_manager",
                "approved_at": "2026-07-12T19:00:00Z",
                "status": "approved_weekly_review",
            },
        ],
    }

    proj_file = tmp_path / "dup_proj.json"
    proj_file.write_text(json.dumps(dup_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="包含重複的週期"):
        load_approved_weekly_history_projection(proj_file)


def test_scheduler_health_observability_directory_fixtures(tmp_path: Path):
    # Construct mock output directory with actual status files
    out_dir = tmp_path / "output"
    sched_dir = out_dir / "scheduled"

    (sched_dir / "data_update_quick").mkdir(parents=True)
    (sched_dir / "data_freshness").mkdir(parents=True)
    (sched_dir / "recommendation_snapshot").mkdir(parents=True)
    (sched_dir / "evidence_pipeline_dry_run").mkdir(parents=True)
    (sched_dir / "v2_2_weekly_collection").mkdir(parents=True)

    (sched_dir / "data_update_quick" / "latest_status.json").write_text(
        json.dumps({"status": "passed_with_warnings", "timestamp": "2026-07-21T04:30:00"}), encoding="utf-8"
    )
    (sched_dir / "data_freshness" / "latest_status.json").write_text(
        json.dumps({"status": "passed", "timestamp": "2026-07-21T05:00:00"}), encoding="utf-8"
    )
    (sched_dir / "recommendation_snapshot" / "latest_status.json").write_text(
        json.dumps({"status": "passed", "timestamp": "2026-07-21T05:10:00"}), encoding="utf-8"
    )
    (sched_dir / "evidence_pipeline_dry_run" / "latest_status.json").write_text(
        json.dumps({"status": "ready_with_advisories", "timestamp": "2026-07-21T05:15:00"}), encoding="utf-8"
    )
    (sched_dir / "v2_2_weekly_collection" / "v2_2_weekly_collection_20260719.json").write_text(
        json.dumps(
            {
                "collection_status": "observed_automatic",
                "collection_record": {"created_at": "2026-07-20T01:00:00"},
            }
        ),
        encoding="utf-8",
    )

    from data_module.config import TWStockConfig
    mock_config = TWStockConfig()
    mock_config.output_root = out_dir

    service = SchedulerHealthService(mock_config)
    report = service.audit_scheduler_health()

    assert report.production_scheduler_allowed is False
    assert len(report.tasks) == 5
    assert report.ordering_valid is True

    # Verify tasks 0-3 are found and classified correctly
    t0 = report.tasks[0]
    assert t0.task_name == "daily_data_update_quick"
    assert t0.status == "PASSED_WITH_WARNINGS"

    t1 = report.tasks[1]
    assert t1.task_name == "daily_data_freshness_check"
    assert t1.status == "SUCCESS"

    t3 = report.tasks[3]
    assert t3.task_name == "scheduled_evidence_pipeline_dry_run"
    assert t3.status == "PASSED_WITH_WARNINGS"

    t4 = report.tasks[4]
    assert t4.task_name == "v2_2_weekly_collection"
    assert t4.status == "SUCCESS"
    assert t4.write_intent == "AUTOMATIC_SIDECAR_APPEND"
    assert t4.last_run_timestamp == "2026-07-20T01:00:00"
    assert all(task.status != "MISSING" for task in report.tasks)
