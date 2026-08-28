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


def test_pre_v2_readiness_reads_explicit_pending_weekly_sidecar_outside_output_root(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    sidecar = tmp_path / "isolated" / "evidence_scheduler.db"
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
        conn.execute(
            """
            INSERT INTO evidence_weekly_collections
                (period_start, period_end, status, error_type, source_hash)
            VALUES ('2026-08-24', '2026-08-28', 'pending_human_review', '', ?)
            """,
            ("sha256:" + "a" * 64,),
        )

    weekly = PreV2ReadinessService(
        config,
        evidence_db_path=tmp_path / "missing.db",
        weekly_collection_sidecar_path=sidecar,
    )._weekly_history_item(3)

    assert weekly.observed_count == 0
    assert weekly.evidence["weekly_collection_sidecar_path"] == str(sidecar)
    assert weekly.evidence["pending_collection_periods"] == [
        {
            "period_start": "2026-08-24",
            "period_end": "2026-08-28",
            "evidence_source": "pending_human_review_sidecar",
        }
    ]
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


def test_program_readiness_projects_p0_license_candidate_evidence(tmp_path: Path) -> None:
    license_path = tmp_path / "p0-license.json"
    license_path.write_text(
        json.dumps(
            {
                "schema_version": "p0-license-evidence-capture.v1",
                "candidate_only": True,
                "source_acceptance_granted": False,
                "license_accepted": False,
                "downstream_eligibility": "none",
                "formal_eligible": False,
                "production_ingestion_allowed": False,
                "production_scheduler_allowed": False,
                "targets": [
                    {
                        "license_evidence_url": "https://www.twse.com.tw/zh/terms/use.html",
                        "source_ids": ["institutional_flows"],
                        "status": "transport_error",
                        "content_persisted": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        p0_license_evidence_path=license_path,
    )

    lane = report["workstreams"]["p0"]
    assert lane["status"] == "waiting_for_external_input"
    assert lane["details"]["projection"]["rows"][7][
        "license_evidence_capture_status"
    ] == "capture_transport_error"
    assert report["inputs"]["p0_license_evidence_path"] == str(license_path.resolve())


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


def test_program_readiness_explains_timezone_required_training_cutoff(tmp_path: Path) -> None:
    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        training_as_of="2026-08-28",
    )
    lane = report["workstreams"]["formal_ml"]

    assert lane["status"] == "action_required"
    assert lane["blockers"] == ["training_as_of_timezone_required"]
    assert lane["external_input_required"] is True
    assert "含時區的 ISO 8601" in lane["next_actions"][0]
    assert lane["details"]["training_as_of"] == "2026-08-28"


def test_program_readiness_projects_scheduler_registration_diagnostics(tmp_path: Path) -> None:
    scheduler_path = tmp_path / "scheduler-status.json"
    scheduler_path.write_text(
        json.dumps(
            {
                "schema_version": "scheduled-task-registration.v1",
                "task_count": 13,
                "available_count": 0,
                "missing_or_unavailable_count": 13,
                "all_available": False,
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        scheduled_task_status_path=scheduler_path,
    )
    lane = report["workstreams"]["update_history"]

    assert "scheduled_tasks_missing_or_unavailable:0/13" in lane["blockers"]
    assert lane["details"]["scheduled_task_status"]["task_count"] == 13
    assert "重新註冊 13 個 baldr task" in lane["next_actions"][0]


def test_program_readiness_projects_scheduler_wrapper_and_action_diagnostics(tmp_path: Path) -> None:
    scheduler_path = tmp_path / "scheduler-status.json"
    scheduler_path.write_text(
        json.dumps(
            {
                "schema_version": "scheduled-task-registration.v1",
                "task_count": 13,
                "available_count": 13,
                "missing_or_unavailable_count": 0,
                "all_available": True,
                "all_wrappers_present": False,
                "all_actions_match": False,
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        scheduled_task_status_path=scheduler_path,
    )
    lane = report["workstreams"]["update_history"]

    assert "scheduled_task_wrapper_missing_or_unreadable" in lane["blockers"]
    assert "scheduled_task_action_mismatch" in lane["blockers"]


def test_program_readiness_projects_scheduler_action_unobserved_diagnostic(tmp_path: Path) -> None:
    scheduler_path = tmp_path / "scheduler-status.json"
    scheduler_path.write_text(
        json.dumps(
            {
                "schema_version": "scheduled-task-registration.v1",
                "task_count": 13,
                "available_count": 13,
                "missing_or_unavailable_count": 0,
                "all_available": True,
                "all_wrappers_present": True,
                "action_mismatch_count": 0,
                "action_unobserved_count": 13,
                "all_actions_observed": False,
                "all_actions_match": True,
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        scheduled_task_status_path=scheduler_path,
    )
    lane = report["workstreams"]["update_history"]

    assert "scheduled_task_action_unobserved" in lane["blockers"]


def test_program_readiness_projects_explicit_freshness_status(tmp_path: Path) -> None:
    freshness_path = tmp_path / "freshness" / "latest_status.json"
    freshness_path.parent.mkdir(parents=True, exist_ok=True)
    freshness_path.write_text(
        json.dumps(
            {
                "task": "baldr-data-freshness-check-daily",
                "status": "passed",
                "read_only": True,
                "checked_at": "2026-08-28T05:00:00+08:00",
                "checks": {
                    "daily_prices_latest_date": "20260828",
                    "technical_indicators_latest_date": "20260828",
                },
                "warnings": [],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        freshness_status_path=freshness_path,
    )
    lane = report["workstreams"]["update_history"]

    assert lane["status"] == "waiting_for_external_input"
    assert "data_freshness_failed" not in lane["blockers"]
    assert lane["details"]["freshness_projection"] == {
        "status": "passed",
        "checked_at": "2026-08-28T05:00:00+08:00",
        "warnings": [],
        "errors": [],
        "read_only": True,
    }
    assert report["inputs"]["freshness_status_path"] == str(freshness_path.resolve())


def test_program_readiness_does_not_hide_freshness_failure_behind_empty_history(
    tmp_path: Path,
) -> None:
    freshness_path = tmp_path / "freshness" / "latest_status.json"
    freshness_path.parent.mkdir(parents=True, exist_ok=True)
    freshness_path.write_text(
        json.dumps(
            {
                "task": "baldr-data-freshness-check-daily",
                "status": "failed",
                "read_only": True,
                "checked_at": "2026-08-28T05:00:00+08:00",
                "checks": {},
                "warnings": [],
                "errors": ["sqlite_read_failed"],
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        freshness_status_path=freshness_path,
    )
    lane = report["workstreams"]["update_history"]

    assert lane["status"] == "action_required"
    assert "data_freshness_failed" in lane["blockers"]
    assert any("freshness latest_status.json" in item for item in lane["next_actions"])


def test_program_readiness_forwards_explicit_weekly_collection_sidecar(tmp_path: Path) -> None:
    sidecar = tmp_path / "sidecar" / "evidence_scheduler.db"
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
        conn.execute(
            """
            INSERT INTO evidence_weekly_collections
                (period_start, period_end, status, error_type, source_hash)
            VALUES ('2026-08-24', '2026-08-28', 'pending_human_review', '', ?)
            """,
            ("sha256:" + "b" * 64,),
        )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        weekly_collection_sidecar_path=sidecar,
    )

    weekly = report["workstreams"]["evidence"]["details"]["readiness"]["items"][0]
    assert weekly["item_id"] == "weekly_history"
    assert weekly["evidence"]["weekly_collection_sidecar_path"] == str(sidecar)
    assert weekly["evidence"]["pending_collection_periods"][0]["period_end"] == "2026-08-28"


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
    write_path = tmp_path / "technical-write.json"
    write_path.write_text(
        json.dumps(
            {
                "schema_version": "technical-indicator-write-probe.v1",
                "status": "measured",
                "read_only": False,
                "write_attempted": True,
                "staging_write_attempted": True,
                "production_write_attempted": False,
                "sqlite_write_attempted": True,
                "production_sqlite_write_attempted": False,
                "cleanup_succeeded": True,
                "parallelism_enabled": False,
                "observed_worker_count": 1,
                "single_writer_required": True,
            }
        ),
        encoding="utf-8",
    )
    worker_path = tmp_path / "technical-worker.json"
    worker_path.write_text(
        json.dumps(
            {
                "schema_version": "bounded-worker-acceptance.v1",
                "status": "measured",
                "read_only": True,
                "write_attempted": False,
                "production_write_attempted": False,
                "synthetic_parallelism_enabled": True,
                "production_worker_enabled": False,
                "checks": {
                    "bounded_in_flight": True,
                    "worker_did_not_write": True,
                },
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        technical_performance_path=technical_path,
        technical_batch_performance_path=batch_path,
        technical_write_performance_path=write_path,
        technical_worker_acceptance_path=worker_path,
        broker_performance_path=broker_path,
    )
    rendered = render_markdown(report)

    assert "# Program Readiness" in rendered
    assert "## 依序推進" in rendered
    assert "`performance`" in rendered
    assert "bounded worker" in rendered
    assert report["workstreams"]["performance"]["status"] == "partial"
    assert report["workstreams"]["performance"]["details"]["artifacts"]["technical_batch"]["status"] == "measured"
    assert report["workstreams"]["performance"]["details"]["artifacts"]["technical_write"]["status"] == "measured"
    assert report["workstreams"]["performance"]["details"]["artifacts"]["technical_worker"]["status"] == "measured"
    assert "technical_bounded_worker_acceptance_not_completed" not in report["workstreams"]["performance"]["blockers"]
    assert "broker_bounded_fetch_acceptance_not_completed" in report["workstreams"]["performance"]["blockers"]
    assert [item["lane"] for item in report["execution_order"]] == [
        "p0",
        "evidence",
        "paper",
        "formal_ml",
        "runtime",
        "performance",
        "update_history",
    ]


def test_program_readiness_accepts_real_staging_process_pool_worker_contract(
    tmp_path: Path,
) -> None:
    worker_path = tmp_path / "technical-process-pool.json"
    worker_path.write_text(
        json.dumps(
            {
                "schema_version": "technical-indicator-process-pool.v1",
                "status": "measured",
                "read_only": False,
                "write_attempted": True,
                "staging_write_attempted": True,
                "production_write_attempted": False,
                "production_sqlite_write_attempted": False,
                "staging_process_pool_enabled": True,
                "production_worker_enabled": False,
                "cleanup_succeeded": True,
                "checks": {
                    "process_pool_started": True,
                    "bounded_in_flight": True,
                    "parent_single_writer": True,
                    "retry_budget_respected": True,
                    "no_worker_sqlite_write": True,
                },
                "crash_recovery": {"status": "measured"},
                "cancellation": {"status": "measured"},
                "production_single_writer_integration": {
                    "status": "staging_measured",
                    "scope": "isolated_staging",
                    "production_worker_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        technical_worker_acceptance_path=worker_path,
    )

    blockers = report["workstreams"]["performance"]["blockers"]
    assert "technical_bounded_worker_acceptance_invalid" not in blockers
    assert "technical_bounded_worker_acceptance_not_completed" not in blockers
    assert "technical_worker_crash_recovery_not_completed" not in blockers
    assert "technical_worker_cancel_acceptance_not_completed" not in blockers
    assert "technical_production_single_writer_canary_not_completed" in blockers
    assert "technical_production_single_writer_integration_not_completed" not in blockers


def test_program_readiness_accepts_bounded_broker_fetch_contract(tmp_path: Path) -> None:
    broker_path = tmp_path / "broker-fetch.json"
    broker_path.write_text(
        json.dumps(
            {
                "schema_version": "broker-bounded-fetch-acceptance.v1",
                "status": "measured",
                "production_write_attempted": False,
                "staging_fetch_pool_enabled": True,
                "production_fetch_pool_enabled": False,
                "bounded_fetch_acceptance": {
                    "status": "measured",
                    "checks": {
                        "bounded_in_flight": True,
                        "global_rate_limit_respected": True,
                        "retry_budget_respected": True,
                        "expected_permanent_failure_isolated": True,
                        "unexpected_failure_absent": True,
                        "duplicate_idempotency": True,
                        "parent_single_writer": True,
                        "worker_did_not_write": True,
                        "selenium_fallback_not_parallelized": True,
                        "source_identity_preserved": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        broker_performance_path=broker_path,
    )

    blockers = report["workstreams"]["performance"]["blockers"]
    assert "broker_bounded_fetch_acceptance_not_completed" not in blockers
    assert "broker_bounded_fetch_acceptance_invalid" not in blockers
    assert "broker_real_http_canary_not_completed" in blockers


def test_program_readiness_records_actual_runtime_staging_probe(tmp_path: Path) -> None:
    probe_path = tmp_path / "runtime-write-probe.json"
    probe_path.write_text(
        json.dumps(
            {
                "schema_version": "runtime-environment-write-probe.v1",
                "status": "passed",
                "file_write_succeeded": True,
                "sqlite_write_succeeded": True,
                "registry_transaction_succeeded": True,
                "cleanup_succeeded": True,
                "write_probe": "actual_ephemeral_registry_transaction",
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        runtime_write_probe_path=probe_path,
    )

    runtime = report["workstreams"]["runtime"]
    assert runtime["status"] == "partial"
    assert runtime["details"]["staging_write_probe"]["status"] == "passed"


def test_program_readiness_accepts_explicit_host_runtime_artifact(
    tmp_path: Path,
) -> None:
    readiness_path = tmp_path / "runtime-host-readiness.json"
    readiness_path.write_text(
        json.dumps(
            {
                "schema_version": "runtime-environment-readiness.v1",
                "overall_state": "ready",
                "diagnostics": [],
                "side_effect_free": True,
                "write_probe": "os.access_plus_existing_handle",
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        runtime_readiness_path=readiness_path,
    )

    runtime = report["workstreams"]["runtime"]
    assert runtime["status"] == "ready"
    assert runtime["blockers"] == []
    assert runtime["details"]["readiness_source_path"] == str(readiness_path.resolve())


def test_program_readiness_accepts_formal_registry_snapshot_clone_probe(
    tmp_path: Path,
) -> None:
    probe_path = tmp_path / "registry-snapshot-probe.json"
    probe_path.write_text(
        json.dumps(
            {
                "schema_version": "research-registry-snapshot-transaction.v1",
                "status": "passed",
                "read_only_source": True,
                "formal_write_attempted": False,
                "writes_formal_registry": False,
                "source_unchanged": True,
                "cleanup_succeeded": True,
                "transaction": {
                    "insert_visible_before_rollback": True,
                    "rolled_back_row_absent": True,
                    "row_count_unchanged": True,
                },
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        runtime_registry_snapshot_probe_path=probe_path,
    )

    runtime = report["workstreams"]["runtime"]
    assert "runtime_registry_snapshot_probe_failed" not in runtime["blockers"]
    assert runtime["details"]["registry_snapshot_transaction_probe"]["status"] == "passed"
    assert any("snapshot clone" in action for action in runtime["next_actions"])


def test_program_readiness_rejects_invalid_formal_registry_snapshot_clone_probe(
    tmp_path: Path,
) -> None:
    probe_path = tmp_path / "registry-snapshot-probe-invalid.json"
    probe_path.write_text(
        json.dumps(
            {
                "schema_version": "research-registry-snapshot-transaction.v1",
                "status": "passed",
                "read_only_source": True,
                "formal_write_attempted": False,
                "writes_formal_registry": False,
                "source_unchanged": False,
                "cleanup_succeeded": True,
                "transaction": {},
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        runtime_registry_snapshot_probe_path=probe_path,
    )

    runtime = report["workstreams"]["runtime"]
    assert "runtime_registry_snapshot_probe_failed" in runtime["blockers"]


def test_program_readiness_rejects_invalid_host_runtime_artifact(
    tmp_path: Path,
) -> None:
    readiness_path = tmp_path / "runtime-host-readiness-invalid.json"
    readiness_path.write_text(
        json.dumps({"schema_version": "wrong", "overall_state": "ready"}),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        runtime_readiness_path=readiness_path,
    )

    runtime = report["workstreams"]["runtime"]
    assert runtime["status"] == "action_required"
    assert "runtime_readiness_inspection_failed" in runtime["blockers"]


def test_program_readiness_accepts_measured_technical_production_canary(
    tmp_path: Path,
) -> None:
    canary_path = tmp_path / "technical-production-canary.json"
    canary_path.write_text(
        json.dumps(
            {
                "schema_version": "technical-indicator-production-canary.v1",
                "status": "measured",
                "production_write_attempted": True,
                "production_sqlite_write_attempted": True,
                "single_writer_verified": True,
                "parent_single_writer": True,
                "worker_writes": False,
                "sqlite_worker_writes": False,
                "network_enabled": False,
                "broker_enabled": False,
                "selenium_invocations": 0,
                "validation": {"ok": True},
                "rollback": {"available": True, "succeeded": None},
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        technical_production_canary_path=canary_path,
    )

    performance = report["workstreams"]["performance"]
    assert performance["details"]["technical_canary_path"] == str(canary_path.resolve())
    assert "technical_production_single_writer_canary_not_completed" not in performance[
        "blockers"
    ]
    assert "technical_production_single_writer_canary_invalid" not in performance[
        "blockers"
    ]


def test_program_readiness_rejects_invalid_technical_production_canary(
    tmp_path: Path,
) -> None:
    canary_path = tmp_path / "technical-production-canary-invalid.json"
    canary_path.write_text(
        json.dumps(
            {
                "schema_version": "technical-indicator-production-canary.invalid",
                "status": "malformed",
                "production_write_attempted": False,
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        technical_production_canary_path=canary_path,
    )

    assert "technical_production_single_writer_canary_invalid" in report["workstreams"][
        "performance"
    ]["blockers"]


def test_program_readiness_projects_direct_chain_storage_preflight_blocker(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "ml-direct-chain-status.json"
    status_path.write_text(
        json.dumps(
            {
                "schema_version": "ml-direct-chain-maintenance-status.v1",
                "status": "blocked_insufficient_storage",
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
                "writes_source_database": False,
                "storage_preflight": {
                    "free_bytes": 6_000,
                    "minimum_free_space_bytes": 20_000,
                    "within_minimum_free_space": False,
                },
            }
        ),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        ml_direct_chain_status_path=status_path,
    )

    performance = report["workstreams"]["performance"]
    assert performance["status"] == "waiting_for_external_input"
    assert "direct_chain_storage_preflight_blocked" in performance["blockers"]
    assert performance["details"]["artifacts"]["ml_direct_chain"]["status"] == (
        "blocked_insufficient_storage"
    )
    assert "容量與保留策略" in performance["next_actions"][0]


def test_program_readiness_rejects_invalid_direct_chain_status(tmp_path: Path) -> None:
    status_path = tmp_path / "ml-direct-chain-status-invalid.json"
    status_path.write_text(
        json.dumps({"schema_version": "wrong", "status": "ready"}),
        encoding="utf-8",
    )

    report = inspect_program_readiness(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
        ml_direct_chain_status_path=status_path,
    )

    assert "ml_direct_chain_status_invalid" in report["workstreams"][
        "performance"
    ]["blockers"]
