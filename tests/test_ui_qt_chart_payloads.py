import math

import pandas as pd

from ui_qt.widgets.chart_payloads import (
    build_drawdown_chart_payload,
    build_equity_chart_payload,
    build_holding_days_histogram_payload,
    build_histogram_chart_payload,
    build_trade_return_histogram_payload,
)


def test_build_equity_chart_payload_normalizes_benchmark_and_trade_markers():
    equity = pd.Series(
        [1000.0, 1100.0, 1210.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    benchmark = pd.Series(
        [50.0, 55.0, 60.0],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    trades = pd.DataFrame(
        {
            "buy_date": ["2024-01-02"],
            "sell_date": ["2024-01-03"],
            "buy_price": [100.0],
            "sell_price": [120.0],
            "shares": [10],
            "return_pct": [0.2],
        }
    )

    payload = build_equity_chart_payload(
        equity_series=equity,
        benchmark_series=benchmark,
        cagr=0.25,
        trade_list=trades,
    )

    assert payload["title"] == "Equity Curve"
    assert payload["cagr"] == 0.25
    assert payload["equity"] == [
        {"time": "2024-01-01", "value": 1000.0},
        {"time": "2024-01-02", "value": 1100.0},
        {"time": "2024-01-03", "value": 1210.0},
    ]
    assert payload["benchmark"] == [
        {"time": "2024-01-01", "value": 1000.0},
        {"time": "2024-01-02", "value": 1100.0},
        {"time": "2024-01-03", "value": 1200.0},
    ]
    assert payload["markers"] == [
        {
            "time": "2024-01-02",
            "position": "belowBar",
            "shape": "arrowUp",
            "color": "#16a34a",
            "text": "BUY 100.00 x 10",
        },
        {
            "time": "2024-01-03",
            "position": "aboveBar",
            "shape": "arrowDown",
            "color": "#dc2626",
            "text": "SELL 120.00 +20.00%",
        },
    ]


def test_build_equity_chart_payload_drops_non_finite_values_and_sorts_dates():
    equity = pd.Series(
        [math.nan, 1200.0, 1000.0, math.inf],
        index=["2024-01-04", "2024-01-03", "2024-01-01", "2024-01-02"],
    )

    payload = build_equity_chart_payload(equity)

    assert payload["equity"] == [
        {"time": "2024-01-01", "value": 1000.0},
        {"time": "2024-01-03", "value": 1200.0},
    ]
    assert payload["benchmark"] == []
    assert payload["markers"] == []


def test_build_drawdown_chart_payload_marks_max_drawdown_window():
    drawdown = pd.Series(
        [0.0, -0.05, -0.2, -0.1],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
    )
    payload = build_drawdown_chart_payload(
        drawdown,
        {
            "max_drawdown": -0.2,
            "max_drawdown_date": pd.Timestamp("2024-01-03"),
            "peak_date": pd.Timestamp("2024-01-01"),
            "recovery_date": pd.Timestamp("2024-01-04"),
        },
    )

    assert payload["title"] == "Drawdown Curve"
    assert payload["series"] == [
        {"time": "2024-01-01", "value": 0.0},
        {"time": "2024-01-02", "value": -5.0},
        {"time": "2024-01-03", "value": -20.0},
        {"time": "2024-01-04", "value": -10.0},
    ]
    assert payload["maxPoint"] == {"time": "2024-01-03", "value": -20.0}
    assert payload["window"] == {"start": "2024-01-01", "end": "2024-01-03"}
    assert payload["recovery"] == "2024-01-04"


def test_build_histogram_chart_payload_bins_values_and_summary_lines():
    payload = build_histogram_chart_payload(
        values=[-10.0, -5.0, 0.0, 5.0, 10.0],
        title="Trade Return Distribution",
        x_label="Return (%)",
        bins=5,
        positive_negative_colors=True,
        stats={"mean": 0.0, "median": 0.0, "var_95": -8.0},
    )

    assert payload["title"] == "Trade Return Distribution"
    assert payload["xLabel"] == "Return (%)"
    assert len(payload["bins"]) == 5
    assert sum(item["count"] for item in payload["bins"]) == 5
    assert payload["bins"][0]["color"] == "#ef4444"
    assert payload["bins"][-1]["color"] == "#22c55e"
    assert payload["markers"] == [
        {"label": "平均", "value": 0.0, "color": "#38bdf8"},
        {"label": "中位數", "value": 0.0, "color": "#f59e0b"},
        {"label": "95% VaR", "value": -8.0, "color": "#ef4444"},
    ]


def test_build_trade_return_histogram_payload_uses_symmetric_zero_centered_bins():
    payload = build_trade_return_histogram_payload(
        [-12.0, -4.0, 1.0, 3.0, 10.0],
        {"mean": -0.4, "median": 1.0, "var_95": -10.4},
    )

    assert payload["title"] == "交易報酬分布"
    assert payload["subtitle"] == "零軸左側為虧損，右側為獲利"
    assert payload["zeroLine"] == 0.0
    assert payload["bins"][0]["start"] == -12.0
    assert payload["bins"][-1]["end"] == 12.0
    assert any(item["label"] == "虧損" and item["color"] == "#ef4444" for item in payload["legend"])
    assert any(item["label"] == "獲利" and item["color"] == "#22c55e" for item in payload["legend"])


def test_build_holding_days_histogram_payload_groups_days_into_readable_buckets():
    payload = build_holding_days_histogram_payload([1, 3, 9, 18, 35, 80])

    assert payload["title"] == "持有天數分布"
    assert payload["xLabel"] == "持有天數區間"
    assert payload["bins"] == [
        {"label": "1-5d", "start": 1.0, "end": 5.0, "center": 3.0, "count": 2, "color": "#38bdf8"},
        {"label": "6-20d", "start": 6.0, "end": 20.0, "center": 13.0, "count": 2, "color": "#22c55e"},
        {"label": "21-60d", "start": 21.0, "end": 60.0, "center": 40.5, "count": 1, "color": "#f59e0b"},
        {"label": "61d+", "start": 61.0, "end": 80.0, "center": 70.5, "count": 1, "color": "#a78bfa"},
    ]
    assert payload["markers"] == [
        {"label": "平均", "value": 24.33, "color": "#38bdf8"},
        {"label": "中位數", "value": 13.5, "color": "#f59e0b"},
    ]
