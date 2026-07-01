from __future__ import annotations

from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.evidence_event_dtos import EvidenceEventType
from app_module.evidence_event_importer_dtos import EvidenceCaptureRequest
from app_module.evidence_event_importers import RecommendationEvidenceImporter
from tests.test_recommendation_evidence_importer import FakeRecommendationRepository


def _base_result(**kwargs) -> RecommendationResultDTO:
    return RecommendationResultDTO(
        result_id="rec-exclusion",
        result_name="Exclusion fixture",
        config={"profile_id": "balanced"},
        recommendations=[
            RecommendationDTO(
                stock_code="2330",
                stock_name="TSMC",
                close_price=100.0,
                price_change=1.0,
                total_score=82.0,
                indicator_score=30.0,
                pattern_score=30.0,
                volume_score=22.0,
                recommendation_reasons="rank_top",
                industry="Semi",
                regime_match=True,
                score_percentile_bp=9000,
            )
        ],
        regime="Trend",
        created_at="2026-07-02T09:00:00",
        **kwargs,
    )


def test_old_recommendation_json_remains_backward_compatible():
    result = RecommendationResultDTO.from_dict(
        {
            "result_id": "legacy",
            "result_name": "Legacy",
            "config": {},
            "recommendations": [],
            "regime": "Trend",
            "created_at": "2026-07-01T00:00:00",
        }
    )

    assert result.result_id == "legacy"
    assert result.excluded_candidates_json == []
    assert result.why_not_payload_json == []
    assert result.liquidity_gate_payload_json == []


def test_exclusion_payload_creates_why_not_and_liquidity_events():
    result = _base_result(
        excluded_candidates_json=[{"stock_code": "1101"}],
        why_not_payload_json=[
            {
                "stock_code": "1101",
                "exclusion_reason_codes": ["weak_relative_strength"],
                "threshold_name": "score_percentile_bp",
                "observed_value": "4200",
                "required_value": "7000",
                "quality": "observed",
                "warnings": ["fixture_warning"],
            }
        ],
        liquidity_gate_payload_json=[
            {
                "stock_code": "2201",
                "exclusion_reason_codes": ["low_liquidity"],
                "threshold_name": "median_amount_20d",
                "observed_value": "1000000",
                "required_value": "5000000",
                "quality": "degraded",
                "warnings": [],
            }
        ],
        exclusion_quality="observed",
        exclusion_warnings_json=["payload_persisted"],
    )
    importer = RecommendationEvidenceImporter(FakeRecommendationRepository(result))

    collected = importer.collect(EvidenceCaptureRequest(source="recommendation", result_id="rec-exclusion"))
    event_types = [event["event_type"] for event in collected.event_payloads]

    assert EvidenceEventType.WHY_NOT_EXCLUDED in event_types
    assert EvidenceEventType.LIQUIDITY_GATE_EXCLUDED in event_types
    why_not = next(event for event in collected.event_payloads if event["event_type"] == EvidenceEventType.WHY_NOT_EXCLUDED)
    assert why_not["metadata"]["source_result_id"] == "rec-exclusion"
    assert why_not["metadata"]["threshold_name"] == "score_percentile_bp"
    assert why_not["why_not_codes"] == ("weak_relative_strength",)
    assert "source_missing_exclusion_payload" not in collected.diagnostics_by_code


def test_missing_exclusion_payload_only_reports_diagnostic():
    importer = RecommendationEvidenceImporter(FakeRecommendationRepository(_base_result()))

    collected = importer.collect(EvidenceCaptureRequest(source="recommendation", result_id="rec-exclusion"))

    assert collected.diagnostics_by_code["source_missing_exclusion_payload"] == 1
    assert all(
        event["event_type"] not in {EvidenceEventType.WHY_NOT_EXCLUDED, EvidenceEventType.LIQUIDITY_GATE_EXCLUDED}
        for event in collected.event_payloads
    )
