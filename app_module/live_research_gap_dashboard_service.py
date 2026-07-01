from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from app_module.live_research_gap_dashboard_dtos import (
    LiveResearchGapDashboardCards,
    LiveResearchGapDashboardRequest,
    LiveResearchGapDashboardResult,
    LiveResearchGapDashboardRow,
)
from app_module.live_research_gap_service import LiveResearchGapService


LIVE_RESEARCH_GAP_LIMITATIONS = (
    "Live vs Research Gap Dashboard 只呈現 research / simulated gap evidence，不代表可執行績效。",
    "source trace、research run 與 evidence outcome 缺口需要人工判讀。",
    "portfolio return 與 forward evidence return 的差異不可直接解讀成策略有效或失效。",
)


class LiveResearchGapDashboardService:
    """Read-only dashboard adapter over saved live research gap observations."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    def load_dashboard(self, request: LiveResearchGapDashboardRequest) -> LiveResearchGapDashboardResult:
        rows = tuple(
            _row_from_observation(row)
            for row in self.backend.list_gap_observations(
                observation_date=_blank_to_none(request.observation_date),
                symbol=_blank_to_none(request.symbol),
                source_type=_blank_to_none(request.source_type),
                strategy_version_id=_blank_to_none(request.strategy_version_id),
            )
            if _observation_matches(row, request)
        )
        return LiveResearchGapDashboardResult(
            request=request,
            cards=_build_cards(rows),
            rows=rows,
            empty_state_message=_empty_state_message(rows),
            limitations=LIVE_RESEARCH_GAP_LIMITATIONS,
            quality_counts=dict(Counter(row.quality for row in rows)),
            warning_counts=_warning_counts(rows),
        )


def create_live_research_gap_dashboard_service(
    config: Any,
    *,
    db_path: str | Path | None = None,
) -> LiveResearchGapDashboardService:
    return LiveResearchGapDashboardService(LiveResearchGapService(config))


def _row_from_observation(row: Any) -> LiveResearchGapDashboardRow:
    attribution_categories = tuple(
        str(item.get("category"))
        for item in row.attribution_json
        if isinstance(item, dict) and item.get("category")
    )
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    return LiveResearchGapDashboardRow(
        symbol=str(row.symbol or ""),
        portfolio_mode=str(row.portfolio_mode or ""),
        source_type=str(row.source_type or ""),
        source_id=str(row.source_id or ""),
        strategy_version_id=str(row.strategy_version_id or ""),
        entry_date=str(row.entry_date or ""),
        holding_days=row.holding_days,
        portfolio_return_bp=row.portfolio_return_bp,
        forward_evidence_return_bp=row.forward_evidence_return_bp,
        benchmark_excess_bp=row.benchmark_excess_bp,
        gap_vs_research_bp=row.gap_vs_research_bp,
        gap_vs_forward_evidence_bp=row.gap_vs_forward_evidence_bp,
        gap_vs_benchmark_bp=row.gap_vs_benchmark_bp,
        condition_status=str(row.condition_status or ""),
        chip_risk_level=str(row.chip_risk_level or ""),
        regime_at_entry=str(row.regime_at_entry or ""),
        regime_current=str(row.regime_current or ""),
        attribution_categories=attribution_categories,
        match_confidence=str(metadata.get("match_confidence") or "none"),
        quality=str(row.data_quality or "missing"),
        warnings=tuple(str(value) for value in row.warnings_json),
        evidence_event_id=str(row.evidence_event_id or ""),
        evidence_outcome_id=str(row.evidence_outcome_id or ""),
        research_run_id=str(row.research_run_id or ""),
    )


def _observation_matches(row: Any, request: LiveResearchGapDashboardRequest) -> bool:
    categories = {
        str(item.get("category"))
        for item in row.attribution_json
        if isinstance(item, dict) and item.get("category")
    }
    return all(
        (
            _matches(row.portfolio_mode, request.portfolio_mode),
            _matches(row.data_quality, request.data_quality),
            _blank_to_none(request.attribution_category) is None
            or str(request.attribution_category) in categories,
        )
    )


def _build_cards(rows: tuple[LiveResearchGapDashboardRow, ...]) -> LiveResearchGapDashboardCards:
    return LiveResearchGapDashboardCards(
        positions_seen=len(rows),
        positions_linked=sum(1 for row in rows if row.evidence_event_id and row.evidence_outcome_id),
        missing_source_trace=sum(1 for row in rows if not row.source_type or not row.source_id),
        missing_research_run=sum(1 for row in rows if not row.research_run_id),
        missing_evidence_event=sum(1 for row in rows if not row.evidence_event_id),
        missing_evidence_outcome=sum(1 for row in rows if not row.evidence_outcome_id),
        simulated_count=sum(1 for row in rows if row.portfolio_mode == "simulated"),
        unknown_count=sum(1 for row in rows if row.portfolio_mode == "unknown"),
        large_gap_count=sum(
            1
            for row in rows
            if row.gap_vs_forward_evidence_bp is not None and abs(int(row.gap_vs_forward_evidence_bp)) >= 1000
        ),
        warnings_count=sum(len(row.warnings) for row in rows),
    )


def _empty_state_message(rows: tuple[LiveResearchGapDashboardRow, ...]) -> str:
    if not rows:
        return "尚無 live research gap evidence。請先以 dry-run 建立 observation。"
    if any(not row.source_type or not row.source_id for row in rows):
        return "缺 source trace，無法可靠連結 portfolio 狀態與 research evidence。"
    if any(not row.evidence_event_id or not row.evidence_outcome_id for row in rows):
        return "缺 evidence event 或 outcome，無法判讀 gap 來源。"
    return ""


def _warning_counts(rows: tuple[LiveResearchGapDashboardRow, ...]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(row.warnings)
    return dict(counter)


def _matches(actual: str | None, expected: str | None) -> bool:
    expected_text = _blank_to_none(expected)
    return expected_text is None or str(actual or "") == expected_text


def _blank_to_none(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None
