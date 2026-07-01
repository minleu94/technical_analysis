from __future__ import annotations

from datetime import date
import inspect

from app_module.decision_desk_dtos import DecisionDeskQuality, WatchlistTriggerSummary
from app_module.evidence_event_dtos import EvidenceEventType
from app_module.evidence_event_importer_dtos import EvidenceCaptureRequest
from app_module.evidence_event_importers import WatchlistTriggerEvidenceImporter


class FakeWatchlistProvider:
    def build_snapshot(self, as_of_date: date) -> WatchlistTriggerSummary:
        return WatchlistTriggerSummary(
            as_of_date=as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=("watchlist_trigger_risk_alert:2454",),
            trigger_count=3,
            triggered_codes=("2330", "2454", "1101"),
            top_signal="new=2330 ; up=2454 ; down=1101",
        )


def test_watchlist_trigger_importer_maps_signal_types_without_ui_import():
    importer = WatchlistTriggerEvidenceImporter(FakeWatchlistProvider())

    result = importer.collect(
        EvidenceCaptureRequest(source="watchlist-trigger", decision_date="2026-07-02")
    )

    event_types = {payload["event_type"] for payload in result.event_payloads}
    assert EvidenceEventType.WATCHLIST_TRIGGER_ADDED in event_types
    assert EvidenceEventType.WATCHLIST_TRIGGER_STRENGTH_UP in event_types
    assert EvidenceEventType.WATCHLIST_TRIGGER_STRENGTH_DOWN in event_types
    assert EvidenceEventType.WATCHLIST_TRIGGER_RISK_ALERT in event_types
    assert "ui_qt" not in inspect.getsource(WatchlistTriggerEvidenceImporter)

