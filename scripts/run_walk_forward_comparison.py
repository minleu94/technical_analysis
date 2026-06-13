"""產生 fixed / quantile walk-forward pilot 比較報告。"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app_module.strategies  # noqa: F401  # 觸發策略註冊
from app_module.backtest_service import BacktestService
from app_module.strategy_spec import StrategySpec
from app_module.walkforward_service import WalkForwardResult, WalkForwardService
from data_module.config import TWStockConfig


STOCKS = ("2330", "2317", "2454", "2603", "2881")
START_DATE = "2024-01-01"
END_DATE = "2026-06-01"
TRAIN_MONTHS = 6
TEST_MONTHS = 3
STEP_MONTHS = 3
CAPITAL = 1_000_000
FEE_BPS = Decimal("14.25")
SLIPPAGE_BPS = Decimal("5")
EXECUTION_PRICE = "next_open"


def build_empirical_conclusion(
    *,
    fixed_total_trades: int,
    quantile_total_trades: int,
    fixed_avg_test_sharpe: float,
    quantile_avg_test_sharpe: float,
) -> str:
    if fixed_total_trades == 0:
        return (
            "Fixed 在全部 OOS fold 都沒有完成交易，缺少可比較的基準樣本，"
            "因此本 pilot 不足以判定 fixed 與 quantile 的相對績效；"
            "目前結果未證明 quantile 改善報酬、Sharpe 或穩健度。"
        )
    if quantile_total_trades == 0:
        return (
            "Quantile 在全部 OOS fold 都沒有完成交易，樣本不足；"
            "目前結果未證明 quantile 改善報酬、Sharpe 或穩健度。"
        )
    if quantile_avg_test_sharpe > fixed_avg_test_sharpe:
        return (
            "Quantile 的平均 OOS Sharpe 高於 fixed，但仍需搭配交易數、"
            "最大回撤與更大股票池確認，不能單憑本 pilot 宣稱穩健改善。"
        )
    return (
        "Quantile 的平均 OOS Sharpe 未優於 fixed；"
        "目前結果未證明 quantile 改善報酬、Sharpe 或穩健度。"
    )


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
        params.update({"buy_score": 70, "sell_score": 50})
    else:
        params.update(
            {
                "buy_quantile_bp": 8000,
                "sell_quantile_bp": 4000,
                "quantile_warmup_observations": 60,
                "quantile_method": "nearest_rank",
            }
        )
    return StrategySpec(
        strategy_id="momentum_aggressive_v1",
        strategy_version="1.0.0",
        config={"params": params},
    )


def _run_mode(
    service: WalkForwardService,
    stock: str,
    mode: str,
) -> list[WalkForwardResult]:
    return service.walk_forward(
        stock_code=stock,
        start_date=START_DATE,
        end_date=END_DATE,
        strategy_spec=_strategy_spec(mode),
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        capital=CAPITAL,
        fee_bps=float(FEE_BPS),  # numeric-boundary: existing backtest API
        slippage_bps=float(SLIPPAGE_BPS),  # numeric-boundary: existing backtest API
    )


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
    lines.extend(
        [
            "",
            "### 5.4 判讀與限制",
            "",
            f"- **結論**：{conclusion}",
            "- 這是 5 檔股票、單一策略與單一成本組合的 pilot，不代表統計顯著性。",
            "- 本次未建立逐日市場 regime 標籤，因此不能宣稱 regime 穩定性已驗證。",
            "- Quantile 維持 opt-in；在 fixed 有足夠交易樣本、擴大股票池並補齊 "
            "regime 分層前，不調整預設模式。",
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
    fingerprint = _dataset_fingerprint(config.db_file)
    service = WalkForwardService(BacktestService(config))
    results: dict[str, dict[str, list[WalkForwardResult]]] = {}
    for stock in STOCKS:
        print(f"[{stock}] fixed")
        fixed = _run_mode(service, stock, "fixed")
        print(f"[{stock}] quantile")
        quantile = _run_mode(service, stock, "quantile")
        results[stock] = {"fixed": fixed, "quantile": quantile}
    _update_report(_build_report_section(results, fingerprint))
    print("已更新 WALK_FORWARD_COMPARISON_REPORT.md")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    run_comparison()
