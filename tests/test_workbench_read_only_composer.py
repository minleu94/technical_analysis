from datetime import date, datetime
from pathlib import Path

from app_module.decision_desk_dtos import (
    DecisionDeskActionSummary,
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
from app_module.pre_v2_readiness_service import (
    PreV2ReadinessItem,
    PreV2ReadinessReport,
    STATUS_READY,
    STATUS_WAITING_FOR_TIME,
)
from app_module.workbench_dtos import (
    WORKBENCH_LEGACY_DRILLDOWN_TARGETS,
    WorkbenchAccessBoundary,
    WorkbenchChecklistItem,
    WorkbenchDashboardDTO,
    WorkbenchEvidenceSummary,
    WorkbenchReviewItem,
    WorkbenchStatusItem,
)
from app_module.workbench_read_only_composer import WorkbenchReadOnlyComposer
from app_module.scheduled_evidence_status_service import ScheduledEvidenceStatus


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
            regime_confidence=8200,
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
            rotation_intensity_bp=150,
        ),
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=sample_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=("low_liquidity:9999",),
            top_strength_codes=("2330", "2454"),
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
        action_summary=DecisionDeskActionSummary(
            action_level="積極研究",
            headline="今日主結論：研究模式。",
            research_mode_note="研究模式：以下為市場與籌碼輔助判讀，不是交易建議。",
            reasons=("市場廣度偏強。",),
        ),
    )


def _readiness_report() -> PreV2ReadinessReport:
    return PreV2ReadinessReport(
        generated_at="2026-07-06T12:00:00Z",
        overall_status=STATUS_WAITING_FOR_TIME,
        production_scheduler_allowed=False,
        items=(
            PreV2ReadinessItem(
                item_id="weekly_history",
                label="多週 weekly evidence operations history",
                status=STATUS_WAITING_FOR_TIME,
                required_count=3,
                observed_count=1,
                blocking_reasons=("insufficient_weekly_history_records",),
                next_actions=("繼續累積跨週樣本。",),
            ),
            PreV2ReadinessItem(
                item_id="multi_day_dry_run",
                label="Multi-day dry-run record",
                status=STATUS_WAITING_FOR_TIME,
                required_count=3,
                observed_count=1,
                blocking_reasons=("insufficient_dry_run_days",),
                next_actions=("繼續填寫 3-5 個交易日 dry-run 紀錄。",),
            ),
            PreV2ReadinessItem(
                item_id="source_gaps",
                label="Source gaps 收斂狀態",
                status=STATUS_READY,
                evidence={"blocking_gaps": [], "warnings": []},
            ),
        ),
        limitations=(
            "waiting_for_time 代表仍需真實多週或多日觀察，不能用單次 smoke 取代。",
            "ready 只代表可進入 V2.0 design discussion，不代表投資有效性。",
        ),
    )


def _agent_report_sample() -> dict[str, object]:
    return {
        "quality": {"evidence_row_count": 5},
        "warnings": ["agent_sample_warning"],
        "limitations": ["AI report 只能整理 evidence rows，不是交易建議。"],
        "source_trace": {"service": "AgentEvidenceAccessService", "mode": "read_only"},
    }


def test_workbench_dto_serializes_read_only_boundary() -> None:
    dto = WorkbenchDashboardDTO(
        as_of_date=date(2026, 7, 6),
        generated_at=datetime(2026, 7, 6, 12, 0, 0),
        source_mode="sample_only",
        access_boundary=WorkbenchAccessBoundary(),
        status_strip=(
            WorkbenchStatusItem(
                item_id="scheduler",
                label="Production Scheduler",
                value="off",
                status="blocked",
            ),
        ),
        review_items=(
            WorkbenchReviewItem(
                item_id="review-1",
                title="Portfolio alert review",
                severity="warning",
                source="portfolio_alert",
                summary="人工覆盤持倉警示。",
                drilldown_target="portfolio_review",
            ),
        ),
        evidence_summary=(
            WorkbenchEvidenceSummary(
                item_id="weekly_history",
                label="Weekly evidence history",
                status="waiting_for_time",
                summary="1/3 records observed.",
            ),
        ),
        market_context={"overall_quality": "observed"},
        portfolio_watchlist_summary={"portfolio_alert_count": 1},
        daily_checklist=(
            WorkbenchChecklistItem(
                item_id="freshness",
                label="資料 freshness",
                status="done",
                summary="Decision snapshot available.",
            ),
        ),
        warnings=("research_mode_only",),
    )

    payload = dto.to_dict()

    assert payload["access_boundary"]["mode"] == "read_only"
    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["access_boundary"]["production_scheduler_allowed"] is False
    assert "place_order" in payload["access_boundary"]["denied_actions"]
    assert payload["status_strip"][0]["status"] == "blocked"
    assert payload["warnings"] == ["research_mode_only"]


def test_composer_keeps_scheduler_and_writes_off() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    assert dashboard.access_boundary.mode == "read_only"
    assert dashboard.access_boundary.writes_allowed is False
    assert dashboard.access_boundary.production_scheduler_allowed is False
    assert any(item.item_id == "scheduler" for item in dashboard.status_strip)


def test_composer_builds_today_review_items_from_watchlist_portfolio_and_risk() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    payload = dashboard.to_dict()
    review_sources = {item["source"] for item in payload["review_items"]}

    assert {"watchlist_trigger", "portfolio_alert", "risk_prompt"}.issubset(review_sources)
    assert any(item["drilldown_target"] == "evidence_mode" for item in payload["review_items"])


def test_composer_builds_background_evidence_feed_from_existing_payloads_only() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
        scheduled_status=ScheduledEvidenceStatus(
            recommendation_status="passed",
            recommendation_source="scheduled_latest_status",
            evidence_status="passed",
            recommendation_result_id="scheduled_rec_20260707_051001",
            recommendations_count=12,
            scheduled_joint_observed_days=2,
            scheduled_joint_observed_dates=("20260706", "20260707"),
            writes_recommendation_result=True,
            writes_evidence_db=False,
            auto_trading=False,
            lifecycle_action=False,
        ),
        historical_replay_summary={
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
            "warnings": ("simulated_scheduler", "missing_industry_benchmark"),
        },
    )

    feed = {item.item_id: item for item in dashboard.background_evidence_feed}

    assert set(feed) == {
        "daily_decision_snapshot",
        "evidence_review_readiness",
        "portfolio_alerts",
        "replay_summary_diagnostics",
        "scheduled_morning_pipeline",
    }
    assert feed["daily_decision_snapshot"].source_trace == "DecisionDeskSnapshot"
    assert feed["evidence_review_readiness"].source_trace == "PreV2ReadinessReport"
    assert feed["portfolio_alerts"].source_trace == "DecisionDeskSnapshot.portfolio_alerts"
    assert feed["replay_summary_diagnostics"].source_trace == "HistoricalReplaySummary"
    assert feed["replay_summary_diagnostics"].status == "degraded"
    assert feed["scheduled_morning_pipeline"].status == "passed"
    assert "共同觀測 2 天" in feed["scheduled_morning_pipeline"].summary
    assert "source=scheduled_latest_status" in feed["scheduled_morning_pipeline"].summary
    assert "simulated_scheduler" in " ".join(feed["replay_summary_diagnostics"].diagnostics)


def test_composer_surfaces_manual_recommendation_observation_without_marking_scheduled_passed() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        scheduled_status=ScheduledEvidenceStatus(
            recommendation_status="manual_observed",
            recommendation_source="manual_result",
            evidence_status="passed",
            recommendation_result_id="rec_20260707_113744",
            recommendations_count=4,
            manual_recommendation_observed_days=1,
            evidence_dry_run_observed_days=1,
            scheduled_joint_observed_days=0,
            writes_recommendation_result=True,
            writes_evidence_db=False,
            auto_trading=False,
            lifecycle_action=False,
        ),
    )

    feed = {item.item_id: item for item in dashboard.background_evidence_feed}

    assert feed["scheduled_morning_pipeline"].status == "degraded"
    assert "manual_result（scheduled latest_status missing）" in feed["scheduled_morning_pipeline"].summary
    assert "共同觀測 0 天" in feed["scheduled_morning_pipeline"].summary
    assert "manual recommendation 1 天" in feed["scheduled_morning_pipeline"].summary


def test_composer_builds_read_only_action_items_with_trace_reason_and_drilldown() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    payload = dashboard.to_dict()
    action_items = payload["action_items"]

    assert action_items
    assert all(item["source_trace"] for item in action_items)
    assert all(item["degraded_reason"] for item in action_items)
    assert all(item["drilldown_target"] for item in action_items)
    assert any(item["source_type"] == "portfolio_alert" for item in action_items)
    assert any(item["source_type"] == "pre_v2_readiness" for item in action_items)
    assert not any(item.get("write_intent") for item in action_items)
    assert payload["access_boundary"]["writes_allowed"] is False


def test_composer_sorts_and_groups_action_items_for_manual_queue_scan() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    items = dashboard.action_items
    payload_items = dashboard.to_dict()["action_items"]

    assert [item.item_id for item in items[:2]] == [
        "portfolio_alert_manual_review",
        "risk_prompt_manual_review_1",
    ]
    assert [item.severity for item in items[:2]] == ["warning", "warning"]
    assert [item.queue_group for item in items] == [
        "portfolio_review",
        "daily_review",
        "daily_review",
        "evidence_gate",
        "evidence_gate",
    ]
    assert [item.source_label for item in items] == [
        "持倉警示",
        "風險提示",
        "觀察清單觸發",
        "Pre-V2 準備度",
        "Pre-V2 準備度",
    ]
    assert [item["sort_rank"] for item in payload_items] == sorted(item["sort_rank"] for item in payload_items)


def test_composer_action_item_drilldown_targets_match_legacy_pages() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    targets = {item.drilldown_target for item in dashboard.action_items}

    assert targets.issubset(WORKBENCH_LEGACY_DRILLDOWN_TARGETS)
    assert WORKBENCH_LEGACY_DRILLDOWN_TARGETS["daily_decision"] == "daily_decision"
    assert WORKBENCH_LEGACY_DRILLDOWN_TARGETS["portfolio_review"] == "portfolio"
    assert WORKBENCH_LEGACY_DRILLDOWN_TARGETS["evidence_review"] == "evidence_review"
    assert WORKBENCH_LEGACY_DRILLDOWN_TARGETS["evidence_mode"] == "evidence_review"


def test_composer_builds_read_only_operating_loop_steps_for_phase2c() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    steps = dashboard.operating_loop_steps
    payload_steps = dashboard.to_dict()["operating_loop_steps"]

    assert [step.step_id for step in steps] == [
        "daily_start",
        "manual_queue",
        "weekly_review_history",
        "multi_day_dry_run",
        "manual_review_note",
        "scheduler_gate",
    ]
    assert [step.status for step in steps] == [
        "manual_required",
        "manual_required",
        "waiting_for_time",
        "waiting_for_time",
        "manual_required",
        "blocked",
    ]
    assert steps[0].source_trace == "WorkbenchDashboardDTO.review_items"
    assert "portfolio_alert_manual_review" in steps[1].linked_item_ids
    assert steps[2].source_trace == "PreV2ReadinessReport.items.weekly_history"
    assert steps[3].source_trace == "PreV2ReadinessReport.items.multi_day_dry_run"
    assert steps[4].source_trace == "WorkbenchDashboardDTO.daily_checklist.manual_review_note"
    assert steps[4].drilldown_target == "evidence_review"
    assert all(step.write_intent is False for step in steps)
    assert not any(step["write_intent"] for step in payload_steps)
    assert "不寫 DB" in steps[4].summary
    assert "真實時間" in steps[2].summary


def test_composer_surfaces_waiting_for_time_as_evidence_gate_not_success() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    evidence = {item.item_id: item for item in dashboard.evidence_summary}

    assert evidence["weekly_history"].status == STATUS_WAITING_FOR_TIME
    assert "不能用單次 smoke 取代" in " ".join(dashboard.warnings)
    assert "weekly_history:insufficient_weekly_history_records" in " ".join(dashboard.warnings)


def test_composer_handles_missing_decision_snapshot_without_fabricating_ui_state() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=None,
        readiness_report=_readiness_report(),
        agent_report_sample=None,
    )

    assert dashboard.market_context["source_status"] == "missing"
    assert dashboard.portfolio_watchlist_summary["source_status"] == "missing"
    assert any(item.item_id == "decision_snapshot" for item in dashboard.status_strip)


def test_composer_surfaces_historical_replay_as_simulated_evidence_input() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
        historical_replay_summary={
            "replay_mode": "historical_replay",
            "source_label": "simulated_scheduler",
            "totals": {
                "days": 118,
                "events_seen": 118056,
                "outcomes_created": 472224,
            },
            "final_outcome_summary": {
                "missing_benchmark": 0,
                "missing_industry_benchmark": 378491,
            },
            "warnings": ("simulated_scheduler", "missing_industry_benchmark"),
        },
    )

    evidence = {item.item_id: item for item in dashboard.evidence_summary}

    assert evidence["historical_replay"].status == "degraded"
    assert "市場 benchmark 已可用" in evidence["historical_replay"].summary
    assert "產業基準缺口 378491" in evidence["historical_replay"].summary
    assert "historical_replay / simulated_scheduler" in " ".join(dashboard.warnings)


def test_workbench_phase1_modules_do_not_import_write_or_trading_surfaces() -> None:
    forbidden = (
        "ScoringEngine",
        "screening_service",
        "broker",
        "place_order",
        "portfolio_module",
        "backtest_module",
        "strategy_lifecycle",
        "scheduler_registration",
    )
    files = (
        Path("app_module/workbench_dtos.py"),
        Path("app_module/workbench_read_only_composer.py"),
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    for token in forbidden:
        assert token not in combined


def test_workbench_payload_does_not_present_buy_sell_recommendations() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    rendered = str(dashboard.to_dict())

    assert "買進" not in rendered
    assert "賣出" not in rendered
    assert "不是交易建議" in rendered
