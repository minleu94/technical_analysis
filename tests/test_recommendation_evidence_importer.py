from __future__ import annotations

from datetime import date

from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.evidence_event_dtos import EvidenceEventType
from app_module.evidence_event_importer_dtos import EvidenceCaptureRequest
from app_module.evidence_event_importers import RecommendationEvidenceImporter


class FakeRecommendationRepository:
    def __init__(self, result: RecommendationResultDTO):
        self.result = result

    def load_result(self, result_id: str) -> RecommendationResultDTO | None:
        return self.result if result_id == self.result.result_id else None

    def list_results(self) -> list[dict[str, object]]:
        return [
            {
                "result_id": self.result.result_id,
                "created_at": self.result.created_at,
            }
        ]


def _result(score_percentile_bp: int | None = None) -> RecommendationResultDTO:
    return RecommendationResultDTO(
        result_id="rec-001",
        result_name="Evidence Import Test",
        config={"profile_id": "balanced", "profile_version": "1.0"},
        recommendations=[
            RecommendationDTO(
                stock_code="2330",
                stock_name="台積電",
                close_price=100.0,
                price_change=1.0,
                total_score=82.0,
                indicator_score=30.0,
                pattern_score=30.0,
                volume_score=22.0,
                recommendation_reasons="rank_top; volume_ok",
                industry="半導體",
                regime_match=True,
                score_percentile_bp=score_percentile_bp,
            )
        ],
        regime="Trend",
        created_at="2026-07-02T09:00:00",
    )


def test_recommendation_importer_preserves_missing_percentile_with_warning():
    importer = RecommendationEvidenceImporter(FakeRecommendationRepository(_result()))

    result = importer.collect(EvidenceCaptureRequest(source="recommendation", result_id="rec-001"))

    assert result.events_seen == 1
    event = result.event_payloads[0]
    assert event["event_type"] == EvidenceEventType.RECOMMENDATION_INCLUDED
    assert event["score_percentile_bp"] is None
    assert "score_percentile_missing" in event["warnings"]
    assert event["profile_id"] == "balanced"
    assert event["metadata"]["profile_version"] == "1.0"
    assert result.diagnostics_by_code["source_missing_exclusion_payload"] == 1


def test_recommendation_importer_uses_requested_decision_date_and_stable_source_id():
    importer = RecommendationEvidenceImporter(FakeRecommendationRepository(_result(score_percentile_bp=9000)))

    result = importer.collect(
        EvidenceCaptureRequest(
            source="recommendation",
            result_id="rec-001",
            decision_date=date(2026, 7, 3),
        )
    )

    event = result.event_payloads[0]
    assert event["decision_date"] == "2026-07-03"
    assert event["source_id"] == "rec-001"
    assert event["score_percentile_bp"] == 9000

