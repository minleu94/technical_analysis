from __future__ import annotations

from datetime import date, datetime
import json
import sqlite3
from pathlib import Path

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskRiskPrompt,
    DecisionDeskRiskPromptSummary,
    DecisionDeskSnapshot,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)
from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.decision_desk_snapshot_storage_dtos import build_stored_decision_desk_snapshot
from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEvent,
    EvidenceEventType,
    EvidenceOutcome,
    EvidenceOutcomeStatus,
)
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.workbench_source_service import WorkbenchSourceService
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence.db"
    config.research_run_db_file = tmp_path / "research_runs.db"
    config.use_sqlite = True
    return config


def _decision_snapshot() -> DecisionDeskSnapshot:
    sample_date = date(2026, 7, 6)
    return DecisionDeskSnapshot(
        as_of_date=sample_date,
        generated_at=datetime(2026, 7, 6, 12, 0, 0),
        schema_version=1,
        overall_quality=DecisionDeskQuality.OBSERVED,
        market_regime=MarketRegimeSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            regime_label="risk-on",
        ),
        market_breadth=MarketBreadthSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            breadth_ratio_bp=6200,
            advancing=120,
            declining=80,
            unchanged=10,
        ),
        sector_rotation=SectorRotationSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            leading_sector="半導體",
            trailing_sector="金融",
        ),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=("low_liquidity:9999",),
            top_strength_codes=("2330",),
            weak_strength_codes=("1101",),
            low_liquidity_codes=("9999",),
        ),
        watchlist_triggers=WatchlistTriggerSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            trigger_count=1,
            triggered_codes=("2603",),
            top_signal="momentum_breakout",
        ),
        portfolio_alerts=PortfolioAlertSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            alert_count=1,
            alert_codes=("2330",),
            alert_level="high",
        ),
        risk_prompts=DecisionDeskRiskPromptSummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            prompts=(
                DecisionDeskRiskPrompt(
                    category="portfolio",
                    severity="warning",
                    source="portfolio_alert",
                    code="2330",
                    title="Thesis invalidation review",
                    reason="持倉警示需要人工覆盤。",
                    action_hint="檢查 journal 與風險來源。",
                ),
            ),
        ),
    )


def _seed_ready_sources(config: TWStockConfig, multi_day_record: Path) -> None:
    _seed_evidence_event(config)
    _seed_weekly_history(config.db_file, count=1)
    _seed_recommendation(config)
    DecisionDeskSnapshotRepository(config, db_path=config.db_file).save_snapshot(
        build_stored_decision_desk_snapshot(_decision_snapshot(), decision_date="2026-07-06")
    )
    _multi_day_record(multi_day_record, rows=1)


def _seed_evidence_event(config: TWStockConfig) -> None:
    repo = EvidenceEventRepository(config, db_path=config.db_file)
    event = repo.insert_event(
        EvidenceEvent(
            event_id="evt-workbench",
            event_hash="sha256:evt-workbench",
            event_date="2026-07-06",
            decision_date="2026-07-06",
            symbol="2330",
            event_type=EvidenceEventType.RECOMMENDATION_INCLUDED,
            event_family="recommendation",
            source_type="recommendation_result",
            source_id="rec-ready",
            data_quality=EvidenceDataQuality.OBSERVED,
            as_of_date="2026-07-06",
            available_date="2026-07-06",
        )
    )
    repo.upsert_outcome(
        EvidenceOutcome(
            outcome_id="out-workbench",
            event_id=event.event_id,
            window_days=5,
            forward_return_bp=120,
            outcome_status=EvidenceOutcomeStatus.READY,
            data_quality=EvidenceDataQuality.OBSERVED,
        )
    )


def _seed_weekly_history(db_path: Path, count: int) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE evidence_operations_weekly_reviews (
                review_id TEXT PRIMARY KEY,
                review_hash TEXT NOT NULL UNIQUE,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                review_status TEXT NOT NULL,
                scheduler_readiness TEXT NOT NULL,
                production_scheduler_allowed INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for index in range(count):
            conn.execute(
                """
                INSERT INTO evidence_operations_weekly_reviews (
                    review_id,
                    review_hash,
                    period_start,
                    period_end,
                    review_status,
                    scheduler_readiness,
                    production_scheduler_allowed
                )
                VALUES (?, ?, ?, ?, 'coverage_only', 'not_ready', 0)
                """,
                (f"review-{index}", f"sha256:review-{index}", "2026-07-01", "2026-07-06"),
            )


def _seed_recommendation(config: TWStockConfig) -> None:
    runs_dir = Path(config.output_root) / "recommendation" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "result_id": "rec-ready",
        "why_not_payload_json": [{"stock_code": "1101", "reason_codes": ["weak_rs"]}],
        "liquidity_gate_payload_json": [{"stock_code": "2201", "reason_codes": ["low_liquidity"]}],
        "screening_matrix_json": [{"stock_code": "2330", "status": "pass", "quality": "observed"}],
    }
    data_path = runs_dir / "rec-ready.json"
    data_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with sqlite3.connect(runs_dir / "recommendation_runs.db") as conn:
        conn.execute(
            """
            CREATE TABLE runs (
                result_id TEXT PRIMARY KEY,
                result_name TEXT NOT NULL,
                regime TEXT,
                stock_count INTEGER,
                config TEXT,
                notes TEXT,
                created_at TEXT,
                data_path TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO runs (
                result_id,
                result_name,
                regime,
                stock_count,
                config,
                notes,
                created_at,
                data_path
            )
            VALUES ('rec-ready', 'Ready recommendation', 'trend', 1, '{}', '', '2026-07-06T12:00:00', ?)
            """,
            (str(data_path),),
        )


def _multi_day_record(path: Path, rows: int) -> None:
    lines = [
        "| Date | Data update status | Source coverage status | Dry-run pipeline status | Working-copy confirm smoke status | Events seen | Events inserted in working copy | Outcomes created in working copy | Summary groups | Warnings count | Blocking gaps | Dashboard review completed | Human reviewer notes | Decision |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|",
    ]
    for index in range(rows):
        lines.append(
            f"| 2026-07-{2 + index:02d} | passed | ready | passed | passed | 10 | 10 | 10 | 1 | 0 |  | yes | ok | continue dry-run |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def test_workbench_source_service_reads_real_read_only_sources(tmp_path: Path) -> None:
    config = _config(tmp_path)
    record_path = tmp_path / "multi-day.md"
    _seed_ready_sources(config, record_path)

    dashboard = WorkbenchSourceService(config, evidence_db_path=config.db_file).inspect(
        decision_date="2026-07-06",
        multi_day_record_path=record_path,
    )
    payload = dashboard.to_dict()
    status_items = {item["item_id"]: item for item in payload["status_strip"]}

    assert payload["source_mode"] == "read_only_sources"
    assert status_items["decision_snapshot"]["value"] == "2026-07-06"
    assert status_items["scheduler"]["value"] == "off"
    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["access_boundary"]["production_scheduler_allowed"] is False
    assert any(item["source"] == "risk_prompt" for item in payload["review_items"])
    assert {item["item_id"] for item in payload["background_evidence_feed"]} == {
        "daily_decision_snapshot",
        "evidence_review_readiness",
        "portfolio_alerts",
        "replay_summary_diagnostics",
    }
    assert payload["action_items"]
    assert all(item["source_trace"] for item in payload["action_items"])
    assert all(item["degraded_reason"] for item in payload["action_items"])
    assert all(item["drilldown_target"] for item in payload["action_items"])
    assert not any(item["write_intent"] for item in payload["action_items"])


def test_workbench_source_service_missing_db_does_not_create_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    missing_db = tmp_path / "missing" / "evidence.db"
    record_path = tmp_path / "multi-day.md"
    _multi_day_record(record_path, rows=0)

    dashboard = WorkbenchSourceService(config, evidence_db_path=missing_db).inspect(
        decision_date="2026-07-06",
        multi_day_record_path=record_path,
    )
    payload = dashboard.to_dict()
    status_items = {item["item_id"]: item for item in payload["status_strip"]}

    assert not missing_db.exists()
    assert status_items["decision_snapshot"]["value"] == "missing"
    assert any("decision_desk_snapshot_db_missing" in warning for warning in payload["warnings"])
    assert payload["access_boundary"]["production_scheduler_allowed"] is False
    assert not any(item["write_intent"] for item in payload["action_items"])


def test_workbench_source_service_missing_snapshot_table_is_degraded_source(tmp_path: Path) -> None:
    config = _config(tmp_path)
    record_path = tmp_path / "multi-day.md"
    _seed_evidence_event(config)
    _seed_weekly_history(config.db_file, count=1)
    _seed_recommendation(config)
    _multi_day_record(record_path, rows=1)

    dashboard = WorkbenchSourceService(config, evidence_db_path=config.db_file).inspect(
        decision_date="2026-07-06",
        multi_day_record_path=record_path,
    )
    payload = dashboard.to_dict()
    status_items = {item["item_id"]: item for item in payload["status_strip"]}

    assert status_items["decision_snapshot"]["status"] == "warning"
    assert any("decision_desk_snapshots_table_missing" in warning for warning in payload["warnings"])
    assert any(item["item_id"] == "readiness_source_gaps" for item in payload["review_items"])


def test_workbench_source_service_surfaces_replay_quality_disclosures_without_replay_db(tmp_path: Path) -> None:
    config = _config(tmp_path)
    missing_db = tmp_path / "missing" / "evidence.db"
    record_path = tmp_path / "multi-day.md"
    replay_summary_path = tmp_path / "replay_summary.json"
    _multi_day_record(record_path, rows=1)
    replay_summary_path.write_text(
        json.dumps(
            {
                "replay_mode": "historical_replay",
                "source_label": "simulated_scheduler",
                "totals": {
                    "days": 118,
                    "events_seen": 118056,
                    "outcomes_created": 472224,
                },
                "final_outcome_summary": {
                    "ready": 380736,
                    "pending_insufficient_future_data": 91488,
                    "missing_benchmark": 0,
                    "missing_industry_benchmark": 378491,
                },
                "days": [
                    {
                        "date": "2026-01-06",
                        "diagnostics": ["source_missing_screening_matrix"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    dashboard = WorkbenchSourceService(config, evidence_db_path=missing_db).inspect(
        decision_date="2026-07-06",
        multi_day_record_path=record_path,
        replay_summary_json=replay_summary_path,
    )
    payload = dashboard.to_dict()
    evidence = {item["item_id"]: item for item in payload["evidence_summary"]}
    replay_diagnostics = " ".join(evidence["historical_replay"]["diagnostics"])

    assert payload["source_mode"] == "read_only_sources_plus_historical_replay"
    assert not missing_db.exists()
    assert "simulated_scheduler" in replay_diagnostics
    assert "source_gap:source_missing_screening_matrix" in replay_diagnostics
    assert "source_gap_coverage:source_missing_screening_matrix=1/1" in replay_diagnostics
    assert "payload_gap:missing_industry_benchmark" in replay_diagnostics
    assert "outcome_maturity:ready=380736,pending_future_data=91488" in replay_diagnostics
    assert "benchmark_coverage:covered=380736,total=380736,missing=0" in replay_diagnostics
    assert "industry_benchmark_coverage:covered=2245,total=380736,missing=378491" in replay_diagnostics
    assert "missing_industry_benchmark:378491" in replay_diagnostics
    assert "pending_future_data:91488" in replay_diagnostics
    assert "replay_direction_assessment" in replay_diagnostics
    assert "phase0_gate_not_satisfied" in replay_diagnostics
