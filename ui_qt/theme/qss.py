from .tokens import MIDNIGHT_ANALYST, ThemeTokens


def build_global_stylesheet(tokens: ThemeTokens = MIDNIGHT_ANALYST) -> str:
    return f"""
    QWidget {{
        background: {tokens.app_bg};
        color: {tokens.text_primary};
        font-family: {tokens.font_family};
        font-size: 10pt;
    }}
    QMainWindow, QDialog {{
        background: {tokens.app_bg};
    }}
    QLabel {{
        background: transparent;
    }}
    QTabWidget::pane {{
        border: 1px solid {tokens.border};
        background: {tokens.surface_1};
        border-radius: {tokens.radius_panel}px;
    }}
    QTabBar::tab {{
        background: {tokens.surface_2};
        color: {tokens.text_secondary};
        padding: 7px 12px;
        border: 1px solid {tokens.border};
        border-bottom: none;
        min-height: 24px;
    }}
    QTabBar::tab:hover {{
        background: {tokens.surface_3};
        color: {tokens.text_primary};
    }}
    QTabBar::tab:selected {{
        background: {tokens.surface_1};
        color: {tokens.text_primary};
        border-top: 2px solid {tokens.accent};
    }}
    QPushButton {{
        background: {tokens.surface_3};
        color: {tokens.text_primary};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_panel}px;
        padding: 6px 10px;
        min-height: 28px;
    }}
    QPushButton:hover {{
        border-color: {tokens.accent};
        background: {tokens.surface_2};
    }}
    QPushButton:pressed {{
        background: {tokens.app_bg};
        border-color: {tokens.accent_hover};
    }}
    QPushButton:focus {{
        border-color: {tokens.accent_hover};
    }}
    QPushButton:disabled {{
        color: {tokens.text_muted};
        background: {tokens.surface_1};
    }}
    QGroupBox {{
        background: {tokens.surface_1};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_panel}px;
        margin-top: 10px;
        padding-top: 12px;
        font-weight: 700;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {tokens.text_primary};
    }}
    QTableView {{
        background: {tokens.surface_1};
        alternate-background-color: {tokens.surface_2};
        color: {tokens.text_primary};
        gridline-color: {tokens.border};
        selection-background-color: {tokens.surface_3};
        selection-color: {tokens.text_primary};
        border: 1px solid {tokens.border};
    }}
    QTableView::item {{
        padding: 3px 6px;
    }}
    QTableView::item:hover {{
        background: {tokens.surface_3};
    }}
    QHeaderView::section {{
        background: {tokens.surface_2};
        color: {tokens.text_secondary};
        padding: 6px 7px;
        border: 0;
        border-right: 1px solid {tokens.border};
        border-bottom: 1px solid {tokens.border};
        font-weight: 700;
    }}
    QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
        background: {tokens.surface_2};
        color: {tokens.text_primary};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_panel}px;
        padding: 5px 7px;
        selection-background-color: {tokens.surface_3};
        selection-color: {tokens.text_primary};
    }}
    QTextEdit:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
        border-color: {tokens.accent};
    }}
    QComboBox::drop-down, QDateEdit::drop-down {{
        border: 0;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {tokens.surface_1};
        color: {tokens.text_primary};
        border: 1px solid {tokens.border};
        selection-background-color: {tokens.surface_3};
    }}
    QScrollArea {{
        border: 0;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: {tokens.app_bg};
        width: 10px;
    }}
    QScrollBar::handle:vertical {{
        background: {tokens.surface_3};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {tokens.accent};
    }}
    QProgressBar {{
        background: {tokens.surface_2};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_panel}px;
        color: {tokens.text_primary};
        text-align: center;
    }}
    QProgressBar::chunk {{
        background: {tokens.accent};
        border-radius: {tokens.radius_panel}px;
    }}
    """
