"""Governed valuation observations for presentation-only valuation factors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality
from decision_module.factors.valuation_policy import ValuationObservation


@dataclass(frozen=True)
class ValuationObservationBuildResult:
    records: tuple[ValuationObservation, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def calculate_industry_percentiles_bp(
    rows: list[Mapping[str, object]],
) -> dict[tuple[str, str], int | None]:
    by_industry: dict[str, list[tuple[str, Decimal]]] = {}
    for row in rows:
        stock_code = str(row["stock_code"])
        industry = str(row["industry"])
        value = row["metric_value"]
        metric_value = value if isinstance(value, Decimal) else Decimal(str(value))
        by_industry.setdefault(industry, []).append((stock_code, metric_value))

    result: dict[tuple[str, str], int | None] = {}
    for industry, items in by_industry.items():
        if len(items) < 2:
            for stock_code, _ in items:
                result[(stock_code, industry)] = None
            continue
        ranked = sorted(items, key=lambda item: (item[1], item[0]))
        denominator = len(ranked)
        for index, (stock_code, _) in enumerate(ranked, start=1):
            result[(stock_code, industry)] = _rounded_bp(index, denominator)
    return result


def build_valuation_observations(
    rows: list[Mapping[str, str]],
) -> ValuationObservationBuildResult:
    records: list[ValuationObservation] = []
    diagnostics: list[FactorDiagnostic] = []
    for row in rows:
        stock_code = row.get("stock_code", "").strip()
        metric_name = row.get("metric_name", "").strip()
        try:
            metric_value = Decimal(row.get("metric_value", "").strip())
            as_of_date = _parse_date(row.get("as_of_date", ""))
            available_date = _parse_date(row.get("available_date", ""))
            percentile_value = row.get("industry_percentile_bp", "")
            percentile_raw = str(percentile_value).strip()
            percentile = int(percentile_raw) if percentile_raw else None
            quality = FactorQuality(row.get("quality", "").strip())
        except (InvalidOperation, ValueError):
            diagnostics.append(
                FactorDiagnostic(
                    code="valuation_data.invalid_row",
                    factor_name=f"valuation.{metric_name or 'unknown'}",
                    stock_code=stock_code,
                    message="valuation row has invalid metric, date, percentile, or quality",
                )
            )
            continue
        records.append(
            ValuationObservation(
                stock_code=stock_code,
                metric_name=metric_name,
                metric_value=metric_value,
                as_of_date=as_of_date,
                available_date=available_date,
                industry_percentile_bp=percentile,
                quality=quality,
                source=row.get("source", "").strip(),
                source_version=row.get("source_version", "").strip(),
            )
        )
    return ValuationObservationBuildResult(records=tuple(records), diagnostics=tuple(diagnostics))


def _rounded_bp(index: int, denominator: int) -> int:
    numerator = index * 10000
    return (numerator + denominator // 2) // denominator


def _parse_date(value: str):
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()
