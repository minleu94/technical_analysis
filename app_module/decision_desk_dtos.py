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
class RelativeStrengthLiquiditySummary:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...]
    top_strength_codes: tuple[str, ...] = ()
    weak_strength_codes: tuple[str, ...] = ()
    low_liquidity_codes: tuple[str, ...] = ()
    meta: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))
        object.__setattr__(self, "top_strength_codes", tuple(str(code) for code in self.top_strength_codes))
        object.__setattr__(self, "weak_strength_codes", tuple(str(code) for code in self.weak_strength_codes))
        object.__setattr__(self, "low_liquidity_codes", tuple(str(code) for code in self.low_liquidity_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
            "top_strength_codes": list(self.top_strength_codes),
            "weak_strength_codes": list(self.weak_strength_codes),
            "low_liquidity_codes": list(self.low_liquidity_codes),
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
class PortfolioAlertAttribution:
    stock_code: str
    source_label: str
    condition_status: str
    chip_risk_level: str
    severity: int
    reasons: tuple[str, ...] = ()
    data_quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock_code", str(self.stock_code))
        object.__setattr__(self, "source_label", str(self.source_label))
        object.__setattr__(self, "condition_status", str(self.condition_status))
        object.__setattr__(self, "chip_risk_level", str(self.chip_risk_level))
        object.__setattr__(self, "severity", int(self.severity))
        object.__setattr__(self, "reasons", tuple(str(item) for item in self.reasons))
        object.__setattr__(self, "data_quality_flags", tuple(str(item) for item in self.data_quality_flags))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "source_label": self.source_label,
            "condition_status": self.condition_status,
            "chip_risk_level": self.chip_risk_level,
            "severity": self.severity,
            "reasons": list(self.reasons),
            "data_quality_flags": list(self.data_quality_flags),
        }


@dataclass(frozen=True)
class PortfolioAlertSummary:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...]
    alert_count: int | None = None
    alert_codes: tuple[str, ...] = ()
    alert_level: str | None = None
    attributions: tuple[PortfolioAlertAttribution, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))
        object.__setattr__(self, "alert_codes", tuple(str(code) for code in self.alert_codes))
        object.__setattr__(self, "attributions", tuple(self.attributions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
            "alert_count": self.alert_count,
            "alert_codes": list(self.alert_codes),
            "alert_level": self.alert_level,
            "attributions": [item.to_dict() for item in self.attributions],
        }


@dataclass(frozen=True)
class DecisionDeskFundamentalDiagnostic:
    code: str
    factor_name: str
    stock_code: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "factor_name", str(self.factor_name))
        object.__setattr__(self, "stock_code", str(self.stock_code))
        object.__setattr__(self, "message", str(self.message))

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "factor_name": self.factor_name,
            "stock_code": self.stock_code,
            "message": self.message,
        }



@dataclass(frozen=True)
class DecisionDeskRiskPrompt:
    category: str
    severity: str
    source: str
    code: str | None
    title: str
    reason: str
    action_hint: str

    def __post_init__(self) -> None:
        allowed = {"info", "warning", "critical"}
        if self.severity not in allowed:
            raise ValueError(f"unsupported risk prompt severity: {self.severity}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "source": self.source,
            "code": self.code,
            "title": self.title,
            "reason": self.reason,
            "action_hint": self.action_hint,
        }


@dataclass(frozen=True)
class DecisionDeskRiskPromptSummary:
    as_of_date: date | None
    quality: DecisionDeskQuality
    warnings: tuple[str, ...]
    prompts: tuple[DecisionDeskRiskPrompt, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", _normalize_warnings(self.warnings))
        object.__setattr__(self, "prompts", tuple(self.prompts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "quality": self.quality.value,
            "warnings": list(self.warnings),
            "prompts": [prompt.to_dict() for prompt in self.prompts],
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
    relative_strength_liquidity: RelativeStrengthLiquiditySummary
    watchlist_triggers: WatchlistTriggerSummary
    portfolio_alerts: PortfolioAlertSummary
    risk_prompts: DecisionDeskRiskPromptSummary
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if (
            self.market_regime is None
            or self.market_breadth is None
            or self.sector_rotation is None
            or self.relative_strength_liquidity is None
        ):
            raise ValueError("all decision sections must be provided")
        if self.watchlist_triggers is None or self.portfolio_alerts is None or self.risk_prompts is None:
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
            "relative_strength_liquidity": self.relative_strength_liquidity.to_dict(),
            "watchlist_triggers": self.watchlist_triggers.to_dict(),
            "portfolio_alerts": self.portfolio_alerts.to_dict(),
            "risk_prompts": self.risk_prompts.to_dict(),
        }
