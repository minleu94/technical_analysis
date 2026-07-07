import os
import sys

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from ui_qt.models.pandas_table_model import PandasTableModel
from ui_qt.views.weak_industries_view import WeakIndustriesView
from ui_qt.views.weak_stocks_view import WeakStocksView


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


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
