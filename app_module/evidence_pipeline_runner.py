from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, datetime
import json
import os
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from app_module.decision_desk_service import DecisionDeskSnapshotBuilder
from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.decision_desk_snapshot_storage_dtos import build_stored_decision_desk_snapshot, section_is_ready
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
    STEP_SKIPPED,
    scheduler_readiness_after_run,
)
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

    def run(self, request: EvidencePipelineRunRequest) -> EvidencePipelineRunSummary:
        self._validate_request(request)
        effective_dry_run = bool(request.dry_run or not request.confirm)
        self.db_path = self._active_db_path(request, effective_dry_run)
        started_at = self.clock().isoformat()
        run_id = self.run_id_factory()
        steps: list[EvidencePipelineStepSummary] = []
        source_coverage, source_step = self._source_coverage_step(request, effective_dry_run)
        steps.append(source_step)

        if request.skip_snapshot:
            steps.append(self._skipped_step("capture_decision_desk_snapshot", effective_dry_run))
        else:
            steps.append(self._snapshot_step(request, effective_dry_run))

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
        warnings = len(blocking_gaps)
        return coverage, EvidencePipelineStepSummary(
            step_name="source_coverage_check",
            status=STEP_DEGRADED if blocking_gaps else STEP_READY,
            dry_run=dry_run,
            records_seen=1,
            warnings_count=warnings,
            errors_count=sum(1 for item in diagnostics if item.severity == "error"),
            diagnostics=tuple(diagnostics),
            duration_ms=timer.elapsed_ms(),
        )

    def _source_coverage(self, request: EvidencePipelineRunRequest) -> dict[str, Any]:
        recommendation_repository = RecommendationRepository(self.config)
        snapshot_repository = DecisionDeskSnapshotRepository(self.config, db_path=self.db_path)
        recommendation = self._latest_recommendation(recommendation_repository, request.result_id)
        snapshots = snapshot_repository.list_snapshots()
        latest_snapshot = snapshot_repository.latest_before_or_on(request.decision_date) if request.decision_date else None
        recommendation_available = recommendation is not None
        why_not_ready = _has_payload(getattr(recommendation, "why_not_payload_json", None)) if recommendation else False
        liquidity_ready = (
            _has_payload(getattr(recommendation, "liquidity_gate_payload_json", None)) if recommendation else False
        )
        watchlist_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.watchlist_trigger_json)
        portfolio_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.portfolio_alert_json)
        risk_ready = latest_snapshot is not None and section_is_ready(latest_snapshot.risk_prompt_json)
        all_gaps: list[str] = []
        if not recommendation_available:
            all_gaps.append("recommendation_persisted_missing")
        if latest_snapshot is None:
            all_gaps.append("decision_desk_snapshot_missing")
        if latest_snapshot is not None and not watchlist_ready:
            all_gaps.append("watchlist_trigger_snapshot_section_missing")
        if latest_snapshot is not None and not portfolio_ready:
            all_gaps.append("portfolio_alert_snapshot_section_missing")
        if latest_snapshot is not None and not risk_ready:
            all_gaps.append("risk_prompt_snapshot_section_missing")
        if not why_not_ready:
            all_gaps.append("why_not_exclusion_payload_missing")
        if not liquidity_ready:
            all_gaps.append("liquidity_gate_payload_missing")
        snapshot_ready = latest_snapshot is not None and watchlist_ready and portfolio_ready and risk_ready
        if not recommendation_available or not snapshot_ready:
            readiness = READINESS_NOT_READY
        elif not (why_not_ready and liquidity_ready):
            readiness = READINESS_DRY_RUN_ONLY
        else:
            readiness = READINESS_READY_FOR_DESIGN
        return {
            "recommendation_persisted_available": recommendation_available,
            "recommendation_exclusion_payload_available": why_not_ready and liquidity_ready,
            "decision_desk_snapshots_count": len(snapshots),
            "latest_decision_desk_snapshot_date": latest_snapshot.decision_date if latest_snapshot is not None else None,
            "watchlist_trigger_capture_ready": watchlist_ready,
            "portfolio_alert_capture_ready": portfolio_ready,
            "risk_prompt_capture_ready": risk_ready,
            "why_not_capture_ready": why_not_ready,
            "liquidity_gate_capture_ready": liquidity_ready,
            "scheduler_readiness": readiness,
            "blocking_gaps": all_gaps,
        }

    def _latest_recommendation(self, repository: RecommendationRepository, result_id: str | None) -> Any | None:
        if result_id:
            return repository.load_result(result_id)
        rows = repository.list_results()
        if not rows:
            return None
        latest = sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]
        return repository.load_result(str(latest.get("result_id") or ""))

    def _blocking_gaps_for_request(self, coverage: dict[str, Any], request: EvidencePipelineRunRequest) -> list[str]:
        requested = set(self._expanded_sources(request.sources))
        gaps: list[str] = []
        if "recommendation" in requested and not coverage.get("recommendation_persisted_available"):
            gaps.append("recommendation_persisted_missing")
        if "watchlist-trigger" in requested and not coverage.get("watchlist_trigger_capture_ready"):
            gaps.append("watchlist_trigger_not_ready")
        if "portfolio-alert" in requested and not coverage.get("portfolio_alert_capture_ready"):
            gaps.append("portfolio_alert_not_ready")
        if "risk-prompt" in requested and not coverage.get("risk_prompt_capture_ready"):
            gaps.append("risk_prompt_not_ready")
        if "why-not" in requested and not coverage.get("why_not_capture_ready"):
            gaps.append("why_not_exclusion_payload_missing")
        if "liquidity-gate" in requested and not coverage.get("liquidity_gate_capture_ready"):
            gaps.append("liquidity_gate_payload_missing")
        return gaps

    def _snapshot_step(self, request: EvidencePipelineRunRequest, dry_run: bool) -> EvidencePipelineStepSummary:
        timer = _Timer()
        diagnostics: list[EvidencePipelineDiagnostic] = []
        try:
            snapshot = DecisionDeskSnapshotBuilder().build_snapshot(date.fromisoformat(request.decision_date[:10]))
            stored = build_stored_decision_desk_snapshot(snapshot, decision_date=request.decision_date[:10])
            created = 0
            skipped = 1
            if not dry_run:
                repository = DecisionDeskSnapshotRepository(self.config, db_path=self.db_path)
                before = repository.get_snapshot_by_hash(stored.snapshot_hash)
                repository.save_snapshot(stored)
                created = 1 if before is None else 0
                skipped = 0 if before is None else 1
            warnings_count = len(stored.warnings_json)
            status = STEP_DEGRADED if warnings_count else STEP_READY
            return EvidencePipelineStepSummary(
                step_name="capture_decision_desk_snapshot",
                status=status,
                dry_run=dry_run,
                records_seen=1,
                records_created=created,
                records_skipped=skipped,
                warnings_count=warnings_count,
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
        error_count = combined.events_failed + sum(1 for item in diagnostics if item.severity == "error")
        status = STEP_FAILED if error_count else (STEP_DEGRADED if warning_count else STEP_READY)
        return combined, EvidencePipelineStepSummary(
            step_name="capture_evidence_events",
            status=status,
            dry_run=dry_run,
            records_seen=combined.events_seen,
            records_created=combined.events_inserted,
            records_skipped=combined.events_skipped_duplicate,
            warnings_count=warning_count,
            errors_count=error_count,
            diagnostics=diagnostics,
            duration_ms=timer.elapsed_ms(),
        )

    def _build_importers(self, request: EvidencePipelineRunRequest) -> dict[str, Any]:
        importers = {
            "recommendation": RecommendationEvidenceImporter(RecommendationRepository(self.config)),
        }
        snapshot_repository = DecisionDeskSnapshotRepository(self.config, db_path=self.db_path)
        stored = snapshot_repository.latest_before_or_on(request.decision_date)
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
        clean = tuple(source.strip() for source in sources if source.strip())
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
        if any(step.status == STEP_FAILED for step in steps):
            return STEP_FAILED
        if blocking_gaps or any(step.status == STEP_DEGRADED for step in steps):
            return STEP_DEGRADED
        return STEP_READY

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


def _has_payload(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    return bool(list(value))


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
