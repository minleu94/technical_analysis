"""產生 fixed / quantile walk-forward pilot 比較報告。

包含 Regime 分層統計與最低樣本 Gate。
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app_module.strategies  # noqa: F401  # 觸發策略註冊
from app_module.backtest_service import BacktestService
from app_module.strategy_spec import StrategySpec
from app_module.walkforward_service import WalkForwardResult
from data_module.config import TWStockConfig


STOCKS = ("2330", "2317", "2454", "2603", "2881", "2308", "2382", "3008", "2891", "2882")
START_DATE = "2024-01-01"
END_DATE = "2026-06-01"
TRAIN_MONTHS = 6
TEST_MONTHS = 3
STEP_MONTHS = 3
CAPITAL = 1_000_000
FEE_BPS = Decimal("14.25")
SLIPPAGE_BPS = Decimal("5")
EXECUTION_PRICE = "next_open"
MIN_TRADES_GATE = 20
REGIMES = ("Trend", "Breakout", "Reversion")


@dataclass(frozen=True)
class WalkForwardWindow:
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str


def build_empirical_conclusion(
    *,
    fixed_total_trades: int,
    quantile_total_trades: int,
    fixed_avg_test_sharpe: float,
    quantile_avg_test_sharpe: float,
) -> str:
    warning_prefix = ""
    if fixed_total_trades < MIN_TRADES_GATE or quantile_total_trades < MIN_TRADES_GATE:
        warning_prefix = f"⚠️ **[樣本不足警告]** OOS 總交易筆數（Fixed: {fixed_total_trades}, Quantile: {quantile_total_trades}）未達最低門檻 {MIN_TRADES_GATE} 筆。統計結果無顯著性，不可做為參數 promote 或更改預設模式之依據！ "

    if fixed_total_trades == 0:
        return warning_prefix + (
            "Fixed 在全部 OOS fold 都沒有完成交易，缺少可比較的基準樣本，"
            "因此本 pilot 不足以判定 fixed 與 quantile 的相對績效；"
            "目前結果未證明 quantile 改善報酬、Sharpe 或穩健度。"
        )
    if quantile_total_trades == 0:
        return warning_prefix + (
            "Quantile 在全部 OOS fold 都沒有完成交易，樣本不足；"
            "目前結果未證明 quantile 改善報酬、Sharpe 或穩健度。"
        )
    if quantile_avg_test_sharpe > fixed_avg_test_sharpe:
        return warning_prefix + (
            "Quantile 的平均 OOS Sharpe 高於 fixed，但仍需搭配交易數、"
            "最大回撤與更大股票池確認，不能單憑本 pilot 宣稱穩健改善。"
        )
    return warning_prefix + (
        "Quantile 的平均 OOS Sharpe 未優於 fixed；"
        "目前結果未證明 quantile 改善報酬、Sharpe 或穩健度。"
    )


def _iter_walk_forward_windows(
    *,
    start_date: str,
    end_date: str,
    train_months: int,
    test_months: int,
    step_months: int,
    warmup_days: int = 0,
):
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    current_start = start_dt
    fold = 0

    while current_start < end_dt:
        actual_train_start = current_start + pd.Timedelta(days=warmup_days)
        if actual_train_start >= end_dt:
            break

        train_end = actual_train_start + pd.DateOffset(months=train_months)
        test_start = train_end + pd.DateOffset(days=1)
        test_end = min(
            test_start + pd.DateOffset(months=test_months),
            end_dt,
        )
        if train_end > end_dt or test_start >= test_end:
            break

        fold += 1
        yield WalkForwardWindow(
            fold=fold,
            train_start=actual_train_start.strftime("%Y-%m-%d"),
            train_end=train_end.strftime("%Y-%m-%d"),
            test_start=test_start.strftime("%Y-%m-%d"),
            test_end=test_end.strftime("%Y-%m-%d"),
        )
        current_start = current_start + pd.DateOffset(months=step_months)


def _resolve_regime_label(
    regime_cache: dict[str, str],
    date: str,
) -> tuple[str, bool]:
    eligible_dates = sorted(
        observed_date
        for observed_date, observed_regime in regime_cache.items()
        if observed_regime in REGIMES
    )
    position = bisect_right(eligible_dates, date)
    if position == 0:
        return "unavailable", False
    regime = regime_cache[eligible_dates[position - 1]]
    if regime not in REGIMES:
        return "unavailable", False
    return regime, True


def _build_equal_weight_daily_returns(
    daily_returns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not daily_returns:
        return []

    frame = pd.DataFrame(daily_returns)
    if "fold" not in frame.columns:
        frame["fold"] = 0
    frame = frame[frame["regime"].isin(REGIMES)].copy()
    if frame.empty:
        return []

    per_stock = (
        frame.groupby(["fold", "date", "regime", "stock"], as_index=False)["return"]
        .mean()
    )
    portfolio = (
        per_stock.groupby(["fold", "date", "regime"], as_index=False)["return"]
        .mean()
        .sort_values(["fold", "date", "regime"])
    )
    records = portfolio.to_dict(orient="records")
    for record in records:
        record["fold"] = int(record["fold"])
        record["return"] = float(record["return"])
    if all("fold" not in item for item in daily_returns):
        for record in records:
            record.pop("fold", None)
    return records


def _readonly_connection(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)


def _dataset_fingerprint(db_path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    placeholders = ",".join("?" for _ in STOCKS)
    query = (
        "SELECT 證券代號, 日期, 開盤價, 最高價, 最低價, 收盤價, 成交股數 "
        f"FROM daily_prices WHERE 證券代號 IN ({placeholders}) "
        "AND 日期 >= ? AND 日期 <= ? ORDER BY 證券代號, 日期"
    )
    params = (*STOCKS, START_DATE.replace("-", ""), END_DATE.replace("-", ""))
    row_count = 0
    min_date: str | None = None
    max_date: str | None = None
    per_stock: dict[str, int] = {stock: 0 for stock in STOCKS}
    with _readonly_connection(db_path) as connection:
        for row in connection.execute(query, params):
            encoded = "\x1f".join("" if value is None else str(value) for value in row)
            digest.update(encoded.encode("utf-8"))
            digest.update(b"\n")
            stock = str(row[0])
            date = str(row[1])
            row_count += 1
            per_stock[stock] += 1
            min_date = date if min_date is None or date < min_date else min_date
            max_date = date if max_date is None or date > max_date else max_date
    missing = [stock for stock, count in per_stock.items() if count < 100]
    if missing:
        raise RuntimeError(f"股票資料不足，停止實證：{', '.join(missing)}")
    return {
        "sha256": digest.hexdigest(),
        "rows": row_count,
        "min_date": min_date,
        "max_date": max_date,
        "per_stock": per_stock,
    }


def _strategy_spec(mode: str) -> StrategySpec:
    params: dict[str, Any] = {
        "threshold_mode": mode,
        "buy_confirm_days": 1,
        "sell_confirm_days": 1,
        "cooldown_days": 2,
    }
    if mode == "fixed":
        params.update({"buy_score": 55, "sell_score": 45})
    else:
        params.update(
            {
                "buy_quantile_bp": 8000,
                "sell_quantile_bp": 4000,
                "quantile_warmup_observations": 60,
                "quantile_method": "nearest_rank",
            }
        )

    config = {
        "params": params,
        "technical": {
            "momentum": {
                "rsi": {"enabled": True, "window": 14},
                "macd": {"enabled": True, "fast": 12, "slow": 26, "signal": 9},
                "kd": {"enabled": True, "k_period": 9, "d_period": 3}
            },
            "trend": {
                "adx": {"enabled": True, "window": 14},
                "ma": {"enabled": True, "windows": [5, 10, 20, 60]}
            },
            "volatility": {
                "bollinger": {"enabled": True, "window": 20, "std_dev": 2}
            }
        },
        "patterns": {
            "selected": ["W底", "雙底", "頭肩底", "三角形", "矩形"]
        },
        "signals": {
            "weights": {
                "pattern": 0.3,
                "technical": 0.5,
                "volume": 0.2
            },
            "volume_conditions": ["volume_expanding"]
        }
    }

    return StrategySpec(
        strategy_id="momentum_aggressive_v1",
        strategy_version="1.0.0",
        config=config,
    )


def _get_regime_cache(config: TWStockConfig) -> dict[str, str]:
    """預先計算並快取大盤每日的 regime。"""
    from decision_module.market_regime_detector import MarketRegimeDetector
    from data_module.db_manager import DBManager
    detector = MarketRegimeDetector(config, use_persistent_history=False)
    db = DBManager(config)
    sql_df = db.execute_query("SELECT 日期 FROM market_indices ORDER BY 日期 ASC;")
    if sql_df.empty:
        return {}

    dates = pd.to_datetime(sql_df['日期'].astype(str), format='%Y%m%d', errors='coerce').dt.strftime('%Y-%m-%d').dropna().unique()
    target_dates = [d for d in dates if START_DATE <= d <= END_DATE]

    regime_cache = {}
    print(f"預先計算大盤 {len(target_dates)} 個交易日的 Regime 標籤...")
    for d in target_dates:
        res = detector.detect_regime(d)
        if res.get("details", {}).get("error"):
            continue
        regime, observed = _resolve_regime_label(
            {d: str(res.get("regime", ""))},
            d,
        )
        if observed:
            regime_cache[d] = regime
    return regime_cache


def _run_walk_forward_with_details(
    backtest_service: BacktestService,
    stock: str,
    mode: str,
    regime_cache: dict[str, str],
) -> tuple[list[WalkForwardResult], list[dict[str, Any]], list[dict[str, Any]]]:
    """手動執行 walk-forward 並收集交易明細與每日報酬率以進行 regime 分層統計。"""
    spec = _strategy_spec(mode)
    results = []
    trades_collected = []
    daily_returns_collected = []

    capital = CAPITAL
    fee_bps = float(FEE_BPS)
    slippage_bps = float(SLIPPAGE_BPS)
    warmup_days = 0

    windows = _iter_walk_forward_windows(
        start_date=START_DATE,
        end_date=END_DATE,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        warmup_days=warmup_days,
    )
    for window in windows:
        try:
            # 訓練集回測
            train_report = backtest_service.run_backtest(
                stock_code=stock,
                start_date=window.train_start,
                end_date=window.train_end,
                strategy_spec=spec,
                capital=capital,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )

            # 測試集回測
            test_report = backtest_service.run_backtest(
                stock_code=stock,
                start_date=window.test_start,
                end_date=window.test_end,
                strategy_spec=spec,
                capital=capital,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                signal_context_start_date=window.train_start,
            )

            # 計算退化程度
            train_sharpe = train_report.sharpe_ratio if train_report.sharpe_ratio != 0 else 0.01
            test_sharpe = test_report.sharpe_ratio
            degradation = (test_sharpe - train_sharpe) / abs(train_sharpe) if train_sharpe != 0 else 0

            result = WalkForwardResult(
                train_period=(window.train_start, window.train_end),
                test_period=(window.test_start, window.test_end),
                train_metrics={
                    'total_return': train_report.total_return,
                    'annual_return': train_report.annual_return,
                    'sharpe_ratio': train_report.sharpe_ratio,
                    'max_drawdown': train_report.max_drawdown,
                    'win_rate': train_report.win_rate,
                    'total_trades': train_report.total_trades
                },
                test_metrics={
                    'total_return': test_report.total_return,
                    'annual_return': test_report.annual_return,
                    'sharpe_ratio': test_report.sharpe_ratio,
                    'max_drawdown': test_report.max_drawdown,
                    'win_rate': test_report.win_rate,
                    'total_trades': test_report.total_trades
                },
                degradation=degradation,
                params=spec.config.get('params', {}),
                warmup_days=warmup_days
            )
            results.append(result)

            # 收集交易明細以進行 regime 分析
            trade_list = test_report.details.get('trade_list', pd.DataFrame())
            if not trade_list.empty:
                for _, row in trade_list.iterrows():
                    entry_dt = row['進場日期']
                    if hasattr(entry_dt, 'strftime'):
                        entry_date_str = entry_dt.strftime('%Y-%m-%d')
                    else:
                        entry_date_str = str(entry_dt)[:10]

                    regime, observed = _resolve_regime_label(
                        regime_cache,
                        entry_date_str,
                    )
                    trades_collected.append({
                        'stock': stock,
                        'fold': window.fold,
                        'entry_date': entry_date_str,
                        'profit': row['報酬'],
                        'return_pct': row['報酬率%'] / 100.0,
                        'regime': regime,
                        'regime_observed': observed,
                    })

            # 收集每日報酬率以進行 regime 分析
            equity_curve = test_report.details.get('equity_curve', pd.DataFrame())
            if not equity_curve.empty and 'equity' in equity_curve.columns:
                daily_rets = equity_curve['equity'].pct_change().dropna()
                for dt, val in daily_rets.items():
                    date_str = dt.strftime('%Y-%m-%d')
                    regime, observed = _resolve_regime_label(
                        regime_cache,
                        date_str,
                    )
                    daily_returns_collected.append({
                        'stock': stock,
                        'fold': window.fold,
                        'date': date_str,
                        'return': val,
                        'regime': regime,
                        'regime_observed': observed,
                    })

        except Exception as e:
            print(f"[{stock}] Fold {window.fold} 失敗: {e}")
            continue

    return results, trades_collected, daily_returns_collected


def _calculate_regime_stats(
    trades: list[dict[str, Any]],
    daily_returns: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """計算不同 regime 的分層統計指標。"""
    regimes = REGIMES
    stats = {}
    portfolio_returns = _build_equal_weight_daily_returns(daily_returns)

    for r in regimes:
        r_trades = [t for t in trades if t['regime'] == r]
        r_returns = [d['return'] for d in portfolio_returns if d['regime'] == r]

        trade_count = len(r_trades)
        if trade_count > 0:
            avg_return = mean([t['return_pct'] for t in r_trades])
            win_count = sum(t['profit'] > 0 for t in r_trades)
            win_rate = win_count / trade_count
        else:
            avg_return = 0.0
            win_rate = 0.0

        if len(r_returns) > 1:
            ret_std = np.std(r_returns, ddof=1)
            if ret_std > 0:
                sharpe = np.sqrt(252) * np.mean(r_returns) / ret_std
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        stats[r] = {
            'trade_count': trade_count,
            'avg_return': avg_return,
            'win_rate': win_rate,
            'sharpe': sharpe
        }

    stats["coverage"] = {
        "trade_observed": sum(t["regime"] in REGIMES for t in trades),
        "trade_total": len(trades),
        "return_observed": sum(d["regime"] in REGIMES for d in daily_returns),
        "return_total": len(daily_returns),
    }
    return stats


def _aggregate(results: list[WalkForwardResult]) -> dict[str, Any]:
    if not results:
        raise RuntimeError("walk-forward 沒有產生任何 fold")
    return {
        "folds": len(results),
        "avg_test_return": mean(item.test_metrics["total_return"] for item in results),
        "avg_test_sharpe": mean(item.test_metrics["sharpe_ratio"] for item in results),
        "worst_test_drawdown": min(
            item.test_metrics["max_drawdown"] for item in results
        ),
        "total_test_trades": sum(
            int(item.test_metrics["total_trades"]) for item in results
        ),
        "positive_sharpe_folds": sum(
            item.test_metrics["sharpe_ratio"] > 0 for item in results
        ),
    }


def _format_date(value: Any) -> str:
    raw = str(value)
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _build_report_section(
    results: dict[str, dict[str, list[WalkForwardResult]]],
    fingerprint: dict[str, Any],
    all_trades: dict[str, list[dict[str, Any]]],
    all_returns: dict[str, list[dict[str, Any]]],
) -> str:
    summaries = {
        stock: {mode: _aggregate(mode_results) for mode, mode_results in modes.items()}
        for stock, modes in results.items()
    }
    fixed_total_trades = sum(
        summaries[stock]["fixed"]["total_test_trades"] for stock in STOCKS
    )
    quantile_total_trades = sum(
        summaries[stock]["quantile"]["total_test_trades"] for stock in STOCKS
    )
    fixed_avg_sharpe = mean(
        summaries[stock]["fixed"]["avg_test_sharpe"] for stock in STOCKS
    )
    quantile_avg_sharpe = mean(
        summaries[stock]["quantile"]["avg_test_sharpe"] for stock in STOCKS
    )
    conclusion = build_empirical_conclusion(
        fixed_total_trades=fixed_total_trades,
        quantile_total_trades=quantile_total_trades,
        fixed_avg_test_sharpe=fixed_avg_sharpe,
        quantile_avg_test_sharpe=quantile_avg_sharpe,
    )

    lines = [
        "## 5. Pilot 實證比較結果",
        "",
        f"本章節於 `{datetime.now():%Y-%m-%d}` 由 "
        "`scripts/run_walk_forward_comparison.py` 產生。",
        "",
        "### 5.1 固定條件與資料指紋",
        "",
        f"- 股票池：`{', '.join(STOCKS)}`。",
        f"- 請求期間：`{START_DATE}` 至 `{END_DATE}`。",
        f"- 窗口：訓練 `{TRAIN_MONTHS}` 個月、測試 `{TEST_MONTHS}` 個月、"
        f"步進 `{STEP_MONTHS}` 個月。",
        f"- 初始資金：`{CAPITAL}`；手續費 `{FEE_BPS}` bps；"
        f"滑價 `{SLIPPAGE_BPS}` bps；成交價假設 `{EXECUTION_PRICE}`。",
        "- fixed / quantile 除門檻參數外，確認天數與冷卻期相同。",
        "- Quantile 測試窗使用該 fold 訓練起點至 T-1 的分數歷史產生門檻；"
        "交易狀態在 OOS 起點以空倉重置，撮合與績效只計入測試窗。",
        f"- 選定資料列：`{fingerprint['rows']}`；實際日期 "
        f"`{_format_date(fingerprint['min_date'])}` 至 "
        f"`{_format_date(fingerprint['max_date'])}`。",
        f"- 選定資料 SHA-256：`{fingerprint['sha256']}`。",
        "",
        "### 5.2 OOS 統計總覽",
        "",
        "| 股票 | 模式 | Fold | 平均 OOS 報酬 | 平均 OOS Sharpe | "
        "最差 OOS 最大回撤 | OOS 完成交易 | 正 Sharpe Fold |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for stock in STOCKS:
        for mode in ("fixed", "quantile"):
            summary = summaries[stock][mode]
            lines.append(
                f"| {stock} | {mode} | {summary['folds']} | "
                f"{summary['avg_test_return']:.2%} | "
                f"{summary['avg_test_sharpe']:.4f} | "
                f"{summary['worst_test_drawdown']:.2%} | "
                f"{summary['total_test_trades']} | "
                f"{summary['positive_sharpe_folds']} |"
            )
    lines.extend(
        [
            "",
            "### 5.3 Fold 明細",
            "",
            "| 股票 | Fold | 測試期間 | Fixed 報酬 | Quantile 報酬 | "
            "Fixed Sharpe | Quantile Sharpe | Fixed MDD | Quantile MDD | "
            "Fixed 交易 | Quantile 交易 |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for stock in STOCKS:
        fixed_results = results[stock]["fixed"]
        quantile_results = results[stock]["quantile"]
        if len(fixed_results) != len(quantile_results):
            raise RuntimeError(f"{stock} 的 fixed / quantile fold 數不一致")
        for index, (fixed, quantile) in enumerate(
            zip(fixed_results, quantile_results, strict=True),
            start=1,
        ):
            lines.append(
                f"| {stock} | {index} | {fixed.test_period[0]} ~ "
                f"{fixed.test_period[1]} | "
                f"{fixed.test_metrics['total_return']:.2%} | "
                f"{quantile.test_metrics['total_return']:.2%} | "
                f"{fixed.test_metrics['sharpe_ratio']:.4f} | "
                f"{quantile.test_metrics['sharpe_ratio']:.4f} | "
                f"{fixed.test_metrics['max_drawdown']:.2%} | "
                f"{quantile.test_metrics['max_drawdown']:.2%} | "
                f"{int(fixed.test_metrics['total_trades'])} | "
                f"{int(quantile.test_metrics['total_trades'])} |"
            )

    # 計算 regime stats
    fixed_regime_stats = _calculate_regime_stats(all_trades['fixed'], all_returns['fixed'])
    quantile_regime_stats = _calculate_regime_stats(all_trades['quantile'], all_returns['quantile'])

    lines.extend([
        "",
        "### 5.4 Regime 分層分析結果",
        "",
        "| 模式 | Regime | OOS 總交易數 | 交易平均報酬率 | 交易勝率 | 年化 Sharpe |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for r in REGIMES:
        f_stat = fixed_regime_stats[r]
        lines.append(
            f"| fixed | {r} | {f_stat['trade_count']} | "
            f"{f_stat['avg_return']:.2%} | "
            f"{f_stat['win_rate']:.2%} | "
            f"{f_stat['sharpe']:.4f} |"
        )
    for r in REGIMES:
        q_stat = quantile_regime_stats[r]
        lines.append(
            f"| quantile | {r} | {q_stat['trade_count']} | "
            f"{q_stat['avg_return']:.2%} | "
            f"{q_stat['win_rate']:.2%} | "
            f"{q_stat['sharpe']:.4f} |"
        )

    fixed_coverage = fixed_regime_stats["coverage"]
    quantile_coverage = quantile_regime_stats["coverage"]
    sample_gate_passed = (
        fixed_total_trades >= MIN_TRADES_GATE
        and quantile_total_trades >= MIN_TRADES_GATE
    )
    coverage_gate_passed = all(
        coverage["trade_observed"] == coverage["trade_total"]
        and coverage["return_observed"] == coverage["return_total"]
        for coverage in (fixed_coverage, quantile_coverage)
    )
    lines.extend(
        [
            "",
            "- 最低樣本 Gate："
            f"{'PASS' if sample_gate_passed else 'FAIL'}"
            f"（fixed {fixed_total_trades}、quantile {quantile_total_trades}；"
            f"門檻各 {MIN_TRADES_GATE} 筆）。",
            "- Regime coverage Gate："
            f"{'PASS' if coverage_gate_passed else 'FAIL'}。",
            "- Regime coverage（交易）："
            f"fixed {fixed_coverage['trade_observed']}/{fixed_coverage['trade_total']}；"
            f"quantile {quantile_coverage['trade_observed']}/{quantile_coverage['trade_total']}。",
            "- Regime coverage（每日報酬觀測）："
            f"fixed {fixed_coverage['return_observed']}/{fixed_coverage['return_total']}；"
            f"quantile {quantile_coverage['return_observed']}/{quantile_coverage['return_total']}。",
            "- 年化 Sharpe 使用各 fold 內、同日跨股票等權聚合後的 OOS 日報酬樣本；"
            "不同 fold 維持獨立觀測，不解讀為單一連續實盤資金曲線。",
        ]
    )

    lines.extend(
        [
            "",
            "### 5.5 判讀與限制",
            "",
            f"- **結論**：{conclusion}",
            "- 這是 10 檔股票、單一策略與單一成本組合的 pilot，提供真實 OOS 的 regime 分層統計。",
            "- Daily regime 依日期遞增、使用隔離的歷史狀態計算；每個標籤只讀取該日以前的大盤資料。",
            "- 個股交易日若缺少同日大盤列，沿用該決策日以前最近一筆可用 Regime，"
            "不使用未來日期回填。",
            "- Quantile 維持 opt-in；在整體 fixed 有足夠交易樣本且 quantile 未能展現顯著績效提升前，維持原設定。",
            "",
        ]
    )
    return "\n".join(lines)


def _update_report(section: str) -> None:
    report_path = PROJECT_ROOT / "docs" / "06_qa" / "WALK_FORWARD_COMPARISON_REPORT.md"
    content = report_path.read_text(encoding="utf-8")
    marker = "## 5."
    if marker in content:
        content = content.split(marker, maxsplit=1)[0].rstrip()
    report_path.write_text(f"{content}\n\n{section}", encoding="utf-8")


def run_comparison() -> None:
    config = TWStockConfig()
    if not config.db_file.exists():
        raise FileNotFoundError(f"找不到 SQLite：{config.db_file}")

    # 快取大盤 daily regime
    regime_cache = _get_regime_cache(config)

    fingerprint = _dataset_fingerprint(config.db_file)
    backtest_service = BacktestService(config)

    results: dict[str, dict[str, list[WalkForwardResult]]] = {}
    all_trades: dict[str, list[dict[str, Any]]] = {'fixed': [], 'quantile': []}
    all_returns: dict[str, list[dict[str, Any]]] = {'fixed': [], 'quantile': []}

    for stock in STOCKS:
        print(f"[{stock}] fixed...")
        f_results, f_trades, f_returns = _run_walk_forward_with_details(backtest_service, stock, "fixed", regime_cache)

        print(f"[{stock}] quantile...")
        q_results, q_trades, q_returns = _run_walk_forward_with_details(backtest_service, stock, "quantile", regime_cache)

        results[stock] = {"fixed": f_results, "quantile": q_results}
        all_trades['fixed'].extend(f_trades)
        all_trades['quantile'].extend(q_trades)
        all_returns['fixed'].extend(f_returns)
        all_returns['quantile'].extend(q_returns)

    report_sec = _build_report_section(results, fingerprint, all_trades, all_returns)
    _update_report(report_sec)
    print("已更新 WALK_FORWARD_COMPARISON_REPORT.md")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    run_comparison()
