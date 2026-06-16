"""基本面資料公告日與可得日解析政策。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality


@dataclass(frozen=True)
class FundamentalAvailabilityInput:
    stock_code: str
    period: str
    as_of_date: date
    announced_date: date | None
    explicit_available_date: date | None
    source: str


@dataclass(frozen=True)
class FundamentalAvailabilityResolution:
    announced_date: date | None
    available_date: date | None
    quality: FactorQuality
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def resolve_fundamental_availability(
    observation: FundamentalAvailabilityInput,
) -> FundamentalAvailabilityResolution:
    factor_name = "fundamental.availability"
    diagnostics: list[FactorDiagnostic] = []

    available_date = observation.explicit_available_date
    if available_date is None:
        return FundamentalAvailabilityResolution(
            announced_date=observation.announced_date,
            available_date=None,
            quality=FactorQuality.MISSING,
            diagnostics=(
                _diagnostic(
                    observation,
                    factor_name,
                    "fundamental_availability.missing_available_date",
                    "fundamental observation has no explicit available_date",
                ),
            ),
        )

    if available_date < observation.as_of_date:
        return FundamentalAvailabilityResolution(
            announced_date=observation.announced_date,
            available_date=None,
            quality=FactorQuality.MISSING,
            diagnostics=(
                _diagnostic(
                    observation,
                    factor_name,
                    "fundamental_availability.available_before_period_end",
                    "available_date is before period end date",
                ),
            ),
        )

    if observation.announced_date is not None and available_date < observation.announced_date:
        return FundamentalAvailabilityResolution(
            announced_date=observation.announced_date,
            available_date=None,
            quality=FactorQuality.MISSING,
            diagnostics=(
                _diagnostic(
                    observation,
                    factor_name,
                    "fundamental_availability.available_before_announcement",
                    "available_date is before announced_date",
                ),
            ),
        )

    if observation.announced_date is None:
        diagnostics.append(
            _diagnostic(
                observation,
                factor_name,
                "fundamental_availability.missing_announced_date",
                "announced_date missing; available_date is explicit but quality is degraded",
            )
        )
        quality = FactorQuality.DEGRADED
    else:
        quality = FactorQuality.OBSERVED

    return FundamentalAvailabilityResolution(
        announced_date=observation.announced_date,
        available_date=available_date,
        quality=quality,
        diagnostics=tuple(diagnostics),
    )


def _diagnostic(
    observation: FundamentalAvailabilityInput,
    factor_name: str,
    code: str,
    message: str,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=code,
        factor_name=factor_name,
        stock_code=observation.stock_code,
        message=f"{message}; period={observation.period}; source={observation.source}",
    )
