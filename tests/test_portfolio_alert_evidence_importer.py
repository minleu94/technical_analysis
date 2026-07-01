from __future__ import annotations

from datetime import date

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    PortfolioAlertAttribution,
    PortfolioAlertSummary,
)
from app_module.evidence_event_dtos import EvidenceEventType
from app_module.evidence_event_importer_dtos import EvidenceCaptureRequest
from app_module.evidence_event_importers import PortfolioAlertEvidenceImporter


class FakePortfolioAlertProvider:
    def __init__(self) -> None:
        self.positions = ["2330"]

    def build_snapshot(self, as_of_date: date) -> PortfolioAlertSummary:
        return PortfolioAlertSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.DEGRADED,
            warnings=("portfolio_alerts_chip_estimated:2330",),
            alert_count=1,
            alert_codes=("2330",),
            alert_level="high",
            attributions=(
                PortfolioAlertAttribution(
                    stock_code="2330",
                    source_label="recommendation_result:rec-001",
                    condition_status="invalid",
                    chip_risk_level="bearish",
                    severity=100,
                    reasons=("condition:invalid", "chip:risk_level:bearish"),
                    data_quality_flags=("chip_estimated",),
                ),
            ),
        )


def test_portfolio_alert_importer_maps_attribution_and_does_not_mutate_provider_state():
    provider = FakePortfolioAlertProvider()
    importer = PortfolioAlertEvidenceImporter(provider)

    result = importer.collect(
        EvidenceCaptureRequest(source="portfolio-alert", decision_date="2026-07-02")
    )

    assert provider.positions == ["2330"]
    event = result.event_payloads[0]
    assert event["event_type"] == EvidenceEventType.PORTFOLIO_ALERT_CONDITION_INVALID
    assert event["symbol"] == "2330"
    assert event["metadata"]["chip_risk_level"] == "bearish"
    assert event["data_quality"].value == "degraded"

