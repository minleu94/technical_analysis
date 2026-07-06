from datetime import date, datetime

from app_module.workbench_dtos import (
    WorkbenchAccessBoundary,
    WorkbenchChecklistItem,
    WorkbenchDashboardDTO,
    WorkbenchEvidenceSummary,
    WorkbenchReviewItem,
    WorkbenchStatusItem,
)


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
