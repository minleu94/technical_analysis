from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any


class DecisionDeskQuality(str, Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    DEGRADED = "degraded"
    MISSING = "missing"


def _normalize_warnings(warnings: tuple[str, ...] | list[str] | set[str] | None) -> tuple[str, ...]:
    if warnings is None:
        return ()
    normalized: list[str] = []
    for item in warnings:
        normalized.append(str(item))
    return tuple(normalized)


def _as_dict(value: Any) -> Any:
    if isinstance(value, (DecisionDeskQuality,)):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [item for item in value]
    if isinstance(value, dict):
        return {key: _as_dict(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class DecisionDeskSectionStatus:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.quality is None:
            raise ValueError("quality must not be None")
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class MarketRegimeSummary:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...]
    regime_label: str | None = None
    regime_score: int | None = None
    regime_confidence: int | None = None
    meta: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
            "regime_label": self.regime_label,
            "regime_score": self.regime_score,
            "regime_confidence": self.regime_confidence,
            "meta": _as_dict(self.meta) if self.meta is not None else None,
        }


@dataclass(frozen=True)
class MarketBreadthSummary:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...]
    breadth_ratio_bp: int | None = None
    advancing: int | None = None
    declining: int | None = None
    unchanged: int | None = None
    meta: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
            "breadth_ratio_bp": self.breadth_ratio_bp,
            "advancing": self.advancing,
            "declining": self.declining,
            "unchanged": self.unchanged,
            "meta": _as_dict(self.meta) if self.meta is not None else None,
        }


@dataclass(frozen=True)
class SectorRotationSummary:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...]
    leading_sector: str | None = None
    trailing_sector: str | None = None
    rotation_intensity_bp: int | None = None
    meta: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
            "leading_sector": self.leading_sector,
            "trailing_sector": self.trailing_sector,
            "rotation_intensity_bp": self.rotation_intensity_bp,
            "meta": _as_dict(self.meta) if self.meta is not None else None,
        }


@dataclass(frozen=True)
class WatchlistTriggerSummary:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...]
    trigger_count: int | None = None
    triggered_codes: tuple[str, ...] = ()
    top_signal: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))
        object.__setattr__(self, "triggered_codes", tuple(str(code) for code in self.triggered_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
            "trigger_count": self.trigger_count,
            "triggered_codes": list(self.triggered_codes),
            "top_signal": self.top_signal,
        }


@dataclass(frozen=True)
class PortfolioAlertSummary:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...]
    alert_count: int | None = None
    alert_codes: tuple[str, ...] = ()
    alert_level: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))
        object.__setattr__(self, "alert_codes", tuple(str(code) for code in self.alert_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
            "alert_count": self.alert_count,
            "alert_codes": list(self.alert_codes),
            "alert_level": self.alert_level,
        }


@dataclass(frozen=True)
class DecisionDeskSnapshot:
    as_of_date: date
    generated_at: datetime
    schema_version: int
    overall_quality: DecisionDeskQuality
    market_regime: MarketRegimeSummary
    market_breadth: MarketBreadthSummary
    sector_rotation: SectorRotationSummary
    watchlist_triggers: WatchlistTriggerSummary
    portfolio_alerts: PortfolioAlertSummary
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if self.market_regime is None or self.market_breadth is None or self.sector_rotation is None:
            raise ValueError("all decision sections must be provided")
        if self.watchlist_triggers is None or self.portfolio_alerts is None:
            raise ValueError("all decision sections must be provided")
        if self.warnings is None:
            raise ValueError("warnings must not be None")
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "as_of_date": self.as_of_date.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "overall_quality": self.overall_quality.value,
            "warnings": list(self.warnings),
            "market_regime": self.market_regime.to_dict(),
            "market_breadth": self.market_breadth.to_dict(),
            "sector_rotation": self.sector_rotation.to_dict(),
            "watchlist_triggers": self.watchlist_triggers.to_dict(),
            "portfolio_alerts": self.portfolio_alerts.to_dict(),
        }
