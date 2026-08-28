import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtWidgets import QApplication

from ui_qt.views.dashboard_view import DashboardView


def _app() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


class _ScreeningService:
    def __init__(self) -> None:
        self.fail_stocks = False
        self.fail_industries = False

    def get_strong_stocks(self, *, period: str, top_n: int):
        if self.fail_stocks:
            raise RuntimeError("daily source unavailable")
        return (
            pd.DataFrame(
                [
                    {
                        "排名": 1,
                        "證券代號": "2330",
                        "證券名稱": "台積電",
                        "收盤價": "1000",
                        "漲幅%": "1.2",
                        "評分": "90",
                        "推薦理由": "測試",
                    }
                ]
            ),
            20,
        )

    def get_strong_industries(self, *, period: str, top_n: int):
        if self.fail_industries:
            raise RuntimeError("industry source unavailable")
        return pd.DataFrame(
            [{"排名": 1, "指數名稱": "半導體", "收盤指數": "100", "漲幅%": "0.8"}]
        )


class _RegimeService:
    def detect_regime(self):
        raise AssertionError("regime is not needed for this test")


def test_dashboard_initializes_and_surfaces_success_counts() -> None:
    _app()
    screening = _ScreeningService()
    view = DashboardView(screening, _RegimeService())

    assert view.strong_stocks_model is not None
    assert view.strong_stocks_model.rowCount() == 1
    assert view.stocks_status_label.text() == "已更新：1 筆；掃描範圍 20 檔"
    assert view.strong_industries_model is not None
    assert view.strong_industries_model.rowCount() == 1
    assert view.industries_status_label.text() == "已更新：1 筆"

    view.deleteLater()


def test_dashboard_clears_stale_rows_when_refresh_fails() -> None:
    _app()
    screening = _ScreeningService()
    view = DashboardView(screening, _RegimeService())

    screening.fail_stocks = True
    screening.fail_industries = True
    view._refresh_stocks()
    view._refresh_industries()

    assert view.strong_stocks_model is not None
    assert view.strong_stocks_model.rowCount() == 0
    assert "載入失敗：daily source unavailable" == view.stocks_status_label.text()
    assert view.strong_industries_model is not None
    assert view.strong_industries_model.rowCount() == 0
    assert "載入失敗：industry source unavailable" == view.industries_status_label.text()

    view.deleteLater()
