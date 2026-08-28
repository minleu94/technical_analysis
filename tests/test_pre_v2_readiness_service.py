from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEvent,
    EvidenceEventType,
    EvidenceOutcome,
    EvidenceOutcomeStatus,
)
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.update_status_history import append_update_status_history
from app_module.pre_v2_readiness_service import (
    PreV2ReadinessService,
    STATUS_ACTION_REQUIRED,
    STATUS_READY,
    STATUS_WAITING_FOR_TIME,
    render_pre_v2_readiness_markdown,
)
from data_module.config import TWStockConfig
from scripts.inspect_program_readiness import (
    inspect_program_readiness,
    render_markdown,
)


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence.db"
    config.use_sqlite = True
    return config


def _seed_evidence_event(config: TWStockConfig) -> None:
    repo = EvidenceEventRepository(config)
    event = repo.insert_event(
        EvidenceEvent(
            event_id="evt-pre-v2",
            event_hash="sha256:evt-pre-v2",
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
            outcome_id="out-pre-v2",
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
                decision_quality_reviews_count INTEGER NOT NULL DEFAULT 0,
                signal_decay_observations_count INTEGER NOT NULL DEFAULT 0,
                manual_lifecycle_candidate_count INTEGER NOT NULL DEFAULT 0,
                warnings_count INTEGER NOT NULL DEFAULT 0,
                generated_by TEXT NOT NULL DEFAULT '',
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
                    production_scheduler_allowed,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, '{}')
                """,
                (
                    f"eor-{index}",
                    f"sha256:{index}",
                    f"2026-07-{1 + index:02d}",
                    f"2026-07-{5 + index:02d}",
                    "coverage_only",
                    "not_ready",
                ),
            )


def _seed_pending_weekly_sidecar(config: TWStockConfig, count: int) -> None:
    sidecar = (
        Path(config.output_root)
        / "scheduled"
        / "v2_2_weekly_collection"
        / "evidence_scheduler.db"
    )
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sidecar) as conn:
        conn.execute(
            """
            CREATE TABLE evidence_weekly_collections (
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                status TEXT NOT NULL,
                error_type TEXT NOT NULL,
                source_hash TEXT NOT NULL
            )
            """
        )
        for index in range(count):
            conn.execute(
                """
                INSERT INTO evidence_weekly_collections
                    (period_start, period_end, status, error_type, source_hash)
                VALUES (?, ?, 'pending_human_review', '', ?)
                """,
                (
                    f"2026-06-{1 + index * 7:02d}",
                    f"2026-06-{7 + index * 7:02d}",
                    f"sha256:{index:064d}",
                ),
            )


def _seed_recommendation(config: TWStockConfig, *, with_payloads: bool) -> None:
    runs_dir = Path(config.output_root) / "recommendation" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "result_id": "rec-ready",
        "why_not_payload_json": [{"stock_code": "1101", "reason_codes": ["weak_rs"]}]
        if with_payloads
        else [],
        "liquidity_gate_payload_json": [{"stock_code": "2201", "reason_codes": ["low_liquidity"]}]
        if with_payloads
        else [],
        "screening_matrix_json": [{"stock_code": "2330", "status": "pass", "quality": "observed"}]
        if with_payloads
        else [],
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


def _seed_decision_desk_snapshot(
    db_path: Path,
    *,
    decision_date: str = "2026-07-06",
    snapshot_id: str = "dds-ready",
) -> None:
    section = {"quality": "observed", "as_of_date": decision_date}
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_desk_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                snapshot_hash TEXT NOT NULL UNIQUE,
                decision_date TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                source_version TEXT NOT NULL,
                builder_version TEXT NOT NULL,
                data_quality TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                market_regime_json TEXT NOT NULL,
                market_breadth_json TEXT NOT NULL,
                sector_rotation_json TEXT NOT NULL,
                relative_strength_liquidity_json TEXT NOT NULL,
                watchlist_trigger_json TEXT NOT NULL,
                portfolio_alert_json TEXT NOT NULL,
                risk_prompt_json TEXT NOT NULL,
                fundamental_diagnostics_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                snapshot_status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO decision_desk_snapshots (
                snapshot_id,
                snapshot_hash,
                decision_date,
                as_of_date,
                source_version,
                builder_version,
                data_quality,
                warnings_json,
                market_regime_json,
                market_breadth_json,
                sector_rotation_json,
                relative_strength_liquidity_json,
                watchlist_trigger_json,
                portfolio_alert_json,
                risk_prompt_json,
                fundamental_diagnostics_json,
                metadata_json,
                snapshot_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                snapshot_id,
                f"sha256:{snapshot_id}",
                decision_date,
                decision_date,
                "test",
                "test",
                "observed",
                "[]",
                json.dumps(section),
                json.dumps(section),
                json.dumps(section),
                json.dumps(section),
                json.dumps(section),
                json.dumps(section),
                json.dumps(section),
                "{}",
                "{}",
            ),
        )


def test_pre_v2_readiness_excludes_future_decision_desk_snapshot_from_current_source_gap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        "app_module.pre_v2_readiness_service.taiwan_market_today",
        lambda: date(2026, 7, 7),
    )
    _seed_recommendation(config, with_payloads=True)
    _seed_decision_desk_snapshot(config.db_file)
    _seed_decision_desk_snapshot(
        config.db_file,
        decision_date="2026-07-08",
        snapshot_id="dds-future",
    )

    source_gaps = {
        item.item_id: item
        for item in PreV2ReadinessService(config, evidence_db_path=config.db_file).inspect().items
    }["source_gaps"]

    assert source_gaps.status == STATUS_ACTION_REQUIRED
    assert "decision_desk_snapshot_future_dated" in source_gaps.blocking_reasons
    assert source_gaps.evidence["latest_decision_desk_snapshot_date"] == "2026-07-06"
    assert source_gaps.evidence["decision_desk_snapshot_future_dates"] == ["2026-07-08"]
    assert "decision_desk_snapshot_future_date:2026-07-08:today=2026-07-07" in source_gaps.diagnostics


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


def _seed_scheduled_dry_run_status(config: TWStockConfig, *, decision_date: str) -> None:
    status_dir = Path(config.output_root) / "scheduled" / "evidence_pipeline_dry_run"
    status_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": f"{decision_date}T11:36:05",
        "decision_date": decision_date,
        "dry_run": True,
        "exit_code": 0,
        "status": "passed",
        "writes_evidence_db": False,
        "scheduler_readiness_after": "ready_for_manual_confirm",
        "source_coverage_basis": "dry_run_transient_decision_desk_snapshot",
        "source_coverage_blocking_gaps": [],
        "source_coverage_warnings": [],
        "pipeline_blocking_gaps": [],
        "pipeline_diagnostic_codes": [],
        "recommendation_exclusion_payload_available": True,
        "recommendation_screening_matrix_available": True,
        "why_not_capture_ready": True,
        "liquidity_gate_capture_ready": True,
        "screening_matrix_capture_ready": True,
        "report_path": str(status_dir / "reports" / f"{decision_date.replace('-', '')}_evidence_pipeline_dry_run.md"),
    }
    (status_dir / "latest_status.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_pre_v2_readiness_reports_parallel_ready_and_time_waiting_items(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_evidence_event(config)
    _seed_weekly_history(config.db_file, 1)
    _seed_recommendation(config, with_payloads=True)
    _seed_decision_desk_snapshot(config.db_file)
    record_path = tmp_path / "multi-day.md"
    _multi_day_record(record_path, rows=1)

    report = PreV2ReadinessService(config, evidence_db_path=config.db_file).inspect(
        decision_date="2026-07-06",
        multi_day_record_path=record_path,
    )
    items = {item.item_id: item for item in report.items}

    assert report.overall_status == STATUS_WAITING_FOR_TIME
    assert items["weekly_history"].status == STATUS_WAITING_FOR_TIME
    assert items["multi_day_dry_run"].status == STATUS_WAITING_FOR_TIME
    assert items["source_gaps"].status == STATUS_READY
    assert items["read_only_agent_report_sample"].status == STATUS_READY
    assert report.production_scheduler_allowed is False
    assert report.rule_operational_scheduler_allowed is True
    assert report.required_human_action is False
    assert report.automatic_revalidation_enabled is True
    assert report.blocking_scope == "formal_evidence_credit_only"
    assert report.formal_credit_authorized is False
    assert "V2.0" in render_pre_v2_readiness_markdown(report)


def test_pre_v2_readiness_uses_explicit_owner_approved_weekly_projection(tmp_path: Path) -> None:
    config = _config(tmp_path)
    projection_path = tmp_path / "approved-weekly-history.json"
    projection_path.write_text(
        json.dumps(
            {
                "schema_version": "approved-weekly-history-projection.v1",
                "formal_credit_authorized": False,
                "records": [
                    {
                        "review_id": "eor_week1",
                        "review_hash": "sha256:week1",
                        "period_start": "2026-07-06",
                        "period_end": "2026-07-12",
                        "owner_role": "archi",
                        "approved_at": "2026-07-13T00:00:00+08:00",
                        "status": "approved_weekly_review",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = PreV2ReadinessService(
        config,
        evidence_db_path=tmp_path / "missing.db",
        approved_weekly_history_projection_path=projection_path,
    ).inspect(decision_date="2026-07-20")
    weekly = {item.item_id: item for item in report.items}["weekly_history"]
    assert weekly.observed_count == 1
    assert weekly.status == STATUS_WAITING_FOR_TIME
    assert weekly.evidence["approved_projection_path"] == str(projection_path)


def test_pre_v2_readiness_flags_source_and_report_gaps_without_creating_missing_db(tmp_path: Path) -> None:
    config = _config(tmp_path)
    missing_db = tmp_path / "missing" / "evidence.db"
    record_path = tmp_path / "multi-day.md"
    _multi_day_record(record_path, rows=0)

    report = PreV2ReadinessService(config, evidence_db_path=missing_db).inspect(
        decision_date="2026-07-06",
        multi_day_record_path=record_path,
    )
    items = {item.item_id: item for item in report.items}

    assert report.overall_status == STATUS_ACTION_REQUIRED
    assert items["weekly_history"].status == STATUS_WAITING_FOR_TIME
    assert "approved_weekly_history_projection_not_configured" in items["weekly_history"].diagnostics
    assert any(
        "WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH" in action
        for action in items["weekly_history"].next_actions
    )
    assert items["source_gaps"].status == STATUS_ACTION_REQUIRED
    assert items["read_only_agent_report_sample"].status == STATUS_ACTION_REQUIRED
    assert not missing_db.exists()


def test_pre_v2_readiness_excludes_pending_weekly_sidecar_from_gate(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    _seed_pending_weekly_sidecar(config, 3)

    weekly = PreV2ReadinessService(
        config,
        evidence_db_path=tmp_path / "missing.db",
    )._weekly_history_item(3)

    assert weekly.status == STATUS_WAITING_FOR_TIME
    assert weekly.observed_count == 0
    assert weekly.evidence["human_approval_required"] is True
    assert weekly.evidence["automatic_revalidation"] is False
    assert len(weekly.evidence["pending_collection_periods"]) == 3
    assert weekly.evidence["observed_periods"] == []
    assert "owner/reviewer" in weekly.next_actions[0]
    assert "不計 Gate credit" in weekly.next_actions[0]


def test_pre_v2_readiness_accepts_same_day_scheduled_dry_run_for_corrected_source_gap_closeout(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    missing_formal_db = tmp_path / "formal" / "twstock.db"
    record_path = tmp_path / "multi-day.md"
    _multi_day_record(record_path, rows=3)
    _seed_scheduled_dry_run_status(config, decision_date="2026-07-08")

    report = PreV2ReadinessService(config, evidence_db_path=missing_formal_db).inspect(
        decision_date="2026-07-08",
        multi_day_record_path=record_path,
    )
    source_gaps = {item.item_id: item for item in report.items}["source_gaps"]

    assert source_gaps.status == STATUS_READY
    assert source_gaps.blocking_reasons == ()
    assert source_gaps.evidence["source_gap_basis"] == "scheduled_dry_run_latest_status"
    assert source_gaps.evidence["corrected_historical_observation_allowed"] is True
    assert source_gaps.evidence["scheduled_dry_run_decision_date"] == "2026-07-08"
    assert source_gaps.evidence["writes_evidence_db"] is False
    assert "decision_desk_snapshot_missing" not in source_gaps.evidence["blocking_gaps"]
    assert not missing_formal_db.exists()


def test_pre_v2_readiness_does_not_use_future_scheduled_status_for_source_gap_closeout(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    missing_formal_db = tmp_path / "formal" / "twstock.db"
    record_path = tmp_path / "multi-day.md"
    _multi_day_record(record_path, rows=3)
    _seed_scheduled_dry_run_status(config, decision_date="2026-07-08")

    report = PreV2ReadinessService(config, evidence_db_path=missing_formal_db).inspect(
        decision_date="2026-07-07",
        multi_day_record_path=record_path,
    )
    source_gaps = {item.item_id: item for item in report.items}["source_gaps"]

    assert source_gaps.status == STATUS_ACTION_REQUIRED
    assert "decision_desk_snapshot_missing" in source_gaps.blocking_reasons


def test_program_readiness_aggregates_lanes_without_creating_missing_roots(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"

    report = inspect_program_readiness(
        data_root=data_root,
        output_root=output_root,
        training_as_of=None,
    )

    assert report["schema_version"] == "program-readiness.v1"
    assert report["status"] == "action_required"
    assert set(report["workstreams"]) == {
        "p0",
        "evidence",
        "paper",
        "formal_ml",
        "runtime",
        "update_history",
        "performance",
    }
    assert report["boundary"]["writes_allowed"] is False
    assert report["boundary"]["formal_oos_allowed"] is False
    assert report["safety"]["side_effect_free"] is True
    assert not data_root.exists()
    assert not output_root.exists()


def test_program_readiness_marks_update_history_identity_mismatch(tmp_path: Path) -> None:
    history_path = tmp_path / "output" / "scheduled" / "data_update_quick" / "history.jsonl"
    payload = {
        "run_id": "run-1",
        "status": "running",
        "started_at": "2026-08-28T01:00:00+08:00",
        "steps": [{"name": "TWSE daily", "status": "passed", "message": "ok"}],
    }
    append_update_status_history(history_path, payload, captured_at="2026-08-28T01:00:01+08:00")
    payload["status"] = "passed"
    payload["completed_at"] = "2026-08-28T01:02:00+08:00"
    append_update_status_history(history_path, payload, captured_at="2026-08-28T01:02:01+08:00")
    latest_status_path = history_path.with_name("latest_status.json")
    latest_status_path.write_text(
        json.dumps({"run_id": "run-2", "status": "passed"}),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        update_history_path=history_path,
        update_status_path=latest_status_path,
    )
    lane = report["workstreams"]["update_history"]

    assert lane["status"] == "action_required"
    assert "latest_status_run_not_equal_to_history_latest_run" in lane["blockers"]
    assert lane["details"]["terminal_record_count"] == 1
    assert lane["details"]["unique_run_count"] == 1


def test_program_readiness_markdown_exposes_order_and_performance_boundary(tmp_path: Path) -> None:
    technical_path = tmp_path / "technical.json"
    technical_path.write_text(
        json.dumps(
            {
                "status": "measured",
                "read_only": True,
                "write_attempted": False,
                "parallelism_enabled": False,
                "observed_worker_count": 1,
            }
        ),
        encoding="utf-8",
    )
    broker_path = tmp_path / "broker.json"
    broker_path.write_text(json.dumps({"status": "measured"}), encoding="utf-8")
    batch_path = tmp_path / "technical-batch.json"
    batch_path.write_text(
        json.dumps(
            {
                "schema_version": "technical-indicator-full-batch-latency.v1",
                "status": "measured",
                "read_only": True,
                "write_attempted": False,
                "sqlite_write_attempted": False,
                "parallelism_enabled": False,
                "observed_worker_count": 1,
                "single_writer_required": True,
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        technical_performance_path=technical_path,
        technical_batch_performance_path=batch_path,
        broker_performance_path=broker_path,
    )
    rendered = render_markdown(report)

    assert "# Program Readiness" in rendered
    assert "## 依序推進" in rendered
    assert "`performance`" in rendered
    assert "bounded worker" in rendered
    assert report["workstreams"]["performance"]["status"] == "partial"
    assert report["workstreams"]["performance"]["details"]["artifacts"]["technical_batch"]["status"] == "measured"
