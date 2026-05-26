# Recommendation Portfolio Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-version recommendation portfolio backtest and optimization flow that replays historical recommendations, records which stocks were selected, and presents readable portfolio-level results.

**Architecture:** Add focused DTOs and services under `app_module/` without rewriting the existing single-stock `BacktestService`. Recommendation replay produces dated snapshots, portfolio backtest consumes those snapshots to simulate allocations and exits, optimizer scans recommendation-layer parameters, and the Qt UI reads summary DataFrames from the result DTO.

**Tech Stack:** Python, pandas, PySide6, pytest, existing `RecommendationDTO`, `PandasTableModel`, and `TWStockConfig`.

---

## File Structure

- Create `app_module/recommendation_portfolio_dtos.py`: dataclasses for snapshots, period holdings, trades, stock contribution, diagnostics, and result DTO.
- Create `app_module/recommendation_replay_service.py`: historical recommendation snapshot adapter with injectable recommendation provider for tests.
- Create `app_module/recommendation_portfolio_backtest_service.py`: portfolio replay simulator with equal-weight and score-weight allocation.
- Create `app_module/recommendation_portfolio_optimizer_service.py`: grid search over recommendation portfolio parameters.
- Modify `app_module/dtos/__init__.py`: export new DTOs if existing import style needs them.
- Modify `ui_qt/views/backtest_view.py`: add recommendation portfolio mode/result tabs after service layer passes.
- Modify `ui_qt/views/recommendation_view.py`: pass Profile/Config payload for recommendation portfolio backtest while preserving current stock-list flow.
- Modify `ui_qt/main.py`: route the new recommendation payload to `BacktestView`.
- Create `tests/test_recommendation_portfolio_backtest.py`: service tests for traceability, allocation, holding exits, contribution, and diagnostics.
- Create `tests/test_recommendation_portfolio_optimizer.py`: optimizer ranking tests.

---

### Task 1: DTOs for Traceable Recommendation Portfolio Results

**Files:**
- Create: `app_module/recommendation_portfolio_dtos.py`
- Test: `tests/test_recommendation_portfolio_backtest.py`

- [ ] **Step 1: Write failing DTO serialization test**

Add this test to `tests/test_recommendation_portfolio_backtest.py`:

```python
import pandas as pd

from app_module.recommendation_portfolio_dtos import (
    PeriodHoldingDTO,
    RecommendationPortfolioBacktestResultDTO,
    RecommendationSnapshotDTO,
    StockContributionDTO,
)


def test_recommendation_portfolio_result_exposes_readable_tables():
    snapshot = RecommendationSnapshotDTO(
        as_of_date="2026-01-02",
        profile_id="momentum",
        strategy_config={"signals": {"weights": {"technical": 0.5}}},
        regime="Trend",
        recommendations=[
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 80.0,
                "factor_scores": {"technical": 82.0, "pattern": 50.0, "volume": 70.0},
                "selection_reason": "score_rank",
            }
        ],
        diagnostics=[],
    )
    holding = PeriodHoldingDTO(
        rebalance_date="2026-01-02",
        stock_code="2330",
        stock_name="台積電",
        rank=1,
        total_score=80.0,
        factor_scores={"technical": 82.0},
        allocation_amount=500000.0,
        allocation_weight=0.5,
        entry_date="2026-01-02",
        entry_price=100.0,
        planned_exit_date="2026-01-06",
        actual_exit_date="2026-01-06",
        actual_exit_price=110.0,
        exit_reason="holding_period",
        holding_days=4,
        return_pct=0.10,
    )
    contribution = StockContributionDTO(
        stock_code="2330",
        stock_name="台積電",
        selected_count=1,
        total_pnl=50000.0,
        avg_return_pct=0.10,
        win_rate=1.0,
        worst_return_pct=0.10,
    )
    result = RecommendationPortfolioBacktestResultDTO(
        summary={"total_return": 0.05, "max_drawdown": 0.0},
        equity_curve=pd.DataFrame([{"date": "2026-01-02", "equity": 1000000.0}]),
        trades=pd.DataFrame([{"stock_code": "2330", "side": "buy"}]),
        snapshots=[snapshot],
        period_holdings=[holding],
        stock_contribution=[contribution],
        selection_diagnostics=[],
    )

    assert result.summary["total_return"] == 0.05
    assert result.period_holdings_dataframe().iloc[0]["股票代號"] == "2330"
    assert result.stock_contribution_dataframe().iloc[0]["總損益"] == 50000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py::test_recommendation_portfolio_result_exposes_readable_tables -q -o addopts=
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app_module.recommendation_portfolio_dtos'`.

- [ ] **Step 3: Implement DTOs**

Create `app_module/recommendation_portfolio_dtos.py`:

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pandas as pd


@dataclass
class RecommendationSnapshotDTO:
    as_of_date: str
    profile_id: str
    strategy_config: Dict[str, Any]
    regime: str
    recommendations: List[Dict[str, Any]]
    diagnostics: List[str] = field(default_factory=list)


@dataclass
class PeriodHoldingDTO:
    rebalance_date: str
    stock_code: str
    stock_name: str
    rank: int
    total_score: float
    factor_scores: Dict[str, float]
    allocation_amount: float
    allocation_weight: float
    entry_date: str
    entry_price: float
    planned_exit_date: str
    actual_exit_date: str
    actual_exit_price: float
    exit_reason: str
    holding_days: int
    return_pct: float

    def pnl(self) -> float:
        return self.allocation_amount * self.return_pct


@dataclass
class StockContributionDTO:
    stock_code: str
    stock_name: str
    selected_count: int
    total_pnl: float
    avg_return_pct: float
    win_rate: float
    worst_return_pct: float


@dataclass
class RecommendationPortfolioBacktestResultDTO:
    summary: Dict[str, Any]
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    snapshots: List[RecommendationSnapshotDTO]
    period_holdings: List[PeriodHoldingDTO]
    stock_contribution: List[StockContributionDTO]
    selection_diagnostics: List[str] = field(default_factory=list)

    def period_holdings_dataframe(self) -> pd.DataFrame:
        rows = []
        for holding in self.period_holdings:
            rows.append(
                {
                    "再平衡日": holding.rebalance_date,
                    "股票代號": holding.stock_code,
                    "股票名稱": holding.stock_name,
                    "排名": holding.rank,
                    "總分": holding.total_score,
                    "配置金額": holding.allocation_amount,
                    "配置權重": holding.allocation_weight,
                    "進場日": holding.entry_date,
                    "進場價": holding.entry_price,
                    "預計出場日": holding.planned_exit_date,
                    "實際出場日": holding.actual_exit_date,
                    "實際出場價": holding.actual_exit_price,
                    "出場原因": holding.exit_reason,
                    "持有天數": holding.holding_days,
                    "報酬率": holding.return_pct,
                    "損益": holding.pnl(),
                }
            )
        return pd.DataFrame(rows)

    def stock_contribution_dataframe(self) -> pd.DataFrame:
        rows = []
        for item in self.stock_contribution:
            rows.append(
                {
                    "股票代號": item.stock_code,
                    "股票名稱": item.stock_name,
                    "被選次數": item.selected_count,
                    "總損益": item.total_pnl,
                    "平均報酬率": item.avg_return_pct,
                    "勝率": item.win_rate,
                    "最大單筆虧損": item.worst_return_pct,
                }
            )
        return pd.DataFrame(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py::test_recommendation_portfolio_result_exposes_readable_tables -q -o addopts=
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app_module\recommendation_portfolio_dtos.py tests\test_recommendation_portfolio_backtest.py
git commit -m "feat: add recommendation portfolio result dtos"
```

---

### Task 2: Recommendation Replay Snapshots

**Files:**
- Create: `app_module/recommendation_replay_service.py`
- Test: `tests/test_recommendation_portfolio_backtest.py`

- [ ] **Step 1: Write failing no-future-data replay test**

Append:

```python
from app_module.recommendation_replay_service import RecommendationReplayService


def test_replay_snapshot_filters_future_rows_before_recommending():
    calls = {}

    def provider(as_of_data, config, top_n):
        calls["max_date"] = as_of_data["日期"].max().strftime("%Y-%m-%d")
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "total_score": 88.0,
                "factor_scores": {"technical": 88.0},
                "selection_reason": "score_rank",
            }
        ]

    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "收盤價": 100},
            {"日期": "2026-01-03", "證券代號": "2330", "收盤價": 200},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    service = RecommendationReplayService(provider=provider)
    snapshot = service.run_snapshot(
        as_of_date="2026-01-02",
        profile_id="momentum",
        config={"regime": "Trend"},
        history=history,
        universe=["2330"],
        top_n=5,
    )

    assert calls["max_date"] == "2026-01-02"
    assert snapshot.as_of_date == "2026-01-02"
    assert snapshot.recommendations[0]["stock_code"] == "2330"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py::test_replay_snapshot_filters_future_rows_before_recommending -q -o addopts=
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement replay service**

Create `app_module/recommendation_replay_service.py`:

```python
from typing import Any, Callable, Dict, Iterable, List, Optional

import pandas as pd

from app_module.recommendation_portfolio_dtos import RecommendationSnapshotDTO


RecommendationProvider = Callable[[pd.DataFrame, Dict[str, Any], int], List[Dict[str, Any]]]


class RecommendationReplayService:
    def __init__(self, provider: RecommendationProvider):
        self.provider = provider

    def run_snapshot(
        self,
        as_of_date: str,
        profile_id: str,
        config: Dict[str, Any],
        history: pd.DataFrame,
        universe: Optional[Iterable[str]],
        top_n: int,
    ) -> RecommendationSnapshotDTO:
        if "日期" not in history.columns:
            raise ValueError("history 必須包含 日期 欄位")

        as_of_ts = pd.to_datetime(as_of_date)
        data = history.copy()
        data["日期"] = pd.to_datetime(data["日期"], errors="coerce")
        data = data[data["日期"].notna()]
        data = data[data["日期"] <= as_of_ts]

        diagnostics = []
        if universe is not None:
            universe_set = {str(code) for code in universe}
            stock_col = "證券代號" if "證券代號" in data.columns else "股票代號"
            if stock_col in data.columns:
                data = data[data[stock_col].astype(str).isin(universe_set)]
            else:
                diagnostics.append("missing_stock_code_column")

        recommendations = self.provider(data, config, top_n)
        recommendations = recommendations[:top_n]

        return RecommendationSnapshotDTO(
            as_of_date=as_of_ts.strftime("%Y-%m-%d"),
            profile_id=profile_id,
            strategy_config=config,
            regime=str(config.get("regime") or ""),
            recommendations=recommendations,
            diagnostics=diagnostics,
        )
```

- [ ] **Step 4: Run replay tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py -q -o addopts=
```

Expected: DTO and replay tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add app_module\recommendation_replay_service.py tests\test_recommendation_portfolio_backtest.py
git commit -m "feat: add historical recommendation replay service"
```

---

### Task 3: Portfolio Backtest Service With Stock Traceability

**Files:**
- Create: `app_module/recommendation_portfolio_backtest_service.py`
- Test: `tests/test_recommendation_portfolio_backtest.py`

- [ ] **Step 1: Write failing portfolio replay test**

Append:

```python
from app_module.recommendation_portfolio_backtest_service import RecommendationPortfolioBacktestService


def test_portfolio_backtest_records_period_holdings_and_contributions():
    history = pd.DataFrame(
        [
            {"日期": "2026-01-02", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 100},
            {"日期": "2026-01-02", "證券代號": "2317", "證券名稱": "鴻海", "收盤價": 50},
            {"日期": "2026-01-06", "證券代號": "2330", "證券名稱": "台積電", "收盤價": 110},
            {"日期": "2026-01-06", "證券代號": "2317", "證券名稱": "鴻海", "收盤價": 45},
        ]
    )
    history["日期"] = pd.to_datetime(history["日期"])

    def provider(as_of_data, config, top_n):
        return [
            {"stock_code": "2330", "stock_name": "台積電", "total_score": 90.0, "factor_scores": {"technical": 90.0}},
            {"stock_code": "2317", "stock_name": "鴻海", "total_score": 80.0, "factor_scores": {"technical": 80.0}},
        ][:top_n]

    service = RecommendationPortfolioBacktestService(provider=provider)
    result = service.run_portfolio_backtest(
        start_date="2026-01-02",
        end_date="2026-01-06",
        profile_id="momentum",
        recommendation_config={"regime": "Trend"},
        history=history,
        initial_capital=1000000.0,
        rebalance_frequency="once",
        top_n=2,
        allocation_method="equal_weight",
        holding_days=4,
    )

    holdings = result.period_holdings_dataframe()
    contribution = result.stock_contribution_dataframe()

    assert list(holdings["股票代號"]) == ["2330", "2317"]
    assert holdings["配置金額"].sum() == 1000000.0
    assert contribution.loc[contribution["股票代號"] == "2330", "總損益"].iloc[0] == 50000.0
    assert contribution.loc[contribution["股票代號"] == "2317", "總損益"].iloc[0] == -50000.0
    assert result.summary["total_return"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py::test_portfolio_backtest_records_period_holdings_and_contributions -q -o addopts=
```

Expected: FAIL with missing service.

- [ ] **Step 3: Implement minimal portfolio service**

Create `app_module/recommendation_portfolio_backtest_service.py`:

```python
from collections import defaultdict
from typing import Any, Callable, Dict, List

import pandas as pd

from app_module.recommendation_portfolio_dtos import (
    PeriodHoldingDTO,
    RecommendationPortfolioBacktestResultDTO,
    StockContributionDTO,
)
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
        data = history.copy()
        data["日期"] = pd.to_datetime(data["日期"], errors="coerce")
        data = data[data["日期"].notna()].sort_values("日期")
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)

        snapshot = self.replay_service.run_snapshot(
            as_of_date=start_ts.strftime("%Y-%m-%d"),
            profile_id=profile_id,
            config=recommendation_config,
            history=data,
            universe=None,
            top_n=top_n,
        )

        recommendations = snapshot.recommendations
        if not recommendations:
            equity_curve = pd.DataFrame([{"date": start_ts.strftime("%Y-%m-%d"), "equity": initial_capital}])
            return RecommendationPortfolioBacktestResultDTO(
                summary={"total_return": 0.0, "max_drawdown": 0.0, "total_trades": 0},
                equity_curve=equity_curve,
                trades=pd.DataFrame(),
                snapshots=[snapshot],
                period_holdings=[],
                stock_contribution=[],
                selection_diagnostics=["no_recommendations"],
            )

        weights = self._calculate_weights(recommendations, allocation_method)
        period_holdings = []
        trade_rows = []

        for rank, rec in enumerate(recommendations, 1):
            code = str(rec["stock_code"])
            stock_rows = data[(data["證券代號"].astype(str) == code) & (data["日期"] >= start_ts) & (data["日期"] <= end_ts)]
            if stock_rows.empty:
                continue

            entry_row = stock_rows.iloc[0]
            exit_row = stock_rows.iloc[-1]
            entry_price = float(entry_row["收盤價"])
            exit_price = float(exit_row["收盤價"])
            allocation_amount = initial_capital * weights[rank - 1]
            return_pct = (exit_price / entry_price) - 1 if entry_price > 0 else 0.0

            holding = PeriodHoldingDTO(
                rebalance_date=start_ts.strftime("%Y-%m-%d"),
                stock_code=code,
                stock_name=str(rec.get("stock_name") or entry_row.get("證券名稱", code)),
                rank=rank,
                total_score=float(rec.get("total_score", 0.0)),
                factor_scores=dict(rec.get("factor_scores", {})),
                allocation_amount=allocation_amount,
                allocation_weight=weights[rank - 1],
                entry_date=entry_row["日期"].strftime("%Y-%m-%d"),
                entry_price=entry_price,
                planned_exit_date=end_ts.strftime("%Y-%m-%d"),
                actual_exit_date=exit_row["日期"].strftime("%Y-%m-%d"),
                actual_exit_price=exit_price,
                exit_reason="holding_period",
                holding_days=int((exit_row["日期"] - entry_row["日期"]).days),
                return_pct=return_pct,
            )
            period_holdings.append(holding)
            trade_rows.append({"date": holding.entry_date, "stock_code": code, "side": "buy", "price": entry_price, "amount": allocation_amount})
            trade_rows.append({"date": holding.actual_exit_date, "stock_code": code, "side": "sell", "price": exit_price, "amount": allocation_amount * (1 + return_pct)})

        final_equity = initial_capital + sum(item.pnl() for item in period_holdings)
        equity_curve = pd.DataFrame(
            [
                {"date": start_ts.strftime("%Y-%m-%d"), "equity": initial_capital},
                {"date": end_ts.strftime("%Y-%m-%d"), "equity": final_equity},
            ]
        )
        stock_contribution = self._build_stock_contribution(period_holdings)

        return RecommendationPortfolioBacktestResultDTO(
            summary={
                "total_return": (final_equity / initial_capital) - 1 if initial_capital > 0 else 0.0,
                "max_drawdown": self._calculate_max_drawdown(equity_curve["equity"]),
                "total_trades": len(period_holdings),
                "avg_holding_days": sum(h.holding_days for h in period_holdings) / len(period_holdings) if period_holdings else 0.0,
                "capital_used": sum(h.allocation_amount for h in period_holdings),
            },
            equity_curve=equity_curve,
            trades=pd.DataFrame(trade_rows),
            snapshots=[snapshot],
            period_holdings=period_holdings,
            stock_contribution=stock_contribution,
            selection_diagnostics=snapshot.diagnostics,
        )

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
```

- [ ] **Step 4: Run portfolio tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app_module\recommendation_portfolio_backtest_service.py tests\test_recommendation_portfolio_backtest.py
git commit -m "feat: add recommendation portfolio backtest service"
```

---

### Task 4: Recommendation Portfolio Optimizer

**Files:**
- Create: `app_module/recommendation_portfolio_optimizer_service.py`
- Test: `tests/test_recommendation_portfolio_optimizer.py`

- [ ] **Step 1: Write failing optimizer ranking test**

Create `tests/test_recommendation_portfolio_optimizer.py`:

```python
from app_module.recommendation_portfolio_optimizer_service import (
    RecommendationPortfolioOptimizerService,
)


class FakeBacktestService:
    def run_portfolio_backtest(self, **kwargs):
        top_n = kwargs["top_n"]
        total_return = 0.10 if top_n == 2 else 0.03
        max_drawdown = -0.02 if top_n == 2 else -0.01
        return type(
            "Result",
            (),
            {
                "summary": {
                    "total_return": total_return,
                    "max_drawdown": max_drawdown,
                    "total_trades": top_n,
                }
            },
        )()


def test_optimizer_ranks_parameter_sets_by_objective_score():
    optimizer = RecommendationPortfolioOptimizerService(FakeBacktestService())
    results = optimizer.grid_search(
        base_request={
            "start_date": "2026-01-02",
            "end_date": "2026-01-06",
            "profile_id": "momentum",
            "recommendation_config": {},
            "history": None,
            "initial_capital": 1000000.0,
            "rebalance_frequency": "once",
            "allocation_method": "equal_weight",
            "holding_days": 4,
        },
        param_grid={"top_n": [1, 2]},
        drawdown_penalty=1.0,
        min_trades=1,
    )

    assert results[0]["params"]["top_n"] == 2
    assert results[0]["score"] == 0.08
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_optimizer.py -q -o addopts=
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement optimizer service**

Create `app_module/recommendation_portfolio_optimizer_service.py`:

```python
import itertools
from typing import Any, Dict, List


class RecommendationPortfolioOptimizerService:
    def __init__(self, portfolio_backtest_service):
        self.portfolio_backtest_service = portfolio_backtest_service

    def grid_search(
        self,
        base_request: Dict[str, Any],
        param_grid: Dict[str, List[Any]],
        drawdown_penalty: float = 1.0,
        min_trades: int = 3,
    ) -> List[Dict[str, Any]]:
        param_names = list(param_grid.keys())
        results = []

        for values in itertools.product(*(param_grid[name] for name in param_names)):
            params = dict(zip(param_names, values))
            request = dict(base_request)
            request.update(params)

            result = self.portfolio_backtest_service.run_portfolio_backtest(**request)
            summary = result.summary
            invalid_sample_penalty = 0.0
            if summary.get("total_trades", 0) < min_trades:
                invalid_sample_penalty = 1.0

            score = (
                float(summary.get("total_return", 0.0))
                - abs(float(summary.get("max_drawdown", 0.0))) * drawdown_penalty
                - invalid_sample_penalty
            )
            results.append({"params": params, "summary": summary, "score": score})

        results.sort(key=lambda item: item["score"], reverse=True)
        return results
```

- [ ] **Step 4: Run optimizer tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_optimizer.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app_module\recommendation_portfolio_optimizer_service.py tests\test_recommendation_portfolio_optimizer.py
git commit -m "feat: add recommendation portfolio optimizer"
```

---

### Task 5: Backtest Tab Readable Result Surfaces

**Files:**
- Modify: `ui_qt/views/backtest_view.py`
- Test: `tests/test_recommendation_portfolio_backtest.py`

- [ ] **Step 1: Write DataFrame shape test for UI tables**

Append:

```python
def test_result_dto_supports_backtest_tab_readability_layers():
    result = RecommendationPortfolioBacktestResultDTO(
        summary={"total_return": 0.02, "max_drawdown": -0.01, "total_trades": 1},
        equity_curve=pd.DataFrame([{"date": "2026-01-02", "equity": 1000000.0}]),
        trades=pd.DataFrame([{"date": "2026-01-02", "stock_code": "2330", "side": "buy"}]),
        snapshots=[],
        period_holdings=[
            PeriodHoldingDTO(
                rebalance_date="2026-01-02",
                stock_code="2330",
                stock_name="台積電",
                rank=1,
                total_score=80.0,
                factor_scores={},
                allocation_amount=1000000.0,
                allocation_weight=1.0,
                entry_date="2026-01-02",
                entry_price=100.0,
                planned_exit_date="2026-01-06",
                actual_exit_date="2026-01-06",
                actual_exit_price=102.0,
                exit_reason="holding_period",
                holding_days=4,
                return_pct=0.02,
            )
        ],
        stock_contribution=[],
        selection_diagnostics=["missing_future_factor:broker_flow"],
    )

    assert "股票代號" in result.period_holdings_dataframe().columns
    assert "missing_future_factor:broker_flow" in result.selection_diagnostics
```

- [ ] **Step 2: Run service tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 3: Add BacktestView helper methods**

Modify `ui_qt/views/backtest_view.py` by adding helper methods near other result display helpers:

```python
    def _show_recommendation_portfolio_result(self, result):
        """顯示推薦組合回測結果。"""
        self.current_recommendation_portfolio_result = result
        if hasattr(self, "portfolio_period_table"):
            self.portfolio_period_table.setModel(PandasTableModel(result.period_holdings_dataframe()))
        if hasattr(self, "portfolio_stock_table"):
            self.portfolio_stock_table.setModel(PandasTableModel(result.stock_contribution_dataframe()))
        if hasattr(self, "portfolio_trades_table"):
            self.portfolio_trades_table.setModel(PandasTableModel(result.trades))
        if hasattr(self, "portfolio_summary_text"):
            summary = result.summary
            self.portfolio_summary_text.setPlainText(
                "\n".join(
                    [
                        f"總報酬率: {summary.get('total_return', 0.0) * 100:.2f}%",
                        f"最大回撤: {summary.get('max_drawdown', 0.0) * 100:.2f}%",
                        f"交易筆數: {summary.get('total_trades', 0)}",
                        f"平均持有天數: {summary.get('avg_holding_days', 0.0):.1f}",
                        f"資金使用: {summary.get('capital_used', 0.0):,.0f}",
                    ]
                )
            )
```

- [ ] **Step 4: Create result widgets in BacktestView**

In the BacktestView result tab setup area, add a new tab named `推薦組合` with:

```python
        recommendation_portfolio_tab = QWidget()
        recommendation_portfolio_layout = QVBoxLayout(recommendation_portfolio_tab)
        self.portfolio_summary_text = QTextEdit()
        self.portfolio_summary_text.setReadOnly(True)
        recommendation_portfolio_layout.addWidget(self.portfolio_summary_text)

        self.portfolio_period_table = QTableView()
        self.portfolio_stock_table = QTableView()
        self.portfolio_trades_table = QTableView()
        recommendation_portfolio_layout.addWidget(QLabel("期間明細"))
        recommendation_portfolio_layout.addWidget(self.portfolio_period_table)
        recommendation_portfolio_layout.addWidget(QLabel("個股貢獻"))
        recommendation_portfolio_layout.addWidget(self.portfolio_stock_table)
        recommendation_portfolio_layout.addWidget(QLabel("交易紀錄"))
        recommendation_portfolio_layout.addWidget(self.portfolio_trades_table)
        result_tabs.addTab(recommendation_portfolio_tab, "推薦組合")
```

Use existing imports already present in `backtest_view.py`; add missing Qt imports only if the file does not already import them.

- [ ] **Step 5: Syntax check BacktestView**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\backtest_view.py
```

Expected: no output and exit code 0.

- [ ] **Step 6: Commit**

```powershell
git add ui_qt\views\backtest_view.py tests\test_recommendation_portfolio_backtest.py
git commit -m "feat: show readable recommendation portfolio results"
```

---

### Task 6: Recommendation Tab Payload for Portfolio Backtest

**Files:**
- Modify: `ui_qt/views/recommendation_view.py`
- Modify: `ui_qt/main.py`
- Test: `tests/test_recommendation_portfolio_backtest.py`

- [ ] **Step 1: Write payload helper test target**

Add a small pure helper in `ui_qt/views/recommendation_view.py`:

```python
def build_recommendation_portfolio_backtest_config(
    profile_id,
    profile_name,
    strategy_config,
    regime,
    top_n=10,
    holding_days=None,
    allocation_method="equal_weight",
):
    return {
        "mode": "recommendation_portfolio",
        "profile_id": profile_id,
        "profile_name": profile_name,
        "strategy_config": strategy_config,
        "regime": regime,
        "top_n": top_n,
        "holding_days": holding_days,
        "allocation_method": allocation_method,
    }
```

Then add test:

```python
from ui_qt.views.recommendation_view import build_recommendation_portfolio_backtest_config


def test_recommendation_portfolio_payload_preserves_profile_config():
    config = build_recommendation_portfolio_backtest_config(
        profile_id="momentum",
        profile_name="暴衝策略",
        strategy_config={"filters": {"price_change_min": 2}},
        regime="Trend",
        top_n=5,
        holding_days=5,
        allocation_method="score_weight",
    )

    assert config["mode"] == "recommendation_portfolio"
    assert config["strategy_config"]["filters"]["price_change_min"] == 2
    assert config["allocation_method"] == "score_weight"
```

- [ ] **Step 2: Run payload test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py::test_recommendation_portfolio_payload_preserves_profile_config -q -o addopts=
```

Expected: PASS after helper is added.

- [ ] **Step 3: Preserve stock-list flow and add portfolio flow**

Modify `_send_to_backtest()` in `ui_qt/views/recommendation_view.py` so it still emits current `stock_list` config for the existing button. Add a second button or menu action labeled `送推薦組合回測`, connected to a new method:

```python
    def _send_profile_to_portfolio_backtest(self):
        if not self.current_config:
            QMessageBox.warning(self, "錯誤", "沒有可送回測的推薦設定")
            return
        profile_name = ""
        if self.current_profile and self.current_profile in self.profiles:
            profile_name = self.profiles[self.current_profile].get("name", "")
        config = build_recommendation_portfolio_backtest_config(
            profile_id=self.current_profile,
            profile_name=profile_name,
            strategy_config=self.current_config,
            regime=self.current_regime,
            top_n=10,
            holding_days=None,
            allocation_method="equal_weight",
        )
        self.sendToBacktestRequested.emit(config)
```

- [ ] **Step 4: Route portfolio payload in BacktestView**

Modify `load_from_recommendation()` in `ui_qt/views/backtest_view.py`:

```python
            if config.get("mode") == "recommendation_portfolio":
                self._load_recommendation_portfolio_config(config)
                return
```

Add:

```python
    def _load_recommendation_portfolio_config(self, config):
        self.current_recommendation_portfolio_config = config
        QMessageBox.information(
            self,
            "已載入推薦組合回測",
            f"Profile: {config.get('profile_name') or config.get('profile_id')}\n"
            f"Top N: {config.get('top_n')}\n"
            f"資金分配: {config.get('allocation_method')}\n\n"
            "請在推薦組合回測區確認期間與資金後執行。",
        )
```

- [ ] **Step 5: Syntax check UI files**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile ui_qt\views\recommendation_view.py ui_qt\views\backtest_view.py ui_qt\main.py
```

Expected: no output and exit code 0.

- [ ] **Step 6: Commit**

```powershell
git add ui_qt\views\recommendation_view.py ui_qt\views\backtest_view.py ui_qt\main.py tests\test_recommendation_portfolio_backtest.py
git commit -m "feat: send profile config to recommendation portfolio backtest"
```

---

### Task 7: Documentation and Regression Verification

**Files:**
- Modify: `docs/02_features/BACKTEST_LAB_FEATURES.md`
- Modify: `docs/02_features/UI_FEATURES_DOCUMENTATION.md`
- Run: targeted tests

- [ ] **Step 1: Update Backtest documentation**

Add a section to `docs/02_features/BACKTEST_LAB_FEATURES.md`:

```markdown
### 推薦組合回測

推薦組合回測會在歷史日期重播推薦邏輯，形成一組股票持倉，並以同一筆初始資金計算組合績效。結果包含總覽、期間明細、個股貢獻、交易紀錄與推薦診斷，用於判斷策略好壞來自哪些股票與哪些推薦條件。
```

- [ ] **Step 2: Update Recommendation UI documentation**

Add to `docs/02_features/UI_FEATURES_DOCUMENTATION.md`:

```markdown
### Recommendation → Backtest

推薦頁保留既有「目前名單送批次單股回測」流程，並新增「Profile/Config 送推薦組合回測」流程。後者會傳遞完整推薦設定，由回測頁在歷史期間重播推薦邏輯。
```

- [ ] **Step 3: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py tests/test_recommendation_portfolio_optimizer.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 4: Run UI syntax checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_portfolio_dtos.py app_module\recommendation_replay_service.py app_module\recommendation_portfolio_backtest_service.py app_module\recommendation_portfolio_optimizer_service.py ui_qt\views\recommendation_view.py ui_qt\views\backtest_view.py ui_qt\main.py
```

Expected: no output and exit code 0.

- [ ] **Step 5: Run existing recommended UI test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
```

Expected: PASS or report pre-existing failures with exact test names.

- [ ] **Step 6: Commit docs and verification fixes**

```powershell
git add docs\02_features\BACKTEST_LAB_FEATURES.md docs\02_features\UI_FEATURES_DOCUMENTATION.md
git commit -m "docs: document recommendation portfolio backtest"
```

---

## Self-Review

- Spec coverage: The plan covers historical snapshots, portfolio replay, stock traceability, optimizer, Backtest readability, Recommendation payload changes, tests, and docs.
- Placeholder scan: No incomplete markers or vague implementation-only steps remain.
- Type consistency: DTO names use `RecommendationSnapshotDTO`, `PeriodHoldingDTO`, `StockContributionDTO`, and `RecommendationPortfolioBacktestResultDTO` consistently across services and tests.
