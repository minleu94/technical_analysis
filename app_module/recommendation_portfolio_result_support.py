"""Recommendation portfolio replay 的 completed-result 組裝支援。"""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Dict, List

import pandas as pd

from app_module.factor_service import FactorService
from app_module.recommendation_portfolio_dtos import PeriodHoldingDTO, RecommendationSnapshotDTO, StockContributionDTO
from financial_module.units import to_decimal


def return_bp_from_values(values: pd.Series) -> int | None:
    if len(values) < 2:
        return None
    first, last = to_decimal(values.iloc[0]), to_decimal(values.iloc[-1])
    if first <= 0:
        return None
    return int((((last / first) - Decimal("1")) * Decimal("10000")).to_integral_value(rounding=ROUND_HALF_UP))


def _reference_return_bp(data: pd.DataFrame, column: str) -> int | None:
    if data.empty or "日期" not in data.columns or column not in data.columns:
        return None
    references = data[["日期", column]].copy()
    references["日期"] = pd.to_datetime(references["日期"], errors="coerce")
    references[column] = pd.to_numeric(references[column], errors="coerce")
    references = references.dropna(subset=["日期", column]).sort_values("日期").drop_duplicates(subset=["日期"], keep="first")
    return return_bp_from_values(references[column])


def build_relative_attribution(equity_curve: pd.DataFrame, data: pd.DataFrame) -> Dict[str, Any]:
    groups = {"benchmark": ("大盤收盤價", "benchmark_close", "market_index_close", "加權指數"), "industry": ("產業指數收盤價", "industry_close", "industry_index_close"), "concept": ("題材指數收盤價", "concept_close", "concept_index_close")}
    columns = {kind: next((column for column in choices if column in data.columns), None) for kind, choices in groups.items()}
    missing = sorted(kind for kind, column in columns.items() if column is None)
    portfolio_return_bp = None if equity_curve is None or equity_curve.empty or "equity" not in equity_curve.columns else return_bp_from_values(pd.to_numeric(equity_curve["equity"], errors="coerce").dropna())
    benchmarks: Dict[str, Dict[str, Any]] = {}
    for kind, column in columns.items():
        if column is None:
            continue
        value = _reference_return_bp(data, column)
        benchmarks[kind] = {"status": "insufficient_reference_observations" if value is None else "observed", "source_column": column, "return_bp": value, "excess_return_bp": None if value is None or portfolio_return_bp is None else portfolio_return_bp - value}
    status = "observed" if benchmarks and not missing else "missing_optional_sources"
    if benchmarks and missing: status = "partial"
    if not benchmarks and not missing: status = "insufficient_reference_observations"
    return {"schema_version": 1, "status": status, "policy": "same_replay_period_optional_reference_columns", "portfolio_return_bp": portfolio_return_bp, "source_columns": columns, "missing_sources": missing, "benchmarks": benchmarks}


def build_stock_contribution(holdings: List[PeriodHoldingDTO]) -> List[StockContributionDTO]:
    grouped = defaultdict(list)
    for holding in holdings: grouped[(holding.stock_code, holding.stock_name)].append(holding)
    result = []
    for (code, name), items in grouped.items():
        returns = [item.return_pct for item in items]
        result.append(StockContributionDTO(code, name, len(items), sum(item.pnl() for item in items), sum(returns) / len(returns), len([value for value in returns if value > 0]) / len(returns), min(returns)))
    return sorted(result, key=lambda item: item.total_pnl, reverse=True)


def build_credibility_manifest(rebalance_frequency: str, allocation_method: str, max_participation_rate: float | None, execution_costs: bool, lot_size: int | None, fee_bps: float | None = None, slippage_bps: float | None = None, tax_bps: float | None = None) -> Dict[str, Any]:
    liquidity = "partial" if max_participation_rate else False
    return {"schema_version": 1, "status": "limited", "execution_assumption": "idealized_same_day_close", "rebalance_frequency": rebalance_frequency, "allocation_method": allocation_method, "cash_account": {"supported": "order_sizing", "policy": "available_cash_checked_before_holding_creation"}, "rebalance": {"supported": False, "policy": "period_holdings_are_independent_replay_slices"}, "unfilled_orders": {"supported": True, "policy": "missing_price_rows_are_recorded_as_unfilled_orders"}, "weights": {"supported": "partial", "policy": "target_and_actual_executable_weights_reported"}, "liquidity_gap": {"supported": liquidity, "policy": "entry_day_volume_participation_checked" if max_participation_rate else "volume_limit_and_gap_risk_not_applied", "max_participation_rate": max_participation_rate}, "gap_risk": {"supported": "partial", "policy": "next_open_gap_labels_when_open_price_available"}, "execution_costs": {"supported": "partial" if execution_costs else False, "policy": "fee_tax_slippage_bps_applied_to_cash_ledger" if execution_costs else "not_applied", "fee_bps": fee_bps, "slippage_bps": slippage_bps, "tax_bps": tax_bps}, "share_sizing": {"supported": "partial" if lot_size else False, "policy": "full_lot_floor_sizing" if lot_size else "money_allocation_without_share_sizing", "lot_size": lot_size}, "warnings": ["rebalance_cash_reuse_partial", "liquidity_gap_not_modeled", "same_day_close_execution_assumption"]}


def build_factor_manifest(snapshots: List[RecommendationSnapshotDTO], records_for: Callable[[RecommendationSnapshotDTO], list[Any]]) -> Dict[str, Any]:
    service = FactorService(); combined: Dict[str, Any] = {"schema_version": 1, "factor_set_version": "factor-layer-v1", "decision_date": snapshots[-1].as_of_date if snapshots else "", "decision_dates": [item.as_of_date for item in snapshots], "records": [], "neutralized": [], "skipped": [], "diagnostics": []}
    for snapshot in snapshots:
        records = records_for(snapshot)
        if records:
            gated = service.build_snapshot(records, decision_date=pd.Timestamp(snapshot.as_of_date).date())
            for key in ("records", "neutralized", "skipped", "diagnostics"): combined[key].extend(gated[key])
    return {"factor_snapshot": combined, "factor_contributions": service.build_contributions(combined)}
