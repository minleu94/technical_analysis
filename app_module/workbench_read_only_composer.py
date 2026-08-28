from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from app_module.advice_dtos import AdviceDashboardDTO
from app_module.decision_desk_dtos import DecisionDeskSnapshot
from app_module.pre_v2_readiness_service import (
    PreV2ReadinessItem,
    PreV2ReadinessReport,
    STATUS_ACTION_REQUIRED,
    STATUS_WAITING_FOR_TIME,
)
from app_module.scheduled_evidence_status_service import ScheduledEvidenceStatus
from app_module.workbench_dtos import (
    WorkbenchAccessBoundary,
    WorkbenchActionItem,
    WorkbenchChecklistItem,
    WorkbenchDashboardDTO,
    WorkbenchEvidenceFeedItem,
    WorkbenchEvidenceSummary,
    WorkbenchOperatingLoopStep,
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
        scheduled_status: ScheduledEvidenceStatus | None = None,
        historical_replay_summary: dict[str, Any] | None = None,
        source_mode: str = "read_only",
        source_diagnostics: tuple[str, ...] = (),
        advice_dashboard: AdviceDashboardDTO | None = None,
    ) -> WorkbenchDashboardDTO:
        warnings = self._warnings(readiness_report, agent_report_sample, historical_replay_summary, source_diagnostics)
        review_items = self._review_items(decision_snapshot, readiness_report)
        daily_checklist = self._daily_checklist(decision_snapshot, readiness_report)
        background_evidence_feed = self._background_evidence_feed(
            decision_snapshot,
            readiness_report,
            scheduled_status,
            historical_replay_summary,
        )
        action_items = self._action_items(decision_snapshot, readiness_report, historical_replay_summary)
        return WorkbenchDashboardDTO(
            as_of_date=decision_snapshot.as_of_date if decision_snapshot is not None else date.today(),
            generated_at=datetime.utcnow().replace(microsecond=0),
            source_mode=str(source_mode),
            access_boundary=WorkbenchAccessBoundary(),
            status_strip=self._status_strip(decision_snapshot, readiness_report),
            review_items=review_items,
            evidence_summary=self._evidence_summary(readiness_report, scheduled_status, historical_replay_summary),
            market_context=self._market_context(decision_snapshot),
            portfolio_watchlist_summary=self._portfolio_watchlist_summary(decision_snapshot),
            daily_checklist=daily_checklist,
            warnings=tuple(warnings),
            background_evidence_feed=background_evidence_feed,
            action_items=action_items,
            operating_loop_steps=self._operating_loop_steps(
                review_items=review_items,
                background_evidence_feed=background_evidence_feed,
                action_items=action_items,
                daily_checklist=daily_checklist,
                readiness_report=readiness_report,
            ),
            advice_dashboard=advice_dashboard,
        )

    def _status_strip(
        self,
        decision_snapshot: DecisionDeskSnapshot | None,
        readiness_report: PreV2ReadinessReport,
    ) -> tuple[WorkbenchStatusItem, ...]:
        if decision_snapshot is None:
            decision_status = WorkbenchStatusItem(
                item_id="decision_snapshot",
                label="每日決策快照",
                value="missing",
                status="warning",
                summary="缺 Daily Decision durable snapshot；不得讀 UI state 偽造。",
            )
            quality = "missing"
        else:
            quality = decision_snapshot.overall_quality.value
            decision_status = WorkbenchStatusItem(
                item_id="decision_snapshot",
                label="每日決策快照",
                value=decision_snapshot.as_of_date.isoformat(),
                status=quality,
                summary="已讀取 Daily Decision service snapshot。",
            )
        return (
            decision_status,
            WorkbenchStatusItem(
                item_id="data_quality",
                label="資料品質",
                value=quality,
                status=quality,
            ),
            WorkbenchStatusItem(
                item_id="evidence_gate",
                label="證據門檻",
                value=readiness_report.overall_status,
                status=_status_to_severity(readiness_report.overall_status),
                summary=_evidence_gate_status_summary(readiness_report),
            ),
            WorkbenchStatusItem(
                item_id="scheduler",
                label="正式排程器",
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
                        title="觀察清單觸發覆盤",
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
                        title="持倉警示覆盤",
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

    def _background_evidence_feed(
        self,
        decision_snapshot: DecisionDeskSnapshot | None,
        readiness_report: PreV2ReadinessReport,
        scheduled_status: ScheduledEvidenceStatus | None,
        historical_replay_summary: dict[str, Any] | None,
    ) -> tuple[WorkbenchEvidenceFeedItem, ...]:
        items: list[WorkbenchEvidenceFeedItem] = []
        if decision_snapshot is None:
            items.append(
                WorkbenchEvidenceFeedItem(
                    item_id="daily_decision_snapshot",
                    label="Daily Decision snapshot",
                    status="missing",
                    summary="缺 Daily Decision durable snapshot；Workbench 不讀 UI state 補值。",
                    source_trace="DecisionDeskSnapshot",
                    degraded_reason="decision_desk_snapshot_missing",
                    drilldown_target="daily_decision",
                )
            )
            items.append(
                WorkbenchEvidenceFeedItem(
                    item_id="portfolio_alerts",
                    label="Portfolio alerts",
                    status="missing",
                    summary="缺 Daily Decision snapshot，因此沒有既有 portfolio alert payload 可呈現。",
                    source_trace="DecisionDeskSnapshot.portfolio_alerts",
                    degraded_reason="decision_desk_snapshot_missing",
                    drilldown_target="portfolio_review",
                )
            )
        else:
            portfolio = decision_snapshot.portfolio_alerts
            risk_prompt_count = len(decision_snapshot.risk_prompts.prompts)
            items.append(
                WorkbenchEvidenceFeedItem(
                    item_id="daily_decision_snapshot",
                    label="Daily Decision snapshot",
                    status=decision_snapshot.overall_quality.value,
                    summary=(
                        f"as_of={decision_snapshot.as_of_date.isoformat()}；"
                        f"watchlist={portfolio_safe_count(decision_snapshot.watchlist_triggers.trigger_count, decision_snapshot.watchlist_triggers.triggered_codes)}；"
                        f"portfolio_alerts={portfolio_safe_count(portfolio.alert_count, portfolio.alert_codes)}；"
                        f"risk_prompts={risk_prompt_count}。"
                    ),
                    source_trace="DecisionDeskSnapshot",
                    degraded_reason=_reason_or_none(decision_snapshot.warnings),
                    drilldown_target="daily_decision",
                    diagnostics=decision_snapshot.warnings,
                )
            )
            portfolio_diagnostics = (
                *portfolio.warnings,
                *(flag for attribution in portfolio.attributions for flag in attribution.data_quality_flags),
            )
            items.append(
                WorkbenchEvidenceFeedItem(
                    item_id="portfolio_alerts",
                    label="Portfolio alerts",
                    status=portfolio.quality.value,
                    summary=(
                        f"{portfolio_safe_count(portfolio.alert_count, portfolio.alert_codes)} alert rows；"
                        f"level={portfolio.alert_level or 'n/a'}。"
                    ),
                    source_trace="DecisionDeskSnapshot.portfolio_alerts",
                    degraded_reason=_reason_or_none(portfolio_diagnostics),
                    drilldown_target="portfolio_review",
                    diagnostics=tuple(str(item) for item in portfolio_diagnostics),
                )
            )

        items.append(
            WorkbenchEvidenceFeedItem(
                item_id="evidence_review_readiness",
                label="Evidence Review readiness",
                status=readiness_report.overall_status,
                summary=_readiness_feed_summary(readiness_report),
                source_trace="PreV2ReadinessReport",
                degraded_reason=_readiness_reason(readiness_report),
                drilldown_target="evidence_review",
                diagnostics=tuple(
                    reason
                    for item in readiness_report.items
                    for reason in (*item.blocking_reasons, *item.diagnostics)
                ),
            )
        )
        if scheduled_status is not None:
            items.append(
                WorkbenchEvidenceFeedItem(
                    item_id="scheduled_morning_pipeline",
                    label="Scheduled morning pipeline",
                    status=_scheduled_status_label(scheduled_status),
                    summary=_scheduled_status_summary(scheduled_status),
                    source_trace="ScheduledEvidenceStatusService",
                    degraded_reason=_reason_or_none(scheduled_status.diagnostics),
                    drilldown_target="evidence_review",
                    diagnostics=scheduled_status.diagnostics,
                )
            )

        if historical_replay_summary:
            diagnostics = _replay_diagnostics(historical_replay_summary)
            final = historical_replay_summary.get("final_outcome_summary", {})
            missing_industry = _int(final.get("missing_industry_benchmark"))
            pending_future = _int(final.get("pending_insufficient_future_data"))
            source_gap_count = sum(1 for item in diagnostics if item.startswith("source_gap:"))
            items.append(
                WorkbenchEvidenceFeedItem(
                    item_id="replay_summary_diagnostics",
                    label="Replay summary diagnostics",
                    status="degraded" if missing_industry or pending_future or source_gap_count else "ready",
                    summary=(
                        "Historical replay JSON summary 已揭露 "
                        f"source_gaps={source_gap_count}；missing_industry={missing_industry}；"
                        f"pending_future_data={pending_future}。"
                    ),
                    source_trace="HistoricalReplaySummary",
                    degraded_reason=_reason_or_none(
                        tuple(item for item in diagnostics if item.startswith(("source_gap:", "payload_gap:", "missing_", "pending_")))
                    ),
                    drilldown_target="evidence_review",
                    diagnostics=tuple(diagnostics),
                )
            )
        else:
            items.append(
                WorkbenchEvidenceFeedItem(
                    item_id="replay_summary_diagnostics",
                    label="Replay summary diagnostics",
                    status="missing",
                    summary="未提供 replay JSON summary；Workbench 不讀 replay DB、不執行 replay。",
                    source_trace="HistoricalReplaySummary",
                    degraded_reason="replay_summary_not_supplied",
                    drilldown_target="evidence_review",
                )
            )
        return tuple(items)

    def _action_items(
        self,
        decision_snapshot: DecisionDeskSnapshot | None,
        readiness_report: PreV2ReadinessReport,
        historical_replay_summary: dict[str, Any] | None,
    ) -> tuple[WorkbenchActionItem, ...]:
        items: list[WorkbenchActionItem] = []
        if decision_snapshot is not None:
            watchlist = decision_snapshot.watchlist_triggers
            watchlist_count = portfolio_safe_count(watchlist.trigger_count, watchlist.triggered_codes)
            if watchlist_count > 0:
                severity = "info"
                queue_group = "daily_review"
                source_type = "watchlist_trigger"
                items.append(
                    WorkbenchActionItem(
                        item_id="watchlist_trigger_manual_review",
                        title="觀察清單觸發人工覆盤",
                        source_type=source_type,
                        severity=severity,
                        summary=f"既有 snapshot 顯示 {watchlist_count} 筆觀察清單觸發，需人工判讀。",
                        source_trace="DecisionDeskSnapshot.watchlist_triggers",
                        degraded_reason=_reason_or_none(watchlist.warnings, "watchlist_trigger_requires_manual_review"),
                        drilldown_target="daily_decision",
                        queue_group=queue_group,
                        source_label="觀察清單觸發",
                        sort_rank=_action_sort_rank(severity, queue_group, source_type, len(items)),
                        code=", ".join(watchlist.triggered_codes) or None,
                    )
                )
            portfolio = decision_snapshot.portfolio_alerts
            portfolio_count = portfolio_safe_count(portfolio.alert_count, portfolio.alert_codes)
            if portfolio_count > 0:
                severity = "warning"
                queue_group = "portfolio_review"
                source_type = "portfolio_alert"
                items.append(
                    WorkbenchActionItem(
                        item_id="portfolio_alert_manual_review",
                        title="持倉警示人工覆盤",
                        source_type=source_type,
                        severity=severity,
                        summary=f"既有 snapshot 顯示 {portfolio_count} 筆持倉警示，需檢查 thesis 與風險來源。",
                        source_trace="DecisionDeskSnapshot.portfolio_alerts",
                        degraded_reason=_reason_or_none(portfolio.warnings, "portfolio_alert_requires_manual_review"),
                        drilldown_target="portfolio_review",
                        queue_group=queue_group,
                        source_label="持倉警示",
                        sort_rank=_action_sort_rank(severity, queue_group, source_type, len(items)),
                        code=", ".join(portfolio.alert_codes) or None,
                    )
                )
            for index, prompt in enumerate(decision_snapshot.risk_prompts.prompts, start=1):
                severity = _severity(prompt.severity)
                queue_group = "daily_review"
                source_type = "risk_prompt"
                items.append(
                    WorkbenchActionItem(
                        item_id=f"risk_prompt_manual_review_{index}",
                        title=prompt.title,
                        source_type=source_type,
                        severity=severity,
                        summary=prompt.action_hint,
                        source_trace=f"DecisionDeskSnapshot.risk_prompts[{index}].{prompt.source}",
                        degraded_reason=prompt.reason,
                        drilldown_target="daily_decision",
                        queue_group=queue_group,
                        source_label="風險提示",
                        sort_rank=_action_sort_rank(severity, queue_group, source_type, len(items)),
                        code=prompt.code,
                    )
                )

        for readiness_item in readiness_report.items:
            if readiness_item.status not in {STATUS_ACTION_REQUIRED, STATUS_WAITING_FOR_TIME}:
                continue
            severity = _status_to_severity(readiness_item.status)
            queue_group = "evidence_gate"
            source_type = "pre_v2_readiness"
            items.append(
                WorkbenchActionItem(
                    item_id=f"readiness_{readiness_item.item_id}",
                    title=readiness_item.label,
                    source_type=source_type,
                    severity=severity,
                    summary=_readiness_summary(readiness_item.observed_count, readiness_item.required_count),
                    source_trace=f"PreV2ReadinessReport.items.{readiness_item.item_id}",
                    degraded_reason=_reason_or_none(
                        (*readiness_item.blocking_reasons, *readiness_item.diagnostics, *readiness_item.next_actions),
                        readiness_item.status,
                    ),
                    drilldown_target="evidence_review",
                    queue_group=queue_group,
                    source_label="Pre-V2 準備度",
                    sort_rank=_action_sort_rank(severity, queue_group, source_type, len(items)),
                )
            )

        if historical_replay_summary:
            diagnostics = tuple(
                item
                for item in _replay_diagnostics(historical_replay_summary)
                if item.startswith(("source_gap:", "payload_gap:", "missing_", "pending_", "phase0_gate_not_satisfied:"))
            )
            if diagnostics:
                severity = "info"
                queue_group = "replay_diagnostics"
                source_type = "replay_summary"
                items.append(
                    WorkbenchActionItem(
                        item_id="replay_summary_manual_review",
                        title="Replay summary gap 人工判讀",
                        source_type=source_type,
                        severity=severity,
                        summary="Replay summary 只揭露 simulated evidence gap，不解除 Phase 0 gate。",
                        source_trace="HistoricalReplaySummary.quality_disclosures",
                        degraded_reason="; ".join(diagnostics),
                        drilldown_target="evidence_review",
                        queue_group=queue_group,
                        source_label="Replay summary",
                        sort_rank=_action_sort_rank(severity, queue_group, source_type, len(items)),
                    )
                )
        return tuple(sorted(items, key=lambda item: (item.sort_rank, item.item_id)))

    def _evidence_summary(
        self,
        readiness_report: PreV2ReadinessReport,
        scheduled_status: ScheduledEvidenceStatus | None,
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
        if scheduled_status is not None:
            items.append(
                WorkbenchEvidenceSummary(
                    item_id="scheduled_morning_pipeline",
                    label="每日排程觀測",
                    status=_scheduled_status_label(scheduled_status),
                    summary=_scheduled_status_summary(scheduled_status),
                    diagnostics=scheduled_status.diagnostics,
                )
            )
        if historical_replay_summary:
            totals = historical_replay_summary.get("totals", {})
            final = historical_replay_summary.get("final_outcome_summary", {})
            missing_benchmark = int(final.get("missing_benchmark", 0) or 0)
            missing_industry = int(final.get("missing_industry_benchmark", 0) or 0)
            benchmark_text = "市場 benchmark 已可用" if missing_benchmark == 0 else "市場 benchmark 有缺口"
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
                    label="歷史 replay 模擬證據",
                    status="degraded" if missing_industry else "ready",
                    summary=(
                        f"{totals.get('days', 0)} 天 / {totals.get('events_seen', 0)} events / "
                        f"{totals.get('outcomes_created', 0)} outcomes；{benchmark_text}；"
                        f"產業基準缺口 {missing_industry}。"
                    ),
                    diagnostics=tuple(diagnostics),
                )
            )
        return tuple(items)

    def _operating_loop_steps(
        self,
        *,
        review_items: tuple[WorkbenchReviewItem, ...],
        background_evidence_feed: tuple[WorkbenchEvidenceFeedItem, ...],
        action_items: tuple[WorkbenchActionItem, ...],
        daily_checklist: tuple[WorkbenchChecklistItem, ...],
        readiness_report: PreV2ReadinessReport,
    ) -> tuple[WorkbenchOperatingLoopStep, ...]:
        weekly_history = _find_readiness_item(readiness_report, "weekly_history")
        multi_day = _find_readiness_item(readiness_report, "multi_day_dry_run")
        manual_note = _find_checklist_item(daily_checklist, "manual_review_note")
        first_action_target = action_items[0].drilldown_target if action_items else "evidence_review"
        return (
            WorkbenchOperatingLoopStep(
                step_id="daily_start",
                label="每日先看",
                cadence="daily",
                status="manual_required" if review_items else "observed",
                summary=(
                    f"今天要看 {len(review_items)} 筆今日待判讀與 "
                    f"{len(background_evidence_feed)} 筆背景證據；只讀，不寫 DB。"
                ),
                source_trace="WorkbenchDashboardDTO.review_items",
                linked_item_ids=tuple(item.item_id for item in review_items),
                drilldown_target="daily_decision" if review_items else "evidence_review",
                guidance="先掃 status strip、今日待判讀、背景證據流與 warnings；不是買賣建議。",
            ),
            WorkbenchOperatingLoopStep(
                step_id="manual_queue",
                label="人工處理佇列",
                cadence="daily",
                status="manual_required" if action_items else "observed",
                summary=(
                    f"目前有 {len(action_items)} 筆 Action Items 要人工處理；"
                    "只依 source trace / degraded reason 覆盤，不標記完成。"
                ),
                source_trace="WorkbenchDashboardDTO.action_items",
                linked_item_ids=tuple(item.item_id for item in action_items),
                drilldown_target=first_action_target,
                guidance="依 severity、queue group 與 source label 掃描；Workbench 不建立 repository。",
            ),
            WorkbenchOperatingLoopStep(
                step_id="weekly_review_history",
                label="Weekly review history",
                cadence="weekly_until_3",
                status=weekly_history.status if weekly_history is not None else "missing",
                summary=_operating_loop_readiness_summary(weekly_history),
                source_trace="PreV2ReadinessReport.items.weekly_history",
                linked_item_ids=("weekly_history",),
                drilldown_target="evidence_review",
                guidance="每週 evidence operations + history 必須靠真實週期累積。",
            ),
            WorkbenchOperatingLoopStep(
                step_id="multi_day_dry_run",
                label="Multi-day dry-run",
                cadence="daily_until_3",
                status=multi_day.status if multi_day is not None else "missing",
                summary=_operating_loop_readiness_summary(multi_day),
                source_trace="PreV2ReadinessReport.items.multi_day_dry_run",
                linked_item_ids=("multi_day_dry_run",),
                drilldown_target="evidence_review",
                guidance="多日 dry-run 必須靠真實交易日紀錄累積；不執行 replay 補值。",
            ),
            WorkbenchOperatingLoopStep(
                step_id="manual_review_note",
                label="人工覆盤註記",
                cadence="after_manual_review",
                status=manual_note.status if manual_note is not None else "manual_required",
                summary=(
                    "人工覆盤後只提示到既有流程留下 note；"
                    "Workbench 不寫 DB、不標記完成、不套用 lifecycle。"
                ),
                source_trace="WorkbenchDashboardDTO.daily_checklist.manual_review_note",
                linked_item_ids=("manual_review_note",),
                drilldown_target="evidence_review",
                guidance="需要紀錄時下鑽到既有 Evidence Review / Daily Decision 流程人工處理。",
            ),
            WorkbenchOperatingLoopStep(
                step_id="scheduler_gate",
                label="Scheduler gate",
                cadence="phase_gate",
                status="blocked",
                summary="production_scheduler_allowed=false；Phase 0 / Phase 5 gate 前不啟用 scheduler。",
                source_trace="WorkbenchAccessBoundary.production_scheduler_allowed",
                linked_item_ids=("scheduler_off",),
                drilldown_target="evidence_review",
                guidance="這是 closeout guard，不是啟用排程或交易建議。",
            ),
        )

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
                label="決策快照新鮮度",
                status="done" if decision_snapshot is not None else "blocked",
                summary="已讀取 snapshot。" if decision_snapshot is not None else "缺 snapshot；不可從 UI state 補值。",
            ),
            WorkbenchChecklistItem(
                item_id="evidence_gate",
                label="證據門檻狀態",
                status=readiness_report.overall_status,
                summary=f"Pre-V2 readiness：{readiness_report.overall_status}",
            ),
            WorkbenchChecklistItem(
                item_id="multi_day_dry_run",
                label="多日 dry-run",
                status=_find_status(readiness_report, "multi_day_dry_run"),
                summary="真實多日 dry-run 仍需依記錄累積。",
            ),
            WorkbenchChecklistItem(
                item_id="manual_review_note",
                label="人工覆盤註記",
                status="manual_required",
                summary="Phase 1 prototype 不新增 append-only manual note repository。",
            ),
            WorkbenchChecklistItem(
                item_id="scheduler_off",
                label="排程器寫入模式",
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
        # 將 readiness 的具體 blocker/diagnostic 帶到首頁 warnings，避免
        # 使用者只看到「等待中」卻不知道缺哪一份證據或設定。
        for item in readiness_report.items:
            warnings.extend(
                f"{item.item_id}:{reason}"
                for reason in (*item.blocking_reasons, *item.diagnostics)
                if str(reason).strip()
            )
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


def portfolio_safe_count(count: int | None, codes: tuple[str, ...]) -> int:
    return int(count if count is not None else len(codes))


def _readiness_feed_summary(readiness_report: PreV2ReadinessReport) -> str:
    parts = [f"overall={readiness_report.overall_status}"]
    for item in readiness_report.items:
        if item.required_count is not None:
            parts.append(f"{item.item_id}={item.observed_count or 0}/{item.required_count}")
        else:
            parts.append(f"{item.item_id}={item.status}")
    return "；".join(parts) + "。"


def _readiness_reason(readiness_report: PreV2ReadinessReport) -> str:
    reasons = tuple(
        reason
        for item in readiness_report.items
        if item.status in {STATUS_ACTION_REQUIRED, STATUS_WAITING_FOR_TIME}
        for reason in (*item.blocking_reasons, *item.diagnostics)
    )
    return _reason_or_none(reasons, readiness_report.overall_status)


def _replay_diagnostics(historical_replay_summary: dict[str, Any]) -> list[str]:
    return _dedupe(
        [
            *(str(item) for item in historical_replay_summary.get("quality_disclosures", ())),
            *(str(item) for item in historical_replay_summary.get("warnings", ())),
            *(str(item) for item in historical_replay_summary.get("limitations", ())),
        ]
    )


def _reason_or_none(values: tuple[str, ...] | list[str] | set[str], fallback: str = "none") -> str:
    clean = tuple(str(item) for item in values if str(item))
    if clean:
        return "; ".join(clean)
    return fallback


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _find_status(readiness_report: PreV2ReadinessReport, item_id: str) -> str:
    for item in readiness_report.items:
        if item.item_id == item_id:
            return item.status
    return "missing"


def _find_readiness_item(readiness_report: PreV2ReadinessReport, item_id: str) -> PreV2ReadinessItem | None:
    for item in readiness_report.items:
        if item.item_id == item_id:
            return item
    return None


def _find_checklist_item(items: tuple[WorkbenchChecklistItem, ...], item_id: str) -> WorkbenchChecklistItem | None:
    for item in items:
        if item.item_id == item_id:
            return item
    return None


def _operating_loop_readiness_summary(item: PreV2ReadinessItem | None) -> str:
    if item is None:
        return "readiness item 缺漏；Workbench 不補值、不讀 DB。"
    return (
        f"{_readiness_summary(item.observed_count, item.required_count)}"
        "；必須靠真實時間累積，不能用 fixture、manual edit 或 replay 補齊。"
    )


def _scheduled_status_label(status: ScheduledEvidenceStatus) -> str:
    if status.has_production_write_risk:
        return "blocked"
    if status.recommendation_status == "passed" and status.evidence_status == "passed":
        return "passed"
    if "missing" in {status.recommendation_status, status.evidence_status}:
        return "missing"
    if "failed" in {status.recommendation_status, status.evidence_status}:
        return "warning"
    return "degraded"


def _scheduled_status_summary(status: ScheduledEvidenceStatus) -> str:
    result_id = status.recommendation_result_id or "尚未保存"
    rec_count = status.recommendations_count if status.recommendations_count is not None else "未知"
    recommendation_source = status.recommendation_source
    if status.recommendation_status == "manual_observed":
        recommendation_source = "manual_result（scheduled latest_status missing）"
    return (
        f"recommendation={status.recommendation_status} / evidence={status.evidence_status}；"
        f"source={recommendation_source}；result_id={result_id}；推薦 {rec_count} 筆；"
        f"共同觀測 {status.scheduled_joint_observed_days} 天"
        f"（recommendation {status.recommendation_snapshot_observed_days} 天 / "
        f"manual recommendation {status.manual_recommendation_observed_days} 天 / "
        f"evidence dry-run {status.evidence_dry_run_observed_days} 天）。"
    )


def _readiness_summary(observed_count: int | None, required_count: int | None) -> str:
    if observed_count is None and required_count is None:
        return "readiness item available."
    if required_count is None:
        return f"已觀測 {observed_count or 0} 筆。"
    return f"{observed_count or 0}/{required_count} records observed."


def _evidence_gate_status_summary(readiness_report: PreV2ReadinessReport) -> str:
    weekly = _find_readiness_item(readiness_report, "weekly_history")
    weekly_text = (
        _readiness_summary(weekly.observed_count, weekly.required_count)
        if weekly is not None
        else "weekly history readiness item missing"
    )
    if readiness_report.formal_credit_authorized:
        credit_text = "formal_credit_authorized=true"
    else:
        credit_text = (
            "formal_credit_authorized=false；目前只代表 read-only readiness，"
            "不授予 Formal evidence credit 或 production scheduler"
        )
    pending_text = _pending_weekly_review_summary(weekly)
    return f"{weekly_text}{pending_text}；{credit_text}。"


def _pending_weekly_review_summary(weekly: PreV2ReadinessItem | None) -> str:
    """Expose pending weekly periods without implying approval or Gate credit."""

    if weekly is None:
        return ""
    pending = weekly.evidence.get("pending_collection_periods")
    if not isinstance(pending, list):
        return ""
    period_labels: list[str] = []
    for item in pending:
        if not isinstance(item, Mapping):
            continue
        start = str(item.get("period_start") or "").strip()
        end = str(item.get("period_end") or "").strip()
        if start and end:
            period_labels.append(f"{start}→{end}")
    if not period_labels:
        return ""
    preview = ", ".join(period_labels[:3])
    if len(period_labels) > 3:
        preview += ", …"
    return f"；pending_human_review {len(period_labels)} 期（{preview}）"


def _status_to_severity(status: str) -> str:
    if status == STATUS_ACTION_REQUIRED:
        return "warning"
    if status == STATUS_WAITING_FOR_TIME:
        return "info"
    return _severity(status)


def _action_sort_rank(severity: str, queue_group: str, source_type: str, sequence: int) -> int:
    severity_order = {
        "critical": 0,
        "warning": 1,
        "degraded": 2,
        "missing": 3,
        "blocked": 4,
        "info": 5,
        "waiting_for_time": 6,
        "observed": 7,
        "ready": 8,
    }
    group_order = {
        "portfolio_review": 0,
        "daily_review": 1,
        "evidence_gate": 2,
        "replay_diagnostics": 3,
        "manual_review": 9,
    }
    source_order = {
        "portfolio_alert": 0,
        "risk_prompt": 1,
        "watchlist_trigger": 2,
        "pre_v2_readiness": 3,
        "replay_summary": 4,
    }
    return (
        severity_order.get(severity, 9) * 1000
        + group_order.get(queue_group, 9) * 100
        + source_order.get(source_type, 9) * 10
        + sequence
    )


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
