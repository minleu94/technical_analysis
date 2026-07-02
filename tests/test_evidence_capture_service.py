from __future__ import annotations

from pathlib import Path

from app_module.evidence_capture_service import EvidenceCaptureService
from app_module.evidence_event_dtos import EvidenceDataQuality, EvidenceEventType
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService
from app_module.evidence_event_importer_dtos import EvidenceCaptureRequest, EvidenceImportResult
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    return TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")


class StaticImporter:
    source_name = "static"
    event_type = EvidenceEventType.RECOMMENDATION_INCLUDED

    def collect(self, request: EvidenceCaptureRequest) -> EvidenceImportResult:
        return EvidenceImportResult(
            source_name=self.source_name,
            decision_date=request.decision_date,
            event_payloads=(
                {
                    "event_date": "2026-07-02",
                    "decision_date": "2026-07-02",
                    "symbol": "2330",
                    "event_type": self.event_type,
                    "event_family": "recommendation",
                    "source_type": "recommendation_result",
                    "source_id": "rec-001",
                    "reason_codes": ("rank_top",),
                    "risk_codes": (),
                    "data_quality": EvidenceDataQuality.OBSERVED,
                    "warnings": ("source_warning",),
                    "as_of_date": "2026-07-02",
                    "available_date": "2026-07-02",
                    "metadata": {"stable": True},
                },
            ),
        )


class StringEventTypeImporter(StaticImporter):
    event_type = EvidenceEventType.RECOMMENDATION_INCLUDED.value


def test_capture_service_dry_run_returns_hash_sample_without_writing(tmp_path):
    repository = EvidenceEventRepository(_config(tmp_path))
    service = EvidenceCaptureService(EvidenceEventService(repository), {"static": StaticImporter()})

    summary = service.capture(EvidenceCaptureRequest(source="static", decision_date="2026-07-02"))

    assert summary.dry_run is True
    assert summary.events_seen == 1
    assert summary.events_valid == 1
    assert summary.events_inserted == 0
    assert summary.sample_events[0]["event_hash"].startswith("sha256:")
    assert repository.list_events() == []


def test_capture_service_hash_is_stable_for_enum_or_string_event_type(tmp_path):
    request = EvidenceCaptureRequest(source="static", decision_date="2026-07-02")
    enum_service = EvidenceCaptureService(
        EvidenceEventService(EvidenceEventRepository(_config(tmp_path / "enum"))),
        {"static": StaticImporter()},
    )
    string_service = EvidenceCaptureService(
        EvidenceEventService(EvidenceEventRepository(_config(tmp_path / "string"))),
        {"static": StringEventTypeImporter()},
    )

    enum_summary = enum_service.capture(request)
    string_summary = string_service.capture(request)

    assert enum_summary.sample_events[0]["event_hash"] == string_summary.sample_events[0]["event_hash"]


def test_capture_service_confirm_writes_and_counts_duplicates(tmp_path):
    repository = EvidenceEventRepository(_config(tmp_path))
    service = EvidenceCaptureService(EvidenceEventService(repository), {"static": StaticImporter()})
    request = EvidenceCaptureRequest(
        source="static",
        decision_date="2026-07-02",
        dry_run=False,
        confirm=True,
    )

    first = service.capture(request)
    second = service.capture(request)

    assert first.events_inserted == 1
    assert first.events_skipped_duplicate == 0
    assert second.events_inserted == 0
    assert second.events_skipped_duplicate == 1
    assert len(repository.list_events()) == 1


def test_capture_service_source_all_keeps_unsupported_diagnostic_and_runs_supported(tmp_path):
    repository = EvidenceEventRepository(_config(tmp_path))
    service = EvidenceCaptureService(EvidenceEventService(repository), {"static": StaticImporter()})

    summary = service.capture(
        EvidenceCaptureRequest(source="all", decision_date="2026-07-02", dry_run=False, confirm=True)
    )

    assert summary.source_name == "all"
    assert summary.events_inserted == 1
    assert summary.diagnostics_by_code["source_unsupported"] >= 1
