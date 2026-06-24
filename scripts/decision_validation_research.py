"""Decision validation research checks for recommendation scoring.

本腳本是唯讀研究工具，用來回答四個問題：

1. same-close / T+1 open / T+1 close 推薦回放差異。
2. Top N sensitivity。
3. Score quintile monotonicity。
4. Baseline battle。

限制：
- 使用 `all_stocks_data.csv` 中可取得的技術指標建立 score proxy。
- 不重放完整 UI Recommendation Profile / pattern analyzer。
- 不寫正式資料庫、不改 raw data，只輸出研究報告到 output 目錄。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig


TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class ReplayParams:
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    holding_days: int
    top_n: int
    fee_bps: float
    tax_bps: float
    slippage_bps: float
    min_turnover: int
    random_seeds: int


def _read_history(config: TWStockConfig, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    path = config.all_stocks_data_file
    if not path.exists():
        raise FileNotFoundError(f"找不到 all_stocks_data.csv: {path}")

    frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    required = {"日期", "證券代號", "證券名稱", "開盤價", "收盤價", "成交股數", "成交金額"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"all_stocks_data.csv 缺少必要欄位: {sorted(missing)}")

    frame["date"] = pd.to_datetime(frame["日期"].astype(str), errors="coerce", format="mixed")
    frame["stock_code"] = frame["證券代號"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    frame["stock_name"] = frame["證券名稱"].astype(str)
    for source, target in [
        ("開盤價", "open"),
        ("最高價", "high"),
        ("最低價", "low"),
        ("收盤價", "close"),
        ("成交股數", "volume"),
        ("成交金額", "turnover"),
        ("RSI", "rsi"),
        ("MACD", "macd"),
        ("MACD_signal", "macd_signal"),
        ("MACD_hist", "macd_hist"),
        ("MA5", "ma5"),
        ("MA10", "ma10"),
        ("MA20", "ma20"),
        ("MA60", "ma60"),
        ("ATR", "atr"),
    ]:
        if source in frame.columns:
            frame[target] = pd.to_numeric(frame[source], errors="coerce")
        else:
            frame[target] = np.nan

    frame = frame[
        (frame["date"].notna())
        & (frame["date"] >= start - pd.Timedelta(days=180))
        & (frame["date"] <= end + pd.Timedelta(days=45))
    ].copy()
    frame = frame.sort_values(["stock_code", "date"])

    common_stock = frame["stock_code"].str.fullmatch(r"\d{4}") & ~frame["stock_code"].str.startswith("00")
    valid_price = frame["close"].gt(0) & frame["open"].gt(0)
    frame = frame[common_stock & valid_price].copy()
    if frame.empty:
        raise ValueError("篩選後沒有可用股票資料")

    frame["ret_1d"] = frame.groupby("stock_code")["close"].pct_change()
    frame["mom_20d"] = frame.groupby("stock_code")["close"].pct_change(20)
    frame["mom_60d"] = frame.groupby("stock_code")["close"].pct_change(60)
    frame["mom_120d"] = frame.groupby("stock_code")["close"].pct_change(120)
    frame["vol_20d"] = frame.groupby("stock_code")["ret_1d"].transform(
        lambda series: series.rolling(20, min_periods=15).std()
    )
    frame["volume_ma20"] = frame.groupby("stock_code")["volume"].transform(
        lambda series: series.rolling(20, min_periods=10).mean()
    )

    frame = _add_score_proxy(frame)
    frame = _add_forward_prices(frame, max_horizon=30)
    frame = frame[(frame["date"] >= start) & (frame["date"] <= end)].copy()
    return frame


def _add_score_proxy(frame: pd.DataFrame) -> pd.DataFrame:
    rsi = frame["rsi"].fillna(50.0)
    rsi_score = pd.Series(50.0, index=frame.index)
    mask = (rsi >= 50) & (rsi <= 70)
    rsi_score[mask] = 60 + (rsi[mask] - 50) / 20 * 25
    mask = (rsi > 70) & (rsi <= 80)
    rsi_score[mask] = 85 - (rsi[mask] - 70) / 10 * 10
    mask = rsi > 80
    rsi_score[mask] = 75 - (rsi[mask] - 80) / 20 * 25
    mask = (rsi >= 40) & (rsi < 50)
    rsi_score[mask] = 50 + (rsi[mask] - 40) / 10 * 10
    mask = rsi < 40
    rsi_score[mask] = 30 + (rsi[mask] / 40) * 20
    frame["technical_rsi_score_proxy"] = rsi_score.clip(0, 100)

    macd_score = pd.Series(50.0, index=frame.index)
    macd_above = frame["macd"] > frame["macd_signal"]
    macd_below = frame["macd"] < frame["macd_signal"]
    hist_delta = frame.groupby("stock_code")["macd_hist"].diff()
    macd_score[macd_above] = 62
    macd_score[macd_above & frame["macd"].gt(0)] = 72
    macd_score[macd_above & hist_delta.gt(0)] += 8
    macd_score[macd_below] = 40
    macd_score[macd_below & frame["macd"].lt(0)] = 32
    frame["technical_macd_score_proxy"] = macd_score.clip(0, 100)

    ma_score = pd.Series(45.0, index=frame.index)
    ma_score += np.where(frame["close"] > frame["ma20"], 18, 0)
    ma_score += np.where(frame["close"] > frame["ma60"], 12, 0)
    ma_score += np.where(frame["ma20"] > frame["ma60"], 15, 0)
    ma_score += np.where(frame["ma5"] > frame["ma10"], 10, 0)
    frame["technical_ma_score_proxy"] = ma_score.clip(0, 100)

    technical = frame[
        ["technical_rsi_score_proxy", "technical_macd_score_proxy", "technical_ma_score_proxy"]
    ].mean(axis=1)
    frame["technical_score_proxy"] = technical.clip(0, 100)

    volume_ratio = (frame["volume"] / frame["volume_ma20"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    volume_score = 50 + np.log(volume_ratio.fillna(1.0).clip(lower=1e-9)).clip(-1.5, 1.5) * 18
    frame["volume_score_proxy"] = pd.Series(volume_score, index=frame.index).clip(0, 100)

    frame["pattern_score_proxy"] = 50.0
    frame["total_score_proxy"] = (
        frame["technical_score_proxy"] * 0.55
        + frame["volume_score_proxy"] * 0.20
        + frame["pattern_score_proxy"] * 0.25
    ).clip(0, 100)
    return frame


def _add_forward_prices(frame: pd.DataFrame, max_horizon: int) -> pd.DataFrame:
    grouped = frame.groupby("stock_code", group_keys=False)
    frame["next_open"] = grouped["open"].shift(-1)
    frame["next_close"] = grouped["close"].shift(-1)
    for horizon in range(1, max_horizon + 2):
        frame[f"fwd_close_{horizon}"] = grouped["close"].shift(-horizon)
    return frame


def _eligible(frame: pd.DataFrame, min_turnover: int) -> pd.DataFrame:
    return frame[
        frame["close"].gt(0)
        & frame["turnover"].ge(min_turnover)
        & frame["ma20"].notna()
        & frame["ma60"].notna()
        & frame["total_score_proxy"].notna()
    ].copy()


def _rebalance_dates(frame: pd.DataFrame, holding_days: int) -> list[pd.Timestamp]:
    dates = sorted(frame["date"].dropna().unique())
    dates = [pd.Timestamp(item) for item in dates]
    return dates[:: max(1, holding_days)]


def _net_return(entry: pd.Series, exit_: pd.Series, fee_bps: float, tax_bps: float, slippage_bps: float) -> pd.Series:
    buy_multiplier = 1 + (fee_bps + slippage_bps) / 10_000
    sell_multiplier = 1 - (fee_bps + tax_bps + slippage_bps) / 10_000
    return (exit_ * sell_multiplier / (entry * buy_multiplier)) - 1


def _select_candidates(day: pd.DataFrame, strategy: str, top_n: int, rng: np.random.Generator | None = None) -> pd.DataFrame:
    if strategy == "score_proxy":
        return day.sort_values(["total_score_proxy", "stock_code"], ascending=[False, True]).head(top_n)
    if strategy == "momentum_20d":
        return day.dropna(subset=["mom_20d"]).sort_values(["mom_20d", "stock_code"], ascending=[False, True]).head(top_n)
    if strategy == "momentum_60d":
        return day.dropna(subset=["mom_60d"]).sort_values(["mom_60d", "stock_code"], ascending=[False, True]).head(top_n)
    if strategy == "momentum_120d":
        return day.dropna(subset=["mom_120d"]).sort_values(["mom_120d", "stock_code"], ascending=[False, True]).head(top_n)
    if strategy == "low_vol_20d":
        return day.dropna(subset=["vol_20d"]).sort_values(["vol_20d", "stock_code"], ascending=[True, True]).head(top_n)
    if strategy == "random":
        if rng is None:
            raise ValueError("random strategy requires rng")
        if len(day) <= top_n:
            return day.copy()
        selected = rng.choice(day.index.to_numpy(), size=top_n, replace=False)
        return day.loc[selected]
    raise ValueError(f"unknown strategy: {strategy}")


def replay_strategy(
    frame: pd.DataFrame,
    params: ReplayParams,
    *,
    strategy: str,
    execution_mode: str,
    top_n: int | None = None,
    random_seed: int | None = None,
) -> tuple[dict[str, float | int | str], pd.DataFrame]:
    top_n = top_n or params.top_n
    date_frame = _eligible(frame, params.min_turnover)
    dates = _rebalance_dates(date_frame, params.holding_days)
    rng = np.random.default_rng(random_seed) if random_seed is not None else None
    rows: list[dict[str, object]] = []
    prev_weights: dict[str, float] = {}

    for date in dates:
        day = date_frame[date_frame["date"] == date]
        if day.empty:
            continue
        selected = _select_candidates(day, strategy, top_n, rng)
        if execution_mode == "same_close":
            entry = selected["close"]
            exit_ = selected[f"fwd_close_{params.holding_days}"]
            execution_date = date
        elif execution_mode == "next_open":
            entry = selected["next_open"]
            exit_ = selected[f"fwd_close_{params.holding_days + 1}"]
            execution_date = date + pd.Timedelta(days=1)
        elif execution_mode == "next_close":
            entry = selected["next_close"]
            exit_ = selected[f"fwd_close_{params.holding_days + 1}"]
            execution_date = date + pd.Timedelta(days=1)
        else:
            raise ValueError(f"unknown execution_mode: {execution_mode}")

        valid = selected[entry.notna() & exit_.notna() & entry.gt(0) & exit_.gt(0)].copy()
        unfilled_count = max(0, top_n - len(valid))
        if valid.empty:
            period_return = 0.0
            weights: dict[str, float] = {}
        else:
            valid_entry = entry.loc[valid.index]
            valid_exit = exit_.loc[valid.index]
            net = _net_return(valid_entry, valid_exit, params.fee_bps, params.tax_bps, params.slippage_bps)
            target_weight = 1.0 / top_n
            period_return = float((net * target_weight).sum())
            weights = {str(code): target_weight for code in valid["stock_code"]}

        overlap_turnover = _turnover_proxy(prev_weights, weights)
        prev_weights = weights
        rows.append(
            {
                "decision_date": date,
                "execution_date_proxy": execution_date,
                "strategy": strategy,
                "execution_mode": execution_mode,
                "top_n": top_n,
                "period_return": period_return,
                "selected_count": len(valid),
                "unfilled_count": unfilled_count,
                "unfilled_ratio": unfilled_count / top_n,
                "turnover_proxy": overlap_turnover,
            }
        )

    period_df = pd.DataFrame(rows)
    metrics = _metrics_from_periods(period_df, params.holding_days)
    metrics.update({"strategy": strategy, "execution_mode": execution_mode, "top_n": top_n})
    return metrics, period_df


def _turnover_proxy(previous: dict[str, float], current: dict[str, float]) -> float:
    if not previous and not current:
        return 0.0
    keys = set(previous) | set(current)
    return float(sum(abs(current.get(key, 0.0) - previous.get(key, 0.0)) for key in keys) / 2)


def _metrics_from_periods(period_df: pd.DataFrame, holding_days: int) -> dict[str, float | int]:
    if period_df.empty:
        return {
            "periods": 0,
            "total_return": 0.0,
            "annual_return": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "avg_period_return": 0.0,
            "avg_unfilled_ratio": 1.0,
            "avg_turnover_proxy": 0.0,
        }
    returns = period_df["period_return"].astype(float)
    equity = (1 + returns).cumprod()
    total_return = float(equity.iloc[-1] - 1)
    periods_per_year = TRADING_DAYS_PER_YEAR / max(1, holding_days)
    years = len(returns) / periods_per_year
    annual_return = float((1 + total_return) ** (1 / years) - 1) if years > 0 and total_return > -1 else -1.0
    std = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / std * math.sqrt(periods_per_year)) if std > 0 else 0.0
    drawdown = equity / equity.cummax() - 1
    return {
        "periods": int(len(returns)),
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "win_rate": float((returns > 0).mean()),
        "avg_period_return": float(returns.mean()),
        "avg_unfilled_ratio": float(period_df["unfilled_ratio"].mean()),
        "avg_turnover_proxy": float(period_df["turnover_proxy"].mean()),
    }


def score_quantile_test(frame: pd.DataFrame, params: ReplayParams) -> pd.DataFrame:
    data = _eligible(frame, params.min_turnover).copy()
    records: list[pd.DataFrame] = []
    for date, group in data.groupby("date", sort=True):
        if len(group) < 50:
            continue
        ranked = group.copy()
        ranked["score_quantile"] = pd.qcut(
            ranked["total_score_proxy"].rank(method="first"),
            q=5,
            labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
        )
        records.append(ranked)
    if not records:
        return pd.DataFrame()
    scored = pd.concat(records, ignore_index=True)
    scored["future_5d_return"] = scored["fwd_close_5"] / scored["close"] - 1
    scored["future_20d_return"] = scored["fwd_close_20"] / scored["close"] - 1
    summary = (
        scored.dropna(subset=["score_quantile", "future_5d_return", "future_20d_return"])
        .groupby("score_quantile", observed=True)
        .agg(
            count=("stock_code", "size"),
            avg_total_score=("total_score_proxy", "mean"),
            avg_5d_return=("future_5d_return", "mean"),
            median_5d_return=("future_5d_return", "median"),
            win_rate_5d=("future_5d_return", lambda series: float((series > 0).mean())),
            avg_20d_return=("future_20d_return", "mean"),
            median_20d_return=("future_20d_return", "median"),
            win_rate_20d=("future_20d_return", lambda series: float((series > 0).mean())),
        )
        .reset_index()
    )
    return summary


def buy_hold_0050(config: TWStockConfig, params: ReplayParams) -> dict[str, float | int | str]:
    source = pd.read_csv(config.stock_data_file, encoding="utf-8-sig", low_memory=False)
    source["date"] = pd.to_datetime(source["日期"].astype(str), errors="coerce", format="mixed")
    source["stock_code"] = source["證券代號"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(4)
    source["close"] = pd.to_numeric(source["收盤價"], errors="coerce")
    data = source[
        (source["stock_code"] == "0050")
        & (source["date"] >= params.start_date)
        & (source["date"] <= params.end_date)
        & source["close"].gt(0)
    ].sort_values("date")
    returns = data["close"].pct_change().dropna()
    if returns.empty:
        return {"strategy": "buy_hold_0050", "execution_mode": "close_to_close", "top_n": 1, "periods": 0}
    equity = (1 + returns).cumprod()
    total_return = float(data["close"].iloc[-1] / data["close"].iloc[0] - 1)
    years = len(returns) / TRADING_DAYS_PER_YEAR
    annual_return = float((1 + total_return) ** (1 / years) - 1) if years > 0 and total_return > -1 else -1.0
    std = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / std * math.sqrt(TRADING_DAYS_PER_YEAR)) if std > 0 else 0.0
    drawdown = equity / equity.cummax() - 1
    return {
        "strategy": "buy_hold_0050",
        "execution_mode": "close_to_close",
        "top_n": 1,
        "periods": int(len(returns)),
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "win_rate": float((returns > 0).mean()),
        "avg_period_return": float(returns.mean()),
        "avg_unfilled_ratio": 0.0,
        "avg_turnover_proxy": 0.0,
    }


def _average_random_runs(frame: pd.DataFrame, params: ReplayParams, top_n: int) -> dict[str, float | int | str]:
    runs = []
    for seed in range(params.random_seeds):
        metrics, _ = replay_strategy(
            frame,
            params,
            strategy="random",
            execution_mode="next_open",
            top_n=top_n,
            random_seed=seed,
        )
        runs.append(metrics)
    numeric_keys = [key for key, value in runs[0].items() if isinstance(value, (int, float))]
    averaged = {key: float(np.mean([float(run.get(key, 0)) for run in runs])) for key in numeric_keys}
    averaged.update({"strategy": f"random_top{top_n}_avg_{params.random_seeds}", "execution_mode": "next_open", "top_n": top_n})
    averaged["periods"] = int(round(averaged.get("periods", 0)))
    return averaged


def _format_pct(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_num(value: object) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_no data_"
    text = frame.astype(str).replace({"nan": "", "None": ""})
    headers = [str(col) for col in text.columns]
    rows = text.values.tolist()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def _metrics_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_無資料_"
    cols = [
        "strategy",
        "execution_mode",
        "top_n",
        "periods",
        "total_return",
        "annual_return",
        "sharpe",
        "max_drawdown",
        "win_rate",
        "avg_unfilled_ratio",
        "avg_turnover_proxy",
    ]
    view = frame[[col for col in cols if col in frame.columns]].copy()
    pct_cols = ["total_return", "annual_return", "max_drawdown", "win_rate", "avg_unfilled_ratio", "avg_turnover_proxy"]
    for col in pct_cols:
        if col in view.columns:
            view[col] = view[col].map(_format_pct)
    if "sharpe" in view.columns:
        view["sharpe"] = view["sharpe"].map(_format_num)
    return _markdown_table(view)


def _quantile_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_無資料_"
    view = frame.copy()
    for col in ["avg_5d_return", "median_5d_return", "win_rate_5d", "avg_20d_return", "median_20d_return", "win_rate_20d"]:
        view[col] = view[col].map(_format_pct)
    view["avg_total_score"] = view["avg_total_score"].map(_format_num)
    return _markdown_table(view)


def write_report(
    output_dir: Path,
    *,
    params: ReplayParams,
    data_range: tuple[pd.Timestamp, pd.Timestamp],
    source_paths: dict[str, str],
    same_vs_t1: pd.DataFrame,
    topn: pd.DataFrame,
    quantiles: pd.DataFrame,
    baseline: pd.DataFrame,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    same_vs_t1.to_csv(output_dir / "same_close_vs_t1.csv", index=False, encoding="utf-8-sig")
    topn.to_csv(output_dir / "topn_sensitivity.csv", index=False, encoding="utf-8-sig")
    quantiles.to_csv(output_dir / "score_quantile_test.csv", index=False, encoding="utf-8-sig")
    baseline.to_csv(output_dir / "baseline_battle.csv", index=False, encoding="utf-8-sig")

    payload = {
        "start_date": params.start_date.strftime("%Y-%m-%d"),
        "end_date": params.end_date.strftime("%Y-%m-%d"),
        "holding_days": params.holding_days,
        "top_n": params.top_n,
        "fee_bps": params.fee_bps,
        "tax_bps": params.tax_bps,
        "slippage_bps": params.slippage_bps,
        "min_turnover": params.min_turnover,
        "random_seeds": params.random_seeds,
        "data_range": [item.strftime("%Y-%m-%d") for item in data_range],
        "source_paths": source_paths,
        "known_limitations": [
            "使用 score proxy，不是完整 UI Recommendation Profile 歷史重放。",
            "pattern_score_proxy 固定 50，因 all_stocks_data.csv 未保存歷史 pattern score。",
            "本報告使用 CSV 冷備份作為研究輸入，未重放 SQLite daily_prices 的完整歷史查詢路徑。",
            "未處理 survivor bias、下市股、完整 PIT 成分股與 corporate action adjusted close。",
            "turnover_proxy 是相鄰 rebalance 目標權重差異，不是完整成交明細 turnover。",
        ],
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report = output_dir / "REPORT.md"
    report.write_text(
        "\n".join(
            [
                "# Decision Validation Research",
                "",
                "## 範圍與限制",
                "",
                "- 本報告使用正式 CSV 冷備份 `all_stocks_data.csv` / `stock_data_whole.csv` 作為研究輸入。",
                "- 推薦分數是 `score proxy`：技術分數由 RSI / MACD / MA proxy 組成，量能分數由成交量相對 20 日均量組成，pattern 分數固定中性 50。",
                "- 因此本報告回答的是「目前可取得技術 score proxy 是否值得深入」，不是完整 UI 推薦引擎最終績效。",
                "- 所有 portfolio replay 均為週期性 Top N、等權、成本後回報；未處理完整委託簿、買賣價差、零股、下市股、survivor bias 或 PIT universe。",
                "",
                "## 參數",
                "",
                f"- 日期：{params.start_date.date()} 到 {params.end_date.date()}",
                f"- 持有天數 / rebalance 間隔：{params.holding_days} 個交易日",
                f"- 預設 Top N：{params.top_n}",
                f"- 成本：fee {params.fee_bps} bps、tax {params.tax_bps} bps、slippage {params.slippage_bps} bps",
                f"- 最低單日成交金額：{params.min_turnover:,}",
                "",
                "## 1. same_close vs T+1",
                "",
                _metrics_table(same_vs_t1),
                "",
                "## 2. Top N Sensitivity（score proxy, next_open）",
                "",
                _metrics_table(topn),
                "",
                "## 3. Score Quantile Test",
                "",
                _quantile_table(quantiles),
                "",
                "## 4. Baseline Battle（next_open，除 0050 buy-hold 外）",
                "",
                _metrics_table(baseline),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run decision validation research checks.")
    parser.add_argument("--start-date", default="2025-01-02")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--holding-days", type=int, default=5)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--top-n-list", default="5,10,20,30,50")
    parser.add_argument("--fee-bps", type=float, default=14.25)
    parser.add_argument("--tax-bps", type=float, default=30.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--min-turnover", type=int, default=20_000_000)
    parser.add_argument("--random-seeds", type=int, default=20)
    parser.add_argument("--output-dir", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = TWStockConfig()
    start = pd.Timestamp(args.start_date)
    if args.end_date:
        end = pd.Timestamp(args.end_date)
    else:
        sample = pd.read_csv(config.all_stocks_data_file, encoding="utf-8-sig", usecols=["日期"])
        end = pd.to_datetime(sample["日期"].astype(str), errors="coerce", format="mixed").max()
    params = ReplayParams(
        start_date=start,
        end_date=end,
        holding_days=args.holding_days,
        top_n=args.top_n,
        fee_bps=args.fee_bps,
        tax_bps=args.tax_bps,
        slippage_bps=args.slippage_bps,
        min_turnover=args.min_turnover,
        random_seeds=args.random_seeds,
    )
    history = _read_history(config, start, end)
    data_range = (history["date"].min(), history["date"].max())
    output_dir = Path(args.output_dir) if args.output_dir else config.output_root / "research_validation" / "decision_validation"

    same_rows = []
    for mode in ["same_close", "next_open", "next_close"]:
        metrics, _ = replay_strategy(history, params, strategy="score_proxy", execution_mode=mode)
        same_rows.append(metrics)
    same_vs_t1 = pd.DataFrame(same_rows)

    top_rows = []
    for value in [int(item.strip()) for item in args.top_n_list.split(",") if item.strip()]:
        metrics, _ = replay_strategy(history, params, strategy="score_proxy", execution_mode="next_open", top_n=value)
        top_rows.append(metrics)
    topn = pd.DataFrame(top_rows)

    quantiles = score_quantile_test(history, params)

    baseline_rows = []
    for strategy in ["score_proxy", "momentum_20d", "momentum_60d", "momentum_120d", "low_vol_20d"]:
        metrics, _ = replay_strategy(history, params, strategy=strategy, execution_mode="next_open")
        baseline_rows.append(metrics)
    baseline_rows.append(_average_random_runs(history, params, args.top_n))
    baseline_rows.append(buy_hold_0050(config, params))
    baseline = pd.DataFrame(baseline_rows)

    report = write_report(
        output_dir,
        params=params,
        data_range=data_range,
        source_paths={
            "all_stocks_data": str(config.all_stocks_data_file),
            "stock_data_whole": str(config.stock_data_file),
        },
        same_vs_t1=same_vs_t1,
        topn=topn,
        quantiles=quantiles,
        baseline=baseline,
    )
    print(report)


if __name__ == "__main__":
    main()
