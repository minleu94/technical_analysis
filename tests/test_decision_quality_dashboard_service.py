from __future__ import annotations

from app_module.decision_quality_dashboard_dtos import DecisionQualityDashboardRequest
from app_module.decision_quality_dashboard_service import DecisionQualityDashboardService
from app_module.decision_quality_dtos import DecisionQualityItem, DecisionQualityReview


class FakeDecisionQualityService:
    def __init__(self) -> None:
        self.review_calls: list[dict] = []
        self.item_calls: list[dict] = []
        self.reviews = [
            DecisionQualityReview(
                review_id="dqr-1",
                review_hash="sha256:1",
                review_period_start="2026-06-01",
                review_period_end="2026-06-30",
                review_type="monthly",
                decision_quality_score_bp=7200,
                process_adherence_score_bp=7000,
                evidence_usage_score_bp=6800,
                risk_discipline_score_bp=8000,
                review_completeness_score_bp=6000,
                review_status="needs_review",
                warnings_json=["journal_missing"],
                quality="degraded",
            )
        ]
        self.items = [
            DecisionQualityItem(
                item_id="dqi-1",
                review_id="dqr-1",
                item_type="large_live_research_gap",
                symbol="2330",
                event_date="2026-06-20",
                source_type="research_run",
                severity="medium",
                status="open",
                reason_codes_json=["large_gap_unreviewed"],
                related_gap_id="gap-1",
                related_decay_id="",
                evidence_json={"data_quality": "observed", "warnings": []},
                suggested_review_question="這個 research gap 是否需要補充覆盤？",
            )
        ]

    def list_reviews(self, **filters):
        self.review_calls.append(filters)
        return self.reviews

    def list_items(self, **filters):
        self.item_calls.append(filters)
        rows = self.items
        if filters.get("status"):
            rows = [item for item in rows if item.status == filters["status"]]
        return rows


def test_decision_quality_dashboard_filters_and_cards() -> None:
    backend = FakeDecisionQualityService()
    service = DecisionQualityDashboardService(backend)

    result = service.load_dashboard(
        DecisionQualityDashboardRequest(
            review_type="monthly",
            start_date="2026-06-01",
            end_date="2026-06-30",
            symbol="2330",
            item_type="large_live_research_gap",
            severity="medium",
            status="open",
            min_score=6000,
        )
    )

    assert backend.review_calls[-1] == {
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "review_type": "monthly",
    }
    assert backend.item_calls[-1] == {"status": "open"}
    assert result.cards.decision_quality_score == 7200
    assert result.cards.open_items == 1
    assert result.cards.reviewed_items == 0
    assert result.cards.dismissed_items == 0
    assert result.cards.warnings_count == 1
    assert result.rows[0].symbol == "2330"
    assert result.rows[0].item_type == "large_live_research_gap"
    assert "流程覆盤" in result.limitations[0]


def test_decision_quality_dashboard_empty_state_is_non_blaming() -> None:
    backend = FakeDecisionQualityService()
    backend.reviews = []
    backend.items = []

    result = DecisionQualityDashboardService(backend).load_dashboard(DecisionQualityDashboardRequest())

    assert result.rows == ()
    assert "尚無 decision quality review evidence" in result.empty_state_message
    assert "使用者錯誤" not in result.empty_state_message
