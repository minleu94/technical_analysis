from pathlib import Path

from ui_qt.theme import MIDNIGHT_ANALYST, build_global_stylesheet

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QTableView, QVBoxLayout, QWidget

from ui_qt.widgets.theme_widgets import CompactCodeList, EmptyStatePanel, StatusBadge
from ui_qt.widgets.table_style import apply_financial_table_style
from ui_qt.widgets.text_sanitizer import remove_symbol_icons, sanitize_button_texts, strip_leading_symbol_icon
from ui_qt.main import apply_app_theme


def test_midnight_analyst_tokens_expose_required_palette():
    assert MIDNIGHT_ANALYST.app_bg == "#070b12"
    assert MIDNIGHT_ANALYST.surface_1 == "#101722"
    assert MIDNIGHT_ANALYST.surface_2 == "#182231"
    assert MIDNIGHT_ANALYST.text_primary == "#eef3f8"
    assert MIDNIGHT_ANALYST.accent == "#4fb7e5"
    assert MIDNIGHT_ANALYST.accent_warm == "#d97706"
    assert MIDNIGHT_ANALYST.data_positive == "#22c55e"
    assert MIDNIGHT_ANALYST.data_negative == "#ef4444"
    assert MIDNIGHT_ANALYST.table_hover == "#20334a"


def test_global_stylesheet_contains_core_qt_selectors():
    qss = build_global_stylesheet()
    assert "QMainWindow" in qss
    assert "QTabWidget::pane" in qss
    assert "QTableView" in qss
    assert "QTableCornerButton::section" in qss
    assert "QToolTip" in qss
    assert "QFrame#midnightEmptyState" in qss
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


def test_empty_state_panel_uses_midnight_style():
    _app()
    panel = EmptyStatePanel("尚無資料", "請先執行一次整理刷新。")
    assert panel.objectName() == "midnightEmptyState"
    assert panel.title_label.text() == "尚無資料"
    assert panel.body_label.text() == "請先執行一次整理刷新。"
    assert panel.body_label.wordWrap()


def test_button_text_sanitizer_removes_missing_symbol_icons_only_from_prefix():
    assert strip_leading_symbol_icon("⚡ 快速更新") == "快速更新"
    assert strip_leading_symbol_icon("🛡️ 安全更新") == "安全更新"
    assert strip_leading_symbol_icon("📊 匯出 Excel") == "匯出 Excel"
    assert strip_leading_symbol_icon("+ 觀察清單") == "+ 觀察清單"
    assert strip_leading_symbol_icon("下鑽 🔍 詳細主力流向") == "下鑽 🔍 詳細主力流向"
    assert remove_symbol_icons("系統角色：📊 分數加權依據 ⚠️") == "系統角色： 分數加權依據 "


def test_sanitize_button_texts_walks_widget_tree():
    _app()
    root = QWidget()
    layout = QVBoxLayout(root)
    fast_button = QPushButton("⚡ 快速更新")
    keep_button = QPushButton("+ 觀察清單")
    layout.addWidget(fast_button)
    layout.addWidget(keep_button)

    sanitize_button_texts(root)

    assert fast_button.text() == "快速更新"
    assert keep_button.text() == "+ 觀察清單"


def test_apply_financial_table_style_sets_dense_research_defaults():
    _app()
    table = QTableView()

    apply_financial_table_style(table)

    assert table.alternatingRowColors()
    assert table.selectionBehavior() == QTableView.SelectRows
    assert table.wordWrap() is False
    assert table.textElideMode() == Qt.ElideRight
    assert table.verticalHeader().defaultSectionSize() == 30
    assert table.horizontalHeader().minimumSectionSize() == 72


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


def test_register_qt_chinese_fonts_registers_candidates_when_no_families(monkeypatch):
    from ui_qt.theme.fonts import register_qt_chinese_fonts

    calls = []

    class FakeFontDatabase:
        @staticmethod
        def families():
            return []

        @staticmethod
        def addApplicationFont(path):
            calls.append(path)
            return len(calls) - 1

        @staticmethod
        def applicationFontFamilies(font_id):
            return (f"Loaded Family {font_id}",)

    monkeypatch.setattr(Path, "exists", lambda self: True)

    loaded = register_qt_chinese_fonts(
        qfont_database=FakeFontDatabase,
        font_paths=(Path("C:/Windows/Fonts/msjh.ttc"), Path("C:/Windows/Fonts/NotoSansTC-VF.ttf")),
    )

    assert loaded == ("Loaded Family 0", "Loaded Family 1")
    assert calls == ["C:\\Windows\\Fonts\\msjh.ttc", "C:\\Windows\\Fonts\\NotoSansTC-VF.ttf"]


def test_register_qt_chinese_fonts_registers_candidates_when_only_latin_families_exist(monkeypatch):
    from ui_qt.theme.fonts import register_qt_chinese_fonts

    calls = []

    class FakeFontDatabase:
        @staticmethod
        def families():
            return ["Arial", "Segoe UI"]

        @staticmethod
        def addApplicationFont(path):
            calls.append(path)
            return len(calls) - 1

        @staticmethod
        def applicationFontFamilies(font_id):
            return (f"Chinese Family {font_id}",)

    monkeypatch.setattr(Path, "exists", lambda self: True)

    loaded = register_qt_chinese_fonts(
        qfont_database=FakeFontDatabase,
        font_paths=(Path("C:/Windows/Fonts/msjh.ttc"),),
    )

    assert loaded == ("Chinese Family 0",)
    assert calls == ["C:\\Windows\\Fonts\\msjh.ttc"]
