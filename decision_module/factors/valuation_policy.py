"""估值呈現政策：只分類相對估值區間，不產生目標價或交易建議。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality


VALUATION_PRESENTATION_POLICY_VERSION = "valuation_presentation_policy_v1"


class ValuationBand(str, Enum):
    LOW_RELATIVE = "low_relative"
    MID_RELATIVE = "mid_relative"
    HIGH_RELATIVE = "high_relative"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ValuationObservation:
    stock_code: str
    metric_name: str
    metric_value: Decimal | None
    as_of_date: date
    available_date: date
    industry_percentile_bp: int | None
    quality: FactorQuality
    source: str
    source_version: str


@dataclass(frozen=True)
class ValuationPolicyResult:
    stock_code: str
    metric_name: str
    metric_value: Decimal | None
    as_of_date: date
    available_date: date
    industry_percentile_bp: int | None
    band: ValuationBand
    quality: FactorQuality
    source: str
    source_version: str
    policy_version: str = VALUATION_PRESENTATION_POLICY_VERSION
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_metadata(self) -> dict[str, object]:
        return {
            "metric_name": self.metric_name,
            "metric_value": str(self.metric_value) if self.metric_value is not None else None,
            "industry_percentile_bp": self.industry_percentile_bp,
            "valuation_band": self.band.value,
            "valuation_band_label": valuation_band_ui_label(self.band),
            "policy_version": self.policy_version,
            "source": self.source,
        }


def classify_relative_valuation(
    observation: ValuationObservation,
) -> ValuationPolicyResult:
    diagnostics: list[FactorDiagnostic] = []
    percentile = observation.industry_percentile_bp

    if percentile is None:
        diagnostics.append(
            _diagnostic(
                observation,
                "valuation.missing_industry_percentile",
                "industry_percentile_bp missing; valuation band unavailable",
            )
        )
        band = ValuationBand.UNAVAILABLE
    elif percentile < 0 or percentile > 10000:
        diagnostics.append(
            _diagnostic(
                observation,
                "valuation.invalid_industry_percentile",
                "industry_percentile_bp outside 0..10000; valuation band unavailable",
            )
        )
        band = ValuationBand.UNAVAILABLE
    elif percentile <= 2000:
        band = ValuationBand.LOW_RELATIVE
    elif percentile <= 8000:
        band = ValuationBand.MID_RELATIVE
    else:
        band = ValuationBand.HIGH_RELATIVE

    return ValuationPolicyResult(
        stock_code=observation.stock_code,
        metric_name=observation.metric_name,
        metric_value=observation.metric_value,
        as_of_date=observation.as_of_date,
        available_date=observation.available_date,
        industry_percentile_bp=observation.industry_percentile_bp,
        band=band,
        quality=observation.quality,
        source=observation.source,
        source_version=observation.source_version,
        diagnostics=tuple(diagnostics),
    )


def valuation_band_ui_label(band: ValuationBand) -> str:
    return {
        ValuationBand.LOW_RELATIVE: "相對低估值區",
        ValuationBand.MID_RELATIVE: "中性估值區",
        ValuationBand.HIGH_RELATIVE: "相對高估值區",
        ValuationBand.UNAVAILABLE: "資料不足",
    }[band]


def _diagnostic(
    observation: ValuationObservation,
    code: str,
    message: str,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=code,
        factor_name=f"valuation.{observation.metric_name}",
        stock_code=observation.stock_code,
        message=message,
    )
