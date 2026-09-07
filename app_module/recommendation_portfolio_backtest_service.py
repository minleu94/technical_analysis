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
from app_module.recommendation_portfolio_metrics import (
    calculate_robustness_metrics,
    calculate_rolling_risk_metrics,
    generate_improvement_hints,
)
from app_module.recommendation_replay_service import RecommendationReplayService
from data_module.microstructure_source_preflight import build_microstructure_source_preflight
from decision_module.factors.factor_adapters import build_technical_total_score_factor
from decision_module.factors.factor_dtos import FactorQuality, FactorRecord, MissingPolicy
from financial_module.units import bps_to_rate, calculate_fee, quantize_money, to_decimal
from backtest_module.broker_simulator import (
    NEXT_OPEN_CONTRACT, LEGACY_CLOSE_CONTRACT, executable_open, exact_execution_costs,
)
from backtest_module.conservative_fill_policy import ConservativeFillPolicy
from app_module.recommendation_portfolio_result_support import build_credibility_manifest, build_factor_manifest, build_relative_attribution, build_stock_contribution, return_bp_from_values


_LIMIT_LOCK_FIELDS = (
    "limit_up_down_flag",
    "limit_lock",
    "漲跌停標示",
    "漲停鎖死",
    "跌停鎖死",
)
_LIMIT_LOCK_MARKERS = frozenset(
    {
        "1",
        "true",
        "yes",
        "locked",
        "limit_lock",
        "limit_up_lock",
        "limit_down_lock",
        "漲停鎖死",
        "跌停鎖死",
    }
)


def _row_observes_limit_lock(row: Any) -> bool:
    """Return true only for an explicit same-session lock observation.

    A next-open price equal to a theoretical +/-10% boundary is not enough to
    infer a locked order book.  The replay may enforce the conservative price
    limit only when the supplied row carries an explicit lock marker.
    """

    if row is None:
        return False
    for field in _LIMIT_LOCK_FIELDS:
        if field not in row.index:
            continue
        value = row[field]
        if pd.isna(value):
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float, Decimal)):
            return to_decimal(value) != 0
        return str(value).strip().lower() in _LIMIT_LOCK_MARKERS
    return False


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
        execution_contract: str = NEXT_OPEN_CONTRACT,
        check_cancel: Callable[[], bool] | None = None,
    ) -> RecommendationPortfolioBacktestResultDTO:
        """
        執行推薦組合回測。

        注意：目前本服務進場點（PeriodHoldingDTO.entry_price）採用 rebalance_ts（訊號日）當天的收盤價。
        此模式隱含「同日收盤訊號同日收盤成交」之理想化研究假設，在實盤操作中可能存在時間差而無法以該價格買入。
        """
        if execution_contract == NEXT_OPEN_CONTRACT:
            return self._run_next_open_portfolio(
                start_date=start_date, end_date=end_date, profile_id=profile_id,
                config=recommendation_config, history=history, initial_capital=initial_capital,
                rebalance_frequency=rebalance_frequency, top_n=top_n,
                allocation_method=allocation_method, holding_days=holding_days,
                stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct,
                max_participation_rate=max_participation_rate, fee_bps=fee_bps,
                slippage_bps=slippage_bps, tax_bps=tax_bps,
                lot_size=lot_size or 1, check_cancel=check_cancel,
            )
        if execution_contract != LEGACY_CLOSE_CONTRACT:
            raise ValueError("不支援的 execution_contract")
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
            rolling_risk_metrics = calculate_rolling_risk_metrics(
                equity_curve=equity_curve,
                period_holdings=period_holdings,
            )
            microstructure_preflight = self._build_microstructure_preflight(snapshots, data)
            relative_attribution = self._build_relative_attribution(equity_curve, data)
            details = {
                "data_manifest": self._build_factor_manifest(snapshots),
                "portfolio_credibility": credibility_manifest,
                "unfilled_orders": unfilled_orders,
                "cash_ledger": cash_ledger,
                "weight_exposure": weight_exposure,
                "gap_risk": gap_risk,
                "rolling_risk_metrics": rolling_risk_metrics,
                "microstructure_preflight": microstructure_preflight,
                "relative_attribution": relative_attribution,
            }
            return RecommendationPortfolioBacktestResultDTO(
                summary={
                    "total_return": 0.0,
                    "max_drawdown": 0.0,
                    "total_trades": 0,
                    "execution_assumption": "idealized_same_day_close",
                    "execution_contract": LEGACY_CLOSE_CONTRACT,
                    "credibility_status": credibility_manifest["status"],
                    "credibility_warning_count": len(credibility_manifest["warnings"]),
                    "unfilled_order_count": len(unfilled_orders),
                    "ending_cash": ending_cash,
                    "total_transaction_cost": total_transaction_cost_float,
                    "rolling_risk_status": rolling_risk_metrics["status"],
                    "microstructure_risk_count": microstructure_preflight["risk_count"],
                    "relative_attribution_status": relative_attribution["status"],
                    "benchmark_excess_return_bp": self._benchmark_excess_return_bp(relative_attribution),
                },
                equity_curve=equity_curve,
                trades=pd.DataFrame(),
                snapshots=snapshots,
                period_holdings=[],
                stock_contribution=[],
                selection_diagnostics=(
                    ["no_recommendations"]
                    + self._unfilled_order_diagnostics(unfilled_orders)
                    + self._microstructure_preflight_diagnostics(microstructure_preflight)
                ),
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
            "execution_contract": LEGACY_CLOSE_CONTRACT,
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
        rolling_risk_metrics = calculate_rolling_risk_metrics(
            equity_curve=equity_curve,
            period_holdings=period_holdings,
        )
        microstructure_preflight = self._build_microstructure_preflight(snapshots, data)
        relative_attribution = self._build_relative_attribution(equity_curve, data)
        summary["rolling_risk_status"] = rolling_risk_metrics["status"]
        summary["microstructure_risk_count"] = microstructure_preflight["risk_count"]
        summary["relative_attribution_status"] = relative_attribution["status"]
        summary["benchmark_excess_return_bp"] = self._benchmark_excess_return_bp(relative_attribution)
        details = {
            "data_manifest": self._build_factor_manifest(snapshots),
            "portfolio_credibility": credibility_manifest,
            "unfilled_orders": unfilled_orders,
            "cash_ledger": cash_ledger,
            "weight_exposure": weight_exposure,
            "gap_risk": gap_risk,
            "rolling_risk_metrics": rolling_risk_metrics,
            "microstructure_preflight": microstructure_preflight,
            "relative_attribution": relative_attribution,
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
            ]
            + self._unfilled_order_diagnostics(unfilled_orders)
            + self._microstructure_preflight_diagnostics(microstructure_preflight),
            improvement_hints=improvement_hints,
            details=details,
        )

    def _run_next_open_portfolio(
        self, *, start_date: str, end_date: str, profile_id: str,
        config: Dict[str, Any], history: pd.DataFrame, initial_capital: Any,
        rebalance_frequency: str, top_n: int, allocation_method: str, holding_days: int,
        stop_loss_pct: Any, take_profit_pct: Any, max_participation_rate: Any,
        fee_bps: Any, slippage_bps: Any, tax_bps: Any, lot_size: int,
        check_cancel: Callable[[], bool] | None,
        include_benchmark: bool = True,
    ) -> RecommendationPortfolioBacktestResultDTO:
        """日序事件撮合；精確帳務直到 DTO 產出才轉展示型別。"""
        capital = quantize_money(to_decimal(initial_capital))
        if not capital.is_finite() or capital <= 0 or top_n < 1 or holding_days < 1 or lot_size < 1:
            raise ValueError("資金、top_n、holding_days 與 lot_size 必須為正數")
        if rebalance_frequency not in {"once", "weekly"} or allocation_method not in {"equal_weight", "score_weight"}:
            raise ValueError("不支援的再平衡或配置方式")
        for threshold in (stop_loss_pct, take_profit_pct, max_participation_rate):
            if threshold is not None and (not to_decimal(threshold).is_finite() or to_decimal(threshold) <= 0):
                raise ValueError("風控與成交量比例必須為有限正數")
        exact_execution_costs(Decimal("0"), side="sell", fee_bps=fee_bps, slippage_bps=slippage_bps, tax_bps=tax_bps)
        data = history.copy()
        if not {"日期", "證券代號", "收盤價"}.issubset(data.columns):
            raise ValueError("歷史資料缺少日期、證券代號或收盤價")
        data["日期"] = parse_stock_dates(data["日期"])
        if data["日期"].isna().any():
            raise ValueError("歷史日期不可解析")
        data["證券代號"] = data["證券代號"].astype(str)
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        if end < start:
            raise ValueError("end_date 不得早於 start_date")
        data = data[data["日期"] <= end].sort_values(["日期", "證券代號"])
        if data.duplicated(["日期", "證券代號"]).any():
            raise ValueError("每檔股票每日只能有一筆市場資料")
        rebalance_dates = set(self._get_rebalance_dates(data, start, end, rebalance_frequency))
        sessions = sorted(data.loc[data["日期"] >= start, "日期"].unique())
        cash, cost_total = capital, Decimal("0")
        positions: dict[str, dict[str, Any]] = {}
        all_positions: list[dict[str, Any]] = []
        pending: dict[str, dict[str, Any]] = {}
        snapshots: list[RecommendationSnapshotDTO] = []
        trade_rows: list[dict[str, Any]] = []
        cash_ledger: list[dict[str, Any]] = []
        curve_rows: list[dict[str, Any]] = []
        unfilled: list[dict[str, Any]] = []
        diagnostics: list[str] = []
        cancelled = False
        peak, max_drawdown = capital, Decimal("0")
        final_equity = capital
        fill_policy = ConservativeFillPolicy(
            lot_size=lot_size,
            max_participation_rate=max_participation_rate,
            enable_limit_up_down=True,
            limit_up_down_pct=Decimal("0.10"),
            apply_volume_to_sell=False,
        )

        for raw_session in sessions:
            if check_cancel is not None and check_cancel():
                cancelled = True
                break
            session = pd.Timestamp(raw_session)
            day = {str(row["證券代號"]): row for _, row in data[data["日期"] == session].iterrows()}
            # 每日先賣再買；只有實際賣出後的現金才能被當天新買單消費。
            ordered = sorted(pending.items(), key=lambda item: (item[1]["side"] != "sell", item[1]["rank"], item[0]))
            for code, order in ordered:
                row = day.get(code)
                price = executable_open(row) if row is not None else None
                if price is None:
                    order["last_reason"] = "missing_open_or_suspended"
                    continue
                side = order["side"]
                if side == "buy":
                    budget = min(order["budget"], cash)
                    buy_rate = (to_decimal(fee_bps or 0) + to_decimal(slippage_bps or 0)) / Decimal("10000")
                    shares = int(budget / (price * (Decimal("1") + buy_rate))) // lot_size * lot_size
                else:
                    budget = cash
                    shares = positions[code]["shares"]
                while shares > 0:
                    gross = quantize_money(price * shares)
                    costs = exact_execution_costs(gross, side=side, fee_bps=fee_bps, slippage_bps=slippage_bps, tax_bps=tax_bps)
                    if side == "sell" or gross + costs["total"] <= budget:
                        break
                    shares -= lot_size
                decision = fill_policy.decide(
                    side=side,
                    requested_shares=shares,
                    open_price=price,
                    # 價位剛好落在理論漲跌停邊界，不足以證明「鎖死」。
                    # 只有同一執行日有官方/明示的鎖死欄位時，才把前收傳給
                    # ConservativeFillPolicy；缺少該來源時由 preflight 揭露
                    # 限制，避免把未知狀態誤判成不可成交。
                    prior_close=(
                        order.get("signal_close")
                        if _row_observes_limit_lock(row)
                        else None
                    ),
                    known_volume=order.get("volume"),
                )
                if decision.status == "unfilled":
                    unfilled.append({"stock_code": code, "signal_date": order["signal_date"], "rebalance_date": order["signal_date"], "allocation_weight": float(order.get("weight", 0)), "reason": decision.reason or "insufficient_cash_or_known_volume", "side": side, "requested_shares": decision.requested_shares, "fill_status": decision.status})  # numeric-boundary: dto
                    del pending[code]
                    continue
                shares = decision.filled_shares
                if shares <= 0:
                    unfilled.append({"stock_code": code, "signal_date": order["signal_date"], "rebalance_date": order["signal_date"], "allocation_weight": float(order.get("weight", 0)), "reason": "insufficient_cash_or_known_volume", "side": side})  # numeric-boundary: dto
                    del pending[code]
                    continue
                gross = quantize_money(price * shares)
                costs = exact_execution_costs(gross, side=side, fee_bps=fee_bps, slippage_bps=slippage_bps, tax_bps=tax_bps)
                cost_total += costs["total"]
                if side == "buy":
                    cash = quantize_money(cash - gross - costs["total"])
                    position = {**order, "stock_code": code, "shares": shares, "entry_date": session,
                                "entry_price": price, "entry_gross": gross, "entry_cost": costs["total"],
                                "mark": price, "status": "open", "exit_reason": "end_of_data_open",
                                "exit_signal_date": "", "exit_date": None, "exit_price": Decimal("0"), "exit_cost": Decimal("0")}
                    positions[code] = position
                    all_positions.append(position)
                else:
                    cash = quantize_money(cash + gross - costs["total"])
                    position = positions.pop(code)
                    position.update(status="closed", exit_date=session, exit_price=price,
                                    exit_cost=costs["total"], exit_signal_date=order["signal_date"], exit_reason=order["reason"])
                trade_rows.append({"date": session.strftime("%Y-%m-%d"), "signal_date": order["signal_date"],
                                   "stock_code": code, "stock_name": order["stock_name"], "side": side,
                                   "price": float(price), "shares": shares, "amount": float(gross),  # numeric-boundary: dto
                                   "fee": float(costs["fee"]), "tax": float(costs["tax"]), "slippage": float(costs["slippage"]),  # numeric-boundary: dto
                                   "requested_shares": decision.requested_shares, "unfilled_shares": decision.unfilled_shares,
                                   "fill_status": decision.status, "fill_reason": decision.reason,
                                   "execution_contract": NEXT_OPEN_CONTRACT})
                cash_ledger.append({"date": session.strftime("%Y-%m-%d"), "stock_code": code, "side": side,
                                    "amount": float(gross), "total_cost": float(costs["total"]), "cash_balance": float(cash)})  # numeric-boundary: dto
                del pending[code]

            for code, position in positions.items():
                row = day.get(code)
                if row is not None and pd.notna(row["收盤價"]) and to_decimal(row["收盤價"]) > 0:
                    position["mark"] = to_decimal(row["收盤價"])
                else:
                    diagnostics.append(f"stale_mark:{code}:{session.date()}")
                if code in pending:
                    continue
                change = position["mark"] / position["entry_price"] - Decimal("1")
                reason = None
                if stop_loss_pct is not None and change <= -abs(to_decimal(stop_loss_pct)):
                    reason = "stop_loss_close_confirmed"
                elif take_profit_pct is not None and change >= abs(to_decimal(take_profit_pct)):
                    reason = "take_profit_close_confirmed"
                elif session >= position["entry_date"] + pd.Timedelta(days=holding_days):
                    reason = "holding_period_close_confirmed"
                if reason:
                    pending[code] = {**position, "side": "sell", "signal_date": session.strftime("%Y-%m-%d"), "reason": reason}

            value = sum((position["mark"] * position["shares"] for position in positions.values()), Decimal("0"))
            final_equity = quantize_money(cash + value)
            peak = max(peak, final_equity)
            max_drawdown = min(max_drawdown, final_equity / peak - Decimal("1"))
            curve_rows.append({"date": session.strftime("%Y-%m-%d"), "equity": float(final_equity), "cash": float(cash), "position_value": float(quantize_money(value))})  # numeric-boundary: dto
            if session in rebalance_dates:
                snapshot = self.replay_service.run_snapshot(as_of_date=session.strftime("%Y-%m-%d"), profile_id=profile_id,
                    config=dict(config), history=data, universe=None, top_n=top_n)
                snapshots.append(snapshot)
                recs = snapshot.recommendations
                scores = [max(to_decimal(rec.get("total_score", 0)), Decimal("0")) for rec in recs]
                total_score = sum(scores, Decimal("0"))
                for rank, rec in enumerate(recs, 1):
                    code = str(rec["stock_code"])
                    if code in positions or code in pending:
                        continue
                    weight = scores[rank - 1] / total_score if allocation_method == "score_weight" and total_score > 0 else Decimal("1") / len(recs)
                    source_row = day.get(code)
                    volume = next((to_decimal(source_row[c]) for c in ("成交股數", "成交量", "Volume", "volume") if source_row is not None and c in source_row and pd.notna(source_row[c])), None)
                    pending[code] = {"side": "buy", "signal_date": session.strftime("%Y-%m-%d"), "stock_name": str(rec.get("stock_name", "")),
                        "rank": rank, "weight": weight, "budget": quantize_money(capital * weight), "score": rec.get("total_score", 0),
                        "factor_scores": dict(rec.get("factor_scores", {})), "volume": volume,
                        "signal_close": to_decimal(source_row["收盤價"]) if source_row is not None and pd.notna(source_row["收盤價"]) else None}
        for code, order in pending.items():
            unfilled.append({"stock_code": code, "signal_date": order["signal_date"], "side": order["side"],
                             "rebalance_date": order["signal_date"], "allocation_weight": float(order.get("weight", 0)) if order["side"] == "buy" else 0,  # numeric-boundary: dto
                             "reason": "cancelled" if cancelled else order.get("last_reason", "end_of_data")})
        if not curve_rows:
            curve_rows = [{"date": start.strftime("%Y-%m-%d"), "equity": float(capital), "cash": float(capital), "position_value": 0}]  # numeric-boundary: dto
        holdings: list[PeriodHoldingDTO] = []
        contribution_groups: dict[str, list[tuple[dict[str, Any], Decimal, Decimal]]] = {}
        realized = Decimal("0")
        for position in all_positions:
            exit_price = position["exit_price"] if position["status"] == "closed" else position["mark"]
            pnl = quantize_money((exit_price - position["entry_price"]) * position["shares"] - position["entry_cost"] - position["exit_cost"])
            if position["status"] == "closed":
                realized += pnl
            contribution_groups.setdefault(position["stock_code"], []).append((position, pnl, pnl / position["entry_gross"]))
            last = position["exit_date"] or pd.Timestamp(curve_rows[-1]["date"])
            holdings.append(PeriodHoldingDTO(
                rebalance_date=position["signal_date"], stock_code=position["stock_code"], stock_name=position["stock_name"], rank=position["rank"],
                total_score=float(position["score"]), factor_scores=position["factor_scores"],  # numeric-boundary: dto
                allocation_amount=float(position["entry_gross"]), allocation_weight=float(position["weight"]),  # numeric-boundary: dto
                entry_date=position["entry_date"].strftime("%Y-%m-%d"), entry_price=float(position["entry_price"]),  # numeric-boundary: dto
                planned_exit_date=(position["entry_date"] + pd.Timedelta(days=holding_days)).strftime("%Y-%m-%d"),
                actual_exit_date=position["exit_date"].strftime("%Y-%m-%d") if position["exit_date"] is not None else "",
                actual_exit_price=float(position["exit_price"]), exit_reason=position["exit_reason"],  # numeric-boundary: dto
                holding_days=(last - position["entry_date"]).days, return_pct=float(pnl / position["entry_gross"]),  # numeric-boundary: dto
                shares=position["shares"], actual_allocation_weight=float(position["entry_gross"] / capital),  # numeric-boundary: dto
                execution_contract=NEXT_OPEN_CONTRACT, position_status=position["status"], exit_signal_date=position["exit_signal_date"],
                pnl_cents=int(pnl * 100),
            ))
        equity_curve = pd.DataFrame(curve_rows)
        contributions = []
        for code, items in contribution_groups.items():
            total_pnl = sum((item[1] for item in items), Decimal("0"))
            returns = [item[2] for item in items]
            contributions.append(StockContributionDTO(stock_code=code, stock_name=items[0][0]["stock_name"], selected_count=len(items),
                total_pnl=float(total_pnl), avg_return_pct=float(sum(returns, Decimal("0")) / len(returns)),  # numeric-boundary: dto
                win_rate=float(Decimal(sum(value > 0 for value in returns)) / len(returns)), worst_return_pct=float(min(returns))))  # numeric-boundary: dto
        # Benchmark 缺同版本撮合／成本資料時明確不可比較，不能沿用 close-to-close excess。
        benchmark: dict[str, Any] = {"status": "not_computable", "policy": "requires_same_execution_contract_and_costs", "execution_contract": NEXT_OPEN_CONTRACT, "benchmarks": {}, "missing_sources": ["aligned_executable_benchmark"]}
        benchmark_excess_bp = None
        if include_benchmark and not cancelled:
            if allocation_method == "equal_weight":
                baseline_equity = final_equity
                baseline_curve = curve_rows
            else:
                frozen = {item.as_of_date: item.recommendations for item in snapshots}
                baseline_service = RecommendationPortfolioBacktestService(lambda frame, *_: frozen.get(frame["日期"].max().strftime("%Y-%m-%d"), []))
                baseline_result = baseline_service._run_next_open_portfolio(start_date=start_date, end_date=end_date,
                    profile_id=profile_id, config=config, history=data, initial_capital=initial_capital,
                    rebalance_frequency=rebalance_frequency, top_n=top_n, allocation_method="equal_weight", holding_days=holding_days,
                    stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct, max_participation_rate=max_participation_rate,
                    fee_bps=fee_bps, slippage_bps=slippage_bps, tax_bps=tax_bps, lot_size=lot_size, check_cancel=None, include_benchmark=False)
                baseline_equity = to_decimal(baseline_result.summary["ending_equity_cents"]) / 100
                baseline_curve = baseline_result.equity_curve.to_dict("records")
            baseline_return = baseline_equity / capital - Decimal("1")
            benchmark_excess_bp = int(((final_equity - baseline_equity) / capital * Decimal("10000")).to_integral_value(rounding=ROUND_HALF_UP))
            benchmark = {"status": "comparable", "policy": "frozen_recommendations_equal_weight_same_costs_sessions",
                "execution_contract": NEXT_OPEN_CONTRACT, "benchmark_type": "equal_weight", "missing_sources": [],
                "benchmarks": {"benchmark": {"status": "observed", "return_bp": int((baseline_return * Decimal("10000")).to_integral_value(rounding=ROUND_HALF_UP)), "excess_return_bp": benchmark_excess_bp}},
                "equity_curve": baseline_curve}
        warnings = ["close_confirmed_exit_only", "price_limit_order_book_not_modeled"]
        if any(value is None for value in (fee_bps, slippage_bps, tax_bps)):
            warnings.append("unspecified_cost_assumptions")
        credibility = {"schema_version": 2, "status": "limited", "execution_assumption": "next_session_open", "execution_contract": NEXT_OPEN_CONTRACT,
            "warnings": warnings, "terminal_policy": "mark_open_positions_without_synthetic_liquidation", "exit_policy": "close_confirmed_next_open",
            "liquidity_policy": "signal_session_known_volume", "share_sizing": {"lot_size": lot_size},
            "execution_costs": {"fee_bps": str(fee_bps or 0), "slippage_bps": str(slippage_bps or 0), "tax_bps": str(tax_bps or 0)}}
        manifest = self._build_factor_manifest(snapshots)
        manifest["execution_contract"] = NEXT_OPEN_CONTRACT
        rolling_risk = calculate_rolling_risk_metrics(equity_curve=equity_curve, period_holdings=holdings)
        microstructure = self._build_microstructure_preflight(snapshots, data)
        gap_records = []
        for position in all_positions:
            signal_close = position["signal_close"]
            if signal_close is None or signal_close <= 0:
                continue
            gap = position["entry_price"] / signal_close - Decimal("1")
            gap_records.append({"stock_code": position["stock_code"], "signal_date": position["signal_date"],
                "execution_date": position["entry_date"].strftime("%Y-%m-%d"),
                "signal_close_price": float(signal_close), "execution_open_price": float(position["entry_price"]), "gap_pct": float(gap),  # numeric-boundary: dto
                "gap_bp": int((gap * 10000).to_integral_value(rounding=ROUND_HALF_UP))})
        gap_risk = {"schema_version": 2, "supported": "partial", "policy": "signal_close_to_actual_execution_open",
                    "records": gap_records, "record_count": len(gap_records)}
        summary = {"total_return": float(final_equity / capital - Decimal("1")), "max_drawdown": float(max_drawdown),  # numeric-boundary: dto
            "total_trades": len([p for p in all_positions if p["status"] == "closed"]), "execution_assumption": "next_session_open", "execution_contract": NEXT_OPEN_CONTRACT,
            "ending_cash": float(cash), "ending_equity": float(final_equity), "total_transaction_cost": float(cost_total), "realized_pnl": float(realized),  # numeric-boundary: dto
            "unrealized_pnl": float(final_equity - capital - realized),  # numeric-boundary: dto
            "ending_equity_cents": int(final_equity * 100), "ending_cash_cents": int(cash * 100),
            "open_position_count": len(positions), "unfilled_order_count": len(unfilled), "status": "cancelled" if cancelled else "completed",
            "rolling_risk_status": rolling_risk["status"], "microstructure_risk_count": microstructure["risk_count"],
            "credibility_status": "limited", "credibility_warning_count": len(warnings), "benchmark_excess_return_bp": benchmark_excess_bp, "relative_attribution_status": benchmark["status"]}
        summary.update(calculate_robustness_metrics(equity_curve=equity_curve, trade_returns=[h.return_pct for h in holdings if h.position_status == "closed"]))
        return RecommendationPortfolioBacktestResultDTO(summary=summary, equity_curve=equity_curve, trades=pd.DataFrame(trade_rows), snapshots=snapshots,
            period_holdings=holdings, stock_contribution=contributions, selection_diagnostics=diagnostics + [str(o["reason"]) for o in unfilled],
            details={"data_manifest": manifest, "execution_contract": NEXT_OPEN_CONTRACT, "portfolio_credibility": credibility,
                     "cash_ledger": cash_ledger, "unfilled_orders": unfilled, "relative_attribution": benchmark, "benchmark_results": benchmark,
                     "weight_exposure": self._build_weight_exposure(period_holdings=holdings, unfilled_orders=unfilled),
                     "gap_risk": gap_risk, "rolling_risk_metrics": rolling_risk, "microstructure_preflight": microstructure})

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
        records: List[Dict[str, Any]] = []
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

    def _build_microstructure_preflight(
        self,
        snapshots: List[RecommendationSnapshotDTO],
        data: pd.DataFrame,
    ) -> Dict[str, Any]:
        source_preflight = build_microstructure_source_preflight(data.columns)
        source_metadata = source_preflight.to_dict()
        source_columns = source_preflight.source_columns
        missing_sources = sorted(source_preflight.missing_sources)
        risks: List[Dict[str, Any]] = []
        if data.empty or "日期" not in data.columns or "證券代號" not in data.columns:
            return {
                "schema_version": 1,
                "status": "missing_required_price_context",
                "policy": "decision_date_optional_microstructure_columns_only",
                **source_metadata,
                "missing_sources": missing_sources,
                "risk_count": 0,
                "risks": [],
            }

        keyed = data.copy()
        keyed["__date_key"] = pd.to_datetime(keyed["日期"], errors="coerce").dt.strftime("%Y-%m-%d")
        keyed["__code_key"] = keyed["證券代號"].astype(str)

        for snapshot in snapshots:
            as_of_date = str(snapshot.as_of_date)
            for recommendation in snapshot.recommendations:
                stock_code = str(recommendation.get("stock_code", ""))
                if not stock_code:
                    continue
                rows = keyed[(keyed["__date_key"] == as_of_date) & (keyed["__code_key"] == stock_code)]
                if rows.empty:
                    continue
                row = rows.iloc[0]
                for risk_type, columns in source_columns.items():
                    for column in columns:
                        value = row.get(column)
                        if self._is_microstructure_flagged(value):
                            risks.append(
                                {
                                    "as_of_date": as_of_date,
                                    "stock_code": stock_code,
                                    "stock_name": str(recommendation.get("stock_name", "")),
                                    "risk_type": risk_type,
                                    "severity": self._microstructure_severity(risk_type),
                                    "source_column": column,
                                    "source_value": str(value),
                                    "policy": "review_execution_assumption_before_using_replay_result",
                                }
                            )
                            break

        status = "risk_observed" if risks else "observed"
        if not risks and missing_sources:
            status = "missing_optional_sources"
        return {
            "schema_version": 1,
            "status": status,
            "policy": "decision_date_optional_microstructure_columns_only",
            **source_metadata,
            "missing_sources": missing_sources,
            "risk_count": len(risks),
            "risks": risks,
        }

    @staticmethod
    def _is_microstructure_flagged(value: Any) -> bool:
        if value is None or pd.isna(value):
            return False
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"", "0", "false", "n", "no", "none", "nan", "-", "無", "否", "正常"}:
            return False
        return True

    @staticmethod
    def _microstructure_severity(risk_type: str) -> str:
        if risk_type in {"disposition_stock", "full_delivery", "limit_lock"}:
            return "high"
        return "medium"

    @staticmethod
    def _microstructure_preflight_diagnostics(preflight: Dict[str, Any]) -> List[str]:
        return [
            f"microstructure:{risk['stock_code']}:{risk['risk_type']}"
            for risk in preflight.get("risks", [])
        ]

    def _build_relative_attribution(
        self,
        equity_curve: pd.DataFrame,
        data: pd.DataFrame,
    ) -> Dict[str, Any]:
        return build_relative_attribution(equity_curve, data)

    def _return_bp_from_equity_curve(self, equity_curve: pd.DataFrame) -> int | None:
        if equity_curve is None or equity_curve.empty or "equity" not in equity_curve.columns:
            return None
        values = pd.to_numeric(equity_curve["equity"], errors="coerce").dropna()
        return self._return_bp_from_values(values)

    def _return_bp_from_reference_column(self, data: pd.DataFrame, column: str) -> int | None:
        if data.empty or "日期" not in data.columns or column not in data.columns:
            return None
        references = data[["日期", column]].copy()
        references["日期"] = pd.to_datetime(references["日期"], errors="coerce")
        references[column] = pd.to_numeric(references[column], errors="coerce")
        references = references.dropna(subset=["日期", column]).sort_values("日期")
        references = references.drop_duplicates(subset=["日期"], keep="first")
        return self._return_bp_from_values(references[column])

    def _return_bp_from_values(self, values: pd.Series) -> int | None:
        return return_bp_from_values(values)

    @staticmethod
    def _benchmark_excess_return_bp(relative_attribution: Dict[str, Any]) -> int | None:
        benchmark = relative_attribution.get("benchmarks", {}).get("benchmark", {})
        value = benchmark.get("excess_return_bp")
        return None if value is None else int(value)

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
        return build_stock_contribution(holdings)

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
        return build_credibility_manifest(rebalance_frequency, allocation_method, max_participation_rate, self._has_execution_cost_params(fee_bps, slippage_bps, tax_bps), lot_size, fee_bps, slippage_bps, tax_bps)

    def _build_factor_manifest(
        self,
        snapshots: List[RecommendationSnapshotDTO],
    ) -> Dict[str, Any]:
        return build_factor_manifest(snapshots, self._factor_records_from_snapshot)

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
