from ui_qt.theme import MIDNIGHT_ANALYST, build_global_stylesheet

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui_qt.widgets.theme_widgets import CompactCodeList, StatusBadge
from ui_qt.main import apply_app_theme


def test_midnight_analyst_tokens_expose_required_palette():
    assert MIDNIGHT_ANALYST.app_bg == "#070b12"
    assert MIDNIGHT_ANALYST.surface_1 == "#101722"
    assert MIDNIGHT_ANALYST.surface_2 == "#182231"
    assert MIDNIGHT_ANALYST.text_primary == "#eef3f8"
    assert MIDNIGHT_ANALYST.accent == "#4fb7e5"


def test_global_stylesheet_contains_core_qt_selectors():
    qss = build_global_stylesheet()
    assert "QMainWindow" in qss
    assert "QTabWidget::pane" in qss
    assert "QTableView" in qss
    assert "QProgressBar::chunk" in qss
    assert "QComboBox QAbstractItemView" in qss
    assert "#070b12" in qss


def _app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_status_badge_maps_quality_to_dark_styles():
    _app()
    badge = StatusBadge("OBSERVED", "observed")
    assert badge.text() == "OBSERVED"
    assert "#22c55e" in badge.styleSheet()


def test_compact_code_list_limits_each_group():
    _app()
    widget = CompactCodeList(limit=4)
    widget.set_groups(
        [
            ("強勢", tuple(f"T{i:03d}" for i in range(7))),
            ("弱勢", ("W001",)),
        ]
    )
    text = widget.text()
    assert "強勢：T000, T001, T002, T003（另 3 檔）" in text
    assert "T006" not in text
    assert "弱勢：W001" in text
    assert widget.wordWrap()


def test_apply_app_theme_sets_global_stylesheet():
    app = _app()
    apply_app_theme(app)
    assert "#070b12" in app.styleSheet()
    assert "QTableView" in app.styleSheet()
