"""Application service for governed fundamental factor records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from data_module.fundamental_sqlite_provider import FundamentalSQLiteProvider
from decision_module.factors.factor_dtos import FactorDiagnostic, FactorRecord
from decision_module.factors.factor_gate import FactorGate
from decision_module.factors.fundamental_adapters import build_revenue_factor_pack
from decision_module.factors.statement_factor_adapters import build_statement_factor_pack
from decision_module.factors.valuation_adapters import build_relative_valuation_factor


@dataclass(frozen=True)
class FundamentalFactorSnapshot:
    records: tuple[FactorRecord, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


class FundamentalFactorService:
    def __init__(
        self,
        db_file: Path,
        *,
        provider: FundamentalSQLiteProvider | None = None,
        gate: FactorGate | None = None,
    ) -> None:
        self.provider = provider or FundamentalSQLiteProvider(db_file)
        self.gate = gate or FactorGate()

    def build_snapshot(
        self,
        *,
        stock_code: str,
        decision_date: date,
    ) -> FundamentalFactorSnapshot:
        records: list[FactorRecord] = []
        diagnostics: list[FactorDiagnostic] = []

        revenue_records = self.provider.load_monthly_revenues(
            stock_code=stock_code,
            decision_date=decision_date,
        )
        if revenue_records:
            revenue_result = build_revenue_factor_pack(
                revenue_records,
                stock_code=stock_code,
                decision_period=revenue_records[-1].period,
            )
            records.extend(revenue_result.records)
            diagnostics.extend(revenue_result.diagnostics)
        else:
            diagnostics.append(
                FactorDiagnostic(
                    code="fundamental_sqlite.monthly_revenue_missing",
                    factor_name="fundamental.revenue",
                    stock_code=stock_code,
                    message=(
                        "no governed monthly revenue records available by decision_date"
                    ),
                )
            )

        valuation_result = self.provider.load_valuation_observations(
            stock_code=stock_code,
            decision_date=decision_date,
        )
        diagnostics.extend(valuation_result.diagnostics)
        for observation in valuation_result.records:
            factor_result = build_relative_valuation_factor(observation)
            records.extend(factor_result.records)
            diagnostics.extend(factor_result.diagnostics)

        statement_items = self.provider.load_statement_items(
            stock_code=stock_code,
            decision_date=decision_date,
        )
        if statement_items:
            decision_statement_period = max(item.period for item in statement_items)
            statement_result = build_statement_factor_pack(
                statement_items,
                stock_code=stock_code,
                decision_period=decision_statement_period,
            )
            records.extend(statement_result.records)
            diagnostics.extend(statement_result.diagnostics)
        else:
            diagnostics.append(
                FactorDiagnostic(
                    code="fundamental_sqlite.statement_items_missing",
                    factor_name="fundamental.statement",
                    stock_code=stock_code,
                    message=(
                        "no governed statement item records available by decision_date"
                    ),
                )
            )

        gate_result = self.gate.validate_for_decision(
            records,
            decision_date=decision_date,
        )
        diagnostics.extend(gate_result.diagnostics)
        return FundamentalFactorSnapshot(
            records=tuple(gate_result.accepted + gate_result.neutralized),
            diagnostics=tuple(diagnostics),
        )
