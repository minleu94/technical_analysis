from __future__ import annotations

from app_module.signal_decay_dashboard_dtos import SignalDecayDashboardRequest
from app_module.signal_decay_dashboard_service import SignalDecayDashboardService
from app_module.signal_decay_dtos import SignalDecayObservation


class FakeSignalDecayService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.rows = [
            SignalDecayObservation(
                decay_id="decay-1",
                decay_hash="sha256:decay-1",
                observation_date="2026-07-09",
                signal_scope_type="event_type",
                signal_scope_id="recommendation_included",
                event_type="recommendation_included",
                event_family="recommendation",
                window_short=12,
                window_long=40,
                sample_size_short=12,
                sample_size_long=40,
                forward_excess_short_bp=-700,
                forward_excess_long_bp=300,
                win_rate_short_bp=3000,
                win_rate_long_bp=6000,
                mae_short_bp=-900,
                mae_long_bp=-150,
                live_gap_short_bp=-800,
                live_gap_long_bp=100,
                decay_score_bp=6500,
                decay_status="decaying",
                suggested_lifecycle_action="demote_candidate",
                confidence="medium",
                quality="degraded",
                warnings_json=["missing_industry_evidence"],
            )
        ]

    def list_decay_observations(self, **filters):
        self.calls.append(filters)
        rows = self.rows
        if filters.get("observation_date"):
            rows = [row for row in rows if row.observation_date == filters["observation_date"]]
        if filters.get("signal_scope_type"):
            rows = [row for row in rows if row.signal_scope_type == filters["signal_scope_type"]]
        return rows


def test_signal_decay_dashboard_filters_cards_and_rows() -> None:
    backend = FakeSignalDecayService()
    service = SignalDecayDashboardService(backend)

    result = service.load_dashboard(
        SignalDecayDashboardRequest(
            observation_date="2026-07-09",
            scope_type="event_type",
            scope_id="recommendation_included",
            event_type="recommendation_included",
            decay_status="decaying",
            suggested_lifecycle_action="demote_candidate",
            confidence="medium",
            min_sample_size=10,
        )
    )

    assert backend.calls[-1] == {
        "observation_date": "2026-07-09",
        "signal_scope_type": "event_type",
        "signal_scope_id": "recommendation_included",
    }
    assert result.cards.scopes_evaluated == 1
    assert result.cards.decaying_count == 1
    assert result.cards.demote_candidate_count == 1
    assert result.cards.low_confidence_count == 0
    assert result.cards.warnings_count == 1
    assert result.rows[0].decay_score_bp == 6500
    assert result.rows[0].suggested_lifecycle_action == "demote_candidate"
    assert "不會自動套用" in result.limitations[0]


def test_signal_decay_dashboard_insufficient_sample_state() -> None:
    backend = FakeSignalDecayService()
    backend.rows[0] = SignalDecayObservation(
        decay_id="decay-small",
        decay_hash="sha256:decay-small",
        observation_date="2026-07-09",
        signal_scope_type="event_type",
        signal_scope_id="recommendation_included",
        sample_size_short=3,
        sample_size_long=8,
        decay_status="insufficient_sample",
        suggested_lifecycle_action="none",
        confidence="low",
        quality="missing",
    )

    result = SignalDecayDashboardService(backend).load_dashboard(
        SignalDecayDashboardRequest(min_sample_size=10)
    )

    assert result.cards.insufficient_sample_count == 1
    assert result.cards.low_confidence_count == 1
    assert "樣本不足" in result.empty_state_message
