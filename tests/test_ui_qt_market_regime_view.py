import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
