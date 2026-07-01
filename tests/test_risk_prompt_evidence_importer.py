from __future__ import annotations

from datetime import date

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskRiskPrompt,
    DecisionDeskRiskPromptSummary,
)
from app_module.evidence_event_dtos import EvidenceEventType
from app_module.evidence_event_importer_dtos import EvidenceCaptureRequest
from app_module.evidence_event_importers import RiskPromptEvidenceImporter


class FakeRiskPromptProvider:
    def build_snapshot(self, as_of_date: date) -> DecisionDeskRiskPromptSummary:
        return DecisionDeskRiskPromptSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            prompts=(
                DecisionDeskRiskPrompt(
                    category="liquidity",
                    severity="warning",
                    source="relative_strength_liquidity",
                    code="1101",
                    title="低流動性",
                    reason="1101 被標記為低流動性。",
                    action_hint="檢查平均成交金額、部位大小與可成交性。",
                ),
            ),
        )


def test_risk_prompt_importer_maps_liquidity_without_forbidden_language():
    importer = RiskPromptEvidenceImporter(FakeRiskPromptProvider())

    result = importer.collect(EvidenceCaptureRequest(source="risk-prompt", decision_date="2026-07-02"))

    event = result.event_payloads[0]
    assert event["event_type"] == EvidenceEventType.RISK_PROMPT_LOW_LIQUIDITY
    combined = str(event).lower()
    assert "target price" not in combined
    assert "fair value" not in combined
    assert "buy" not in combined
    assert "sell" not in combined

