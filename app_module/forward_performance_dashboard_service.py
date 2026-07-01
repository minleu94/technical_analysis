from __future__ import annotations

from collections import Counter
from pathlib import Path
import sqlite3
from typing import Any

from app_module.evidence_event_dtos import EvidenceEvent, EvidenceOutcome, normalize_event_type
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.forward_performance_dashboard_dtos import (
    ForwardPerformanceDashboardCardSummary,
    ForwardPerformanceDashboardRequest,
    ForwardPerformanceDashboardResult,
    ForwardPerformanceDashboardRow,
)
from app_module.forward_performance_read_model import (
    ForwardPerformanceFilter,
    ForwardPerformanceGroupSummary,
    ForwardPerformanceReadModel,
    SUMMARY_STATUS_DEGRADED,
    SUMMARY_STATUS_INSUFFICIENT_SAMPLE,
    SUMMARY_STATUS_MISSING_BENCHMARK,
    SUMMARY_STATUS_MISSING_INDUSTRY,
    SUMMARY_STATUS_READY,
)


RESEARCH_LIMITATIONS = (
    "這是 research evidence，不是買賣建議。",
    "close-to-close forward return 不代表實盤可執行績效。",
    "樣本不足、benchmark 缺失、industry 缺失與 data quality degraded 必須人工判讀。",
)


class ForwardPerformanceDashboardService:
    """Read-only application service for the Forward Performance dashboard."""

    def __init__(self, read_model: ForwardPerformanceReadModel) -> None:
        self.read_model = read_model

    def load_dashboard(self, request: ForwardPerformanceDashboardRequest) -> ForwardPerformanceDashboardResult:
        filters = ForwardPerformanceFilter(
            start_date=_blank_to_none(request.start_date),
            end_date=_blank_to_none(request.end_date),
            event_type=_blank_to_none(request.event_type),
            event_family=_blank_to_none(request.event_family),
            source_type=_blank_to_none(request.source_type),
            symbol=_blank_to_none(request.symbol),
            regime=_blank_to_none(request.regime),
            sector=_blank_to_none(request.sector),
            profile_id=_blank_to_none(request.profile_id),
            strategy_version_id=_blank_to_none(request.strategy_version_id),
            window_days=int(request.window_days),
        )
        try:
            summaries = self.read_model.summarize(
                group_by=request.group_by,
                filters=filters,
                min_sample_size=int(request.min_sample_size),
            )
            diagnostics: tuple[str, ...] = ()
        except (FileNotFoundError, sqlite3.Error) as exc:
            summaries = []
            diagnostics = (f"evidence_store_unavailable:{exc}",)

        rows = tuple(_row_from_summary(summary) for summary in summaries)
        return ForwardPerformanceDashboardResult(
            request=request,
            cards=_build_cards(rows),
            rows=rows,
            empty_state_message=_empty_state_message(rows),
            limitations=RESEARCH_LIMITATIONS,
            diagnostics=diagnostics,
        )


def create_forward_performance_dashboard_service(config: Any) -> ForwardPerformanceDashboardService:
    repository = ReadOnlyEvidenceEventRepository(config)
    return ForwardPerformanceDashboardService(ForwardPerformanceReadModel(repository))


class ReadOnlyEvidenceEventRepository(EvidenceEventRepository):
    """Evidence repository variant that opens SQLite in read-only mode."""

    def __init__(self, config: Any, *, db_path: str | Path | None = None) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)

    def ensure_schema(self) -> None:
        return None

    def list_events(
        self,
        *,
        symbol: str | None = None,
        event_type: Any | None = None,
        decision_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> list[EvidenceEvent]:
        where: list[str] = []
        params: list[Any] = []
        if symbol is not None:
            where.append("symbol = ?")
            params.append(symbol)
        if event_type is not None:
            where.append("event_type = ?")
            params.append(normalize_event_type(event_type).value)
        if decision_date is not None:
            where.append("decision_date = ?")
            params.append(decision_date)
        if start_date is not None:
            where.append("decision_date >= ?")
            params.append(start_date)
        if end_date is not None:
            where.append("decision_date <= ?")
            params.append(end_date)
        sql = "SELECT * FROM evidence_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY decision_date ASC, event_id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))

        with self._connect_read_only() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_event(dict(row)) for row in rows]

    def list_outcomes(
        self,
        *,
        event_id: str | None = None,
        window_days: int | None = None,
    ) -> list[EvidenceOutcome]:
        where: list[str] = []
        params: list[Any] = []
        if event_id is not None:
            where.append("event_id = ?")
            params.append(event_id)
        if window_days is not None:
            where.append("window_days = ?")
            params.append(int(window_days))
        sql = "SELECT * FROM evidence_outcomes"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY event_id ASC, window_days ASC"
        with self._connect_read_only() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_outcome(dict(row)) for row in rows]

    def _connect_read_only(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(str(self.db_path))
        uri_path = self.db_path.resolve().as_posix()
        return sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)


def _row_from_summary(summary: ForwardPerformanceGroupSummary) -> ForwardPerformanceDashboardRow:
    return ForwardPerformanceDashboardRow(
        group_by=summary.group_by,
        group_key=summary.group_key,
        window_days=summary.window_days,
        sample_size=summary.sample_size,
        pending_count=summary.pending_count,
        missing_count=summary.missing_count,
        mean_forward_return_bp=summary.mean_forward_return_bp,
        median_forward_return_bp=summary.median_forward_return_bp,
        mean_benchmark_excess_bp=summary.mean_benchmark_excess_bp,
        median_benchmark_excess_bp=summary.median_benchmark_excess_bp,
        mean_industry_excess_bp=summary.mean_industry_excess_bp,
        median_industry_excess_bp=summary.median_industry_excess_bp,
        positive_rate_bp=summary.positive_rate_bp,
        win_vs_benchmark_rate_bp=summary.win_vs_benchmark_rate_bp,
        win_vs_industry_rate_bp=summary.win_vs_industry_rate_bp,
        mean_mae_bp=summary.mean_mae_bp,
        mean_mfe_bp=summary.mean_mfe_bp,
        summary_status=summary.summary_status,
        first_event_date=summary.first_event_date,
        last_event_date=summary.last_event_date,
        quality_counts=dict(summary.quality_counts),
        warning_counts=dict(summary.warning_counts),
    )


def _build_cards(rows: tuple[ForwardPerformanceDashboardRow, ...]) -> ForwardPerformanceDashboardCardSummary:
    statuses = Counter(row.summary_status for row in rows)
    warnings: Counter[str] = Counter()
    for row in rows:
        warnings.update(row.warning_counts)

    return ForwardPerformanceDashboardCardSummary(
        total_events=sum(row.sample_size + row.pending_count + row.missing_count for row in rows),
        ready_outcomes=sum(row.sample_size for row in rows),
        pending_outcomes=sum(row.pending_count for row in rows),
        missing_outcomes=sum(row.missing_count for row in rows),
        groups_ready=statuses[SUMMARY_STATUS_READY],
        groups_insufficient_sample=statuses[SUMMARY_STATUS_INSUFFICIENT_SAMPLE],
        groups_degraded=(
            statuses[SUMMARY_STATUS_DEGRADED]
            + statuses[SUMMARY_STATUS_MISSING_BENCHMARK]
            + statuses[SUMMARY_STATUS_MISSING_INDUSTRY]
        ),
        missing_benchmark_count=_warning_count(warnings, ("missing_benchmark", "missing_benchmark_return")),
        missing_industry_count=_warning_count(
            warnings,
            ("missing_industry_benchmark", "missing_industry_return"),
        ),
        warnings_count=sum(warnings.values()),
    )


def _empty_state_message(rows: tuple[ForwardPerformanceDashboardRow, ...]) -> str:
    if not rows:
        return "尚無足夠 forward evidence。請先 capture evidence events 並 calculate forward outcomes。"
    if any(row.summary_status == SUMMARY_STATUS_MISSING_BENCHMARK for row in rows):
        return "Benchmark 缺失，無法判斷相對大盤超額。"
    if any(row.summary_status == SUMMARY_STATUS_MISSING_INDUSTRY for row in rows):
        return "Industry benchmark 缺失，無法判斷相對同產業超額。"
    if any(row.summary_status == SUMMARY_STATUS_INSUFFICIENT_SAMPLE for row in rows):
        return "樣本不足，只能作資料品質檢查，不可作訊號有效性判斷。"
    return ""


def _warning_count(warnings: Counter[str], names: tuple[str, ...]) -> int:
    return sum(warnings[name] for name in names)


def _blank_to_none(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def format_bp_as_percent(value: int | None) -> str:
    if value is None:
        return "N/A"
    return f"{int(value) / 100:.2f}%"
