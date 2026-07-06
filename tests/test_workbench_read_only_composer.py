from datetime import date, datetime

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
    WorkbenchAccessBoundary,
    WorkbenchChecklistItem,
    WorkbenchDashboardDTO,
    WorkbenchEvidenceSummary,
    WorkbenchReviewItem,
    WorkbenchStatusItem,
)
from app_module.workbench_read_only_composer import WorkbenchReadOnlyComposer


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


def test_composer_surfaces_waiting_for_time_as_evidence_gate_not_success() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=_decision_snapshot(),
        readiness_report=_readiness_report(),
        agent_report_sample=_agent_report_sample(),
    )

    evidence = {item.item_id: item for item in dashboard.evidence_summary}

    assert evidence["weekly_history"].status == STATUS_WAITING_FOR_TIME
    assert "不能用單次 smoke 取代" in " ".join(dashboard.warnings)


def test_composer_handles_missing_decision_snapshot_without_fabricating_ui_state() -> None:
    dashboard = WorkbenchReadOnlyComposer().compose(
        decision_snapshot=None,
        readiness_report=_readiness_report(),
        agent_report_sample=None,
    )

    assert dashboard.market_context["source_status"] == "missing"
    assert dashboard.portfolio_watchlist_summary["source_status"] == "missing"
    assert any(item.item_id == "decision_snapshot" for item in dashboard.status_strip)
