from __future__ import annotations

from app_module.component_ablation_readiness import (
    COMPONENT_SETS,
    ComponentAblationReadinessService,
)
from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEvent,
    EvidenceEventType,
)


def _event(event_id: str, metadata: dict[str, object] | None = None) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id,
        event_hash=f"hash-{event_id}",
        event_date="2026-01-02",
        decision_date="2026-01-02",
        symbol="2330",
        event_type=EvidenceEventType.RECOMMENDATION_INCLUDED,
        event_family="recommendation",
        source_type="persisted_recommendation",
        score_bp=7200,
        data_quality=EvidenceDataQuality.OBSERVED,
        as_of_date="2026-01-02",
        available_date="2026-01-02",
        metadata=metadata or {},
    )


def test_component_sets_are_complete_and_missing_payload_is_explicit() -> None:
    report = ComponentAblationReadinessService(events=(_event("legacy"),)).build_report()
    payload = report.to_dict()

    assert [row["component_set_id"] for row in payload["component_sets"]] == [
        item.component_set_id for item in COMPONENT_SETS
    ]
    assert [item.label for item in COMPONENT_SETS] == [
        "technical only",
        "pattern only",
        "volume only",
        "technical + pattern",
        "technical + volume",
        "pattern + volume",
        "technical + pattern + volume",
    ]
    assert {row["status"] for row in payload["component_sets"]} == {"component_payload_missing"}
    assert "component_payload_missing" in payload["diagnostics"]
    assert "new_evidence_metadata_required" in payload["diagnostics"]
    assert payload["access_boundary"]["backfill_allowed"] is False
    assert payload["access_boundary"]["recompute_legacy_recommendations_allowed"] is False


def test_component_payload_available_when_decision_time_scores_are_present() -> None:
    report = ComponentAblationReadinessService(
        events=(
            _event(
                "new",
                {
                    "component_scores_bp": {
                        "technical": 7100,
                        "pattern": 6200,
                        "volume": 5300,
                    },
                    "component_scores_available_date": "2026-01-02",
                },
            ),
        )
    ).build_report()
    payload = report.to_dict()

    assert {row["status"] for row in payload["component_sets"]} == {"ready_for_shadow_ablation"}
    assert payload["component_sets"][0]["available_event_count"] == 1
    assert payload["diagnostics"] == []
    assert payload["access_boundary"]["production_decision_allowed"] is False
