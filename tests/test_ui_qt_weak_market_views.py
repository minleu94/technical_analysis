import os
import sys

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox

from ui_qt.models.pandas_table_model import PandasTableModel
from ui_qt.views.weak_industries_view import WeakIndustriesView
from ui_qt.views.weak_stocks_view import WeakStocksView
from ui_qt.views.strong_industries_view import StrongIndustriesView
from ui_qt.views.strong_stocks_view import StrongStocksView


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


class _ScreeningService:
    def __init__(self) -> None:
        self.fail = False

    @staticmethod
    def _stocks() -> tuple[pd.DataFrame, int]:
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

    @staticmethod
    def _industries() -> pd.DataFrame:
        return pd.DataFrame(
            [{"排名": 1, "指數名稱": "半導體", "收盤指數": "100", "漲幅%": "0.8"}]
        )

    def get_strong_stocks(self, *, period: str, top_n: int):
        if self.fail:
            raise RuntimeError("stock source unavailable")
        return self._stocks()

    def get_weak_stocks(self, *, period: str, top_n: int):
        if self.fail:
            raise RuntimeError("weak stock source unavailable")
        return self._stocks()

    def get_strong_industries(self, *, period: str, top_n: int):
        if self.fail:
            raise RuntimeError("industry source unavailable")
        return self._industries()

    def get_weak_industries(self, *, period: str, top_n: int):
        if self.fail:
            raise RuntimeError("weak industry source unavailable")
        return self._industries()


def _column_index(model: PandasTableModel, column_name: str) -> int:
    return model.getVisibleColumns().index(column_name)


def test_pandas_table_model_can_mark_positive_decline_column_red():
    model = PandasTableModel(pd.DataFrame([{"跌幅%": 9.9}]), red_positive_columns={"跌幅%"})
    index = model.index(0, 0)

    assert model.data(index, Qt.DisplayRole) == "9.90"
    assert model.data(index, Qt.ForegroundRole) == QColor(255, 68, 68)


def test_weak_stocks_show_decline_as_positive_value_with_red_semantic_color():
    app()
    view = WeakStocksView(screening_service=object())
    view._update_table_with_data(
        pd.DataFrame(
            [
                {
                    "排名": 1,
                    "證券代號": "2603",
                    "證券名稱": "長榮",
                    "收盤價": 100.0,
                    "漲幅%": -9.9,
                    "評分": "Bottom 1%",
                    "推薦理由": "相對弱勢",
                }
            ]
        )
    )

    assert view.stocks_model is not None
    decline_index = view.stocks_model.index(0, _column_index(view.stocks_model, "跌幅%"))
    assert view.stocks_model.data(decline_index, Qt.DisplayRole) == "9.90"
    assert view.stocks_model.data(decline_index, Qt.ForegroundRole) == QColor(255, 68, 68)


def test_weak_industries_show_decline_as_positive_value_with_red_semantic_color():
    app()
    view = WeakIndustriesView(screening_service=object())
    view._update_table_with_data(
        pd.DataFrame(
            [
                {
                    "排名": 1,
                    "指數名稱": "航運",
                    "收盤指數": 1234.5,
                    "漲幅%": -7.5,
                }
            ]
        )
    )

    assert view.industries_model is not None
    decline_index = view.industries_model.index(0, _column_index(view.industries_model, "跌幅%"))
    assert view.industries_model.data(decline_index, Qt.DisplayRole) == "7.50"
    assert view.industries_model.data(decline_index, Qt.ForegroundRole) == QColor(255, 68, 68)


def test_market_views_use_empty_models_instead_of_fake_zero_rows():
    app()
    service = _ScreeningService()
    views = (
        StrongStocksView(service),
        WeakStocksView(service),
        StrongIndustriesView(service),
        WeakIndustriesView(service),
    )

    for view in views:
        model = view.stocks_model if hasattr(view, "stocks_model") else view.industries_model
        assert model is not None
        assert model.rowCount() == 0
        assert "尚未載入" in view.status_label.text()
        view.deleteLater()


def test_market_views_clear_stale_rows_and_show_error_status(monkeypatch):
    app()
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))
    service = _ScreeningService()
    views = (
        StrongStocksView(service),
        WeakStocksView(service),
        StrongIndustriesView(service),
        WeakIndustriesView(service),
    )

    for view in views:
        if hasattr(view, "_refresh_stocks"):
            view._refresh_stocks(use_cache=False)
        else:
            view._refresh_industries(use_cache=False)
    counts = [
        (view.stocks_model if hasattr(view, "stocks_model") else view.industries_model).rowCount()
        for view in views
    ]
    statuses = [view.status_label.text() for view in views]
    assert counts == [1, 1, 1, 1], statuses

    service.fail = True
    for view in views:
        if hasattr(view, "_refresh_stocks"):
            view._refresh_stocks(use_cache=False)
        else:
            view._refresh_industries(use_cache=False)

    for view in views:
        model = view.stocks_model if hasattr(view, "stocks_model") else view.industries_model
        assert model is not None
        assert model.rowCount() == 0
        assert view.status_label.text().startswith("載入失敗：")
        view.deleteLater()
