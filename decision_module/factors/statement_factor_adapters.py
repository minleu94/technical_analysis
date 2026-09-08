"""Quarterly statement factor adapters.

These adapters emit governed factor records and diagnostics only. They do not
score, rank, recommend, or connect to ScoringEngine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from data_module.fundamental_statement_data import StatementItemRecord
from data_module.statement_semantic_mapping import map_statement_items_for_factors
from decision_module.factors.factor_dtos import (
    FactorDiagnostic,
    FactorQuality,
    FactorRecord,
    MissingPolicy,
)


_REPORT_BASES = frozenset({"consolidated", "individual"})


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
    include_yoy: bool = False,
) -> StatementFactorBuildResult:
    mapping_result = map_statement_items_for_factors(records)
    scoped = tuple(
        record
        for record in mapping_result.records
        if record.stock_code == stock_code and record.period <= decision_period
    )
    mapping_diagnostics = list(mapping_result.diagnostics)
    if not scoped:
        return StatementFactorBuildResult(
            diagnostics=(
                *mapping_diagnostics,
                FactorDiagnostic(
                    code="fundamental_statement.current_period_missing",
                    factor_name="fundamental.statement",
                    stock_code=stock_code,
                    message=f"current statement period missing; period={decision_period}",
                ),
            )
        )

    report_basis_diagnostics = _report_basis_diagnostics(
        scoped,
        stock_code=stock_code,
        decision_period=decision_period,
    )
    if report_basis_diagnostics:
        # 同一期間的個別／合併報表不能混用，避免同一科目因來源排序被覆蓋，
        # 讓比率或後續期間比較失去可比性。
        return StatementFactorBuildResult(
            diagnostics=tuple((*mapping_diagnostics, *report_basis_diagnostics))
        )

    by_period = _items_by_period(scoped)
    records_out: list[FactorRecord] = []
    diagnostics: list[FactorDiagnostic] = mapping_diagnostics

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
    if include_yoy:
        yoy_result = build_statement_yoy_factor(
            scoped,
            stock_code=stock_code,
            current_period=decision_period,
        )
        records_out.extend(yoy_result.records)
        diagnostics.extend(yoy_result.diagnostics)
    return StatementFactorBuildResult(
        records=tuple(records_out),
        diagnostics=tuple(diagnostics),
    )


def build_statement_yoy_factor(
    records: tuple[StatementItemRecord, ...],
    *,
    stock_code: str,
    current_period: str,
    statement_type: str = "income_statement",
    item_code: str = "Revenue",
    factor_name: str = "fundamental.statement.revenue_yoy",
) -> StatementFactorBuildResult:
    """以同一報表範圍建立跨年同期同比；範圍不一致時明確拒絕。"""

    mapping_result = map_statement_items_for_factors(records)
    records = mapping_result.records
    mapping_diagnostics = mapping_result.diagnostics
    prior_period = _prior_year_period(current_period)
    if prior_period is None:
        return StatementFactorBuildResult(
            diagnostics=(
                *mapping_diagnostics,
                FactorDiagnostic(
                    code="fundamental_statement.invalid_period",
                    factor_name=factor_name,
                    stock_code=stock_code,
                    message=f"statement period is not YYYY-Qn; period={current_period}",
                ),
            )
        )
    current_result = _select_yoy_item(
        records,
        stock_code=stock_code,
        period=current_period,
        statement_type=statement_type,
        item_code=item_code,
        factor_name=factor_name,
    )
    prior_result = _select_yoy_item(
        records,
        stock_code=stock_code,
        period=prior_period,
        statement_type=statement_type,
        item_code=item_code,
        factor_name=factor_name,
    )
    diagnostics = [*current_result[1], *prior_result[1]]
    diagnostics = [*mapping_diagnostics, *diagnostics]
    current = current_result[0]
    prior = prior_result[0]
    if current is None or prior is None:
        if not diagnostics:
            diagnostics.append(
                _missing_item_diagnostic(
                    stock_code,
                    f"{current_period} vs {prior_period}",
                    factor_name,
                    (statement_type, item_code),
                )
            )
        return StatementFactorBuildResult(diagnostics=tuple(diagnostics))
    current_basis = current.report_basis.strip()
    prior_basis = prior.report_basis.strip()
    if current_basis != prior_basis:
        return StatementFactorBuildResult(
            diagnostics=(
                *diagnostics,
                FactorDiagnostic(
                    code="fundamental_statement.report_basis_cross_period_mismatch",
                    factor_name=factor_name,
                    stock_code=stock_code,
                    message=(
                        "statement YoY requires one report basis across periods; "
                        f"current_period={current_period}; prior_period={prior_period}; "
                        f"current_report_basis={current_basis}; prior_report_basis={prior_basis}"
                    ),
                ),
            )
        )
    if prior.value == Decimal("0"):
        return StatementFactorBuildResult(
            diagnostics=(
                *diagnostics,
                FactorDiagnostic(
                    code="fundamental_statement.denominator_zero",
                    factor_name=factor_name,
                    stock_code=stock_code,
                    message=(
                        "statement YoY prior-period denominator is zero; "
                        f"period={prior_period}; item_code={item_code}"
                    ),
                ),
            )
        )
    value = (current.value - prior.value) / prior.value
    return StatementFactorBuildResult(
        records=(
            FactorRecord(
                factor_name=factor_name,
                stock_code=stock_code,
                as_of_date=max(current.as_of_date, prior.as_of_date),
                available_date=max(current.available_date, prior.available_date),
                value=value,
                score_bp=None,
                quality=_combined_quality((current, prior)),
                missing_policy=MissingPolicy.SKIP,
                source_version=current.source_version,
                metadata={
                    "period": current_period,
                    "comparison_period": prior_period,
                    "statement_source": "fundamental_statement_items",
                    "statement_type": statement_type,
                    "item_code": item_code,
                    "report_basis": current_basis,
                    "report_basis_comparable": "same_basis",
                    **_statement_lineage_metadata((current, prior)),
                },
            ),
        ),
        diagnostics=tuple(diagnostics),
    )


def _prior_year_period(period: str) -> str | None:
    import re

    match = re.fullmatch(r"(\d{4})-Q([1-4])", str(period).strip())
    if match is None:
        return None
    return f"{int(match.group(1)) - 1:04d}-Q{match.group(2)}"


def _select_yoy_item(
    records: tuple[StatementItemRecord, ...],
    *,
    stock_code: str,
    period: str,
    statement_type: str,
    item_code: str,
    factor_name: str,
) -> tuple[StatementItemRecord | None, tuple[FactorDiagnostic, ...]]:
    matches = tuple(
        record
        for record in records
        if record.stock_code == stock_code
        and record.period == period
        and record.statement_type == statement_type
        and record.item_code == item_code
    )
    if not matches:
        return None, ()
    bases = {record.report_basis.strip() for record in matches}
    if not bases <= _REPORT_BASES:
        return None, (
            FactorDiagnostic(
                code="fundamental_statement.report_basis_invalid",
                factor_name=factor_name,
                stock_code=stock_code,
                message=(
                    "statement YoY report basis is unsupported; "
                    f"period={period}; report_basis={','.join(sorted(bases))}"
                ),
            ),
        )
    if len(bases) > 1:
        return None, (
            FactorDiagnostic(
                code="fundamental_statement.report_basis_mixed",
                factor_name=factor_name,
                stock_code=stock_code,
                message=(
                    "statement period contains multiple report bases for the YoY item; "
                    f"period={period}; report_basis={','.join(sorted(bases))}"
                ),
            ),
        )
    values = {(record.value, record.source_version) for record in matches}
    if len(values) > 1:
        return None, (
            FactorDiagnostic(
                code="fundamental_statement.revision_ambiguous",
                factor_name=factor_name,
                stock_code=stock_code,
                message=(
                    "statement YoY item has conflicting revisions; "
                    f"period={period}; item_code={item_code}"
                ),
            ),
        )
    return max(matches, key=lambda record: (record.available_date, record.source_version)), ()


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
            "report_basis": primary.report_basis,
            "item_codes": tuple(item.item_code for item in items),
            "statement_types": tuple(item.statement_type for item in items),
            **_statement_lineage_metadata(items),
        },
    )


def _combined_quality(items: tuple[StatementItemRecord, ...]) -> FactorQuality:
    if any(item.quality == FactorQuality.MISSING for item in items):
        return FactorQuality.MISSING
    if any(item.quality == FactorQuality.DEGRADED for item in items):
        return FactorQuality.DEGRADED
    return FactorQuality.OBSERVED


def _statement_lineage_metadata(
    items: tuple[StatementItemRecord, ...],
) -> dict[str, object]:
    """把語意碼與其官方 row-code 證據一起帶到 factor record。"""

    return {
        "raw_item_codes": tuple(item.raw_item_code or item.item_code for item in items),
        "item_code_sources": tuple(item.item_code_source for item in items),
        "item_code_lineage_sha256s": tuple(
            item.item_code_lineage_sha256 for item in items
        ),
        "candidate_source_versions": tuple(
            item.candidate_source_version or item.source_version for item in items
        ),
        "semantic_mapping_sources": tuple(
            item.semantic_mapping_source for item in items
        ),
        "industry_categories": tuple(item.industry_category for item in items),
        "period_bases": tuple(item.period_basis for item in items),
        "period_starts": tuple(
            item.period_start.isoformat() if item.period_start else None
            for item in items
        ),
        "period_ends": tuple(
            item.period_end.isoformat() if item.period_end else None for item in items
        ),
        "value_units": tuple(item.value_unit for item in items),
        "value_scales": tuple(item.value_scale for item in items),
    }


def _report_basis_diagnostics(
    records: tuple[StatementItemRecord, ...],
    *,
    stock_code: str,
    decision_period: str,
) -> tuple[FactorDiagnostic, ...]:
    """拒絕同一期間混合個別／合併範圍，並拒絕未知範圍。"""

    bases_by_period: dict[str, set[str]] = {}
    invalid: list[tuple[str, str]] = []
    for record in records:
        raw_basis = record.report_basis
        basis = raw_basis.strip() if isinstance(raw_basis, str) else ""
        if basis not in _REPORT_BASES:
            invalid.append((record.period, basis or "<missing>"))
            continue
        bases_by_period.setdefault(record.period, set()).add(basis)

    diagnostics: list[FactorDiagnostic] = []
    for period, basis in sorted(invalid):
        diagnostics.append(
            FactorDiagnostic(
                code="fundamental_statement.report_basis_invalid",
                factor_name="fundamental.statement",
                stock_code=stock_code,
                message=(
                    "statement report basis is unsupported; "
                    f"period={period}; report_basis={basis}; decision_period={decision_period}"
                ),
            )
        )
    for period, bases in sorted(bases_by_period.items()):
        if len(bases) <= 1:
            continue
        diagnostics.append(
            FactorDiagnostic(
                code="fundamental_statement.report_basis_mixed",
                factor_name="fundamental.statement",
                stock_code=stock_code,
                message=(
                    "statement period mixes report bases; "
                    f"period={period}; report_basis={','.join(sorted(bases))}; "
                    f"decision_period={decision_period}"
                ),
            )
        )
    return tuple(diagnostics)
