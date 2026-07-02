from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from app_module.evidence_event_dtos import EvidenceDataQuality, EvidenceEventType
from app_module.evidence_event_importer_dtos import (
    EvidenceCaptureRequest,
    EvidenceCaptureSummary,
    EvidenceImportDiagnostic,
    EvidenceImportResult,
)
from app_module.evidence_event_importers import EvidenceImporter
from app_module.evidence_event_service import EvidenceEventService


DEFAULT_CAPTURE_SOURCES = (
    "recommendation",
    "watchlist-trigger",
    "portfolio-alert",
    "risk-prompt",
)


class EvidenceCaptureService:
    """Capture importer payloads through the EvidenceEventService boundary."""

    def __init__(
        self,
        event_service: EvidenceEventService,
        importers: Mapping[str, EvidenceImporter],
    ) -> None:
        self.event_service = event_service
        self.importers = dict(importers)

    def capture(self, request: EvidenceCaptureRequest) -> EvidenceCaptureSummary:
        effective_dry_run = bool(request.dry_run or not request.confirm)
        diagnostics: list[EvidenceImportDiagnostic] = []
        payloads: list[dict[str, Any]] = []

        sources = self._sources_for_request(request)
        for source_name in sources:
            importer = self.importers.get(source_name)
            if importer is None:
                diagnostics.append(
                    EvidenceImportDiagnostic(
                        code="source_unsupported",
                        message="source importer is not configured",
                        source_name=source_name,
                    )
                )
                continue
            try:
                import_result = importer.collect(request)
            except Exception as exc:  # noqa: BLE001
                diagnostics.append(
                    EvidenceImportDiagnostic(
                        code="source_collect_failed",
                        message=str(exc),
                        source_name=source_name,
                        severity="error",
                    )
                )
                continue
            diagnostics.extend(import_result.diagnostics)
            payloads.extend(import_result.event_payloads)

        event_type_counts = Counter(self._event_type_value(payload.get("event_type")) for payload in payloads)
        quality_counts = Counter(self._quality_value(payload.get("data_quality")) for payload in payloads)
        warnings_count = sum(len(tuple(payload.get("warnings") or ())) for payload in payloads)
        warnings_count += sum(1 for diagnostic in diagnostics if diagnostic.severity == "warning")
        sample_events = tuple(self._sample_event(payload) for payload in payloads[:10])

        events_inserted = 0
        events_skipped_duplicate = 0
        events_failed = 0
        if not effective_dry_run:
            for payload in payloads:
                try:
                    event_hash = self._event_hash(payload)
                    existing = self.event_service.repository.get_event_by_hash(event_hash)
                    self.event_service.record_event(**payload)
                    if existing is None:
                        events_inserted += 1
                    else:
                        events_skipped_duplicate += 1
                except Exception as exc:  # noqa: BLE001
                    events_failed += 1
                    diagnostics.append(
                        EvidenceImportDiagnostic(
                            code="event_record_failed",
                            message=str(exc),
                            source_name=str(payload.get("source_type") or request.source),
                            symbol=str(payload.get("symbol") or "") or None,
                            severity="error",
                        )
                    )

        diagnostics_by_code = Counter(item.code for item in diagnostics)
        return EvidenceCaptureSummary(
            source_name=request.source,
            decision_date=request.decision_date_text,
            dry_run=effective_dry_run,
            events_seen=len(payloads),
            events_valid=len(payloads),
            events_inserted=events_inserted,
            events_skipped_duplicate=events_skipped_duplicate,
            events_failed=events_failed,
            warnings_count=warnings_count,
            diagnostics_by_code=dict(diagnostics_by_code),
            event_type_counts={key: value for key, value in event_type_counts.items() if key},
            quality_counts={key: value for key, value in quality_counts.items() if key},
            diagnostics=tuple(diagnostics),
            sample_events=sample_events,
        )

    def _sources_for_request(self, request: EvidenceCaptureRequest) -> tuple[str, ...]:
        if request.source == "all":
            ordered = [name for name in DEFAULT_CAPTURE_SOURCES if name in self.importers]
            ordered.extend(name for name in self.importers if name not in ordered)
            missing = [name for name in DEFAULT_CAPTURE_SOURCES if name not in ordered]
            return tuple(ordered + missing)
        return (request.source,)

    def _event_hash(self, payload: Mapping[str, Any]) -> str:
        return self.event_service.build_event_hash(
            event_date=str(payload.get("event_date") or ""),
            decision_date=str(payload.get("decision_date") or ""),
            symbol=payload.get("symbol"),
            event_type=self._event_type_value(payload.get("event_type")),
            source_type=str(payload.get("source_type") or ""),
            source_id=str(payload.get("source_id") or ""),
            source_snapshot_id=str(payload.get("source_snapshot_id") or ""),
            reason_codes=payload.get("reason_codes") or (),
            why_not_codes=payload.get("why_not_codes") or (),
            risk_codes=payload.get("risk_codes") or (),
            strategy_version_id=str(payload.get("strategy_version_id") or ""),
            profile_id=str(payload.get("profile_id") or ""),
            run_id=str(payload.get("run_id") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )

    def _sample_event(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "event_hash": self._event_hash(payload),
            "event_type": self._event_type_value(payload.get("event_type")),
            "symbol": payload.get("symbol"),
            "source_id": payload.get("source_id"),
        }

    def _event_type_value(self, value: Any) -> str:
        if isinstance(value, EvidenceEventType):
            return value.value
        return str(value or "")

    def _quality_value(self, value: Any) -> str:
        if isinstance(value, EvidenceDataQuality):
            return value.value
        if hasattr(value, "value"):
            return str(value.value)
        return str(value or "")
