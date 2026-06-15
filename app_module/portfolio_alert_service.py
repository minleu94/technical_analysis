from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Protocol, Sequence

from app_module.decision_desk_dtos import DecisionDeskQuality, PortfolioAlertSummary


class PortfolioPositionProvider(Protocol):
    """Read-only interface for portfolio queries used by alerts."""

    def list_positions(self, portfolio_id: str = "default") -> Sequence[Any]: ...


class ConditionMonitorProtocol(Protocol):
    """Abstract protocol for evaluating whether a position condition remains valid."""

    def evaluate(self, position: Any, current_snapshot: Any | None = None) -> Any: ...


class ChipSummaryProviderProtocol(Protocol):
    """Interface for per-stock chip-summary lookups."""

    def get_stock_chip_summary(self, stock_code: str, period_days: int = 5) -> Mapping[str, Any] | Any: ...


@dataclass(frozen=True)
class _AlertItem:
    stock_code: str
    source_label: str
    severity: int
    reasons: tuple[str, ...]


class PortfolioAlertService:
    """Aggregate portfolio position status into a decision-desk alert summary."""

    def __init__(
        self,
        portfolio_service: PortfolioPositionProvider,
        condition_monitor: ConditionMonitorProtocol,
        chip_summary_provider: ChipSummaryProviderProtocol | None = None,
        *,
        portfolio_id: str = "default",
        chip_lookback_days: int = 5,
    ) -> None:
        self.portfolio_service = portfolio_service
        self.condition_monitor = condition_monitor
        self.chip_summary_provider = chip_summary_provider
        self.portfolio_id = portfolio_id
        self.chip_lookback_days = chip_lookback_days

    def build_snapshot(self, as_of_date: date) -> PortfolioAlertSummary:
        warnings: list[str] = []
        warnings_for_quality: list[str] = []
        try:
            positions = list(self.portfolio_service.list_positions(self.portfolio_id))
        except Exception as exc:  # noqa: BLE001
            return PortfolioAlertSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.DEGRADED,
                warnings=(f"portfolio_alerts_portfolio_service_error:{exc}",),
                alert_count=0,
                alert_codes=(),
                alert_level="high",
            )

        if not positions:
            return PortfolioAlertSummary(
                as_of_date=as_of_date,
                quality=DecisionDeskQuality.MISSING,
                warnings=("portfolio_alerts_no_active_position",),
                alert_count=0,
                alert_codes=(),
                alert_level="low",
            )

        alerts, hard_failures = self._collect_alerts(positions, warnings_for_quality)
        source_summary = self._build_source_summary(alerts)
        if source_summary:
            warnings.extend(source_summary)
        warnings.extend(warnings_for_quality)

        if not alerts:
            quality = (
                DecisionDeskQuality.DEGRADED
                if hard_failures > 0
                else DecisionDeskQuality.ESTIMATED if warnings_for_quality else DecisionDeskQuality.OBSERVED
            )
            return PortfolioAlertSummary(
                as_of_date=as_of_date,
                quality=quality,
                warnings=tuple(warnings),
                alert_count=0,
                alert_codes=(),
                alert_level="low",
            )

        return PortfolioAlertSummary(
            as_of_date=as_of_date,
            quality=(
                DecisionDeskQuality.DEGRADED
                if hard_failures > 0
                else DecisionDeskQuality.ESTIMATED if warnings_for_quality else DecisionDeskQuality.OBSERVED
            ),
            warnings=tuple(warnings),
            alert_count=len(alerts),
            alert_codes=self._top_alert_codes(alerts),
            alert_level=self._infer_alert_level(alerts),
        )

    def _collect_alerts(
        self,
        positions: Iterable[Any],
        warnings: list[str],
    ) -> tuple[list[_AlertItem], int]:
        items: list[_AlertItem] = []
        hard_failures = 0
        for index, position in enumerate(positions):
            stock_code = self._read_stock_code(position, index)
            source_label = self._read_position_source_label(position)

            try:
                condition_result = self.condition_monitor.evaluate(position)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"portfolio_alerts_condition_monitor_error:{stock_code}:{exc}")
                hard_failures += 1
                continue

            status = str(getattr(condition_result, "status", "")).lower()
            reasons: list[str] = []

            if status in ("invalid", "warning"):
                reasons.append(f"condition:{status}")
            status_severity = self._status_severity(status)

            chip_risk_severity = self._chip_risk_severity(stock_code, warnings)
            if chip_risk_severity > 0:
                reasons.append("chip_alert")

            if status_severity > 0 or chip_risk_severity > 0:
                severity = max(status_severity, chip_risk_severity)
                items.append(
                    _AlertItem(
                        stock_code=stock_code,
                        source_label=source_label,
                        severity=severity,
                        reasons=tuple(reasons),
                    )
                )

        return items, hard_failures

    def _chip_risk_severity(self, stock_code: str, warnings: list[str]) -> int:
        provider = self.chip_summary_provider
        if provider is None:
            return 0
        try:
            summary = provider.get_stock_chip_summary(stock_code, period_days=self.chip_lookback_days)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"portfolio_alerts_chip_provider_error:{stock_code}:{exc}")
            return 1

        if not isinstance(summary, Mapping):
            return 0

        risk_level = str(summary.get("risk_level", "")).lower().strip()
        if risk_level in {"bearish", "extreme", "risk"}:
            return 80
        return 0

    def _status_severity(self, status: str) -> int:
        if status == "invalid":
            return 100
        if status == "warning":
            return 70
        return 0

    def _build_source_summary(self, alerts: list[_AlertItem]) -> list[str]:
        if not alerts:
            return []
        counter = Counter(item.source_label for item in alerts if item.source_label)
        if not counter:
            return []
        top_source, top_count = counter.most_common(1)[0]
        return [f"portfolio_alert_top_source:{top_source}:{top_count}"]

    def _top_alert_codes(self, alerts: list[_AlertItem]) -> tuple[str, ...]:
        sorted_alerts = sorted(alerts, key=lambda item: (-item.severity, item.stock_code))
        return tuple(item.stock_code for item in sorted_alerts)

    def _infer_alert_level(self, alerts: list[_AlertItem]) -> str:
        highest = max(item.severity for item in alerts)
        if highest >= 100:
            return "high"
        if highest >= 80:
            return "high"
        if highest >= 70:
            return "medium"
        return "low"

    def _read_stock_code(self, position: Any, fallback_index: int) -> str:
        stock_code = str(getattr(position, "stock_code", "")).strip()
        return stock_code if stock_code else f"unknown_{fallback_index}"

    def _read_position_source_label(self, position: Any) -> str:
        source_type = str(getattr(position, "source_type", "")).strip()
        source_id = str(getattr(position, "source_id", "")).strip()
        if source_type and source_id:
            return f"{source_type}:{source_id}"
        if source_type:
            return source_type
        return "manual"
