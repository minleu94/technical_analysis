"""Conservative abnormal fundamental flags emitted as diagnostics only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from decision_module.factors.factor_dtos import FactorDiagnostic


class AbnormalFundamentalFlag(str, Enum):
    REVENUE_PROFIT_DIVERGENCE = "abnormal_fundamental.revenue_profit_divergence"
    ONE_OFF_GAIN_RISK = "abnormal_fundamental.one_off_gain_risk"
    DATA_QUALITY_GAP = "abnormal_fundamental.data_quality_gap"


def build_abnormal_fundamental_diagnostics(
    *,
    stock_code: str,
    as_of_date: date,
    revenue_yoy: Decimal | None,
    operating_profit_yoy: Decimal | None,
    one_off_gain_ratio: Decimal | None,
    quality_warnings: tuple[str, ...],
    source_version: str,
) -> tuple[FactorDiagnostic, ...]:
    diagnostics: list[FactorDiagnostic] = []
    factor_name = "fundamental.abnormal_flags"
    if (
        revenue_yoy is not None
        and operating_profit_yoy is not None
        and revenue_yoy > Decimal("0")
        and operating_profit_yoy < Decimal("0")
    ):
        diagnostics.append(
            FactorDiagnostic(
                code=AbnormalFundamentalFlag.REVENUE_PROFIT_DIVERGENCE.value,
                factor_name=factor_name,
                stock_code=stock_code,
                message=(
                    f"revenue_yoy={revenue_yoy}; operating_profit_yoy={operating_profit_yoy}; "
                    f"as_of_date={as_of_date.isoformat()}; source_version={source_version}"
                ),
            )
        )
    if one_off_gain_ratio is not None and one_off_gain_ratio >= Decimal("0.30"):
        diagnostics.append(
            FactorDiagnostic(
                code=AbnormalFundamentalFlag.ONE_OFF_GAIN_RISK.value,
                factor_name=factor_name,
                stock_code=stock_code,
                message=(
                    f"one_off_gain_ratio={one_off_gain_ratio}; "
                    f"as_of_date={as_of_date.isoformat()}; source_version={source_version}"
                ),
            )
        )
    for warning in quality_warnings:
        diagnostics.append(
            FactorDiagnostic(
                code=AbnormalFundamentalFlag.DATA_QUALITY_GAP.value,
                factor_name=factor_name,
                stock_code=stock_code,
                message=(
                    f"quality_warning={warning}; "
                    f"as_of_date={as_of_date.isoformat()}; source_version={source_version}"
                ),
            )
        )
    return tuple(diagnostics)
