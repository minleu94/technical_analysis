from ui_qt.widgets.chart_widget import (
    DrawdownCurveWidget,
    EquityCurveWidget,
    HoldingDaysHistogramWidget,
    TradeReturnHistogramWidget,
)
from ui_qt.widgets.fast_chart_widget import (
    FastDrawdownCurveWidget,
    FastEquityCurveWidget,
    FastHoldingDaysHistogramWidget,
    FastTradeReturnHistogramWidget,
    select_drawdown_curve_widget_class,
    select_equity_curve_widget_class,
    select_holding_days_histogram_widget_class,
    select_trade_return_histogram_widget_class,
)


def test_select_equity_curve_widget_class_uses_fast_widget_when_available():
    selected = select_equity_curve_widget_class(prefer_fast=True, webengine_available=True)

    assert selected is FastEquityCurveWidget


def test_select_equity_curve_widget_class_falls_back_when_disabled():
    selected = select_equity_curve_widget_class(prefer_fast=False, webengine_available=True)

    assert selected is EquityCurveWidget


def test_select_equity_curve_widget_class_falls_back_without_webengine():
    selected = select_equity_curve_widget_class(prefer_fast=True, webengine_available=False)

    assert selected is EquityCurveWidget


def test_select_remaining_chart_classes_use_fast_widgets_when_available():
    assert select_drawdown_curve_widget_class(prefer_fast=True, webengine_available=True) is FastDrawdownCurveWidget
    assert (
        select_trade_return_histogram_widget_class(prefer_fast=True, webengine_available=True)
        is FastTradeReturnHistogramWidget
    )
    assert (
        select_holding_days_histogram_widget_class(prefer_fast=True, webengine_available=True)
        is FastHoldingDaysHistogramWidget
    )


def test_select_remaining_chart_classes_fall_back_without_webengine():
    assert select_drawdown_curve_widget_class(prefer_fast=True, webengine_available=False) is DrawdownCurveWidget
    assert (
        select_trade_return_histogram_widget_class(prefer_fast=True, webengine_available=False)
        is TradeReturnHistogramWidget
    )
    assert (
        select_holding_days_histogram_widget_class(prefer_fast=True, webengine_available=False)
        is HoldingDaysHistogramWidget
    )
