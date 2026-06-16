"""基本面資料的 Factor adapter 前置契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from decision_module.factors.factor_dtos import (
    FactorDiagnostic,
    FactorQuality,
    FactorRecord,
    MissingPolicy,
)


@dataclass(frozen=True)
class FundamentalObservation:
    stock_code: str
    period: str
    as_of_date: date
    announced_date: date | None
    available_date: date | None
    value: Decimal | int | str | None
    source: str
    source_version: str
    quality: FactorQuality


@dataclass(frozen=True)
class FundamentalFactorBuildResult:
    records: tuple[FactorRecord, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def build_revenue_yoy_factor(
    observation: FundamentalObservation,
) -> FundamentalFactorBuildResult:
    factor_name = "fundamental.revenue_yoy"
    if observation.available_date is None:
        return FundamentalFactorBuildResult(
            diagnostics=(
                FactorDiagnostic(
                    code="fundamental.missing_available_date",
                    factor_name=factor_name,
                    stock_code=observation.stock_code,
                    message="fundamental observation missing available_date; no factor record emitted",
                ),
            )
        )

    return FundamentalFactorBuildResult(
        records=(
            FactorRecord(
                factor_name=factor_name,
                stock_code=observation.stock_code,
                as_of_date=observation.as_of_date,
                available_date=observation.available_date,
                value=observation.value,
                score_bp=None,
                quality=observation.quality,
                missing_policy=MissingPolicy.SKIP,
                source_version=observation.source_version,
                metadata={
                    "period": observation.period,
                    "announced_date": observation.announced_date,
                    "source": observation.source,
                },
            ),
        )
    )
