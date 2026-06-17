"""Quarterly statement factor adapters.

These adapters emit governed factor records and diagnostics only. They do not
score, rank, recommend, or connect to ScoringEngine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from data_module.fundamental_statement_data import StatementItemRecord
from decision_module.factors.factor_dtos import (
    FactorDiagnostic,
    FactorQuality,
    FactorRecord,
    MissingPolicy,
)


@dataclass(frozen=True)
class StatementFactorBuildResult:
    records: tuple[FactorRecord, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def build_statement_factor_pack(
    records: tuple[StatementItemRecord, ...],
    *,
    stock_code: str,
    decision_period: str,
) -> StatementFactorBuildResult:
    scoped = tuple(
        record
        for record in records
        if record.stock_code == stock_code and record.period <= decision_period
    )
    if not scoped:
        return StatementFactorBuildResult(
            diagnostics=(
                FactorDiagnostic(
                    code="fundamental_statement.current_period_missing",
                    factor_name="fundamental.statement",
                    stock_code=stock_code,
                    message=f"current statement period missing; period={decision_period}",
                ),
            )
        )

    by_period = _items_by_period(scoped)
    records_out: list[FactorRecord] = []
    diagnostics: list[FactorDiagnostic] = []

    _append_single_item_factor(
        records_out,
        diagnostics,
        by_period,
        stock_code=stock_code,
        decision_period=decision_period,
        item_key=("income_statement", "EPS"),
        factor_name="fundamental.statement.eps",
    )
    _append_ratio_factor(
        records_out,
        diagnostics,
        by_period,
        stock_code=stock_code,
        decision_period=decision_period,
        numerator_key=("income_statement", "GrossProfit"),
        denominator_key=("income_statement", "Revenue"),
        factor_name="fundamental.statement.gross_margin",
    )
    _append_ratio_factor(
        records_out,
        diagnostics,
        by_period,
        stock_code=stock_code,
        decision_period=decision_period,
        numerator_key=("income_statement", "OperatingIncome"),
        denominator_key=("income_statement", "Revenue"),
        factor_name="fundamental.statement.operating_margin",
    )
    _append_ratio_factor(
        records_out,
        diagnostics,
        by_period,
        stock_code=stock_code,
        decision_period=decision_period,
        numerator_key=("income_statement", "NetIncome"),
        denominator_key=("balance_sheet", "Equity"),
        factor_name="fundamental.statement.roe",
    )
    _append_non_operating_factor(
        records_out,
        diagnostics,
        by_period,
        stock_code=stock_code,
        decision_period=decision_period,
    )
    return StatementFactorBuildResult(
        records=tuple(records_out),
        diagnostics=tuple(diagnostics),
    )


def _append_single_item_factor(
    records_out: list[FactorRecord],
    diagnostics: list[FactorDiagnostic],
    by_period: dict[str, dict[tuple[str, str], StatementItemRecord]],
    *,
    stock_code: str,
    decision_period: str,
    item_key: tuple[str, str],
    factor_name: str,
) -> None:
    period, items = _latest_period_with_items(by_period, (item_key,))
    item = items[0] if items else None
    if item is None:
        diagnostics.append(_missing_item_diagnostic(stock_code, decision_period, factor_name, item_key))
        return
    records_out.append(_base_record((item,), factor_name, item.value))


def _append_ratio_factor(
    records_out: list[FactorRecord],
    diagnostics: list[FactorDiagnostic],
    by_period: dict[str, dict[tuple[str, str], StatementItemRecord]],
    *,
    stock_code: str,
    decision_period: str,
    numerator_key: tuple[str, str],
    denominator_key: tuple[str, str],
    factor_name: str,
) -> None:
    period, items = _latest_period_with_items(by_period, (numerator_key, denominator_key))
    numerator = items[0] if items else None
    denominator = items[1] if len(items) > 1 else None
    if numerator is None:
        diagnostics.append(_missing_item_diagnostic(stock_code, period or decision_period, factor_name, numerator_key))
        return
    if denominator is None:
        diagnostics.append(_missing_item_diagnostic(stock_code, period or decision_period, factor_name, denominator_key))
        return
    if denominator.value == Decimal("0"):
        diagnostics.append(
            FactorDiagnostic(
                code="fundamental_statement.denominator_zero",
                factor_name=factor_name,
                stock_code=stock_code,
                message=(
                    "statement factor denominator is zero; "
                    f"period={denominator.period}; denominator={denominator_key[1]}"
                ),
            )
        )
        return
    records_out.append(_base_record((numerator, denominator), factor_name, numerator.value / denominator.value))


def _append_non_operating_factor(
    records_out: list[FactorRecord],
    diagnostics: list[FactorDiagnostic],
    by_period: dict[str, dict[tuple[str, str], StatementItemRecord]],
    *,
    stock_code: str,
    decision_period: str,
) -> None:
    factor_name = "fundamental.statement.non_operating_income_ratio"
    period, items = _latest_period_with_items(
        by_period,
        (
            ("income_statement", "IncomeBeforeIncomeTax"),
            ("income_statement", "OperatingIncome"),
            ("income_statement", "Revenue"),
        ),
    )
    pretax = items[0] if items else None
    operating = items[1] if len(items) > 1 else None
    revenue = items[2] if len(items) > 2 else None
    if pretax is None:
        diagnostics.append(
            _missing_item_diagnostic(
                stock_code,
                period or decision_period,
                factor_name,
                ("income_statement", "IncomeBeforeIncomeTax"),
            )
        )
        return
    if operating is None:
        diagnostics.append(
            _missing_item_diagnostic(
                stock_code,
                period or decision_period,
                factor_name,
                ("income_statement", "OperatingIncome"),
            )
        )
        return
    if revenue is None:
        diagnostics.append(
            _missing_item_diagnostic(
                stock_code,
                period or decision_period,
                factor_name,
                ("income_statement", "Revenue"),
            )
        )
        return
    if revenue.value == Decimal("0"):
        diagnostics.append(
            FactorDiagnostic(
                code="fundamental_statement.denominator_zero",
                factor_name=factor_name,
                stock_code=stock_code,
                message=f"statement factor denominator is zero; period={revenue.period}; denominator=Revenue",
            )
        )
        return
    records_out.append(
        _base_record((pretax, operating, revenue), factor_name, (pretax.value - operating.value) / revenue.value)
    )


def _missing_item_diagnostic(
    stock_code: str,
    decision_period: str,
    factor_name: str,
    item_key: tuple[str, str],
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code="fundamental_statement.required_item_missing",
        factor_name=factor_name,
        stock_code=stock_code,
        message=(
            "required statement item missing; "
            f"period={decision_period}; statement_type={item_key[0]}; item_code={item_key[1]}"
        ),
    )


def _items_by_period(
    records: tuple[StatementItemRecord, ...],
) -> dict[str, dict[tuple[str, str], StatementItemRecord]]:
    grouped: dict[str, dict[tuple[str, str], StatementItemRecord]] = {}
    for record in records:
        grouped.setdefault(record.period, {})[(record.statement_type, record.item_code)] = record
    return grouped


def _latest_period_with_items(
    by_period: dict[str, dict[tuple[str, str], StatementItemRecord]],
    keys: tuple[tuple[str, str], ...],
) -> tuple[str | None, tuple[StatementItemRecord, ...]]:
    for period in sorted(by_period, reverse=True):
        period_items = by_period[period]
        if all(key in period_items for key in keys):
            return period, tuple(period_items[key] for key in keys)
    return None, ()


def _base_record(
    items: tuple[StatementItemRecord, ...],
    factor_name: str,
    value: Decimal,
) -> FactorRecord:
    primary = items[0]
    return FactorRecord(
        factor_name=factor_name,
        stock_code=primary.stock_code,
        as_of_date=max(item.as_of_date for item in items),
        available_date=max(item.available_date for item in items),
        value=value,
        score_bp=None,
        quality=_combined_quality(items),
        missing_policy=MissingPolicy.SKIP,
        source_version=primary.source_version,
        metadata={
            "period": primary.period,
            "statement_source": "fundamental_statement_items",
            "item_codes": tuple(item.item_code for item in items),
            "statement_types": tuple(item.statement_type for item in items),
        },
    )


def _combined_quality(items: tuple[StatementItemRecord, ...]) -> FactorQuality:
    if any(item.quality == FactorQuality.MISSING for item in items):
        return FactorQuality.MISSING
    if any(item.quality == FactorQuality.DEGRADED for item in items):
        return FactorQuality.DEGRADED
    return FactorQuality.OBSERVED
