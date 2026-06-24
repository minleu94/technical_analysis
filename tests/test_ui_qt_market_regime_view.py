import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from app_module.dtos import RegimeResultDTO
from ui_qt.views.market_regime_view import MarketRegimeView


class FakeRegimeService:
    def detect_regime(self):
        return RegimeResultDTO(
            regime="Trend",
            confidence=0.82,
            regime_name_cn="趨勢盤",
            details={
                "date": "2026-05-19",
                "close": 21900.0,
                "ma20": 21600.0,
                "ma60": 20500.0,
                "ma20_slope": 0.12,
                "adx": 31.5,
                "close_above_ma60": True,
                "ma20_slope_positive": True,
                "structure_score": 0.8,
                "strength_score": 0.75,
            },
        )

    def get_strategy_config(self, regime):
        return {"technical": {}, "patterns": {}, "signals": {}}


class FullMatchRegimeService:
    def detect_regime(self):
        return RegimeResultDTO(
            regime="Breakout",
            confidence=1.0,
            regime_name_cn="突破準備",
            details={
                "date": "2026-06-19",
                "breakout_score": 1.0,
                "bandwidth_compressed": True,
                "price_in_range": True,
                "adx_low": True,
                "volume_expanding": True,
            },
        )

    def get_strategy_config(self, regime):
        return {"technical": {}, "patterns": {}, "signals": {}}


class BreakoutBaseIndicatorsRegimeService:
    def detect_regime(self):
        return RegimeResultDTO(
            regime="Breakout",
            confidence=0.7,
            regime_name_cn="突破準備",
            details={
                "date": "2026-06-24",
                "close": 46043.60,
                "ma20": 45195.74,
                "ma60": 43888.12,
                "ma20_slope": 0.08,
                "adx": 30.07,
                "plus_di": 24.5,
                "minus_di": 18.2,
                "bb_bandwidth": 11.32,
                "breakout_score": 0.7,
                "bandwidth_compressed": True,
                "price_in_range": True,
                "adx_low": False,
                "volume_expanding": False,
            },
        )

    def get_strategy_config(self, regime):
        return {"technical": {}, "patterns": {}, "signals": {}}


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_market_regime_detection_shows_technical_details():
    app()
    view = MarketRegimeView(FakeRegimeService())

    view._detect_regime()

    assert view.layer3_group.isChecked() is True
    assert view.layer3_content.isHidden() is False
    assert "已展開" in view.layer3_group.title()
    assert view.layer3_layout.count() > 1

    layer3_text = []
    for index in range(view.layer3_layout.count()):
        item = view.layer3_layout.itemAt(index)
        widget = item.widget()
        if widget:
            layer3_text.append(widget.toolTip())
            for child in widget.findChildren(QLabel):
                layer3_text.append(child.text())
                layer3_text.append(child.toolTip())

    combined = "\n".join(layer3_text)
    assert "ADX 衡量趨勢強度" in combined
    assert "+DI 高於 -DI" in combined
    assert "0~1 的規則化分數" in combined


def test_market_regime_full_match_is_not_labeled_as_probability_confidence():
    app()
    view = MarketRegimeView(FullMatchRegimeService())

    view._detect_regime()

    confidence_text = view.layer1_confidence.text()
    assert "規則匹配度 100%" in confidence_text
    assert "信心度 100%" not in confidence_text
    assert "不是未來勝率" in view.layer1_confidence.toolTip()


def test_breakout_technical_details_show_base_indicators():
    app()
    view = MarketRegimeView(BreakoutBaseIndicatorsRegimeService())

    view._detect_regime()

    layer3_text = []
    for index in range(view.layer3_layout.count()):
        item = view.layer3_layout.itemAt(index)
        widget = item.widget()
        if widget:
            for child in widget.findChildren(QLabel):
                layer3_text.append(child.text())

    combined = "\n".join(layer3_text)
    assert "60日均線: 43888.12" in combined
    assert "+DI: 24.50" in combined
    assert "-DI: 18.20" in combined
    assert "突破分數: 0.700" in combined
