from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, datetime
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable, Mapping
from uuid import uuid4

from app_module.decision_desk_builder_factory import build_service_backed_decision_desk_snapshot_builder
from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.decision_desk_snapshot_storage_dtos import (
    StoredDecisionDeskSnapshot,
    build_stored_decision_desk_snapshot,
    section_is_ready,
)
from app_module.evidence_capture_service import EvidenceCaptureService
from app_module.evidence_event_importer_dtos import EvidenceCaptureRequest
from app_module.evidence_event_importers import (
    MissingSnapshotEvidenceImporter,
    PortfolioAlertEvidenceImporter,
    RecommendationEvidenceImporter,
    RiskPromptEvidenceImporter,
    WatchlistTriggerEvidenceImporter,
)
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService
from app_module.evidence_pipeline_runner_support import derive_overall_status
from app_module.evidence_pipeline_runner_dtos import (
    EvidencePipelineDiagnostic,
    EvidencePipelineRunRequest,
    EvidencePipelineRunSummary,
    EvidencePipelineStepSummary,
    READINESS_DRY_RUN_ONLY,
    READINESS_NOT_READY,
    READINESS_READY_FOR_DESIGN,
    STEP_DEGRADED,
    STEP_FAILED,
    STEP_READY,
    STEP_READY_WITH_ADVISORIES,
    STEP_SKIPPED,
    scheduler_readiness_after_run,
)
from app_module.evidence_source_coverage_service import EvidenceSourceCoverageService
from app_module.forward_performance_read_model import (
    ForwardPerformanceFilter,
    ForwardPerformanceReadModel,
    SUMMARY_STATUS_DEGRADED,
    SUMMARY_STATUS_INSUFFICIENT_SAMPLE,
    SUMMARY_STATUS_READY,
)
from app_module.forward_performance_service import ForwardPerformanceService
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig


CAPTURE_SOURCE_ORDER = (
    "recommendation",
    "watchlist-trigger",
    "portfolio-alert",
    "risk-prompt",
)
EXCLUSION_SOURCE_ALIASES = {"why-not", "liquidity-gate"}


class _Timer:
    def __init__(self) -> None:
        self.start = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int(round((time.perf_counter() - self.start) * 1000))


class _DecisionDeskSnapshotSectionProvider:
    def __init__(self, stored_snapshot: Any, section_name: str) -> None:
        self.stored_snapshot = stored_snapshot
        self.section_name = section_name
        self.snapshot_id = stored_snapshot.snapshot_id
        self.metadata = {
            "decision_desk_snapshot_id": stored_snapshot.snapshot_id,
            "decision_desk_snapshot_hash": stored_snapshot.snapshot_hash,
            "decision_desk_snapshot_source": "durable_snapshot",
        }

    def build_snapshot(self, as_of_date: date) -> Any:
        snapshot = self.stored_snapshot.to_decision_desk_snapshot()
        if self.section_name == "watchlist-trigger":
            return snapshot.watchlist_triggers
        if self.section_name == "portfolio-alert":
            return snapshot.portfolio_alerts
        if self.section_name == "risk-prompt":
            return snapshot.risk_prompts
        raise ValueError(f"unsupported decision desk snapshot section: {self.section_name}")


class EvidencePipelineRunner:
    """Manual evidence pipeline runner with dry-run as the default."""

    def __init__(
        self,
        config: TWStockConfig,
        *,
        db_path: str | Path | None = None,
        clock: Any | None = None,
        run_id_factory: Any | None = None,
    ) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)
        self.clock = clock or (lambda: datetime.utcnow().replace(microsecond=0))
        self.run_id_factory = run_id_factory or (lambda: f"epr_{uuid4().hex[:12]}")
        self._transient_decision_desk_snapshot: StoredDecisionDeskSnapshot | None = None

    def run(self, request: EvidencePipelineRunRequest) -> EvidencePipelineRunSummary:
        self._validate_request(request)
        effective_dry_run = bool(request.dry_run or not request.confirm)
        self.db_path = self._active_db_path(request, effective_dry_run)
        self._transient_decision_desk_snapshot = None
        started_at = self.clock().isoformat()
        run_id = self.run_id_factory()
        steps: list[EvidencePipelineStepSummary] = []
        source_coverage, source_step = self._source_coverage_step(request, effective_dry_run)
        steps.append(source_step)

        if request.skip_snapshot:
            steps.append(self._skipped_step("capture_decision_desk_snapshot", effective_dry_run))
        else:
            snapshot_step = self._snapshot_step(request, effective_dry_run)
            steps.append(snapshot_step)
            source_coverage = self._reconciled_source_coverage(source_coverage, request)
            steps[0] = self._reconciled_source_step(steps[0], source_coverage, request)

        if request.skip_capture:
            capture_step = self._skipped_step("capture_evidence_events", effective_dry_run)
            capture_summary = None
        else:
            capture_summary, capture_step = self._capture_step(request, effective_dry_run)
        steps.append(capture_step)

        if request.skip_outcomes:
            outcome_summary = None
            steps.append(self._skipped_step("calculate_forward_outcomes", effective_dry_run))
        else:
            outcome_summary, outcome_step = self._outcome_step(request, effective_dry_run)
            steps.append(outcome_step)

        if request.skip_summary:
            forward_summaries: list[dict[str, Any]] = []
            steps.append(self._skipped_step("summarize_forward_performance", effective_dry_run))
        else:
            forward_summaries, summary_step = self._summary_step(request, effective_dry_run)
            steps.append(summary_step)

        warnings_count = sum(step.warnings_count for step in steps)
        warning_counts = _combined_warning_counts(step.warning_counts for step in steps)
        advisory_counts = _combined_advisory_counts(step.advisory_counts for step in steps)
        advisories_count = _advisory_count(advisory_counts)
        errors_count = sum(step.errors_count for step in steps)
        blocking_gaps = self._blocking_gaps_for_request(source_coverage, request)
        readiness_before = str(source_coverage.get("scheduler_readiness") or READINESS_NOT_READY)
        readiness_after = scheduler_readiness_after_run(
            readiness_before,
            dry_run=effective_dry_run,
            blocking_gaps=tuple(blocking_gaps),
            errors_count=errors_count,
        )
        groups_ready = sum(1 for item in forward_summaries if item.get("summary_status") == SUMMARY_STATUS_READY)
        groups_insufficient = sum(
            1 for item in forward_summaries if item.get("summary_status") == SUMMARY_STATUS_INSUFFICIENT_SAMPLE
        )
        groups_degraded = sum(
            1 for item in forward_summaries if item.get("summary_status") == SUMMARY_STATUS_DEGRADED
        )
        events_seen = int(getattr(capture_summary, "events_seen", 0) or 0)
        events_inserted = int(getattr(capture_summary, "events_inserted", 0) or 0)
        events_skipped_duplicate = int(getattr(capture_summary, "events_skipped_duplicate", 0) or 0)
        outcomes_created = int(getattr(outcome_summary, "outcomes_created", 0) or 0)
        outcomes_updated = int(getattr(outcome_summary, "outcomes_updated", 0) or 0)
        outcomes_pending = int(getattr(outcome_summary, "pending_insufficient_future_data", 0) or 0)
        outcomes_attempted = int(getattr(outcome_summary, "events_ready", 0) or 0) * len(request.windows)
        overall_status = self._overall_status(steps, blocking_gaps)

        report_output = request.report_output
        report_step = self._report_step_placeholder(effective_dry_run)
        steps.append(report_step)
        summary = EvidencePipelineRunSummary(
            run_id=run_id,
            decision_date=request.decision_date,
            start_date=request.start_date,
            end_date=request.end_date,
            dry_run=effective_dry_run,
            confirm=bool(request.confirm),
            db_path=str(self.db_path) if request.db_path or request.confirm else request.db_path,
            started_at=started_at,
            finished_at=self.clock().isoformat(),
            overall_status=overall_status,
            scheduler_readiness_before=readiness_before,
            scheduler_readiness_after=readiness_after,
            source_coverage=source_coverage,
            steps=tuple(steps),
            events_seen=events_seen,
            events_inserted=events_inserted,
            events_skipped_duplicate=events_skipped_duplicate,
            outcomes_attempted=outcomes_attempted,
            outcomes_created=outcomes_created,
            outcomes_updated=outcomes_updated,
            outcomes_pending=outcomes_pending,
            summary_groups=len(forward_summaries),
            groups_ready=groups_ready,
            groups_insufficient_sample=groups_insufficient,
            groups_degraded=groups_degraded,
            warnings_count=warnings_count,
            warning_counts=warning_counts,
            advisories_count=advisories_count,
            advisory_counts=advisory_counts,
            quality_coverage_rows=tuple(getattr(capture_summary, "quality_coverage_rows", ()) or ()),
            errors_count=errors_count,
            blocking_gaps=tuple(blocking_gaps),
            next_recommended_action=self._next_action(readiness_after, blocking_gaps, effective_dry_run),
            report_output=report_output,
            forward_summary=tuple(forward_summaries),
        )
        if report_output:
            timer = _Timer()
            try:
                write_pipeline_report(summary, Path(report_output))
                final_step = replace(steps[-1], status=STEP_READY, records_created=1, duration_ms=timer.elapsed_ms())
            except Exception as exc:  # noqa: BLE001
                diagnostic = EvidencePipelineDiagnostic(
                    code="report_write_failed",
                    message=str(exc),
                    severity="error",
                    step_name="write_diagnostics_report",
                )
                final_step = replace(
                    steps[-1],
                    status=STEP_FAILED,
                    errors_count=1,
                    diagnostics=(diagnostic,),
                    duration_ms=timer.elapsed_ms(),
                )
            steps[-1] = final_step
            summary = replace(
                summary,
                steps=tuple(steps),
                warnings_count=sum(step.warnings_count for step in steps),
                warning_counts=_combined_warning_counts(step.warning_counts for step in steps),
                errors_count=sum(step.errors_count for step in steps),
            )
        return summary

    def _validate_request(self, request: EvidencePipelineRunRequest) -> None:
        if request.confirm and request.dry_run:
            raise ValueError("--dry-run and --confirm are mutually exclusive")
        if request.confirm and not request.db_path:
            raise ValueError("--confirm requires explicit --db-path")
        if request.confirm and self._looks_like_production_db(request.db_path) and not request.allow_production_db_confirm:
            raise ValueError("--confirm against production-like DB requires --allow-production-db-confirm")

    def _looks_like_production_db(self, db_path: str | None) -> bool:
        if not db_path:
            return False
        target = Path(db_path).resolve()
        default_data_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data"))
        default_target = (default_data_root / "sqlite" / "twstock.db").resolve()
        return target == default_target

    def _active_db_path(self, request: EvidencePipelineRunRequest, dry_run: bool) -> Path:
        if request.db_path:
            return Path(request.db_path)
        if not dry_run:
            return self.db_path
        return self.config.output_root / "evidence_pipeline" / "dry_run_scratch" / "evidence_pipeline_dry_run.db"

    def _source_coverage_step(
        self,
        request: EvidencePipelineRunRequest,
        dry_run: bool,
    ) -> tuple[dict[str, Any], EvidencePipelineStepSummary]:
        timer = _Timer()
        diagnostics: list[EvidencePipelineDiagnostic] = []
        try:
            coverage = self._source_coverage(request)
        except Exception as exc:  # noqa: BLE001
            coverage = {
                "scheduler_readiness": READINESS_NOT_READY,
                "blocking_gaps": ["source_coverage_check_failed"],
            }
            diagnostics.append(
                EvidencePipelineDiagnostic(
                    code="source_coverage_check_failed",
                    message=str(exc),
                    severity="error",
                    step_name="source_coverage_check",
                )
            )
        blocking_gaps = self._blocking_gaps_for_request(coverage, request)
        warning_counts = _warning_counts(blocking_gaps)
        warnings = sum(warning_counts.values())
        return coverage, EvidencePipelineStepSummary(
            step_name="source_coverage_check",
            status=STEP_DEGRADED if blocking_gaps else STEP_READY,
            dry_run=dry_run,
            records_seen=1,
            warnings_count=warnings,
            warning_counts=warning_counts,
            errors_count=sum(1 for item in diagnostics if item.severity == "error"),
            diagnostics=tuple(diagnostics),
            duration_ms=timer.elapsed_ms(),
        )

    def _source_coverage(self, request: EvidencePipelineRunRequest) -> dict[str, Any]:
        return EvidenceSourceCoverageService(self.config, db_path=self.db_path).inspect(
            decision_date=request.decision_date,
            result_id=request.result_id,
        ).to_dict()

    def _reconciled_source_coverage(
        self,
        coverage: dict[str, Any],
        request: EvidencePipelineRunRequest,
    ) -> dict[str, Any]:
        stored = self._transient_snapshot_for_request(request)
        if stored is None:
            return coverage

        reconciled = dict(coverage)
        watchlist_ready = section_is_ready(stored.watchlist_trigger_json)
        portfolio_ready = section_is_ready(stored.portfolio_alert_json)
        risk_ready = section_is_ready(stored.risk_prompt_json)
        reconciled.update(
            {
                "decision_desk_snapshots_count": max(int(reconciled.get("decision_desk_snapshots_count") or 0), 1),
                "latest_decision_desk_snapshot_date": stored.decision_date,
                "watchlist_trigger_capture_ready": watchlist_ready,
                "portfolio_alert_capture_ready": portfolio_ready,
                "risk_prompt_capture_ready": risk_ready,
                "source_coverage_basis": "dry_run_transient_decision_desk_snapshot",
            }
        )
        gaps = [
            str(gap)
            for gap in reconciled.get("blocking_gaps", [])
            if str(gap)
            not in {
                "decision_desk_snapshot_missing",
                "watchlist_trigger_snapshot_section_missing",
                "portfolio_alert_snapshot_section_missing",
                "risk_prompt_snapshot_section_missing",
            }
        ]
        if not watchlist_ready:
            gaps.append("watchlist_trigger_snapshot_section_missing")
        if not portfolio_ready:
            gaps.append("portfolio_alert_snapshot_section_missing")
        if not risk_ready:
            gaps.append("risk_prompt_snapshot_section_missing")
        reconciled["blocking_gaps"] = gaps

        snapshot_ready = watchlist_ready and portfolio_ready and risk_ready
        if not reconciled.get("recommendation_persisted_available") or not snapshot_ready:
            reconciled["scheduler_readiness"] = READINESS_NOT_READY
        elif reconciled.get("warnings"):
            reconciled["scheduler_readiness"] = READINESS_DRY_RUN_ONLY
        else:
            reconciled["scheduler_readiness"] = READINESS_READY_FOR_DESIGN
        return reconciled

    def _reconciled_source_step(
        self,
        step: EvidencePipelineStepSummary,
        coverage: dict[str, Any],
        request: EvidencePipelineRunRequest,
    ) -> EvidencePipelineStepSummary:
        blocking_gaps = self._blocking_gaps_for_request(coverage, request)
        return replace(
            step,
            status=STEP_DEGRADED if blocking_gaps else STEP_READY,
            warnings_count=len(blocking_gaps),
            warning_counts=_warning_counts(blocking_gaps),
        )

    def _blocking_gaps_for_request(self, coverage: dict[str, Any], request: EvidencePipelineRunRequest) -> list[str]:
        requested = set(self._expanded_sources(request.sources))
        explicit = set(self._clean_sources(request.sources))
        gaps: list[str] = []
        if "recommendation" in requested and not coverage.get("recommendation_persisted_available"):
            gaps.append("recommendation_persisted_missing")
        if (
            "watchlist-trigger" in requested
            and not coverage.get("watchlist_trigger_capture_ready")
            and not self._transient_section_ready(request, "watchlist-trigger")
        ):
            gaps.append("watchlist_trigger_not_ready")
        if (
            "portfolio-alert" in requested
            and not coverage.get("portfolio_alert_capture_ready")
            and not self._transient_section_ready(request, "portfolio-alert")
        ):
            gaps.append("portfolio_alert_not_ready")
        if (
            "risk-prompt" in requested
            and not coverage.get("risk_prompt_capture_ready")
            and not self._transient_section_ready(request, "risk-prompt")
        ):
            gaps.append("risk_prompt_not_ready")
        if "why-not" in explicit and not coverage.get("why_not_capture_ready"):
            gaps.append("why_not_exclusion_payload_missing")
        if "liquidity-gate" in explicit and not coverage.get("liquidity_gate_capture_ready"):
            gaps.append("liquidity_gate_payload_missing")
        return gaps

    def _snapshot_step(self, request: EvidencePipelineRunRequest, dry_run: bool) -> EvidencePipelineStepSummary:
        timer = _Timer()
        diagnostics: list[EvidencePipelineDiagnostic] = []
        try:
            snapshot = build_service_backed_decision_desk_snapshot_builder(
                self.config,
                clock=self.clock,
            ).build_snapshot(date.fromisoformat(request.decision_date[:10]))
            stored = build_stored_decision_desk_snapshot(snapshot, decision_date=request.decision_date[:10])
            self._transient_decision_desk_snapshot = stored
            created = 0
            skipped = 1
            if not dry_run:
                repository = DecisionDeskSnapshotRepository(self.config, db_path=self.db_path)
                before = repository.get_snapshot_by_hash(stored.snapshot_hash)
                repository.save_snapshot(stored)
                created = 1 if before is None else 0
                skipped = 0 if before is None else 1
            warning_counts, advisory_counts = _split_warning_and_advisory_counts(stored.warnings_json)
            warnings_count = sum(warning_counts.values())
            advisories_count = sum(advisory_counts.values())
            status = (
                STEP_DEGRADED
                if warnings_count
                else STEP_READY_WITH_ADVISORIES
                if advisories_count
                else STEP_READY
            )
            return EvidencePipelineStepSummary(
                step_name="capture_decision_desk_snapshot",
                status=status,
                dry_run=dry_run,
                records_seen=1,
                records_created=created,
                records_skipped=skipped,
                warnings_count=warnings_count,
                warning_counts=warning_counts,
                advisories_count=advisories_count,
                advisory_counts=advisory_counts,
                duration_ms=timer.elapsed_ms(),
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                EvidencePipelineDiagnostic(
                    code="snapshot_capture_failed",
                    message=str(exc),
                    severity="error",
                    step_name="capture_decision_desk_snapshot",
                )
            )
            return EvidencePipelineStepSummary(
                step_name="capture_decision_desk_snapshot",
                status=STEP_FAILED,
                dry_run=dry_run,
                errors_count=1,
                diagnostics=tuple(diagnostics),
                duration_ms=timer.elapsed_ms(),
            )

    def _capture_step(self, request: EvidencePipelineRunRequest, dry_run: bool) -> tuple[Any, EvidencePipelineStepSummary]:
        timer = _Timer()
        repository = EvidenceEventRepository(self.config, db_path=self.db_path)
        service = EvidenceCaptureService(EvidenceEventService(repository), self._build_importers(request))
        summaries = []
        sources = self._capture_sources(request.sources)
        for source in sources:
            summary = service.capture(
                EvidenceCaptureRequest(
                    source=source,
                    decision_date=request.decision_date,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    result_id=request.result_id,
                    symbol=request.symbol,
                    limit=request.limit,
                    dry_run=dry_run,
                    confirm=not dry_run,
                    capture_exclusion_payloads=self._explicit_exclusion_requested(request),
                    replay_context=dict(request.replay_context),
                )
            )
            summaries.append(summary)
        combined = _CombinedCaptureSummary(summaries)
        diagnostics = tuple(
            EvidencePipelineDiagnostic(
                code=item.code,
                message=item.message,
                severity=item.severity,
                step_name="capture_evidence_events",
                source_name=item.source_name,
                metadata=item.metadata,
            )
            for summary in summaries
            for item in summary.diagnostics
        )
        warning_count = combined.warnings_count
        advisory_count = combined.advisories_count
        error_count = combined.events_failed + sum(1 for item in diagnostics if item.severity == "error")
        status = (
            STEP_FAILED
            if error_count
            else STEP_DEGRADED
            if warning_count
            else STEP_READY_WITH_ADVISORIES
            if advisory_count
            else STEP_READY
        )
        return combined, EvidencePipelineStepSummary(
            step_name="capture_evidence_events",
            status=status,
            dry_run=dry_run,
            records_seen=combined.events_seen,
            records_created=combined.events_inserted,
            records_skipped=combined.events_skipped_duplicate,
            warnings_count=warning_count,
            warning_counts=combined.warning_counts,
            advisories_count=advisory_count,
            advisory_counts=combined.advisory_counts,
            errors_count=error_count,
            diagnostics=diagnostics,
            duration_ms=timer.elapsed_ms(),
        )

    def _build_importers(self, request: EvidencePipelineRunRequest) -> dict[str, Any]:
        importers: dict[str, Any] = {
            "recommendation": RecommendationEvidenceImporter(RecommendationRepository(self.config)),
        }
        snapshot_repository = DecisionDeskSnapshotRepository(self.config, db_path=self.db_path)
        stored = snapshot_repository.latest_before_or_on(request.decision_date)
        if stored is None:
            stored = self._transient_snapshot_for_request(request)
        if stored is None:
            reason = "durable decision desk snapshot not found; run capture_decision_desk_snapshot.py first"
            importers.update(
                {
                    "watchlist-trigger": MissingSnapshotEvidenceImporter("watchlist-trigger", reason),
                    "portfolio-alert": MissingSnapshotEvidenceImporter("portfolio-alert", reason),
                    "risk-prompt": MissingSnapshotEvidenceImporter("risk-prompt", reason),
                }
            )
        else:
            importers.update(
                {
                    "watchlist-trigger": WatchlistTriggerEvidenceImporter(
                        _DecisionDeskSnapshotSectionProvider(stored, "watchlist-trigger")
                    ),
                    "portfolio-alert": PortfolioAlertEvidenceImporter(
                        _DecisionDeskSnapshotSectionProvider(stored, "portfolio-alert")
                    ),
                    "risk-prompt": RiskPromptEvidenceImporter(
                        _DecisionDeskSnapshotSectionProvider(stored, "risk-prompt")
                    ),
                }
            )
        return importers

    def _transient_snapshot_for_request(self, request: EvidencePipelineRunRequest) -> Any | None:
        stored = getattr(self, "_transient_decision_desk_snapshot", None)
        if stored is None:
            return None
        if str(getattr(stored, "decision_date", "")) != request.decision_date[:10]:
            return None
        return stored

    def _transient_section_ready(self, request: EvidencePipelineRunRequest, section_name: str) -> bool:
        stored = self._transient_snapshot_for_request(request)
        if stored is None:
            return False
        if section_name == "watchlist-trigger":
            return section_is_ready(stored.watchlist_trigger_json)
        if section_name == "portfolio-alert":
            return section_is_ready(stored.portfolio_alert_json)
        if section_name == "risk-prompt":
            return section_is_ready(stored.risk_prompt_json)
        return False

    def _clean_sources(self, sources: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(source.strip() for source in sources if source.strip())

    def _explicit_exclusion_requested(self, request: EvidencePipelineRunRequest) -> bool:
        return bool(set(self._clean_sources(request.sources)) & EXCLUSION_SOURCE_ALIASES)

    def _capture_sources(self, sources: tuple[str, ...]) -> tuple[str, ...]:
        expanded = self._expanded_sources(sources)
        capture_sources: list[str] = []
        if "recommendation" in expanded or any(source in expanded for source in EXCLUSION_SOURCE_ALIASES):
            capture_sources.append("recommendation")
        for source in ("watchlist-trigger", "portfolio-alert", "risk-prompt"):
            if source in expanded:
                capture_sources.append(source)
        return tuple(dict.fromkeys(capture_sources))

    def _expanded_sources(self, sources: tuple[str, ...]) -> tuple[str, ...]:
        clean = self._clean_sources(sources)
        if not clean or "all" in clean:
            return (*CAPTURE_SOURCE_ORDER, "why-not", "liquidity-gate")
        return clean

    def _outcome_step(self, request: EvidencePipelineRunRequest, dry_run: bool) -> tuple[Any, EvidencePipelineStepSummary]:
        timer = _Timer()
        try:
            repository = EvidenceEventRepository(self.config, db_path=self.db_path)
            summary = ForwardPerformanceService(self.config, repository).calculate(
                windows=request.windows,
                dry_run=dry_run,
                decision_date=request.decision_date,
                start_date=request.start_date,
                end_date=request.end_date,
                symbol=request.symbol,
                limit=request.limit,
            )
            warnings = summary.warnings_count
            status = STEP_DEGRADED if warnings else STEP_READY
            return summary, EvidencePipelineStepSummary(
                step_name="calculate_forward_outcomes",
                status=status,
                dry_run=dry_run,
                records_seen=summary.events_scanned,
                records_created=summary.outcomes_created if not dry_run else 0,
                records_updated=summary.outcomes_updated if not dry_run else 0,
                records_skipped=summary.pending_insufficient_future_data,
                warnings_count=warnings,
                warning_counts=_forward_outcome_warning_counts(summary),
                duration_ms=timer.elapsed_ms(),
            )
        except Exception as exc:  # noqa: BLE001
            diagnostic = EvidencePipelineDiagnostic(
                code="forward_outcome_calculation_failed",
                message=str(exc),
                severity="error",
                step_name="calculate_forward_outcomes",
            )
            return None, EvidencePipelineStepSummary(
                step_name="calculate_forward_outcomes",
                status=STEP_FAILED,
                dry_run=dry_run,
                errors_count=1,
                diagnostics=(diagnostic,),
                duration_ms=timer.elapsed_ms(),
            )

    def _summary_step(
        self,
        request: EvidencePipelineRunRequest,
        dry_run: bool,
    ) -> tuple[list[dict[str, Any]], EvidencePipelineStepSummary]:
        timer = _Timer()
        try:
            repository = EvidenceEventRepository(self.config, db_path=self.db_path)
            summaries = ForwardPerformanceReadModel(repository).summarize(
                group_by=request.group_by,
                filters=ForwardPerformanceFilter(
                    start_date=request.start_date,
                    end_date=request.end_date,
                    symbol=request.symbol,
                    window_days=request.window,
                ),
                min_sample_size=request.min_sample_size,
            )
            payloads = [item.to_dict() for item in summaries]
            degraded = sum(1 for item in payloads if item.get("summary_status") != SUMMARY_STATUS_READY)
            return payloads, EvidencePipelineStepSummary(
                step_name="summarize_forward_performance",
                status=STEP_DEGRADED if degraded else STEP_READY,
                dry_run=dry_run,
                records_seen=len(payloads),
                warnings_count=degraded,
                warning_counts=_forward_summary_warning_counts(payloads),
                duration_ms=timer.elapsed_ms(),
            )
        except Exception as exc:  # noqa: BLE001
            diagnostic = EvidencePipelineDiagnostic(
                code="forward_summary_failed",
                message=str(exc),
                severity="error",
                step_name="summarize_forward_performance",
            )
            return [], EvidencePipelineStepSummary(
                step_name="summarize_forward_performance",
                status=STEP_FAILED,
                dry_run=dry_run,
                errors_count=1,
                diagnostics=(diagnostic,),
                duration_ms=timer.elapsed_ms(),
            )

    def _report_step_placeholder(self, dry_run: bool) -> EvidencePipelineStepSummary:
        return EvidencePipelineStepSummary(
            step_name="write_diagnostics_report",
            status=STEP_SKIPPED,
            dry_run=dry_run,
        )

    def _skipped_step(self, step_name: str, dry_run: bool) -> EvidencePipelineStepSummary:
        return EvidencePipelineStepSummary(step_name=step_name, status=STEP_SKIPPED, dry_run=dry_run)

    def _overall_status(self, steps: list[EvidencePipelineStepSummary], blocking_gaps: list[str]) -> str:
        return derive_overall_status((step.status for step in steps), blocking_gaps)

    def _next_action(self, readiness: str, blocking_gaps: list[str], dry_run: bool) -> str:
        if blocking_gaps:
            return "Resolve blocking gaps, then rerun the manual dry-run."
        if readiness == "ready_for_manual_confirm" and dry_run:
            return "Run manual confirm mode against a working-copy DB after review."
        return "Review diagnostics before any future scheduler design."


class _CombinedCaptureSummary:
    def __init__(self, summaries: list[Any]) -> None:
        self.summaries = tuple(summaries)
        self.events_seen = sum(int(item.events_seen) for item in summaries)
        self.events_inserted = sum(int(item.events_inserted) for item in summaries)
        self.events_skipped_duplicate = sum(int(item.events_skipped_duplicate) for item in summaries)
        self.events_failed = sum(int(item.events_failed) for item in summaries)
        self.warnings_count = sum(int(item.warnings_count) for item in summaries)
        self.warning_counts = _combined_warning_counts(item.warning_counts for item in summaries)
        self.advisories_count = sum(int(item.advisories_count) for item in summaries)
        self.advisory_counts = _combined_advisory_counts(item.advisory_counts for item in summaries)
        self.quality_coverage_rows = tuple(
            row
            for summary in summaries
            for row in getattr(summary, "quality_coverage_rows", ())
        )


def _warning_tokens(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    try:
        return tuple(str(item).strip() for item in value if str(item).strip())
    except TypeError:
        text = str(value).strip()
        return (text,) if text else ()


def _warning_counts(value: Any) -> dict[str, int]:
    return dict(sorted(Counter(_warning_tokens(value)).items()))


def _combined_warning_counts(mappings: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for mapping in mappings:
        for key, value in dict(mapping or {}).items():
            token = str(key).strip()
            if not token:
                continue
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            if count > 0:
                counter[token] += count
    return dict(sorted(counter.items()))


def _combined_advisory_counts(mappings: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for mapping in mappings:
        for key, value in dict(mapping or {}).items():
            token = str(key).strip()
            if not token:
                continue
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            if count > counter[token]:
                counter[token] = count
    return dict(sorted(counter.items()))


def _advisory_count(advisory_counts: Mapping[str, Any]) -> int:
    return sum(int(value) for value in advisory_counts.values() if int(value) > 0)


def _split_warning_and_advisory_counts(value: Any) -> tuple[dict[str, int], dict[str, int]]:
    warnings: Counter[str] = Counter()
    advisories: Counter[str] = Counter()
    for token in _warning_tokens(value):
        advisory_token = _canonical_advisory_token(token)
        if advisory_token is not None:
            advisories[advisory_token] += 1
        else:
            warnings[token] += 1
    return dict(sorted(warnings.items())), dict(sorted(advisories.items()))


def _canonical_advisory_token(token: str) -> str | None:
    normalized = token
    for prefix in ("portfolio_alerts:", "risk_prompts:", "relative_strength_liquidity:"):
        if normalized.startswith(prefix):
            normalized = normalized.removeprefix(prefix)
            break
    if normalized.startswith((
        "portfolio_alert_top_source:",
        "portfolio_alerts_chip_estimated:",
        "relative_strength_liquidity_skipped_symbols:",
    )):
        return normalized
    if normalized.startswith("risk_prompt_source_quality:") and normalized.endswith(":estimated"):
        return normalized
    return None


def _top_warning_counts(warning_counts: Mapping[str, int], *, limit: int = 10) -> dict[str, int]:
    rows = sorted(
        ((str(key), int(value)) for key, value in warning_counts.items() if str(key).strip() and int(value) > 0),
        key=lambda item: (-item[1], item[0]),
    )
    return dict(rows[:limit])


def _forward_outcome_warning_counts(summary: Any) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for attr, token in (
        ("pending_insufficient_future_data", "insufficient_future_data"),
        ("missing_event_price", "missing_event_price"),
        ("missing_outcome_price", "missing_outcome_price"),
        ("missing_benchmark", "missing_benchmark"),
        ("missing_industry_benchmark", "missing_industry_benchmark"),
    ):
        count = int(getattr(summary, attr, 0) or 0)
        if count > 0:
            counter[token] += count
    remaining = int(getattr(summary, "warnings_count", 0) or 0) - sum(counter.values())
    if remaining > 0:
        counter["forward_outcome_warning_unclassified"] += remaining
    return dict(sorted(counter.items()))


def _forward_summary_warning_counts(payloads: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for payload in payloads:
        status = str(payload.get("summary_status") or "").strip()
        if status and status != SUMMARY_STATUS_READY:
            counter[f"forward_summary_status:{status}"] += 1
    return dict(sorted(counter.items()))


def write_pipeline_report(summary: EvidencePipelineRunSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return
    path.write_text(_markdown_report(summary), encoding="utf-8")


def _markdown_report(summary: EvidencePipelineRunSummary) -> str:
    step_rows = "\n".join(
        f"- {step.step_name}: {step.status}, seen={step.records_seen}, created={step.records_created}, "
        f"warnings={step.warnings_count}, errors={step.errors_count}"
        for step in summary.steps
    )
    coverage = json.dumps(summary.source_coverage, ensure_ascii=False, sort_keys=True, indent=2)
    gaps = "\n".join(f"- {gap}" for gap in summary.blocking_gaps) or "- none"
    diagnostics = Counter(summary.diagnostic_codes)
    diagnostic_rows = "\n".join(f"- {code}: {count}" for code, count in sorted(diagnostics.items())) or "- none"
    top_warning_rows = "\n".join(
        f"- {code}: {count}" for code, count in _top_warning_counts(summary.warning_counts).items()
    ) or "- none"
    warning_rows = "\n".join(
        f"- {code}: {count}" for code, count in sorted(summary.warning_counts.items())
    ) or "- none"
    advisory_rows = "\n".join(
        f"- {code}: {count}" for code, count in sorted(summary.advisory_counts.items())
    ) or "- none"
    quality_coverage_rows = "\n".join(
        "- {symbol}: observed={observed}, estimated={estimated}, unavailable={unavailable}".format(
            symbol=row.get("symbol") or "",
            observed=int(row.get("observed_event_count") or 0),
            estimated=int(row.get("estimated_event_count") or 0),
            unavailable=int(row.get("unavailable_event_count") or 0),
        )
        for row in summary.quality_coverage_rows
    ) or "- none"
    return (
        "# Evidence Pipeline Dry-run Report\n\n"
        "## Run Metadata\n"
        f"- run_id: {summary.run_id}\n"
        f"- decision_date: {summary.decision_date}\n"
        f"- dry_run: {summary.dry_run}\n"
        f"- confirm: {summary.confirm}\n"
        f"- db_path: {summary.db_path}\n\n"
        "## Source Coverage\n"
        f"```json\n{coverage}\n```\n\n"
        "## Step Summary\n"
        f"{step_rows}\n\n"
        "## Event Capture Summary\n"
        f"- events_seen: {summary.events_seen}\n"
        f"- events_inserted: {summary.events_inserted}\n"
        f"- events_skipped_duplicate: {summary.events_skipped_duplicate}\n\n"
        "## Outcome Calculation Summary\n"
        f"- outcomes_attempted: {summary.outcomes_attempted}\n"
        f"- outcomes_created: {summary.outcomes_created}\n"
        f"- outcomes_updated: {summary.outcomes_updated}\n"
        f"- outcomes_pending: {summary.outcomes_pending}\n\n"
        "## Forward Performance Summary\n"
        f"- summary_groups: {summary.summary_groups}\n"
        f"- groups_ready: {summary.groups_ready}\n"
        f"- groups_insufficient_sample: {summary.groups_insufficient_sample}\n"
        f"- groups_degraded: {summary.groups_degraded}\n\n"
        "## Warnings / Degraded Sources\n"
        f"- warnings_count: {summary.warnings_count}\n"
        f"- diagnostics:\n{diagnostic_rows}\n\n"
        "## Warning Summary\n"
        f"- warning_occurrence_count: {summary.warnings_count}\n"
        f"- unique_warning_token_count: {len(summary.warning_counts)}\n"
        f"- top_warning_tokens:\n{top_warning_rows}\n\n"
        "## Warning Breakdown\n"
        f"{warning_rows}\n\n"
        "## Advisories\n"
        f"- advisory_occurrence_count: {summary.advisories_count}\n"
        f"- unique_advisory_token_count: {len(summary.advisory_counts)}\n"
        f"{advisory_rows}\n\n"
        "## Source Quality Coverage\n"
        f"{quality_coverage_rows}\n\n"
        "## Blocking Gaps\n"
        f"{gaps}\n\n"
        "## Evidence Boundary\n"
        "- This report is research evidence only.\n"
        "- Close-to-close forward return is research evidence only.\n"
        "- Close-to-close forward return is not executable live performance.\n"
        "- No trading recommendation is produced.\n\n"
        "## Scheduler Readiness\n"
        f"- before: {summary.scheduler_readiness_before}\n"
        f"- after: {summary.scheduler_readiness_after}\n\n"
        "## Next Recommended Action\n"
        f"{summary.next_recommended_action}\n"
    )
