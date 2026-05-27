from collections import defaultdict
from typing import Any, Callable, Dict, List

import pandas as pd

from app_module.recommendation_portfolio_dtos import (
    PeriodHoldingDTO,
    RecommendationPortfolioBacktestResultDTO,
    StockContributionDTO,
)
from app_module.recommendation_portfolio_dates import parse_stock_dates
from app_module.recommendation_replay_service import RecommendationReplayService


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
    ) -> RecommendationPortfolioBacktestResultDTO:
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
            return RecommendationPortfolioBacktestResultDTO(
                summary={"total_return": 0.0, "max_drawdown": 0.0, "total_trades": 0},
                equity_curve=equity_curve,
                trades=pd.DataFrame(),
                snapshots=snapshots,
                period_holdings=[],
                stock_contribution=[],
                selection_diagnostics=["no_recommendations"],
            )

        final_equity = initial_capital + sum(holding.pnl() for holding in period_holdings)
        equity_curve = self._build_equity_curve(initial_capital, period_holdings, start_ts, end_ts)
        stock_contribution = self._build_stock_contribution(period_holdings)

        return RecommendationPortfolioBacktestResultDTO(
            summary={
                "total_return": (final_equity / initial_capital) - 1 if initial_capital > 0 else 0.0,
                "max_drawdown": self._calculate_max_drawdown(equity_curve["equity"]),
                "total_trades": len(period_holdings),
                "avg_holding_days": (
                    sum(holding.holding_days for holding in period_holdings) / len(period_holdings)
                    if period_holdings
                    else 0.0
                ),
                "capital_used": sum(holding.allocation_amount for holding in period_holdings),
            },
            equity_curve=equity_curve,
            trades=pd.DataFrame(trade_rows),
            snapshots=snapshots,
            period_holdings=period_holdings,
            stock_contribution=stock_contribution,
            selection_diagnostics=[item for snapshot in snapshots for item in snapshot.diagnostics],
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
        exit_row = stock_rows.iloc[-1]
        entry_price = float(entry_row["收盤價"])
        exit_price = float(exit_row["收盤價"])
        return_pct = round((exit_price / entry_price) - 1, 10) if entry_price else 0.0
        actual_exit_ts = pd.to_datetime(exit_row["日期"])
        return PeriodHoldingDTO(
            rebalance_date=rebalance_ts.strftime("%Y-%m-%d"),
            stock_code=code,
            stock_name=str(rec.get("stock_name") or entry_row.get("證券名稱", "")),
            rank=rank,
            total_score=float(rec.get("total_score", 0.0)),
            factor_scores=dict(rec.get("factor_scores", {})),
            allocation_amount=allocation_amount,
            allocation_weight=allocation_weight,
            entry_date=pd.to_datetime(entry_row["日期"]).strftime("%Y-%m-%d"),
            entry_price=entry_price,
            planned_exit_date=planned_exit_ts.strftime("%Y-%m-%d"),
            actual_exit_date=actual_exit_ts.strftime("%Y-%m-%d"),
            actual_exit_price=exit_price,
            exit_reason="holding_period",
            holding_days=(actual_exit_ts - pd.to_datetime(entry_row["日期"])).days,
            return_pct=return_pct,
        )

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
    ) -> pd.DataFrame:
        rows = [{"date": start_ts.strftime("%Y-%m-%d"), "equity": initial_capital}]
        running_equity = initial_capital
        for holding in sorted(holdings, key=lambda item: item.actual_exit_date):
            running_equity += holding.pnl()
            rows.append({"date": holding.actual_exit_date, "equity": running_equity})
        if rows[-1]["date"] != end_ts.strftime("%Y-%m-%d"):
            rows.append({"date": end_ts.strftime("%Y-%m-%d"), "equity": running_equity})
        return pd.DataFrame(rows)

    def _calculate_weights(self, recommendations: List[Dict[str, Any]], allocation_method: str) -> List[float]:
        if allocation_method == "score_weight":
            scores = [max(float(item.get("total_score", 0.0)), 0.0) for item in recommendations]
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

    def _calculate_max_drawdown(self, equity: pd.Series) -> float:
        if equity.empty:
            return 0.0
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max
        return float(drawdown.min())
