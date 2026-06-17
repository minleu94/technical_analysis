"""季度財報 raw CSV 的唯讀正規化契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from data_module.fundamental_availability import (
    FundamentalAvailabilityInput,
    resolve_fundamental_availability,
)
from data_module.fundamental_statement_availability_sources import (
    StatementAvailabilityOverride,
)
from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality


StatementAvailableDateKey = tuple[str, str, str]
StatementAvailableDateValue = date | StatementAvailabilityOverride


@dataclass(frozen=True)
class StatementItemRecord:
    stock_code: str
    statement_type: str
    period: str
    as_of_date: date
    announced_date: date | None
    available_date: date
    item_code: str
    item_name: str
    value: Decimal
    source: str
    source_version: str
    quality: FactorQuality


@dataclass(frozen=True)
class StatementItemParseResult:
    records: tuple[StatementItemRecord, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def parse_statement_rows(
    rows: Iterable[Mapping[str, str]],
    *,
    statement_type: str,
    available_dates: Mapping[StatementAvailableDateKey, StatementAvailableDateValue],
    source_version: str,
) -> StatementItemParseResult:
    records: list[StatementItemRecord] = []
    diagnostics: list[FactorDiagnostic] = []
    source = f"financial_data.{statement_type}_csv"

    for row in rows:
        stock_code = row.get("stock_id", "").strip()
        as_of_date = _parse_iso_date(row.get("date", ""))
        period = _quarter_period(as_of_date)
        item_code = row.get("type", "").strip()
        factor_name = f"fundamental.statement.{statement_type}"

        try:
            value = Decimal(row.get("value", "").strip())
        except (InvalidOperation, AttributeError):
            diagnostics.append(
                FactorDiagnostic(
                    code="fundamental_statement.invalid_value",
                    factor_name=factor_name,
                    stock_code=stock_code,
                    message=(
                        "statement item value is not a valid Decimal; "
                        f"statement_type={statement_type}; period={period}; item_code={item_code}"
                    ),
                )
            )
            continue

        availability = _resolve_statement_availability(
            stock_code=stock_code,
            statement_type=statement_type,
            period=period,
            as_of_date=as_of_date,
            availability_value=available_dates.get((stock_code, statement_type, period)),
            source=source,
        )
        diagnostics.extend(availability.diagnostics)
        if availability.available_date is None:
            continue

        records.append(
            StatementItemRecord(
                stock_code=stock_code,
                statement_type=statement_type,
                period=period,
                as_of_date=as_of_date,
                announced_date=availability.announced_date,
                available_date=availability.available_date,
                item_code=item_code,
                item_name=row.get("origin_name", "").strip(),
                value=value,
                source=source,
                source_version=source_version,
                quality=availability.quality,
            )
        )

    return StatementItemParseResult(records=tuple(records), diagnostics=tuple(diagnostics))


def _resolve_statement_availability(
    *,
    stock_code: str,
    statement_type: str,
    period: str,
    as_of_date: date,
    availability_value: StatementAvailableDateValue | None,
    source: str,
):
    if isinstance(availability_value, StatementAvailabilityOverride):
        return resolve_fundamental_availability(
            FundamentalAvailabilityInput(
                stock_code=stock_code,
                period=period,
                as_of_date=as_of_date,
                announced_date=availability_value.announced_date,
                explicit_available_date=availability_value.available_date,
                source=availability_value.source,
            )
        )

    return resolve_fundamental_availability(
        FundamentalAvailabilityInput(
            stock_code=stock_code,
            period=period,
            as_of_date=as_of_date,
            announced_date=None,
            explicit_available_date=availability_value,
            source=source,
        )
    )


def _quarter_period(value: date) -> str:
    quarter = ((value.month - 1) // 3) + 1
    return f"{value.year:04d}-Q{quarter}"


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()
