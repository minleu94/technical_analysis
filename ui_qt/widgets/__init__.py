"""
圖表組件模組
"""

from ui_qt.widgets.chart_widget import (
    EquityCurveWidget,
    DrawdownCurveWidget,
    TradeReturnHistogramWidget,
    HoldingDaysHistogramWidget
)
from ui_qt.widgets.fast_chart_widget import (
    FastDrawdownCurveWidget,
    FastEquityCurveWidget,
    FastHoldingDaysHistogramWidget,
    FastTradeReturnHistogramWidget,
    create_drawdown_curve_widget,
    create_equity_curve_widget,
    create_holding_days_histogram_widget,
    create_trade_return_histogram_widget,
    select_drawdown_curve_widget_class,
    select_equity_curve_widget_class,
    select_holding_days_histogram_widget_class,
    select_trade_return_histogram_widget_class,
)
from ui_qt.widgets.info_button import InfoButton, InfoDialog

__all__ = [
    'EquityCurveWidget',
    'FastEquityCurveWidget',
    'FastDrawdownCurveWidget',
    'FastTradeReturnHistogramWidget',
    'FastHoldingDaysHistogramWidget',
    'DrawdownCurveWidget',
    'TradeReturnHistogramWidget',
    'HoldingDaysHistogramWidget',
    'create_equity_curve_widget',
    'create_drawdown_curve_widget',
    'create_trade_return_histogram_widget',
    'create_holding_days_histogram_widget',
    'select_equity_curve_widget_class',
    'select_drawdown_curve_widget_class',
    'select_trade_return_histogram_widget_class',
    'select_holding_days_histogram_widget_class',
    'InfoButton',
    'InfoDialog'
]

