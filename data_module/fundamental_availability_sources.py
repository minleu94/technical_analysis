"""受治理的基本面 available_date 來源契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

from data_module.fundamental_availability import (
    FundamentalAvailabilityInput,
    resolve_fundamental_availability,
)
from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality


AvailabilityKey = tuple[str, str]


@dataclass(frozen=True)
class FundamentalAvailabilityOverride:
    stock_code: str
    period: str
    as_of_date: date
    announced_date: date | None
    available_date: date
    quality: FactorQuality
    source: str
    source_version: str


@dataclass(frozen=True)
class FundamentalAvailabilityOverrideLoadResult:
    overrides: dict[AvailabilityKey, FundamentalAvailabilityOverride]
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "overrides", dict(self.overrides))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def load_monthly_revenue_availability_overrides(
    rows: list[Mapping[str, str]],
) -> FundamentalAvailabilityOverrideLoadResult:
    overrides: dict[AvailabilityKey, FundamentalAvailabilityOverride] = {}
    diagnostics: list[FactorDiagnostic] = []

    for row in rows:
        stock_code = row.get("stock_code", "").strip()
        period = row.get("period", "").strip()
        source = row.get("source", "").strip()
        source_version = row.get("source_version", "").strip()
        factor_name = "fundamental.availability"

        if source == "financial_data.monthly_revenue_csv":
            diagnostics.append(
                FactorDiagnostic(
                    code="fundamental_availability.raw_csv_not_available_source",
                    factor_name=factor_name,
                    stock_code=stock_code,
                    message=(
                        "raw monthly revenue CSV date is not an announcement or "
                        f"available_date source; period={period}"
                    ),
                )
            )
            continue

        try:
            as_of_date = _parse_required_date(row.get("as_of_date", ""))
        except ValueError:
            diagnostics.append(_invalid_date_diagnostic(stock_code, period, "as_of_date"))
            continue

        try:
            announced_date = _parse_optional_date(row.get("announced_date", ""))
            available_date = _parse_optional_date(row.get("available_date", ""))
        except ValueError as exc:
            diagnostics.append(_invalid_date_diagnostic(stock_code, period, str(exc)))
            continue

        resolution = resolve_fundamental_availability(
            FundamentalAvailabilityInput(
                stock_code=stock_code,
                period=period,
                as_of_date=as_of_date,
                announced_date=announced_date,
                explicit_available_date=available_date,
                source=source,
            )
        )
        diagnostics.extend(resolution.diagnostics)
        if resolution.available_date is None:
            continue

        overrides[(stock_code, period)] = FundamentalAvailabilityOverride(
            stock_code=stock_code,
            period=period,
            as_of_date=as_of_date,
            announced_date=resolution.announced_date,
            available_date=resolution.available_date,
            quality=resolution.quality,
            source=source,
            source_version=source_version,
        )

    return FundamentalAvailabilityOverrideLoadResult(
        overrides=overrides,
        diagnostics=tuple(diagnostics),
    )


def _parse_required_date(value: str) -> date:
    parsed = _parse_optional_date(value)
    if parsed is None:
        raise ValueError("required date is missing")
    return parsed


def _parse_optional_date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("invalid_date") from exc


def _invalid_date_diagnostic(stock_code: str, period: str, field_name: str) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=f"fundamental_availability.invalid_{field_name}",
        factor_name="fundamental.availability",
        stock_code=stock_code,
        message=f"availability mapping has invalid date field; period={period}; field={field_name}",
    )
