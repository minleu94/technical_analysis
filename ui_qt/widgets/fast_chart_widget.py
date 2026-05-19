from __future__ import annotations

import json
from typing import Optional, Type

import pandas as pd
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui_qt.widgets.chart_payloads import (
    build_drawdown_chart_payload,
    build_equity_chart_payload,
    build_holding_days_histogram_payload,
    build_histogram_chart_payload,
    build_trade_return_histogram_payload,
)
from ui_qt.widgets.chart_widget import (
    DrawdownCurveWidget,
    EquityCurveWidget,
    HoldingDaysHistogramWidget,
    TradeReturnHistogramWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    HAS_QTWEBENGINE = True
except ImportError:
    QWebEngineView = None
    HAS_QTWEBENGINE = False


class _FastCanvasChartWidget(QWidget):
    """Shared QtWebEngine host for compact HTML canvas chart payloads."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if not HAS_QTWEBENGINE:
            self.web_view = None
            self.fallback_label = QLabel("Fast chart unavailable: QtWebEngine is not installed.")
            self.fallback_label.setStyleSheet("color: #666; padding: 12px;")
            layout.addWidget(self.fallback_label)
            return

        self.web_view = QWebEngineView(self)
        self.web_view.setMinimumSize(400, 300)
        layout.addWidget(self.web_view)
        self._set_payload(self.empty_payload())

    def empty_payload(self) -> dict:
        return {"kind": "empty", "title": "Chart"}

    def _set_payload(self, payload: dict):
        if self.web_view is None:
            self.fallback_label.setText("Fast chart unavailable: QtWebEngine is not installed.")
            return
        self.web_view.setHtml(_build_html(payload))


class FastEquityCurveWidget(_FastCanvasChartWidget):
    """HTML canvas equity chart for faster pan-free redraws than Matplotlib."""

    def empty_payload(self) -> dict:
        return build_equity_chart_payload(pd.Series(dtype=float))

    def plot(
        self,
        equity_series: pd.Series,
        benchmark_series: Optional[pd.Series] = None,
        cagr: Optional[float] = None,
        trade_list: Optional[pd.DataFrame] = None,
    ):
        payload = build_equity_chart_payload(equity_series, benchmark_series, cagr, trade_list)
        self._set_payload(payload)


class FastDrawdownCurveWidget(_FastCanvasChartWidget):
    """HTML canvas drawdown area chart."""

    def empty_payload(self) -> dict:
        return build_drawdown_chart_payload(pd.Series(dtype=float))

    def plot(self, drawdown_series: pd.Series, max_dd_info: Optional[dict] = None):
        self._set_payload(build_drawdown_chart_payload(drawdown_series, max_dd_info))


class FastTradeReturnHistogramWidget(_FastCanvasChartWidget):
    """HTML canvas trade return distribution chart."""

    def empty_payload(self) -> dict:
        return build_trade_return_histogram_payload([], None)

    def plot(self, returns, stats: Optional[dict] = None):
        self._set_payload(build_trade_return_histogram_payload(returns, stats))


class FastHoldingDaysHistogramWidget(_FastCanvasChartWidget):
    """HTML canvas holding-period distribution chart."""

    def empty_payload(self) -> dict:
        return build_holding_days_histogram_payload([])

    def plot(self, holding_days):
        self._set_payload(build_holding_days_histogram_payload(holding_days))


def create_equity_curve_widget(parent=None, prefer_fast: bool = True) -> QWidget:
    widget_class = select_equity_curve_widget_class(prefer_fast=prefer_fast)
    return widget_class(parent)


def create_drawdown_curve_widget(parent=None, prefer_fast: bool = True) -> QWidget:
    widget_class = select_drawdown_curve_widget_class(prefer_fast=prefer_fast)
    return widget_class(parent)


def create_trade_return_histogram_widget(parent=None, prefer_fast: bool = True) -> QWidget:
    widget_class = select_trade_return_histogram_widget_class(prefer_fast=prefer_fast)
    return widget_class(parent)


def create_holding_days_histogram_widget(parent=None, prefer_fast: bool = True) -> QWidget:
    widget_class = select_holding_days_histogram_widget_class(prefer_fast=prefer_fast)
    return widget_class(parent)


def select_equity_curve_widget_class(
    prefer_fast: bool = True,
    webengine_available: Optional[bool] = None,
) -> Type[QWidget]:
    available = HAS_QTWEBENGINE if webengine_available is None else webengine_available
    if prefer_fast and available:
        return FastEquityCurveWidget
    return EquityCurveWidget


def select_drawdown_curve_widget_class(
    prefer_fast: bool = True,
    webengine_available: Optional[bool] = None,
) -> Type[QWidget]:
    available = HAS_QTWEBENGINE if webengine_available is None else webengine_available
    if prefer_fast and available:
        return FastDrawdownCurveWidget
    return DrawdownCurveWidget


def select_trade_return_histogram_widget_class(
    prefer_fast: bool = True,
    webengine_available: Optional[bool] = None,
) -> Type[QWidget]:
    available = HAS_QTWEBENGINE if webengine_available is None else webengine_available
    if prefer_fast and available:
        return FastTradeReturnHistogramWidget
    return TradeReturnHistogramWidget


def select_holding_days_histogram_widget_class(
    prefer_fast: bool = True,
    webengine_available: Optional[bool] = None,
) -> Type[QWidget]:
    available = HAS_QTWEBENGINE if webengine_available is None else webengine_available
    if prefer_fast and available:
        return FastHoldingDaysHistogramWidget
    return HoldingDaysHistogramWidget


def _build_html(payload: dict) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #0b1020;
      color: #e5e7eb;
      font-family: "Segoe UI", Arial, sans-serif;
    }}
    #wrap {{
      position: relative;
      width: 100vw;
      height: 100vh;
    }}
    canvas {{
      width: 100%;
      height: 100%;
      display: block;
    }}
    #tooltip {{
      position: absolute;
      pointer-events: none;
      display: none;
      padding: 6px 8px;
      border: 1px solid #334155;
      border-radius: 6px;
      background: rgba(15, 23, 42, 0.94);
      color: #f8fafc;
      font-size: 12px;
      box-shadow: 0 8px 20px rgba(0,0,0,0.28);
      white-space: pre;
    }}
  </style>
</head>
<body>
  <div id="wrap">
    <canvas id="chart"></canvas>
    <div id="tooltip"></div>
  </div>
  <script>
    const payload = {payload_json};
    const canvas = document.getElementById('chart');
    const tooltip = document.getElementById('tooltip');
    const ctx = canvas.getContext('2d');
    const colors = {{
      grid: '#1f2937',
      axis: '#64748b',
      text: '#cbd5e1',
      equity: '#38bdf8',
      benchmark: '#94a3b8',
      markerBuy: '#16a34a',
      markerSell: '#dc2626',
      crosshair: 'rgba(203, 213, 225, 0.45)'
    }};
    let hoverX = null;

    function resize() {{
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(canvas.clientWidth * dpr);
      canvas.height = Math.floor(canvas.clientHeight * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    }}

    function allPoints() {{
      if (payload.equity) {{
        return [...payload.equity, ...payload.benchmark].filter(p => Number.isFinite(p.value));
      }}
      if (payload.series) {{
        const baseline = Number.isFinite(payload.baseline) ? [{{time: '', value: payload.baseline}}] : [];
        return [...payload.series, ...baseline].filter(p => Number.isFinite(p.value));
      }}
      return [];
    }}

    function ranges(points) {{
      if (!points.length) return null;
      const minY = Math.min(...points.map(p => p.value));
      const maxY = Math.max(...points.map(p => p.value));
      const pad = Math.max((maxY - minY) * 0.08, Math.abs(maxY || 1) * 0.02);
      return {{
        minY: minY - pad,
        maxY: maxY + pad,
        minX: 0,
        maxX: Math.max((payload.equity || payload.series || []).length - 1, (payload.benchmark || []).length - 1, 1)
      }};
    }}

    function plotArea() {{
      return {{
        left: 64,
        right: canvas.clientWidth - 20,
        top: payload.subtitle ? 56 : 36,
        bottom: canvas.clientHeight - (payload.legend && payload.legend.length ? 58 : 38)
      }};
    }}

    function xForIndex(i, area, range) {{
      return area.left + ((i - range.minX) / (range.maxX - range.minX)) * (area.right - area.left);
    }}

    function yForValue(value, area, range) {{
      return area.bottom - ((value - range.minY) / (range.maxY - range.minY)) * (area.bottom - area.top);
    }}

    function drawGrid(area, range) {{
      ctx.strokeStyle = colors.grid;
      ctx.lineWidth = 1;
      ctx.font = '12px Segoe UI, Arial';
      ctx.fillStyle = colors.text;
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      for (let i = 0; i <= 4; i++) {{
        const y = area.top + (area.bottom - area.top) * i / 4;
        const value = range.maxY - (range.maxY - range.minY) * i / 4;
        ctx.beginPath();
        ctx.moveTo(area.left, y);
        ctx.lineTo(area.right, y);
        ctx.stroke();
        ctx.fillText(value.toLocaleString(undefined, {{maximumFractionDigits: 0}}), area.left - 8, y);
      }}
    }}

    function drawSeries(series, color, width, dash = []) {{
      if (!series.length) return;
      const area = plotArea();
      const range = ranges(allPoints());
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.setLineDash(dash);
      ctx.beginPath();
      series.forEach((point, i) => {{
        const x = xForIndex(i, area, range);
        const y = yForValue(point.value, area, range);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }});
      ctx.stroke();
      ctx.restore();
    }}

    function drawAreaSeries(series, color, fillColor) {{
      if (!series.length) return;
      const area = plotArea();
      const range = ranges(allPoints());
      const baseline = Number.isFinite(payload.baseline) ? payload.baseline : 0;
      const baselineY = yForValue(baseline, area, range);
      ctx.save();
      ctx.beginPath();
      series.forEach((point, i) => {{
        const x = xForIndex(i, area, range);
        const y = yForValue(point.value, area, range);
        if (i === 0) ctx.moveTo(x, baselineY);
        ctx.lineTo(x, y);
      }});
      const lastX = xForIndex(series.length - 1, area, range);
      const firstX = xForIndex(0, area, range);
      ctx.lineTo(lastX, baselineY);
      ctx.lineTo(firstX, baselineY);
      ctx.closePath();
      ctx.fillStyle = fillColor || 'rgba(56, 189, 248, 0.18)';
      ctx.fill();
      ctx.restore();
      drawSeries(series, color, 2);
    }}

    function drawMarkers(area, range) {{
      const indexByTime = new Map(payload.equity.map((p, i) => [p.time, i]));
      for (const marker of payload.markers) {{
        const i = indexByTime.get(marker.time);
        if (i === undefined) continue;
        const point = payload.equity[i];
        const x = xForIndex(i, area, range);
        const y = yForValue(point.value, area, range);
        ctx.fillStyle = marker.shape === 'arrowUp' ? colors.markerBuy : colors.markerSell;
        ctx.beginPath();
        if (marker.shape === 'arrowUp') {{
          ctx.moveTo(x, y - 14);
          ctx.lineTo(x - 6, y - 2);
          ctx.lineTo(x + 6, y - 2);
        }} else {{
          ctx.moveTo(x, y + 14);
          ctx.lineTo(x - 6, y + 2);
          ctx.lineTo(x + 6, y + 2);
        }}
        ctx.closePath();
        ctx.fill();
      }}
    }}

    function drawCrosshair(area, range) {{
      const hoverSeries = payload.equity || payload.series || [];
      if (hoverX === null || !hoverSeries.length) return;
      const rawIndex = Math.round((hoverX - area.left) / (area.right - area.left) * range.maxX);
      const i = Math.max(0, Math.min(hoverSeries.length - 1, rawIndex));
      const point = hoverSeries[i];
      const x = xForIndex(i, area, range);
      const y = yForValue(point.value, area, range);
      ctx.strokeStyle = colors.crosshair;
      ctx.setLineDash([3, 4]);
      ctx.beginPath();
      ctx.moveTo(x, area.top);
      ctx.lineTo(x, area.bottom);
      ctx.moveTo(area.left, y);
      ctx.lineTo(area.right, y);
      ctx.stroke();
      ctx.setLineDash([]);
      tooltip.style.display = 'block';
      tooltip.style.left = `${{Math.min(x + 12, canvas.clientWidth - 170)}}px`;
      tooltip.style.top = `${{Math.max(area.top + 4, y - 38)}}px`;
      const label = payload.equity ? 'Equity' : (payload.yLabel || 'Value');
      const prefix = payload.equity ? '$' : '';
      tooltip.textContent = `${{point.time}}\\n${{label}}: ${{prefix}}${{point.value.toLocaleString(undefined, {{maximumFractionDigits: 2}})}}`;
    }}

    function drawTitle() {{
      ctx.fillStyle = colors.text;
      ctx.font = '600 14px Segoe UI, Arial';
      ctx.textAlign = 'left';
      const cagr = payload.cagr === null || payload.cagr === undefined ? '' : `  CAGR: ${{(payload.cagr * 100).toFixed(2)}}%`;
      ctx.fillText(`${{payload.title}}${{cagr}}`, 16, 22);
      if (payload.subtitle) {{
        ctx.font = '12px Segoe UI, Arial';
        ctx.fillStyle = colors.axis;
        ctx.fillText(payload.subtitle, 16, 42);
      }}
    }}

    function drawLegend(area) {{
      const legend = payload.legend || [];
      if (!legend.length) return;
      let x = area.left;
      const y = canvas.clientHeight - 28;
      ctx.font = '12px Segoe UI, Arial';
      ctx.textAlign = 'left';
      for (const item of legend) {{
        ctx.fillStyle = item.color;
        ctx.fillRect(x, y - 8, 10, 10);
        ctx.fillStyle = colors.text;
        ctx.fillText(item.label, x + 16, y);
        x += ctx.measureText(item.label).width + 42;
      }}
    }}

    function drawLineAreaChart() {{
      const points = allPoints();
      if (!points.length) {{
        drawEmpty();
        return;
      }}
      const area = plotArea();
      const range = ranges(points);
      drawGrid(area, range);
      drawAreaSeries(payload.series || [], payload.lineColor || colors.equity, payload.fillColor);
      if (payload.window) {{
        const indexByTime = new Map((payload.series || []).map((p, i) => [p.time, i]));
        const start = indexByTime.get(payload.window.start);
        const end = indexByTime.get(payload.window.end);
        if (start !== undefined && end !== undefined) {{
          ctx.fillStyle = 'rgba(239, 68, 68, 0.10)';
          const x1 = xForIndex(start, area, range);
          const x2 = xForIndex(end, area, range);
          ctx.fillRect(Math.min(x1, x2), area.top, Math.abs(x2 - x1), area.bottom - area.top);
        }}
      }}
      if (payload.maxPoint) {{
        const i = (payload.series || []).findIndex(p => p.time === payload.maxPoint.time);
        if (i >= 0) {{
          ctx.fillStyle = '#f87171';
          ctx.beginPath();
          ctx.arc(xForIndex(i, area, range), yForValue(payload.maxPoint.value, area, range), 4, 0, Math.PI * 2);
          ctx.fill();
        }}
      }}
      drawCrosshair(area, range);
    }}

    function drawHistogram() {{
      const bins = payload.bins || [];
      if (!bins.length) {{
        drawEmpty();
        return;
      }}
      const area = plotArea();
      const maxCount = Math.max(...bins.map(b => b.count), 1);
      const minX = Math.min(...bins.map(b => b.start));
      const maxX = Math.max(...bins.map(b => b.end));
      const categorical = bins.every(b => b.label);
      ctx.strokeStyle = colors.grid;
      ctx.fillStyle = colors.text;
      ctx.font = '12px Segoe UI, Arial';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {{
        const y = area.top + (area.bottom - area.top) * i / 4;
        const value = Math.round(maxCount - maxCount * i / 4);
        ctx.beginPath();
        ctx.moveTo(area.left, y);
        ctx.lineTo(area.right, y);
        ctx.stroke();
        ctx.fillText(value.toString(), area.left - 8, y);
      }}
      const width = area.right - area.left;
      const height = area.bottom - area.top;
      for (const bin of bins) {{
        const idx = bins.indexOf(bin);
        const x1 = categorical
          ? area.left + idx * width / bins.length
          : area.left + ((bin.start - minX) / (maxX - minX)) * width;
        const x2 = categorical
          ? area.left + (idx + 1) * width / bins.length
          : area.left + ((bin.end - minX) / (maxX - minX)) * width;
        const barH = (bin.count / maxCount) * height;
        ctx.fillStyle = bin.color || colors.equity;
        ctx.fillRect(x1 + 1, area.bottom - barH, Math.max(1, x2 - x1 - 2), barH);
        ctx.fillStyle = colors.text;
        ctx.font = '12px Segoe UI, Arial';
        ctx.textAlign = 'center';
        ctx.fillText(String(bin.count), (x1 + x2) / 2, area.bottom - barH - 8);
        if (categorical) {{
          ctx.fillStyle = colors.axis;
          ctx.fillText(bin.label, (x1 + x2) / 2, area.bottom + 18);
        }}
      }}
      if (!categorical && Number.isFinite(payload.zeroLine)) {{
        const zeroX = area.left + ((payload.zeroLine - minX) / (maxX - minX)) * width;
        ctx.strokeStyle = '#e5e7eb';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(zeroX, area.top);
        ctx.lineTo(zeroX, area.bottom);
        ctx.stroke();
        ctx.fillStyle = colors.text;
        ctx.textAlign = 'center';
        ctx.fillText('0%', zeroX, area.bottom + 18);
      }}
      for (const marker of payload.markers || []) {{
        if (categorical) continue;
        const x = area.left + ((marker.value - minX) / (maxX - minX)) * width;
        if (x < area.left || x > area.right) continue;
        ctx.strokeStyle = marker.color;
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(x, area.top);
        ctx.lineTo(x, area.bottom);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = marker.color;
        ctx.textAlign = 'left';
        ctx.fillText(marker.label, x + 4, area.top + 12);
      }}
      ctx.fillStyle = colors.text;
      ctx.textAlign = 'center';
      ctx.fillText(payload.xLabel || '', (area.left + area.right) / 2, canvas.clientHeight - (payload.legend && payload.legend.length ? 42 : 12));
      drawLegend(area);
    }}

    function drawEmpty() {{
      ctx.fillStyle = colors.text;
      ctx.font = '14px Segoe UI, Arial';
      ctx.textAlign = 'center';
      ctx.fillText('No chart data', canvas.clientWidth / 2, canvas.clientHeight / 2);
    }}

    function draw() {{
      ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
      drawTitle();
      if (payload.kind === 'histogram') {{
        drawHistogram();
        return;
      }}
      if (payload.kind === 'lineArea') {{
        drawLineAreaChart();
        return;
      }}
      const points = allPoints();
      if (!points.length) {{
        drawEmpty();
        return;
      }}
      const area = plotArea();
      const range = ranges(points);
      drawGrid(area, range);
      drawSeries(payload.benchmark, colors.benchmark, 1.5, [6, 5]);
      drawSeries(payload.equity, colors.equity, 2.5);
      drawMarkers(area, range);
      drawCrosshair(area, range);
    }}

    canvas.addEventListener('mousemove', event => {{
      hoverX = event.offsetX;
      draw();
    }});
    canvas.addEventListener('mouseleave', () => {{
      hoverX = null;
      tooltip.style.display = 'none';
      draw();
    }});
    window.addEventListener('resize', resize);
    resize();
  </script>
</body>
</html>"""
