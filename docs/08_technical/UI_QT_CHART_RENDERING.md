# UI Qt Chart Rendering

> Last updated: 2026-05-19

## Summary

The Backtest chart tab now uses a fast QtWebEngine + HTML5 Canvas renderer for the four primary result charts:

- Equity Curve
- Drawdown Curve
- Trade Return Distribution
- Holding Period Distribution

The legacy Matplotlib widgets remain available as fallback widgets. Factory functions choose the fast renderer when QtWebEngine is importable and fall back to the Matplotlib implementation otherwise.

## Architecture

Chart rendering is split into two layers:

1. `ui_qt/widgets/chart_payloads.py`
   - Pure Python payload builders.
   - Converts pandas `Series` and `DataFrame` inputs into JSON-serializable structures.
   - Owns benchmark normalization, drawdown window metadata, trade markers, return bins, and holding-period buckets.

2. `ui_qt/widgets/fast_chart_widget.py`
   - QtWebEngine host widgets.
   - Renders payloads with a local HTML5 Canvas document.
   - Does not load external JavaScript, CDN assets, or TradingView dependencies.

`ui_qt/views/backtest_view.py` creates charts through factory functions instead of instantiating concrete widgets directly.

## Widgets

Fast widgets:

- `FastEquityCurveWidget`
- `FastDrawdownCurveWidget`
- `FastTradeReturnHistogramWidget`
- `FastHoldingDaysHistogramWidget`

Factory functions:

- `create_equity_curve_widget()`
- `create_drawdown_curve_widget()`
- `create_trade_return_histogram_widget()`
- `create_holding_days_histogram_widget()`

Fallback widgets:

- `EquityCurveWidget`
- `DrawdownCurveWidget`
- `TradeReturnHistogramWidget`
- `HoldingDaysHistogramWidget`

## Visualization Rules

Trade return distribution:

- Uses a symmetric zero-centered range.
- Red bars represent losses left of zero.
- Green bars represent wins right of zero.
- Shows a zero axis, legend, and per-bin trade counts.

Holding period distribution:

- Uses practical holding buckets instead of many small day-level bars:
  - `1-5d`
  - `6-20d`
  - `21-60d`
  - `61d+`
- Shows per-bucket trade counts and legend labels.

Drawdown:

- Uses an area chart below the zero baseline.
- Highlights maximum drawdown point and peak-to-trough window when metadata is available.

Equity curve:

- Shows strategy equity, normalized benchmark, buy/sell markers, and hover crosshair.

## Why Not TradingView Lightweight Charts Yet

The current charts are performance/result-analysis charts rather than full trading workbench charts. A local Canvas renderer avoids new package dependencies, JavaScript build tooling, network assets, and TradingView integration/licensing questions.

Consider TradingView Lightweight Charts later if the UI needs:

- Candlestick/K-line primary charts.
- Multi-pane technical indicators.
- Volume overlays.
- Rich drawing tools or TradingView-style time/price axes.

## Verification

Focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts= tests\test_ui_qt_chart_payloads.py tests\test_ui_qt_chart_widget_factory.py tests\test_portfolio_mvp.py -q
```

Import/compile check:

```powershell
.\.venv\Scripts\python.exe -m py_compile ui_qt\widgets\chart_payloads.py ui_qt\widgets\fast_chart_widget.py ui_qt\views\backtest_view.py ui_qt\widgets\__init__.py
```
