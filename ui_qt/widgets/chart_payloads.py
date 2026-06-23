from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


def build_equity_chart_payload(
    equity_series: pd.Series,
    benchmark_series: Optional[pd.Series] = None,
    cagr: Optional[float] = None,
    trade_list: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    equity = _clean_series(equity_series)
    benchmark = _clean_series(benchmark_series) if benchmark_series is not None else pd.Series(dtype=float)
    first_buy_date = _first_trade_date(trade_list, ["buy_date", "Buy Date", "進場日期"])
    align_date = _align_date(first_buy_date, equity.index) if first_buy_date is not None else None
    if align_date is None and len(equity) > 0:
        align_date = equity.index[0]

    return {
        "title": "Equity Curve",
        "cagr": float(cagr) if cagr is not None and _is_finite(cagr) else None,
        "equity": _series_to_points(equity),
        "benchmark": _normalized_benchmark_points(equity, benchmark, align_date),
        "markers": _trade_markers(trade_list, equity.index),
    }


def build_drawdown_chart_payload(
    drawdown_series: pd.Series,
    max_dd_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    drawdown = _clean_series(drawdown_series) * 100
    max_point = None
    window = None
    recovery = None

    if max_dd_info:
        max_date = _align_date(_to_timestamp(max_dd_info.get("max_drawdown_date")), drawdown.index)
        if max_date is not None and max_date in drawdown.index:
            max_point = {"time": max_date.strftime("%Y-%m-%d"), "value": float(drawdown.loc[max_date])}

        peak_date = _align_date(_to_timestamp(max_dd_info.get("peak_date")), drawdown.index)
        if peak_date is not None and max_date is not None:
            window = {"start": peak_date.strftime("%Y-%m-%d"), "end": max_date.strftime("%Y-%m-%d")}

        recovery_date = _align_date(_to_timestamp(max_dd_info.get("recovery_date")), drawdown.index)
        if recovery_date is not None:
            recovery = recovery_date.strftime("%Y-%m-%d")

    return {
        "kind": "lineArea",
        "title": "Drawdown Curve",
        "yLabel": "Drawdown (%)",
        "series": _series_to_points(drawdown),
        "lineColor": "#ef4444",
        "fillColor": "rgba(239, 68, 68, 0.22)",
        "baseline": 0.0,
        "maxPoint": max_point,
        "window": window,
        "recovery": recovery,
    }


def build_histogram_chart_payload(
    values: Iterable[Any],
    title: str,
    x_label: str,
    bins: int = 30,
    positive_negative_colors: bool = False,
    stats: Optional[Dict[str, float]] = None,
    default_color: str = "#38bdf8",
) -> Dict[str, Any]:
    clean_values = [_optional_float(value) for value in values]
    clean_values = [value for value in clean_values if value is not None]
    if not clean_values:
        return {
            "kind": "histogram",
            "title": title,
            "xLabel": x_label,
            "bins": [],
            "markers": [],
        }

    bin_count = max(1, min(int(bins), len(clean_values)))
    min_value = min(clean_values)
    max_value = max(clean_values)
    if min_value == max_value:
        min_value -= 0.5
        max_value += 0.5

    step = (max_value - min_value) / bin_count
    counts = [0 for _ in range(bin_count)]
    for value in clean_values:
        idx = min(int((value - min_value) / step), bin_count - 1)
        counts[idx] += 1

    bin_payload = []
    for idx, count in enumerate(counts):
        start = min_value + idx * step
        end = start + step
        center = (start + end) / 2
        color = default_color
        if positive_negative_colors:
            color = "#ef4444" if center < 0 else "#22c55e"
        bin_payload.append(
            {
                "start": float(start),
                "end": float(end),
                "center": float(center),
                "count": int(count),
                "color": color,
            }
        )

    return {
        "kind": "histogram",
        "title": title,
        "xLabel": x_label,
        "bins": bin_payload,
        "markers": _histogram_markers(stats),
    }


def build_trade_return_histogram_payload(
    returns: Iterable[Any],
    stats: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    clean_values = [_optional_float(value) for value in returns]
    clean_values = [value for value in clean_values if value is not None]
    if not clean_values:
        payload = build_histogram_chart_payload([], "交易報酬分布", "報酬率 (%)")
        payload["subtitle"] = "零軸左側為虧損，右側為獲利"
        payload["zeroLine"] = 0.0
        payload["legend"] = _return_legend()
        return payload

    max_abs = max(abs(min(clean_values)), abs(max(clean_values)))
    max_abs = float(math.ceil(max_abs)) if max_abs > 0 else 1.0
    bin_count = min(16, max(8, len(clean_values)))
    if bin_count % 2 != 0:
        bin_count += 1
    min_value = -max_abs
    max_value = max_abs
    step = (max_value - min_value) / bin_count
    counts = [0 for _ in range(bin_count)]
    for value in clean_values:
        idx = min(int((value - min_value) / step), bin_count - 1)
        counts[idx] += 1

    bins = []
    for idx, count in enumerate(counts):
        start = min_value + idx * step
        end = start + step
        center = (start + end) / 2
        bins.append(
            {
                "start": round(float(start), 2),
                "end": round(float(end), 2),
                "center": round(float(center), 2),
                "count": int(count),
                "color": "#ef4444" if center < 0 else "#22c55e",
            }
        )

    return {
        "kind": "histogram",
        "title": "交易報酬分布",
        "subtitle": "零軸左側為虧損，右側為獲利",
        "xLabel": "報酬率 (%)",
        "bins": bins,
        "markers": _histogram_markers(stats),
        "zeroLine": 0.0,
        "legend": _return_legend(),
    }


def build_holding_days_histogram_payload(holding_days: Iterable[Any]) -> Dict[str, Any]:
    clean_values = [_optional_float(value) for value in holding_days]
    clean_values = [value for value in clean_values if value is not None and value >= 0]
    if not clean_values:
        return {
            "kind": "histogram",
            "title": "持有天數分布",
            "xLabel": "持有天數區間",
            "bins": [],
            "markers": [],
            "legend": [],
        }

    buckets = [
        ("1-5d", 1.0, 5.0, "#38bdf8"),
        ("6-20d", 6.0, 20.0, "#22c55e"),
        ("21-60d", 21.0, 60.0, "#f59e0b"),
        ("61d+", 61.0, max(61.0, float(max(clean_values))), "#a78bfa"),
    ]
    bins = []
    for label, start, end, color in buckets:
        if label == "61d+":
            count = sum(1 for value in clean_values if value >= start)
        else:
            count = sum(1 for value in clean_values if start <= value <= end)
        if count == 0:
            continue
        bins.append(
            {
                "label": label,
                "start": start,
                "end": end,
                "center": round((start + end) / 2, 2),
                "count": int(count),
                "color": color,
            }
        )

    series = pd.Series(clean_values, dtype=float)
    markers = [
        {"label": "平均", "value": round(float(series.mean()), 2), "color": "#38bdf8"},
        {"label": "中位數", "value": round(float(series.median()), 2), "color": "#f59e0b"},
    ]
    return {
        "kind": "histogram",
        "title": "持有天數分布",
        "subtitle": "依實際持倉週期分組",
        "xLabel": "持有天數區間",
        "bins": bins,
        "markers": markers,
        "legend": [{"label": item["label"], "color": item["color"]} for item in bins],
    }


def _clean_series(series: Optional[pd.Series]) -> pd.Series:
    if series is None or len(series) == 0:
        return pd.Series(dtype=float)

    cleaned = series.copy()
    cleaned.index = pd.to_datetime(cleaned.index, errors="coerce")
    cleaned = pd.to_numeric(cleaned, errors="coerce")
    cleaned = cleaned[cleaned.index.notna()]
    cleaned = cleaned[cleaned.map(_is_finite)]
    return cleaned.sort_index()


def _series_to_points(series: pd.Series) -> List[Dict[str, Any]]:
    return [
        {"time": index.strftime("%Y-%m-%d"), "value": float(value)}
        for index, value in series.items()
    ]


def _normalized_benchmark_points(
    equity: pd.Series,
    benchmark: pd.Series,
    align_date: Optional[pd.Timestamp],
) -> List[Dict[str, Any]]:
    if len(equity) == 0 or len(benchmark) == 0 or align_date is None:
        return []

    bench_align_date = _align_date(align_date, benchmark.index)
    if bench_align_date is None:
        return []

    equity_align_value = float(equity.loc[align_date])
    benchmark_align_value = float(benchmark.loc[bench_align_date])
    if not _is_finite(benchmark_align_value) or benchmark_align_value == 0:
        return []

    common_index = equity.index.intersection(benchmark.index)
    if len(common_index) == 0:
        return []

    normalized = benchmark.loc[common_index] / benchmark_align_value * equity_align_value
    return _series_to_points(normalized)


def _trade_markers(trade_list: Optional[pd.DataFrame], equity_index: pd.DatetimeIndex) -> List[Dict[str, Any]]:
    if trade_list is None or len(trade_list) == 0 or len(equity_index) == 0:
        return []

    markers: List[Dict[str, Any]] = []
    buy_col = _find_column(trade_list, ["buy_date", "Buy Date", "進場日期"])
    sell_col = _find_column(trade_list, ["sell_date", "Sell Date", "出場日期"])
    buy_price_col = _find_column(trade_list, ["buy_price", "Buy Price", "進場價格"])
    sell_price_col = _find_column(trade_list, ["sell_price", "Sell Price", "出場價格"])
    shares_col = _find_column(trade_list, ["shares", "Shares", "股數"])
    return_pct_col = _find_column(trade_list, ["return_pct", "Return%", "報酬率%"])

    for _, row in trade_list.iterrows():
        buy_date = _align_date(_to_timestamp(row.get(buy_col)) if buy_col else None, equity_index)
        if buy_date is not None:
            price = _optional_float(row.get(buy_price_col)) if buy_price_col else None
            shares = _optional_float(row.get(shares_col)) if shares_col else None
            text = "BUY"
            if price is not None and shares is not None:
                text = f"BUY {price:.2f} x {int(shares)}"
            markers.append(
                {
                    "time": buy_date.strftime("%Y-%m-%d"),
                    "position": "belowBar",
                    "shape": "arrowUp",
                    "color": "#16a34a",
                    "text": text,
                }
            )

        sell_date = _align_date(_to_timestamp(row.get(sell_col)) if sell_col else None, equity_index)
        if sell_date is not None:
            price = _optional_float(row.get(sell_price_col)) if sell_price_col else None
            return_pct = _optional_float(row.get(return_pct_col)) if return_pct_col else None
            text = "SELL"
            if price is not None and return_pct is not None:
                pct = return_pct * 100 if abs(return_pct) <= 1 else return_pct
                sign = "+" if pct >= 0 else ""
                text = f"SELL {price:.2f} {sign}{pct:.2f}%"
            markers.append(
                {
                    "time": sell_date.strftime("%Y-%m-%d"),
                    "position": "aboveBar",
                    "shape": "arrowDown",
                    "color": "#dc2626",
                    "text": text,
                }
            )

    return sorted(markers, key=lambda marker: marker["time"])


def _first_trade_date(trade_list: Optional[pd.DataFrame], candidates: List[str]) -> Optional[pd.Timestamp]:
    if trade_list is None or len(trade_list) == 0:
        return None
    col = _find_column(trade_list, candidates)
    if col is None:
        return None
    return _to_timestamp(trade_list[col].iloc[0])


def _histogram_markers(stats: Optional[Dict[str, float]]) -> List[Dict[str, Any]]:
    if not stats:
        return []

    markers = []
    marker_defs = [
        ("mean", "平均", "#38bdf8"),
        ("median", "中位數", "#f59e0b"),
        ("var_95", "95% VaR", "#ef4444"),
    ]
    for key, label, color in marker_defs:
        value = _optional_float(stats.get(key))
        if value is not None:
            markers.append({"label": label, "value": value, "color": color})
    return markers


def _return_legend() -> List[Dict[str, str]]:
    return [
        {"label": "虧損", "color": "#ef4444"},
        {"label": "獲利", "color": "#22c55e"},
    ]


def _find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def _align_date(target: Optional[pd.Timestamp], index: pd.DatetimeIndex) -> Optional[pd.Timestamp]:
    if target is None or len(index) == 0:
        return None
    target = _normalize_timestamp_tz(target, index)
    if target in index:
        return pd.Timestamp(target)
    loc = index.searchsorted(target)
    if loc == 0:
        return pd.Timestamp(index[0])
    if loc >= len(index):
        return pd.Timestamp(index[-1])
    left = index[loc - 1]
    right = index[loc]
    return pd.Timestamp(left if abs(target - left) <= abs(right - target) else right)


def _normalize_timestamp_tz(target: pd.Timestamp, index: pd.DatetimeIndex) -> pd.Timestamp:
    if index.tz is None and target.tz is not None:
        return target.tz_localize(None)
    if index.tz is not None and target.tz is None:
        return target.tz_localize(index.tz)
    if index.tz is not None and target.tz != index.tz:
        return target.tz_convert(index.tz)
    return target


def _to_timestamp(value: Any) -> Optional[pd.Timestamp]:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return pd.Timestamp(timestamp)


def _optional_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if _is_finite(number) else None


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
