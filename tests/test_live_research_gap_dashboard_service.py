from __future__ import annotations

from app_module.live_research_gap_dashboard_dtos import LiveResearchGapDashboardRequest
from app_module.live_research_gap_dashboard_service import LiveResearchGapDashboardService
from app_module.live_research_gap_dtos import LiveResearchGapObservation


class FakeLiveGapService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.rows = [
            LiveResearchGapObservation(
                gap_id="gap-1",
                gap_hash="sha256:gap-1",
                observation_date="2026-07-08",
                position_id="default:2330",
                symbol="2330",
                portfolio_mode="simulated",
                source_type="research_run",
                source_id="run-1",
                strategy_version_id="strategy-v1",
                evidence_event_id="evt-1",
                evidence_outcome_id="out-1",
                entry_date="2026-07-01",
                holding_days=7,
                portfolio_return_bp=300,
                forward_evidence_return_bp=400,
                benchmark_excess_bp=100,
                gap_vs_research_bp=-200,
                gap_vs_forward_evidence_bp=-100,
                gap_vs_benchmark_bp=200,
                condition_status="watch",
                chip_risk_level="neutral",
                regime_at_entry="bull",
                regime_current="bear",
                data_quality="observed",
                attribution_json=[{"category": "market_regime_gap", "confidence": "medium"}],
                metadata_json={"match_confidence": "high"},
            )
        ]

    def list_gap_observations(self, **filters):
        self.calls.append(filters)
        rows = self.rows
        if filters.get("observation_date"):
            rows = [row for row in rows if row.observation_date == filters["observation_date"]]
        if filters.get("symbol"):
            rows = [row for row in rows if row.symbol == filters["symbol"]]
        return rows


def test_live_research_gap_dashboard_filters_cards_and_rows() -> None:
    backend = FakeLiveGapService()
    service = LiveResearchGapDashboardService(backend)

    result = service.load_dashboard(
        LiveResearchGapDashboardRequest(
            observation_date="2026-07-08",
            symbol="2330",
            source_type="research_run",
            strategy_version_id="strategy-v1",
            portfolio_mode="simulated",
            attribution_category="market_regime_gap",
            data_quality="observed",
        )
    )

    assert backend.calls[-1] == {
        "observation_date": "2026-07-08",
        "symbol": "2330",
        "source_type": "research_run",
        "strategy_version_id": "strategy-v1",
    }
    assert result.cards.positions_seen == 1
    assert result.cards.positions_linked == 1
    assert result.cards.simulated_count == 1
    assert result.cards.large_gap_count == 0
    assert result.rows[0].symbol == "2330"
    assert result.rows[0].match_confidence == "high"
    assert "research / simulated gap" in result.limitations[0]


def test_live_research_gap_dashboard_missing_sources_are_degraded() -> None:
    backend = FakeLiveGapService()
    backend.rows[0] = LiveResearchGapObservation(
        gap_id="gap-missing",
        gap_hash="sha256:gap-missing",
        observation_date="2026-07-08",
        position_id="default:2317",
        symbol="2317",
        portfolio_mode="unknown",
        source_type="",
        source_id="",
        evidence_event_id="",
        evidence_outcome_id="",
        data_quality="missing",
        warnings_json=["source_trace_missing"],
    )

    result = LiveResearchGapDashboardService(backend).load_dashboard(LiveResearchGapDashboardRequest())

    assert result.cards.missing_source_trace == 1
    assert result.cards.missing_evidence_event == 1
    assert result.cards.missing_evidence_outcome == 1
    assert result.cards.unknown_count == 1
    assert "缺 source trace" in result.empty_state_message
