from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app_module.decision_desk_dtos import DecisionDeskSnapshot
from app_module.pre_v2_readiness_service import (
    PreV2ReadinessReport,
    STATUS_ACTION_REQUIRED,
    STATUS_WAITING_FOR_TIME,
)
from app_module.workbench_dtos import (
    WorkbenchAccessBoundary,
    WorkbenchChecklistItem,
    WorkbenchDashboardDTO,
    WorkbenchEvidenceSummary,
    WorkbenchReviewItem,
    WorkbenchStatusItem,
)


class WorkbenchReadOnlyComposer:
    """Compose the V2.0 Phase 1 workbench payload from read-only inputs."""

    def compose(
        self,
        *,
        decision_snapshot: DecisionDeskSnapshot | None,
        readiness_report: PreV2ReadinessReport,
        agent_report_sample: dict[str, Any] | None = None,
        historical_replay_summary: dict[str, Any] | None = None,
        source_mode: str = "read_only",
        source_diagnostics: tuple[str, ...] = (),
    ) -> WorkbenchDashboardDTO:
        warnings = self._warnings(readiness_report, agent_report_sample, historical_replay_summary, source_diagnostics)
        return WorkbenchDashboardDTO(
            as_of_date=decision_snapshot.as_of_date if decision_snapshot is not None else date.today(),
            generated_at=datetime.utcnow().replace(microsecond=0),
            source_mode=str(source_mode),
            access_boundary=WorkbenchAccessBoundary(),
            status_strip=self._status_strip(decision_snapshot, readiness_report),
            review_items=self._review_items(decision_snapshot, readiness_report),
            evidence_summary=self._evidence_summary(readiness_report, historical_replay_summary),
            market_context=self._market_context(decision_snapshot),
            portfolio_watchlist_summary=self._portfolio_watchlist_summary(decision_snapshot),
            daily_checklist=self._daily_checklist(decision_snapshot, readiness_report),
            warnings=tuple(warnings),
        )

    def _status_strip(
        self,
        decision_snapshot: DecisionDeskSnapshot | None,
        readiness_report: PreV2ReadinessReport,
    ) -> tuple[WorkbenchStatusItem, ...]:
        if decision_snapshot is None:
            decision_status = WorkbenchStatusItem(
                item_id="decision_snapshot",
                label="Daily Decision snapshot",
                value="missing",
                status="warning",
                summary="缺 Daily Decision durable snapshot；不得讀 UI state 偽造。",
            )
            quality = "missing"
        else:
            quality = decision_snapshot.overall_quality.value
            decision_status = WorkbenchStatusItem(
                item_id="decision_snapshot",
                label="Daily Decision snapshot",
                value=decision_snapshot.as_of_date.isoformat(),
                status=quality,
                summary="已讀取 Daily Decision service snapshot。",
            )
        return (
            decision_status,
            WorkbenchStatusItem(
                item_id="data_quality",
                label="Data quality",
                value=quality,
                status=quality,
            ),
            WorkbenchStatusItem(
                item_id="evidence_gate",
                label="Evidence gate",
                value=readiness_report.overall_status,
                status=_status_to_severity(readiness_report.overall_status),
            ),
            WorkbenchStatusItem(
                item_id="scheduler",
                label="Production Scheduler",
                value="off",
                status="blocked",
                summary="Phase 5 approval 前固定維持 write-mode off。",
            ),
        )

    def _review_items(
        self,
        decision_snapshot: DecisionDeskSnapshot | None,
        readiness_report: PreV2ReadinessReport,
    ) -> tuple[WorkbenchReviewItem, ...]:
        items: list[WorkbenchReviewItem] = []
        if decision_snapshot is not None:
            watchlist = decision_snapshot.watchlist_triggers
            if (watchlist.trigger_count or 0) > 0 or watchlist.triggered_codes:
                items.append(
                    WorkbenchReviewItem(
                        item_id="watchlist_trigger",
                        title="Watchlist trigger review",
                        severity="info",
                        source="watchlist_trigger",
                        summary=f"候選池觸發 {watchlist.trigger_count or len(watchlist.triggered_codes)} 筆，需要人工判讀。",
                        drilldown_target="evidence_mode",
                    )
                )
            portfolio = decision_snapshot.portfolio_alerts
            if (portfolio.alert_count or 0) > 0 or portfolio.alert_codes:
                items.append(
                    WorkbenchReviewItem(
                        item_id="portfolio_alert",
                        title="Portfolio alert review",
                        severity="warning",
                        source="portfolio_alert",
                        summary=f"持倉警示 {portfolio.alert_count or len(portfolio.alert_codes)} 筆，需檢查 thesis 與風險來源。",
                        drilldown_target="portfolio_review",
                    )
                )
            for index, prompt in enumerate(decision_snapshot.risk_prompts.prompts, start=1):
                items.append(
                    WorkbenchReviewItem(
                        item_id=f"risk_prompt_{index}",
                        title=prompt.title,
                        severity=_severity(prompt.severity),
                        source="risk_prompt",
                        summary=prompt.reason,
                        drilldown_target="evidence_mode",
                        code=prompt.code,
                    )
                )
        for item in readiness_report.items:
            if item.status in {STATUS_ACTION_REQUIRED, STATUS_WAITING_FOR_TIME}:
                items.append(
                    WorkbenchReviewItem(
                        item_id=f"readiness_{item.item_id}",
                        title=item.label,
                        severity=_status_to_severity(item.status),
                        source="pre_v2_readiness",
                        summary=_readiness_summary(item.observed_count, item.required_count),
                        drilldown_target="evidence_mode",
                    )
                )
        return tuple(items)

    def _evidence_summary(
        self,
        readiness_report: PreV2ReadinessReport,
        historical_replay_summary: dict[str, Any] | None,
    ) -> tuple[WorkbenchEvidenceSummary, ...]:
        items = [
            WorkbenchEvidenceSummary(
                item_id=item.item_id,
                label=item.label,
                status=item.status,
                summary=_readiness_summary(item.observed_count, item.required_count),
                diagnostics=(*item.blocking_reasons, *item.diagnostics),
            )
            for item in readiness_report.items
        ]
        if historical_replay_summary:
            totals = historical_replay_summary.get("totals", {})
            final = historical_replay_summary.get("final_outcome_summary", {})
            missing_benchmark = int(final.get("missing_benchmark", 0) or 0)
            missing_industry = int(final.get("missing_industry_benchmark", 0) or 0)
            benchmark_text = "benchmark reference ready" if missing_benchmark == 0 else "benchmark reference gap"
            quality_disclosures = tuple(
                str(item) for item in historical_replay_summary.get("quality_disclosures", ())
            )
            diagnostics = _dedupe(
                [
                    *quality_disclosures,
                    *(str(item) for item in historical_replay_summary.get("warnings", ())),
                    *(str(item) for item in historical_replay_summary.get("limitations", ())),
                ]
            )
            items.append(
                WorkbenchEvidenceSummary(
                    item_id="historical_replay",
                    label="Historical replay simulated evidence",
                    status="degraded" if missing_industry else "ready",
                    summary=(
                        f"{totals.get('days', 0)} days / {totals.get('events_seen', 0)} events / "
                        f"{totals.get('outcomes_created', 0)} outcomes; {benchmark_text}; "
                        f"industry gaps {missing_industry}."
                    ),
                    diagnostics=tuple(diagnostics),
                )
            )
        return tuple(items)

    def _market_context(self, decision_snapshot: DecisionDeskSnapshot | None) -> dict[str, Any]:
        if decision_snapshot is None:
            return {"source_status": "missing"}
        return {
            "source_status": "ready",
            "overall_quality": decision_snapshot.overall_quality.value,
            "market_regime": decision_snapshot.market_regime.to_dict(),
            "market_breadth": decision_snapshot.market_breadth.to_dict(),
            "sector_rotation": decision_snapshot.sector_rotation.to_dict(),
            "relative_strength_liquidity": decision_snapshot.relative_strength_liquidity.to_dict(),
        }

    def _portfolio_watchlist_summary(self, decision_snapshot: DecisionDeskSnapshot | None) -> dict[str, Any]:
        if decision_snapshot is None:
            return {"source_status": "missing"}
        return {
            "source_status": "ready",
            "watchlist_triggers": decision_snapshot.watchlist_triggers.to_dict(),
            "portfolio_alerts": decision_snapshot.portfolio_alerts.to_dict(),
        }

    def _daily_checklist(
        self,
        decision_snapshot: DecisionDeskSnapshot | None,
        readiness_report: PreV2ReadinessReport,
    ) -> tuple[WorkbenchChecklistItem, ...]:
        return (
            WorkbenchChecklistItem(
                item_id="freshness",
                label="Decision snapshot freshness",
                status="done" if decision_snapshot is not None else "blocked",
                summary="已讀取 snapshot。" if decision_snapshot is not None else "缺 snapshot；不可從 UI state 補值。",
            ),
            WorkbenchChecklistItem(
                item_id="evidence_gate",
                label="Evidence gate status",
                status=readiness_report.overall_status,
                summary=f"Pre-V2 readiness: {readiness_report.overall_status}",
            ),
            WorkbenchChecklistItem(
                item_id="multi_day_dry_run",
                label="Multi-day dry-run",
                status=_find_status(readiness_report, "multi_day_dry_run"),
                summary="真實多日 dry-run 仍需依記錄累積。",
            ),
            WorkbenchChecklistItem(
                item_id="manual_review_note",
                label="Manual review note",
                status="manual_required",
                summary="Phase 1 prototype 不新增 append-only manual note repository。",
            ),
            WorkbenchChecklistItem(
                item_id="scheduler_off",
                label="Scheduler write-mode",
                status="blocked",
                summary="production_scheduler_allowed=false；不是交易建議。",
            ),
        )

    def _warnings(
        self,
        readiness_report: PreV2ReadinessReport,
        agent_report_sample: dict[str, Any] | None,
        historical_replay_summary: dict[str, Any] | None,
        source_diagnostics: tuple[str, ...] = (),
    ) -> list[str]:
        warnings = [
            "Phase 1 prototype 為 research/read-only 模式，不是交易建議。",
            "waiting_for_time 不能用單次 smoke 取代。",
            *readiness_report.limitations,
            *source_diagnostics,
        ]
        if agent_report_sample:
            warnings.extend(str(item) for item in agent_report_sample.get("warnings", ()))
            warnings.extend(str(item) for item in agent_report_sample.get("limitations", ()))
        if historical_replay_summary:
            warnings.extend(
                (
                    "historical_replay / simulated_scheduler 只作 V2.0 設計輸入。",
                    "historical replay 不滿足 Phase 0 weekly / multi-day gate。",
                )
            )
            warnings.extend(str(item) for item in historical_replay_summary.get("warnings", ()))
        return _dedupe(warnings)


def _find_status(readiness_report: PreV2ReadinessReport, item_id: str) -> str:
    for item in readiness_report.items:
        if item.item_id == item_id:
            return item.status
    return "missing"


def _readiness_summary(observed_count: int | None, required_count: int | None) -> str:
    if observed_count is None and required_count is None:
        return "readiness item available."
    if required_count is None:
        return f"{observed_count or 0} records observed."
    return f"{observed_count or 0}/{required_count} records observed."


def _status_to_severity(status: str) -> str:
    if status == STATUS_ACTION_REQUIRED:
        return "warning"
    if status == STATUS_WAITING_FOR_TIME:
        return "info"
    return _severity(status)


def _severity(value: str) -> str:
    if value in {"critical", "warning", "info", "blocked", "ready", "observed", "degraded", "missing"}:
        return value
    return "info"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
