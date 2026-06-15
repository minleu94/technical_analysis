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
from financial_module.units import quantize_money, to_decimal


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

        data = history.copy()
        data["日期"] = parse_stock_dates(data["日期"])
        data = data[data["日期"].notna()].sort_values("日期")
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        rebalance_dates = self._get_rebalance_dates(data, start_ts, end_ts, rebalance_frequency)

        snapshots = []
        period_holdings = []
        trade_rows = []
        capital_per_period = initial_capital

        for rebalance_ts in rebalance_dates:
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
                holding = self._build_period_holding(
                    data=data,
                    rec=rec,
                    rank=rank,
                    rebalance_ts=rebalance_ts,
                    planned_exit_ts=planned_exit_ts,
                    allocation_amount=capital_per_period * weights[rank - 1],
                    allocation_weight=weights[rank - 1],
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                )
                if holding is None:
                    continue
                period_holdings.append(holding)
                trade_rows.extend(self._build_trade_rows(holding))

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
            details = {
                "data_manifest": self._build_factor_manifest(snapshots),
            }
            return RecommendationPortfolioBacktestResultDTO(
                summary={"total_return": 0.0, "max_drawdown": 0.0, "total_trades": 0, "execution_assumption": "idealized_same_day_close"},
                equity_curve=equity_curve,
                trades=pd.DataFrame(),
                snapshots=snapshots,
                period_holdings=[],
                stock_contribution=[],
                selection_diagnostics=["no_recommendations"],
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
        }
        summary.update(self._build_exit_diagnostics(period_holdings, stock_contribution))
        summary.update(
            calculate_robustness_metrics(
                equity_curve=equity_curve,
                trade_returns=[holding.return_pct for holding in period_holdings],
            )
        )

        improvement_hints = generate_improvement_hints(summary)
        details = {
            "data_manifest": self._build_factor_manifest(snapshots),
        }

        return RecommendationPortfolioBacktestResultDTO(
            summary=summary,
            equity_curve=equity_curve,
            trades=pd.DataFrame(trade_rows),
            snapshots=snapshots,
            period_holdings=period_holdings,
            stock_contribution=stock_contribution,
            selection_diagnostics=[item for snapshot in snapshots for item in snapshot.diagnostics],
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
