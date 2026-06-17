"""受治理的季度財報 available_date 來源契約。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

from data_module.fundamental_availability import (
    FundamentalAvailabilityInput,
    RETROACTIVE_STATEMENT_BASELINE_SOURCE,
    resolve_fundamental_availability,
)
from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality


StatementAvailabilityKey = tuple[str, str, str]
STATEMENT_AVAILABILITY_COLUMNS = (
    "stock_code",
    "statement_type",
    "period",
    "as_of_date",
    "announced_date",
    "available_date",
    "source",
    "source_version",
)
RAW_STATEMENT_SOURCES = frozenset(
    {
        "financial_data.income_statement_csv",
        "financial_data.balance_sheet_csv",
        "financial_data.cash_flows_statement_csv",
    }
)


@dataclass(frozen=True)
class StatementAvailabilityOverride:
    stock_code: str
    statement_type: str
    period: str
    as_of_date: date
    announced_date: date | None
    available_date: date
    quality: FactorQuality
    source: str
    source_version: str


@dataclass(frozen=True)
class StatementAvailabilityOverrideLoadResult:
    overrides: dict[StatementAvailabilityKey, StatementAvailabilityOverride]
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "overrides", dict(self.overrides))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def load_statement_availability_overrides(
    rows: list[Mapping[str, str]],
) -> StatementAvailabilityOverrideLoadResult:
    overrides: dict[StatementAvailabilityKey, StatementAvailabilityOverride] = {}
    diagnostics: list[FactorDiagnostic] = []

    for row in rows:
        stock_code = row.get("stock_code", "").strip()
        statement_type = row.get("statement_type", "").strip()
        period = row.get("period", "").strip()
        source = row.get("source", "").strip()
        source_version = row.get("source_version", "").strip()
        factor_name = "fundamental.statement_availability"

        if source in RAW_STATEMENT_SOURCES:
            diagnostics.append(
                FactorDiagnostic(
                    code="fundamental_statement_availability.raw_csv_not_available_source",
                    factor_name=factor_name,
                    stock_code=stock_code,
                    message=(
                        "raw statement CSV date is not an announcement or "
                        f"available_date source; statement_type={statement_type}; period={period}"
                    ),
                )
            )
            continue

        try:
            as_of_date = _parse_required_date(row.get("as_of_date", ""))
            announced_date = _parse_optional_date(row.get("announced_date", ""))
            available_date = _parse_optional_date(row.get("available_date", ""))
        except ValueError as exc:
            diagnostics.append(_invalid_date_diagnostic(stock_code, statement_type, period, str(exc)))
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

        overrides[(stock_code, statement_type, period)] = StatementAvailabilityOverride(
            stock_code=stock_code,
            statement_type=statement_type,
            period=period,
            as_of_date=as_of_date,
            announced_date=resolution.announced_date,
            available_date=resolution.available_date,
            quality=resolution.quality,
            source=source,
            source_version=source_version,
        )

    return StatementAvailabilityOverrideLoadResult(
        overrides=overrides,
        diagnostics=tuple(diagnostics),
    )


def load_statement_availability_overrides_csv(
    path: Path,
) -> StatementAvailabilityOverrideLoadResult:
    path = Path(path)
    if not path.exists():
        return StatementAvailabilityOverrideLoadResult(
            overrides={},
            diagnostics=(
                FactorDiagnostic(
                    code="fundamental_statement_availability.mapping_file_missing",
                    factor_name="fundamental.statement_availability",
                    stock_code="",
                    message=f"statement availability mapping file missing; path={path}",
                ),
            ),
        )

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        missing_columns = [
            column for column in STATEMENT_AVAILABILITY_COLUMNS if column not in fieldnames
        ]
        if missing_columns:
            return StatementAvailabilityOverrideLoadResult(
                overrides={},
                diagnostics=(
                    FactorDiagnostic(
                        code="fundamental_statement_availability.mapping_missing_columns",
                        factor_name="fundamental.statement_availability",
                        stock_code="",
                        message=(
                            "statement availability mapping missing required columns; "
                            f"path={path}; missing={','.join(missing_columns)}"
                        ),
                    ),
                ),
            )
        return load_statement_availability_overrides(list(reader))


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


def _invalid_date_diagnostic(
    stock_code: str,
    statement_type: str,
    period: str,
    field_name: str,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=f"fundamental_statement_availability.invalid_{field_name}",
        factor_name="fundamental.statement_availability",
        stock_code=stock_code,
        message=(
            "statement availability mapping has invalid date field; "
            f"statement_type={statement_type}; period={period}; field={field_name}"
        ),
    )
