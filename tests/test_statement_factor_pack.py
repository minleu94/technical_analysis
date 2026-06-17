from __future__ import annotations

from datetime import date
from decimal import Decimal

from data_module.fundamental_statement_data import StatementItemRecord
from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy
from decision_module.factors.statement_factor_adapters import build_statement_factor_pack


def _item(statement_type: str, item_code: str, value: str) -> StatementItemRecord:
    return StatementItemRecord(
        stock_code="2330",
        statement_type=statement_type,
        period="2023-Q4",
        as_of_date=date(2023, 12, 31),
        announced_date=None,
        available_date=date(2026, 6, 17),
        item_code=item_code,
        item_name=item_code,
        value=Decimal(value),
        source=f"financial_data.{statement_type}_csv",
        source_version="financial-data-statements-2026-06-17",
        quality=FactorQuality.DEGRADED,
    )


def test_build_statement_factor_pack_emits_eps_margins_roe_and_non_operating_ratio():
    result = build_statement_factor_pack(
        (
            _item("income_statement", "EPS", "9.21"),
            _item("income_statement", "Revenue", "1000"),
            _item("income_statement", "GrossProfit", "400"),
            _item("income_statement", "OperatingIncome", "250"),
            _item("income_statement", "IncomeBeforeIncomeTax", "300"),
            _item("income_statement", "NetIncome", "200"),
            _item("balance_sheet", "Equity", "2000"),
        ),
        stock_code="2330",
        decision_period="2023-Q4",
    )

    by_name = {record.factor_name: record for record in result.records}
    assert by_name["fundamental.statement.eps"].value == Decimal("9.21")
    assert by_name["fundamental.statement.gross_margin"].value == Decimal("0.4")
    assert by_name["fundamental.statement.operating_margin"].value == Decimal("0.25")
    assert by_name["fundamental.statement.roe"].value == Decimal("0.1")
    assert by_name["fundamental.statement.non_operating_income_ratio"].value == Decimal("0.05")
    assert result.diagnostics == ()
    for record in result.records:
        assert record.score_bp is None
        assert record.missing_policy == MissingPolicy.SKIP
        assert record.quality == FactorQuality.DEGRADED
        assert record.available_date == date(2026, 6, 17)
        assert record.metadata["period"] == "2023-Q4"
        assert record.metadata["statement_source"] == "fundamental_statement_items"


def test_build_statement_factor_pack_reports_missing_items_without_neutral_records():
    result = build_statement_factor_pack(
        (
            _item("income_statement", "EPS", "9.21"),
            _item("income_statement", "Revenue", "1000"),
        ),
        stock_code="2330",
        decision_period="2023-Q4",
    )

    names = {record.factor_name for record in result.records}
    assert "fundamental.statement.eps" in names
    assert "fundamental.statement.gross_margin" not in names
    assert any(
        diagnostic.code == "fundamental_statement.required_item_missing"
        for diagnostic in result.diagnostics
    )


def test_build_statement_factor_pack_reports_zero_denominator():
    result = build_statement_factor_pack(
        (
            _item("income_statement", "Revenue", "0"),
            _item("income_statement", "GrossProfit", "400"),
        ),
        stock_code="2330",
        decision_period="2023-Q4",
    )

    assert result.records == ()
    assert any(
        diagnostic.code == "fundamental_statement.denominator_zero"
        for diagnostic in result.diagnostics
    )
