from __future__ import annotations

from app_module.signal_decay_dtos import SignalDecayObservation
from app_module.signal_decay_service import SignalDecayLifecycleEvidenceAdapter


def _observation(action: str = "demote_candidate") -> SignalDecayObservation:
    return SignalDecayObservation(
        decay_id="decay-1",
        decay_hash="sha256:decay-1",
        observation_date="2026-07-09",
        signal_scope_type="event_type",
        signal_scope_id="recommendation_included",
        event_type="recommendation_included",
        event_family="recommendation",
        window_short=30,
        window_long=120,
        sample_size_short=30,
        sample_size_long=120,
        forward_excess_short_bp=-500,
        forward_excess_long_bp=200,
        win_rate_short_bp=3000,
        win_rate_long_bp=5500,
        mae_short_bp=-700,
        mae_long_bp=-200,
        live_gap_short_bp=-400,
        live_gap_long_bp=50,
        decay_score_bp=6500,
        decay_status="decaying",
        suggested_lifecycle_action=action,
        confidence="medium",
        evidence_event_count=120,
        gap_observation_count=20,
        quality="degraded",
        warnings_json=["quality_degraded"],
        diagnostics_json=[{"code": "short_window_weaker"}],
    )


def test_lifecycle_payload_is_proposed_evidence_without_apply_action() -> None:
    payload = SignalDecayLifecycleEvidenceAdapter().build_payload(_observation())

    assert payload["source"] == "signal_decay_monitor_v1"
    assert payload["decay_id"] == "decay-1"
    assert payload["suggested_lifecycle_action"] == "demote_candidate"
    assert payload["apply_action"] is False
    assert payload["status"] == "proposed"
    assert payload["metrics"]["decay_score_bp"] == 6500


def test_payload_builder_does_not_require_lifecycle_repository() -> None:
    payload = SignalDecayLifecycleEvidenceAdapter().build_payload(_observation("retire_candidate"))

    assert payload["suggested_lifecycle_action"] == "retire_candidate"
    assert payload["apply_action"] is False

