"""Month 6 Portfolio feedback attribution service.

此服務只讀 Portfolio position DTO、來源快照與既有 condition/drift 結果，
把 live position 與 research thesis 的落差拆成可追溯原因。它不下單、
不改持倉、不寫資料，也不重新跑推薦或回測。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Sequence

from app_module.dtos.portfolio_dtos import PositionDTO
from app_module.strategy_lifecycle_service import GateStatus, StrategyDriftReport


class FeedbackCategory(str, Enum):
    SOURCE = "source"
    EXECUTION = "execution"
    SIGNAL = "signal"
    MARKET = "market"
    DATA_QUALITY = "data_quality"


@dataclass(frozen=True)
class PortfolioAttributionItem:
    stock_code: str
    category: FeedbackCategory
    status: GateStatus
    severity: int
    reason: str
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PositionFeedbackReport:
    stock_code: str
    source_label: str
    thesis_status: GateStatus
    items: tuple[PortfolioAttributionItem, ...]
    summary_tokens: tuple[str, ...]


@dataclass(frozen=True)
class LiveResearchGapReport:
    portfolio_id: str
    total_positions: int
    invalid_count: int
    warning_count: int
    observed_count: int
    reports: tuple[PositionFeedbackReport, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PortfolioFeedbackPolicy:
    max_entry_price_gap_bp: int = 500
    warning_entry_price_gap_bp: int = 300


class PortfolioFeedbackService:
    """Build post-trade attribution from already-governed evidence."""

    def __init__(self, policy: PortfolioFeedbackPolicy | None = None) -> None:
        self.policy = policy or PortfolioFeedbackPolicy()

    def build_position_feedback(
        self,
        position: PositionDTO,
        *,
        condition_result: Any | None = None,
        drift_report: StrategyDriftReport | None = None,
    ) -> PositionFeedbackReport:
        items: list[PortfolioAttributionItem] = []
        source_summary = dict(position.source_summary or {})
        source_label = self._source_label(position)

        items.append(self._source_item(position, source_summary))
        execution_item = self._execution_item(position, source_summary)
        if execution_item is not None:
            items.append(execution_item)
        if condition_result is not None:
            items.extend(self._condition_items(position, condition_result))
        if drift_report is not None:
            items.extend(self._drift_items(position, drift_report))
        data_item = self._data_quality_item(position, source_summary)
        if data_item is not None:
            items.append(data_item)

        thesis_status = self._infer_thesis_status(items)
        return PositionFeedbackReport(
            stock_code=position.stock_code,
            source_label=source_label,
            thesis_status=thesis_status,
            items=tuple(items),
            summary_tokens=self._summary_tokens(items),
        )

    def build_live_research_gap_report(
        self,
        positions: Sequence[PositionDTO],
        *,
        condition_results: Mapping[str, Any] | None = None,
        drift_reports: Mapping[str, StrategyDriftReport] | None = None,
        portfolio_id: str = "default",
    ) -> LiveResearchGapReport:
        condition_results = condition_results or {}
        drift_reports = drift_reports or {}
        reports = tuple(
            self.build_position_feedback(
                position,
                condition_result=condition_results.get(position.stock_code),
                drift_report=drift_reports.get(position.stock_code),
            )
            for position in positions
        )
        invalid_count = sum(1 for report in reports if report.thesis_status == GateStatus.FAIL)
        warning_count = sum(1 for report in reports if report.thesis_status == GateStatus.DEGRADED)
        observed_count = sum(1 for report in reports if report.thesis_status == GateStatus.PASS)
        warnings = tuple(
            f"portfolio_feedback_position_warning:{report.stock_code}"
            for report in reports
            if report.thesis_status != GateStatus.PASS
        )
        return LiveResearchGapReport(
            portfolio_id=portfolio_id,
            total_positions=len(positions),
            invalid_count=invalid_count,
            warning_count=warning_count,
            observed_count=observed_count,
            reports=reports,
            warnings=warnings,
        )

    def _source_item(
        self,
        position: PositionDTO,
        source_summary: Mapping[str, Any],
    ) -> PortfolioAttributionItem:
        if position.source_type and position.source_id and source_summary:
            return PortfolioAttributionItem(
                position.stock_code,
                FeedbackCategory.SOURCE,
                GateStatus.PASS,
                0,
                "position source trace is available",
                {
                    "source_type": position.source_type,
                    "source_id": position.source_id,
                },
            )
        return PortfolioAttributionItem(
            position.stock_code,
            FeedbackCategory.SOURCE,
            GateStatus.DEGRADED,
            50,
            "position source trace is incomplete",
            {
                "source_type": position.source_type,
                "source_id": position.source_id,
                "source_summary_available": bool(source_summary),
            },
        )

    def _execution_item(
        self,
        position: PositionDTO,
        source_summary: Mapping[str, Any],
    ) -> PortfolioAttributionItem | None:
        expected_price = self._first_decimal(
            source_summary,
            "price",
            "close_price",
            "entry_price",
        )
        actual_price = self._to_decimal(position.average_cost)
        if expected_price is None or expected_price <= 0 or actual_price is None:
            return None

        gap_bp = int(((actual_price - expected_price) / expected_price * Decimal("10000")).to_integral_value())
        abs_gap_bp = abs(gap_bp)
        if abs_gap_bp >= self.policy.max_entry_price_gap_bp:
            status = GateStatus.FAIL
            severity = 90
            reason = "entry price gap exceeds execution gate"
        elif abs_gap_bp >= self.policy.warning_entry_price_gap_bp:
            status = GateStatus.DEGRADED
            severity = 60
            reason = "entry price gap requires review"
        else:
            status = GateStatus.PASS
            severity = 0
            reason = "entry price gap is within policy"

        return PortfolioAttributionItem(
            position.stock_code,
            FeedbackCategory.EXECUTION,
            status,
            severity,
            reason,
            {
                "expected_price": self._format_decimal(expected_price),
                "actual_average_cost": self._format_decimal(actual_price),
                "gap_bp": gap_bp,
            },
        )

    def _condition_items(
        self,
        position: PositionDTO,
        condition_result: Any,
    ) -> list[PortfolioAttributionItem]:
        status_text = str(getattr(condition_result, "status", "")).lower()
        if status_text == "invalid":
            gate_status = GateStatus.FAIL
            severity = 100
        elif status_text == "warning":
            gate_status = GateStatus.DEGRADED
            severity = 70
        else:
            gate_status = GateStatus.PASS
            severity = 0

        items = [
            PortfolioAttributionItem(
                position.stock_code,
                FeedbackCategory.SIGNAL,
                gate_status,
                severity,
                f"condition monitor status:{status_text or 'unknown'}",
                {
                    "condition_status": status_text,
                    "reasons": tuple(getattr(condition_result, "reasons", []) or ()),
                },
            )
        ]
        entry_regime = str(getattr(condition_result, "entry_regime", "") or "")
        current_regime = str(getattr(condition_result, "current_regime", "") or "")
        if entry_regime and current_regime:
            changed = entry_regime != current_regime
            items.append(
                PortfolioAttributionItem(
                    position.stock_code,
                    FeedbackCategory.MARKET,
                    GateStatus.DEGRADED if changed else GateStatus.PASS,
                    60 if changed else 0,
                    "regime changed since entry" if changed else "regime remains compatible",
                    {
                        "entry_regime": entry_regime,
                        "current_regime": current_regime,
                    },
                )
            )
        return items

    def _drift_items(
        self,
        position: PositionDTO,
        drift_report: StrategyDriftReport,
    ) -> list[PortfolioAttributionItem]:
        if drift_report.status == GateStatus.PASS:
            return [
                PortfolioAttributionItem(
                    position.stock_code,
                    FeedbackCategory.SIGNAL,
                    GateStatus.PASS,
                    0,
                    "strategy drift gate passed",
                    {"current_run_id": drift_report.current_run_id},
                )
            ]
        return [
            PortfolioAttributionItem(
                position.stock_code,
                FeedbackCategory.SIGNAL,
                GateStatus.FAIL,
                95,
                "strategy drift detected",
                {
                    "baseline_run_id": drift_report.baseline_run_id,
                    "current_run_id": drift_report.current_run_id,
                    "drift_reasons": drift_report.drift_reasons,
                },
            )
        ]

    def _data_quality_item(
        self,
        position: PositionDTO,
        source_summary: Mapping[str, Any],
    ) -> PortfolioAttributionItem | None:
        flags: list[str] = []
        if not position.source_snapshot_hash:
            flags.append("source_snapshot_hash_missing")
        quality = str(source_summary.get("quality") or source_summary.get("data_quality") or "").lower()
        if quality in {"missing", "degraded", "estimated", "unavailable"}:
            flags.append(f"source_quality:{quality}")
        if not flags:
            return None
        return PortfolioAttributionItem(
            position.stock_code,
            FeedbackCategory.DATA_QUALITY,
            GateStatus.DEGRADED,
            40,
            "source data quality requires review",
            {"flags": tuple(flags)},
        )

    def _infer_thesis_status(self, items: Sequence[PortfolioAttributionItem]) -> GateStatus:
        if any(item.status == GateStatus.FAIL for item in items):
            return GateStatus.FAIL
        if any(item.status == GateStatus.DEGRADED for item in items):
            return GateStatus.DEGRADED
        return GateStatus.PASS

    def _summary_tokens(self, items: Sequence[PortfolioAttributionItem]) -> tuple[str, ...]:
        return tuple(
            f"{item.category.value}:{item.status.value}"
            for item in sorted(items, key=lambda item: (item.category.value, -item.severity))
        )

    def _source_label(self, position: PositionDTO) -> str:
        if position.source_type and position.source_id:
            return f"{position.source_type}:{position.source_id}"
        if position.source_type:
            return position.source_type
        return "manual"

    def _first_decimal(self, source: Mapping[str, Any], *keys: str) -> Decimal | None:
        for key in keys:
            if key in source:
                parsed = self._to_decimal(source.get(key))
                if parsed is not None:
                    return parsed
        return None

    def _to_decimal(self, value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    def _format_decimal(self, value: Decimal) -> str:
        return format(value.quantize(Decimal("0.01")), "f")
