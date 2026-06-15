from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Dict, List

import pandas as pd

from app_module.factor_service import FactorService
from app_module.recommendation_portfolio_dtos import (
    PeriodHoldingDTO,
    RecommendationSnapshotDTO,
    RecommendationPortfolioBacktestResultDTO,
    StockContributionDTO,
)
from app_module.recommendation_portfolio_dates import parse_stock_dates
from app_module.recommendation_portfolio_metrics import calculate_robustness_metrics, generate_improvement_hints
from app_module.recommendation_replay_service import RecommendationReplayService
from decision_module.factors.factor_adapters import build_technical_total_score_factor
from decision_module.factors.factor_dtos import FactorQuality, FactorRecord, MissingPolicy
from financial_module.units import bps_to_rate, calculate_fee, quantize_money, to_decimal


class RecommendationPortfolioBacktestService:
    def __init__(self, provider: Callable[[pd.DataFrame, Dict[str, Any], int], List[Dict[str, Any]]]):
        self.replay_service = RecommendationReplayService(provider=provider)

    def run_portfolio_backtest(
        self,
        start_date: str,
        end_date: str,
        profile_id: str,
        recommendation_config: Dict[str, Any],
        history: pd.DataFrame,
        initial_capital: float,
        rebalance_frequency: str,
        top_n: int,
        allocation_method: str,
        holding_days: int,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        max_participation_rate: float | None = None,
        fee_bps: float | None = None,
        slippage_bps: float | None = None,
        tax_bps: float | None = None,
        lot_size: int | None = None,
    ) -> RecommendationPortfolioBacktestResultDTO:
        """
        執行推薦組合回測。

        注意：目前本服務進場點（PeriodHoldingDTO.entry_price）採用 rebalance_ts（訊號日）當天的收盤價。
        此模式隱含「同日收盤訊號同日收盤成交」之理想化研究假設，在實盤操作中可能存在時間差而無法以該價格買入。
        """
        import warnings
        warnings.warn(
            "推薦組合回測目前採用「同日收盤訊號同日收盤成交」之理想化研究假設，實盤中可能因時間差無法以收盤價買入。",
            UserWarning
        )
        if rebalance_frequency not in {"once", "weekly"}:
            raise ValueError("目前推薦組合回測支援 once 或 weekly rebalance")
        if lot_size is not None and lot_size <= 0:
            raise ValueError("lot_size must be positive when provided")

        data = history.copy()
        data["日期"] = parse_stock_dates(data["日期"])
        data = data[data["日期"].notna()].sort_values("日期")
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        rebalance_dates = self._get_rebalance_dates(data, start_ts, end_ts, rebalance_frequency)
        credibility_manifest = self._build_credibility_manifest(
            rebalance_frequency=rebalance_frequency,
            allocation_method=allocation_method,
            max_participation_rate=max_participation_rate,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            tax_bps=tax_bps,
            lot_size=lot_size,
        )

        snapshots = []
        period_holdings = []
        trade_rows = []
        unfilled_orders = []
        active_holdings: List[PeriodHoldingDTO] = []
        cash_ledger: List[Dict[str, Any]] = []
        available_cash = to_decimal(initial_capital)
        total_transaction_cost = to_decimal("0.00")
        capital_per_period = initial_capital

        for rebalance_ts in rebalance_dates:
            available_cash, released_cost = self._release_exited_holdings(
                rebalance_ts=rebalance_ts,
                active_holdings=active_holdings,
                cash_ledger=cash_ledger,
                available_cash=available_cash,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                tax_bps=tax_bps,
            )
            total_transaction_cost = quantize_money(total_transaction_cost + released_cost)
            planned_exit_ts = min(rebalance_ts + pd.Timedelta(days=holding_days), end_ts)
            snapshot = self.replay_service.run_snapshot(
                as_of_date=rebalance_ts.strftime("%Y-%m-%d"),
                profile_id=profile_id,
                config=recommendation_config,
                history=data,
                universe=None,
                top_n=top_n,
            )
            snapshots.append(snapshot)
            recommendations = snapshot.recommendations
            if not recommendations:
                continue

            weights = self._calculate_weights(recommendations, allocation_method)
            for rank, rec in enumerate(recommendations, 1):
                allocation_amount = capital_per_period * weights[rank - 1]
                allocation_weight = weights[rank - 1]
                allocation_amount_dec = quantize_money(to_decimal(allocation_amount))
                liquidity_unfilled = self._liquidity_unfilled_reason(
                    data=data,
                    rec=rec,
                    rebalance_ts=rebalance_ts,
                    planned_exit_ts=planned_exit_ts,
                    allocation_amount=allocation_amount,
                    max_participation_rate=max_participation_rate,
                )
                if liquidity_unfilled is not None:
                    unfilled_orders.append(
                        self._build_unfilled_order(
                            rec=rec,
                            rank=rank,
                            rebalance_ts=rebalance_ts,
                            planned_exit_ts=planned_exit_ts,
                            allocation_amount=allocation_amount,
                            allocation_weight=allocation_weight,
                            reason="liquidity_limited",
                            liquidity=liquidity_unfilled,
                        )
                    )
                    continue
                holding = self._build_period_holding(
                    data=data,
                    rec=rec,
                    rank=rank,
                    rebalance_ts=rebalance_ts,
                    planned_exit_ts=planned_exit_ts,
                    allocation_amount=allocation_amount,
                    allocation_weight=allocation_weight,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                )
                if holding is None:
                    unfilled_orders.append(
                        self._build_unfilled_order(
                            rec=rec,
                            rank=rank,
                            rebalance_ts=rebalance_ts,
                            planned_exit_ts=planned_exit_ts,
                            allocation_amount=allocation_amount,
                            allocation_weight=allocation_weight,
                            reason="missing_price_rows",
                        )
                    )
                    continue
                sizing_unfilled = self._apply_lot_sizing(
                    holding=holding,
                    planned_allocation_amount=allocation_amount_dec,
                    lot_size=lot_size,
                )
                if sizing_unfilled is not None:
                    unfilled_orders.append(
                        self._build_unfilled_order(
                            rec=rec,
                            rank=rank,
                            rebalance_ts=rebalance_ts,
                            planned_exit_ts=planned_exit_ts,
                            allocation_amount=allocation_amount,
                            allocation_weight=allocation_weight,
                            reason="lot_size_limited",
                            sizing=sizing_unfilled,
                        )
                    )
                    continue
                actual_allocation_dec = quantize_money(to_decimal(holding.allocation_amount))
                holding.actual_allocation_weight = self._weight_from_amount(
                    amount=actual_allocation_dec,
                    initial_capital=initial_capital,
                )
                buy_costs = self._build_execution_costs(
                    gross_amount=actual_allocation_dec,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    tax_bps=tax_bps,
                    include_tax=False,
                )
                buy_cash_required = quantize_money(actual_allocation_dec + buy_costs["total"])
                if buy_cash_required > available_cash:
                    unfilled_orders.append(
                        self._build_unfilled_order(
                            rec=rec,
                            rank=rank,
                            rebalance_ts=rebalance_ts,
                            planned_exit_ts=planned_exit_ts,
                            allocation_amount=allocation_amount,
                            allocation_weight=allocation_weight,
                            reason="cash_limited",
                            cash={
                                "available_cash": float(available_cash),  # numeric-boundary: dto
                                "required_cash": float(buy_cash_required),  # numeric-boundary: dto
                                "cash_shortfall": float(quantize_money(buy_cash_required - available_cash)),  # numeric-boundary: dto
                            },
                        )
                    )
                    continue
                period_holdings.append(holding)
                active_holdings.append(holding)
                available_cash = quantize_money(available_cash - buy_cash_required)
                total_transaction_cost = quantize_money(total_transaction_cost + buy_costs["total"])
                cash_ledger.append(
                    self._build_cash_ledger_row(
                        date=holding.entry_date,
                        stock_code=holding.stock_code,
                        event="buy",
                        gross_amount=-actual_allocation_dec,
                        costs=buy_costs,
                        net_amount=-buy_cash_required,
                        cash_balance=available_cash,
                        include_costs=self._has_execution_cost_params(fee_bps, slippage_bps, tax_bps),
                    )
                )
                trade_rows.extend(self._build_trade_rows(holding))

        available_cash, released_cost = self._release_exited_holdings(
            rebalance_ts=end_ts + pd.Timedelta(days=1),
            active_holdings=active_holdings,
            cash_ledger=cash_ledger,
            available_cash=available_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            tax_bps=tax_bps,
        )
        total_transaction_cost = quantize_money(total_transaction_cost + released_cost)
        ending_cash = float(quantize_money(available_cash))  # numeric-boundary: dto
        total_transaction_cost_float = float(quantize_money(total_transaction_cost))  # numeric-boundary: dto

        if not snapshots:
            snapshots.append(
                self.replay_service.run_snapshot(
                    as_of_date=start_ts.strftime("%Y-%m-%d"),
                    profile_id=profile_id,
                    config=recommendation_config,
                    history=data,
                    universe=None,
                    top_n=top_n,
                )
            )

        if not period_holdings:
            equity_curve = pd.DataFrame([{"date": start_ts.strftime("%Y-%m-%d"), "equity": initial_capital}])
            weight_exposure = self._build_weight_exposure(
                period_holdings=period_holdings,
                unfilled_orders=unfilled_orders,
            )
            gap_risk = self._build_gap_risk_manifest(period_holdings, data)
            details = {
                "data_manifest": self._build_factor_manifest(snapshots),
                "portfolio_credibility": credibility_manifest,
                "unfilled_orders": unfilled_orders,
                "cash_ledger": cash_ledger,
                "weight_exposure": weight_exposure,
                "gap_risk": gap_risk,
            }
            return RecommendationPortfolioBacktestResultDTO(
                summary={
                    "total_return": 0.0,
                    "max_drawdown": 0.0,
                    "total_trades": 0,
                    "execution_assumption": "idealized_same_day_close",
                    "credibility_status": credibility_manifest["status"],
                    "credibility_warning_count": len(credibility_manifest["warnings"]),
                    "unfilled_order_count": len(unfilled_orders),
                    "ending_cash": ending_cash,
                    "total_transaction_cost": total_transaction_cost_float,
                },
                equity_curve=equity_curve,
                trades=pd.DataFrame(),
                snapshots=snapshots,
                period_holdings=[],
                stock_contribution=[],
                selection_diagnostics=["no_recommendations"] + self._unfilled_order_diagnostics(unfilled_orders),
                details=details,
            )

        final_equity = initial_capital + sum(holding.pnl() for holding in period_holdings)
        equity_curve = self._build_equity_curve(initial_capital, period_holdings, start_ts, end_ts, data)
        stock_contribution = self._build_stock_contribution(period_holdings)
        summary = {
            "total_return": (final_equity / initial_capital) - 1 if initial_capital > 0 else 0.0,
            "max_drawdown": self._calculate_max_drawdown(equity_curve["equity"]),
            "total_trades": len(period_holdings),
            "avg_holding_days": (
                sum(holding.holding_days for holding in period_holdings) / len(period_holdings)
                if period_holdings
                else 0.0
            ),
            "capital_used": sum(holding.allocation_amount for holding in period_holdings),
            "execution_assumption": "idealized_same_day_close",
            "credibility_status": credibility_manifest["status"],
            "credibility_warning_count": len(credibility_manifest["warnings"]),
            "unfilled_order_count": len(unfilled_orders),
            "ending_cash": ending_cash,
            "total_transaction_cost": total_transaction_cost_float,
        }
        summary.update(self._build_exit_diagnostics(period_holdings, stock_contribution))
        summary.update(
            calculate_robustness_metrics(
                equity_curve=equity_curve,
                trade_returns=[holding.return_pct for holding in period_holdings],
            )
        )

        improvement_hints = generate_improvement_hints(summary)
        weight_exposure = self._build_weight_exposure(
            period_holdings=period_holdings,
            unfilled_orders=unfilled_orders,
        )
        gap_risk = self._build_gap_risk_manifest(period_holdings, data)
        details = {
            "data_manifest": self._build_factor_manifest(snapshots),
            "portfolio_credibility": credibility_manifest,
            "unfilled_orders": unfilled_orders,
            "cash_ledger": cash_ledger,
            "weight_exposure": weight_exposure,
            "gap_risk": gap_risk,
        }

        return RecommendationPortfolioBacktestResultDTO(
            summary=summary,
            equity_curve=equity_curve,
            trades=pd.DataFrame(trade_rows),
            snapshots=snapshots,
            period_holdings=period_holdings,
            stock_contribution=stock_contribution,
            selection_diagnostics=[
                item for snapshot in snapshots for item in snapshot.diagnostics
            ] + self._unfilled_order_diagnostics(unfilled_orders),
            improvement_hints=improvement_hints,
            details=details,
        )

    def _get_rebalance_dates(
        self,
        data: pd.DataFrame,
        start_ts: pd.Timestamp,
        end_ts: pd.Timestamp,
        rebalance_frequency: str,
    ) -> List[pd.Timestamp]:
        trading_dates = (
            data[(data["日期"] >= start_ts) & (data["日期"] <= end_ts)]["日期"]
            .drop_duplicates()
            .sort_values()
            .tolist()
        )
        if not trading_dates:
            return [start_ts]
        if rebalance_frequency == "once":
            return [pd.to_datetime(trading_dates[0])]

        rebalance_dates = []
        seen_weeks = set()
        for value in trading_dates:
            ts = pd.to_datetime(value)
            week_key = (ts.isocalendar().year, ts.isocalendar().week)
            if week_key in seen_weeks:
                continue
            seen_weeks.add(week_key)
            rebalance_dates.append(ts)
        return rebalance_dates

    def _liquidity_unfilled_reason(
        self,
        *,
        data: pd.DataFrame,
        rec: Dict[str, Any],
        rebalance_ts: pd.Timestamp,
        planned_exit_ts: pd.Timestamp,
        allocation_amount: float,
        max_participation_rate: float | None,
    ) -> Dict[str, Any] | None:
        if max_participation_rate is None or max_participation_rate <= 0:
            return None
        code = str(rec.get("stock_code", ""))
        stock_rows = data[
            (data["證券代號"].astype(str) == code)
            & (data["日期"] >= rebalance_ts)
            & (data["日期"] <= planned_exit_ts)
        ]
        if stock_rows.empty:
            return None
        entry_row = stock_rows.iloc[0]
        if "成交股數" not in entry_row.index:
            return None
        volume = pd.to_numeric(entry_row["成交股數"], errors="coerce")
        if pd.isna(volume):
            return None
        volume_shares = int(volume)
        close_price = float(entry_row["收盤價"])  # numeric-boundary: analytics
        max_amount = round(float(volume_shares * close_price * max_participation_rate), 6)  # numeric-boundary: analytics
        if allocation_amount <= max_amount:
            return None
        return {
            "volume_shares": volume_shares,
            "close_price": close_price,
            "max_participation_rate": max_participation_rate,
            "max_participation_amount": max_amount,
        }

    def _build_unfilled_order(
        self,
        *,
        rec: Dict[str, Any],
        rank: int,
        rebalance_ts: pd.Timestamp,
        planned_exit_ts: pd.Timestamp,
        allocation_amount: float,
        allocation_weight: float,
        reason: str,
        liquidity: Dict[str, Any] | None = None,
        cash: Dict[str, Any] | None = None,
        sizing: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        order = {
            "rebalance_date": rebalance_ts.strftime("%Y-%m-%d"),
            "stock_code": str(rec.get("stock_code", "")),
            "stock_name": str(rec.get("stock_name", "")),
            "rank": rank,
            "reason": reason,
            "planned_exit_date": planned_exit_ts.strftime("%Y-%m-%d"),
            "allocation_amount": allocation_amount,
            "allocation_weight": allocation_weight,
            "total_score": float(rec.get("total_score", 0.0)),  # numeric-boundary: dto
        }
        if liquidity is not None:
            order["liquidity"] = liquidity
        if cash is not None:
            order["cash"] = cash
        if sizing is not None:
            order["sizing"] = sizing
        return order

    def _unfilled_order_diagnostics(self, unfilled_orders: List[Dict[str, Any]]) -> List[str]:
        return [
            f"unfilled_order:{order['stock_code']}:{order['reason']}"
            for order in unfilled_orders
        ]

    def _has_execution_cost_params(
        self,
        fee_bps: float | None,
        slippage_bps: float | None,
        tax_bps: float | None,
    ) -> bool:
        return fee_bps is not None or slippage_bps is not None or tax_bps is not None

    def _build_execution_costs(
        self,
        *,
        gross_amount: Decimal,
        fee_bps: float | None,
        slippage_bps: float | None,
        tax_bps: float | None,
        include_tax: bool,
    ) -> Dict[str, Decimal]:
        amount = quantize_money(abs(gross_amount))
        fee = (
            calculate_fee(amount, fee_bps, minimum_fee=to_decimal("0.00"))
            if fee_bps is not None
            else to_decimal("0.00")
        )
        tax = (
            calculate_fee(amount, tax_bps, minimum_fee=to_decimal("0.00"))
            if include_tax and tax_bps is not None
            else to_decimal("0.00")
        )
        slippage = (
            quantize_money(amount * bps_to_rate(slippage_bps))
            if slippage_bps is not None
            else to_decimal("0.00")
        )
        total = quantize_money(fee + tax + slippage)
        return {"fee": fee, "tax": tax, "slippage": slippage, "total": total}

    def _serialize_execution_costs(self, costs: Dict[str, Decimal]) -> Dict[str, float]:
        return {
            "fee": float(costs["fee"]),  # numeric-boundary: dto
            "tax": float(costs["tax"]),  # numeric-boundary: dto
            "slippage": float(costs["slippage"]),  # numeric-boundary: dto
            "total": float(costs["total"]),  # numeric-boundary: dto
        }

    def _build_cash_ledger_row(
        self,
        *,
        date: str,
        stock_code: str,
        event: str,
        gross_amount: Decimal,
        costs: Dict[str, Decimal],
        net_amount: Decimal,
        cash_balance: Decimal,
        include_costs: bool,
    ) -> Dict[str, Any]:
        row = {
            "date": date,
            "stock_code": stock_code,
            "event": event,
            "amount": float(net_amount),  # numeric-boundary: dto
            "cash_balance": float(cash_balance),  # numeric-boundary: dto
        }
        if include_costs:
            row["gross_amount"] = float(gross_amount)  # numeric-boundary: dto
            row["costs"] = self._serialize_execution_costs(costs)
        return row

    def _apply_lot_sizing(
        self,
        *,
        holding: PeriodHoldingDTO,
        planned_allocation_amount: Decimal,
        lot_size: int | None,
    ) -> Dict[str, Any] | None:
        if lot_size is None:
            return None
        entry_price = to_decimal(holding.entry_price)
        if entry_price <= 0:
            return {
                "lot_size": lot_size,
                "entry_price": float(entry_price),  # numeric-boundary: dto
                "planned_allocation_amount": float(planned_allocation_amount),  # numeric-boundary: dto
                "shares": 0,
                "executable_amount": 0.0,
            }
        raw_shares = int(planned_allocation_amount / entry_price)
        shares = (raw_shares // lot_size) * lot_size
        executable_amount = quantize_money(entry_price * to_decimal(shares))
        if shares <= 0:
            return {
                "lot_size": lot_size,
                "entry_price": float(entry_price),  # numeric-boundary: dto
                "planned_allocation_amount": float(planned_allocation_amount),  # numeric-boundary: dto
                "shares": shares,
                "executable_amount": float(executable_amount),  # numeric-boundary: dto
            }
        holding.shares = shares
        holding.allocation_amount = float(executable_amount)  # numeric-boundary: dto
        return None

    def _release_exited_holdings(
        self,
        *,
        rebalance_ts: pd.Timestamp,
        active_holdings: List[PeriodHoldingDTO],
        cash_ledger: List[Dict[str, Any]],
        available_cash: Decimal,
        fee_bps: float | None,
        slippage_bps: float | None,
        tax_bps: float | None,
    ) -> tuple[Decimal, Decimal]:
        remaining = []
        released_cost = to_decimal("0.00")
        include_costs = self._has_execution_cost_params(fee_bps, slippage_bps, tax_bps)
        for holding in active_holdings:
            exit_ts = pd.to_datetime(holding.actual_exit_date)
            if exit_ts <= rebalance_ts:
                gross_amount = quantize_money(to_decimal(holding.allocation_amount) + to_decimal(holding.pnl()))
                sell_costs = self._build_execution_costs(
                    gross_amount=gross_amount,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    tax_bps=tax_bps,
                    include_tax=True,
                )
                sell_amount = quantize_money(gross_amount - sell_costs["total"])
                available_cash = quantize_money(available_cash + sell_amount)
                released_cost = quantize_money(released_cost + sell_costs["total"])
                cash_ledger.append(
                    self._build_cash_ledger_row(
                        date=holding.actual_exit_date,
                        stock_code=holding.stock_code,
                        event="sell",
                        gross_amount=gross_amount,
                        costs=sell_costs,
                        net_amount=sell_amount,
                        cash_balance=available_cash,
                        include_costs=include_costs,
                    )
                )
            else:
                remaining.append(holding)
        active_holdings[:] = remaining
        return available_cash, released_cost

    def _build_period_holding(
        self,
        data: pd.DataFrame,
        rec: Dict[str, Any],
        rank: int,
        rebalance_ts: pd.Timestamp,
        planned_exit_ts: pd.Timestamp,
        allocation_amount: float,
        allocation_weight: float,
        stop_loss_pct: float | None,
        take_profit_pct: float | None,
    ) -> PeriodHoldingDTO | None:
        code = str(rec["stock_code"])
        stock_rows = data[
            (data["證券代號"].astype(str) == code)
            & (data["日期"] >= rebalance_ts)
            & (data["日期"] <= planned_exit_ts)
        ]
        if stock_rows.empty:
            return None

        entry_row = stock_rows.iloc[0]
        entry_price = float(entry_row["收盤價"])  # numeric-boundary: analytics
        exit_row, exit_reason = self._select_exit_row(
            stock_rows=stock_rows,
            entry_price=entry_price,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        exit_price = float(exit_row["收盤價"])  # numeric-boundary: analytics
        return_pct = round((exit_price / entry_price) - 1, 10) if entry_price else 0.0
        actual_exit_ts = pd.to_datetime(exit_row["日期"])
        return PeriodHoldingDTO(
            rebalance_date=rebalance_ts.strftime("%Y-%m-%d"),
            stock_code=code,
            stock_name=str(rec.get("stock_name") or entry_row.get("證券名稱", "")),
            rank=rank,
            total_score=float(rec.get("total_score", 0.0)),  # numeric-boundary: dto
            factor_scores=dict(rec.get("factor_scores", {})),
            allocation_amount=allocation_amount,
            allocation_weight=allocation_weight,
            entry_date=pd.to_datetime(entry_row["日期"]).strftime("%Y-%m-%d"),
            entry_price=entry_price,
            planned_exit_date=planned_exit_ts.strftime("%Y-%m-%d"),
            actual_exit_date=actual_exit_ts.strftime("%Y-%m-%d"),
            actual_exit_price=exit_price,
            exit_reason=exit_reason,
            holding_days=(actual_exit_ts - pd.to_datetime(entry_row["日期"])).days,
            return_pct=return_pct,
        )

    def _select_exit_row(
        self,
        stock_rows: pd.DataFrame,
        entry_price: float,
        stop_loss_pct: float | None,
        take_profit_pct: float | None,
    ) -> tuple[pd.Series, str]:
        if entry_price <= 0:
            return stock_rows.iloc[-1], "holding_period"

        for _, row in stock_rows.iloc[1:].iterrows():
            price = float(row["收盤價"])  # numeric-boundary: analytics
            return_pct = (price / entry_price) - 1
            if stop_loss_pct is not None and return_pct <= -abs(stop_loss_pct):
                return row, "stop_loss"
            if take_profit_pct is not None and return_pct >= abs(take_profit_pct):
                return row, "take_profit"

        return stock_rows.iloc[-1], "holding_period"

    def _build_trade_rows(self, holding: PeriodHoldingDTO) -> List[Dict[str, Any]]:
        return [
            {
                "date": holding.entry_date,
                "stock_code": holding.stock_code,
                "stock_name": holding.stock_name,
                "side": "buy",
                "price": holding.entry_price,
                "amount": holding.allocation_amount,
            },
            {
                "date": holding.actual_exit_date,
                "stock_code": holding.stock_code,
                "stock_name": holding.stock_name,
                "side": "sell",
                "price": holding.actual_exit_price,
                "amount": holding.allocation_amount + holding.pnl(),
            },
        ]

    def _build_equity_curve(
        self,
        initial_capital: float,
        holdings: List[PeriodHoldingDTO],
        start_ts: pd.Timestamp,
        end_ts: pd.Timestamp,
        data: pd.DataFrame,
    ) -> pd.DataFrame:
        trading_dates = (
            data[(data["日期"] >= start_ts) & (data["日期"] <= end_ts)]["日期"]
            .drop_duplicates()
            .sort_values()
            .tolist()
        )
        if not trading_dates:
            trading_dates = [start_ts, end_ts]

        rows = []
        for value in trading_dates:
            ts = pd.to_datetime(value)
            equity = initial_capital
            for holding in holdings:
                equity += self._holding_pnl_at_date(holding, data, ts)
            rows.append({"date": ts.strftime("%Y-%m-%d"), "equity": round(float(equity), 6)})  # numeric-boundary: dto

        if rows and rows[0]["date"] != start_ts.strftime("%Y-%m-%d"):
            rows.insert(0, {"date": start_ts.strftime("%Y-%m-%d"), "equity": initial_capital})
        if rows and rows[-1]["date"] != end_ts.strftime("%Y-%m-%d"):
            final_equity = initial_capital + sum(holding.pnl() for holding in holdings)
            rows.append({"date": end_ts.strftime("%Y-%m-%d"), "equity": round(float(final_equity), 6)})  # numeric-boundary: dto
        return pd.DataFrame(rows)

    def _holding_pnl_at_date(
        self,
        holding: PeriodHoldingDTO,
        data: pd.DataFrame,
        ts: pd.Timestamp,
    ) -> float:
        entry_ts = pd.to_datetime(holding.entry_date)
        exit_ts = pd.to_datetime(holding.actual_exit_date)
        if ts < entry_ts:
            return 0.0
        if ts >= exit_ts:
            return holding.pnl()

        stock_rows = data[
            (data["證券代號"].astype(str) == holding.stock_code)
            & (data["日期"] >= entry_ts)
            & (data["日期"] <= ts)
        ].sort_values("日期")
        if stock_rows.empty or not holding.entry_price:
            return 0.0

        current_price = float(stock_rows.iloc[-1]["收盤價"])  # numeric-boundary: analytics
        return_pct = (to_decimal(current_price) / to_decimal(holding.entry_price)) - to_decimal("1")
        return float(quantize_money(to_decimal(holding.allocation_amount) * return_pct))  # numeric-boundary: dto

    def _calculate_weights(self, recommendations: List[Dict[str, Any]], allocation_method: str) -> List[float]:
        if allocation_method == "score_weight":
            scores = [max(float(item.get("total_score", 0.0)), 0.0) for item in recommendations]  # numeric-boundary: analytics
            total = sum(scores)
            if total > 0:
                return [score / total for score in scores]
        return [1.0 / len(recommendations)] * len(recommendations)

    def _weight_from_amount(self, *, amount: Decimal, initial_capital: float) -> float:
        capital = to_decimal(initial_capital)
        if capital <= 0:
            return 0.0
        return float((amount / capital).quantize(Decimal("0.000001")))  # numeric-boundary: dto

    def _build_weight_exposure(
        self,
        *,
        period_holdings: List[PeriodHoldingDTO],
        unfilled_orders: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        period_keys = sorted(
            {holding.rebalance_date for holding in period_holdings}
            | {
                str(order.get("rebalance_date", ""))
                for order in unfilled_orders
                if order.get("rebalance_date")
            }
        )
        periods = []
        for rebalance_date in period_keys:
            holdings = [holding for holding in period_holdings if holding.rebalance_date == rebalance_date]
            orders = [order for order in unfilled_orders if order.get("rebalance_date") == rebalance_date]
            target_weight = sum(
                (to_decimal(holding.allocation_weight) for holding in holdings),
                to_decimal("0"),
            )
            target_weight += sum(
                (to_decimal(order.get("allocation_weight", 0)) for order in orders),
                to_decimal("0"),
            )
            actual_weight = sum(
                (to_decimal(holding.actual_allocation_weight or 0) for holding in holdings),
                to_decimal("0"),
            )
            unfilled_weight = sum(
                (to_decimal(order.get("allocation_weight", 0)) for order in orders),
                to_decimal("0"),
            )
            cash_residual_weight = max(to_decimal("0"), target_weight - actual_weight - unfilled_weight)
            periods.append(
                {
                    "rebalance_date": rebalance_date,
                    "target_weight": float(target_weight.quantize(Decimal("0.000001"))),  # numeric-boundary: dto
                    "actual_weight": float(actual_weight.quantize(Decimal("0.000001"))),  # numeric-boundary: dto
                    "unfilled_weight": float(unfilled_weight.quantize(Decimal("0.000001"))),  # numeric-boundary: dto
                    "cash_residual_weight": float(cash_residual_weight.quantize(Decimal("0.000001"))),  # numeric-boundary: dto
                    "holding_count": len(holdings),
                    "unfilled_order_count": len(orders),
                }
            )
        return {
            "schema_version": 1,
            "supported": "partial",
            "policy": "target_weight_vs_executable_weight_by_rebalance_date",
            "periods": periods,
        }

    def _build_gap_risk_manifest(
        self,
        holdings: List[PeriodHoldingDTO],
        data: pd.DataFrame,
    ) -> Dict[str, Any]:
        records = []
        if "開盤價" not in data.columns:
            return {
                "schema_version": 1,
                "supported": "partial",
                "policy": "next_open_gap_labels_when_open_price_available",
                "record_count": 0,
                "max_abs_gap_pct": 0.0,
                "records": records,
            }
        for holding in holdings:
            entry_ts = pd.to_datetime(holding.entry_date)
            stock_rows = data[
                (data["證券代號"].astype(str) == holding.stock_code)
                & (data["日期"] > entry_ts)
            ].sort_values("日期")
            if stock_rows.empty:
                continue
            next_row = stock_rows.iloc[0]
            next_open = pd.to_numeric(next_row["開盤價"], errors="coerce")
            if pd.isna(next_open) or holding.entry_price <= 0:
                continue
            gap_pct = self._quantize_ratio(
                (to_decimal(next_open) / to_decimal(holding.entry_price)) - to_decimal("1")
            )
            records.append(
                {
                    "stock_code": holding.stock_code,
                    "stock_name": holding.stock_name,
                    "rebalance_date": holding.rebalance_date,
                    "entry_date": holding.entry_date,
                    "entry_close_price": holding.entry_price,
                    "next_open_date": pd.to_datetime(next_row["日期"]).strftime("%Y-%m-%d"),
                    "next_open_price": float(next_open),  # numeric-boundary: dto
                    "gap_pct": gap_pct,
                    "gap_direction": self._gap_direction(gap_pct),
                    "severity": self._gap_severity(gap_pct),
                }
            )
        max_abs_gap = max((abs(to_decimal(record["gap_pct"])) for record in records), default=to_decimal("0"))
        return {
            "schema_version": 1,
            "supported": "partial",
            "policy": "next_open_gap_labels_when_open_price_available",
            "record_count": len(records),
            "max_abs_gap_pct": float(max_abs_gap.quantize(Decimal("0.000001"))),  # numeric-boundary: dto
            "records": records,
        }

    def _quantize_ratio(self, value: Decimal) -> float:
        return float(value.quantize(Decimal("0.000001")))  # numeric-boundary: dto

    def _gap_direction(self, gap_pct: float) -> str:
        gap = to_decimal(gap_pct)
        if gap > 0:
            return "gap_up"
        if gap < 0:
            return "gap_down"
        return "flat"

    def _gap_severity(self, gap_pct: float) -> str:
        gap = abs(to_decimal(gap_pct))
        if gap >= to_decimal("0.05"):
            return "high"
        if gap >= to_decimal("0.02"):
            return "medium"
        return "low"

    def _build_stock_contribution(self, holdings: List[PeriodHoldingDTO]) -> List[StockContributionDTO]:
        grouped = defaultdict(list)
        for holding in holdings:
            grouped[(holding.stock_code, holding.stock_name)].append(holding)

        results = []
        for (code, name), items in grouped.items():
            returns = [item.return_pct for item in items]
            wins = [value for value in returns if value > 0]
            results.append(
                StockContributionDTO(
                    stock_code=code,
                    stock_name=name,
                    selected_count=len(items),
                    total_pnl=sum(item.pnl() for item in items),
                    avg_return_pct=sum(returns) / len(returns),
                    win_rate=len(wins) / len(returns),
                    worst_return_pct=min(returns),
                )
            )
        return sorted(results, key=lambda item: item.total_pnl, reverse=True)

    def _build_credibility_manifest(
        self,
        *,
        rebalance_frequency: str,
        allocation_method: str,
        max_participation_rate: float | None = None,
        fee_bps: float | None = None,
        slippage_bps: float | None = None,
        tax_bps: float | None = None,
        lot_size: int | None = None,
    ) -> Dict[str, Any]:
        liquidity_supported: bool | str = "partial" if max_participation_rate else False
        liquidity_policy = (
            "entry_day_volume_participation_checked"
            if max_participation_rate
            else "volume_limit_and_gap_risk_not_applied"
        )
        execution_costs_supported: bool | str = (
            "partial" if self._has_execution_cost_params(fee_bps, slippage_bps, tax_bps) else False
        )
        execution_costs_policy = (
            "fee_tax_slippage_bps_applied_to_cash_ledger"
            if execution_costs_supported
            else "not_applied"
        )
        warnings = [
            "rebalance_cash_reuse_partial",
            "liquidity_gap_not_modeled",
            "same_day_close_execution_assumption",
        ]
        return {
            "schema_version": 1,
            "status": "limited",
            "execution_assumption": "idealized_same_day_close",
            "rebalance_frequency": rebalance_frequency,
            "allocation_method": allocation_method,
            "cash_account": {
                "supported": "order_sizing",
                "policy": "available_cash_checked_before_holding_creation",
            },
            "rebalance": {
                "supported": False,
                "policy": "period_holdings_are_independent_replay_slices",
            },
            "unfilled_orders": {
                "supported": True,
                "policy": "missing_price_rows_are_recorded_as_unfilled_orders",
            },
            "weights": {
                "supported": "partial",
                "policy": "target_and_actual_executable_weights_reported",
            },
            "liquidity_gap": {
                "supported": liquidity_supported,
                "policy": liquidity_policy,
                "max_participation_rate": max_participation_rate,
            },
            "gap_risk": {
                "supported": "partial",
                "policy": "next_open_gap_labels_when_open_price_available",
            },
            "execution_costs": {
                "supported": execution_costs_supported,
                "policy": execution_costs_policy,
                "fee_bps": fee_bps,
                "slippage_bps": slippage_bps,
                "tax_bps": tax_bps,
            },
            "share_sizing": {
                "supported": "partial" if lot_size else False,
                "policy": "full_lot_floor_sizing" if lot_size else "money_allocation_without_share_sizing",
                "lot_size": lot_size,
            },
            "warnings": warnings,
        }

    def _build_factor_manifest(
        self,
        snapshots: List[RecommendationSnapshotDTO],
    ) -> Dict[str, Any]:
        factor_service = FactorService()
        combined_snapshot: Dict[str, Any] = {
            "schema_version": 1,
            "factor_set_version": "factor-layer-v1",
            "decision_date": snapshots[-1].as_of_date if snapshots else "",
            "decision_dates": [snapshot.as_of_date for snapshot in snapshots],
            "records": [],
            "neutralized": [],
            "skipped": [],
            "diagnostics": [],
        }

        for snapshot in snapshots:
            records = self._factor_records_from_snapshot(snapshot)
            if not records:
                continue
            decision_date = date.fromisoformat(snapshot.as_of_date)
            gated = factor_service.build_snapshot(records, decision_date=decision_date)
            combined_snapshot["records"].extend(gated["records"])
            combined_snapshot["neutralized"].extend(gated["neutralized"])
            combined_snapshot["skipped"].extend(gated["skipped"])
            combined_snapshot["diagnostics"].extend(gated["diagnostics"])

        return {
            "factor_snapshot": combined_snapshot,
            "factor_contributions": factor_service.build_contributions(combined_snapshot),
        }

    def _factor_records_from_snapshot(
        self,
        snapshot: RecommendationSnapshotDTO,
    ) -> List[FactorRecord]:
        as_of_date = date.fromisoformat(snapshot.as_of_date)
        records: List[FactorRecord] = []
        for recommendation in snapshot.recommendations:
            stock_code = str(recommendation.get("stock_code", ""))
            if not stock_code:
                continue
            if recommendation.get("total_score") is not None:
                records.append(
                    build_technical_total_score_factor(
                        stock_code=stock_code,
                        as_of_date=as_of_date,
                        available_date=as_of_date,
                        total_score=Decimal(str(recommendation["total_score"])),
                    )
                )

            factor_scores = recommendation.get("factor_scores", {})
            if isinstance(factor_scores, dict) and factor_scores.get("volume") is not None:
                volume_score = Decimal(str(factor_scores["volume"]))
                records.append(
                    FactorRecord(
                        factor_name="volume.volume_ratio",
                        stock_code=stock_code,
                        as_of_date=as_of_date,
                        available_date=as_of_date,
                        value=volume_score,
                        score_bp=self._score_to_bp(volume_score),
                        quality=FactorQuality.OBSERVED,
                        missing_policy=MissingPolicy.NEUTRAL,
                        source_version="volume-v1",
                        metadata={"source_field": "factor_scores.volume"},
                    )
                )
        return records

    def _score_to_bp(self, score: Decimal) -> int:
        score_bp = (score * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)
        return max(0, min(10000, int(score_bp)))

    def _build_exit_diagnostics(
        self,
        holdings: List[PeriodHoldingDTO],
        stock_contribution: List[StockContributionDTO],
    ) -> Dict[str, Any]:
        total = len(holdings)
        loss_count = len([holding for holding in holdings if holding.return_pct < 0])
        worst_stock = min(stock_contribution, key=lambda item: item.total_pnl) if stock_contribution else None
        return {
            "stop_loss_exits": len([holding for holding in holdings if holding.exit_reason == "stop_loss"]),
            "take_profit_exits": len([holding for holding in holdings if holding.exit_reason == "take_profit"]),
            "holding_period_exits": len([holding for holding in holdings if holding.exit_reason == "holding_period"]),
            "loss_trade_ratio": loss_count / total if total else 0.0,
            "worst_stock_code": worst_stock.stock_code if worst_stock else "",
            "worst_stock_name": worst_stock.stock_name if worst_stock else "",
            "worst_stock_pnl": worst_stock.total_pnl if worst_stock else 0.0,
        }

    def _calculate_max_drawdown(self, equity: pd.Series) -> float:
        if equity.empty:
            return 0.0
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max
        return float(drawdown.min())  # numeric-boundary: analytics
