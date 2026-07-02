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
    QToolTip {{
        background: {tokens.surface_1};
        color: {tokens.text_primary};
        border: 1px solid {tokens.border};
        padding: 6px 8px;
        border-radius: {tokens.radius_badge}px;
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
        padding: 7px 12px;
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
    QPushButton[variant="primary"] {{
        background: {tokens.accent};
        color: {tokens.app_bg};
        border-color: {tokens.accent};
        font-weight: 700;
    }}
    QPushButton[variant="primary"]:hover {{
        background: {tokens.accent_hover};
        border-color: {tokens.accent_hover};
    }}
    QPushButton[variant="danger"] {{
        background: {tokens.danger};
        color: {tokens.text_primary};
        border-color: {tokens.danger};
        font-weight: 700;
    }}
    QPushButton[variant="ghost"] {{
        background: transparent;
        color: {tokens.text_secondary};
        border-color: {tokens.border_subtle};
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
        gridline-color: {tokens.border_subtle};
        selection-background-color: {tokens.table_selected};
        selection-color: {tokens.text_primary};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_panel}px;
        font-family: {tokens.font_family};
    }}
    QTableView::item {{
        padding: 5px 8px;
        border: 0;
    }}
    QTableView::item:hover {{
        background: {tokens.table_hover};
    }}
    QTableCornerButton::section {{
        background: {tokens.surface_2};
        border: 0;
        border-right: 1px solid {tokens.border};
        border-bottom: 1px solid {tokens.border};
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
    QListWidget {{
        background: {tokens.surface_1};
        color: {tokens.text_primary};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_panel}px;
        alternate-background-color: {tokens.surface_2};
    }}
    QListWidget::item {{
        padding: 6px 8px;
    }}
    QListWidget::item:selected {{
        background: {tokens.table_selected};
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
    QSplitter::handle {{
        background: {tokens.border_subtle};
    }}
    QSplitter::handle:hover {{
        background: {tokens.border};
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
    QScrollBar:horizontal {{
        background: {tokens.app_bg};
        height: 10px;
    }}
    QScrollBar::handle:horizontal {{
        background: {tokens.surface_3};
        border-radius: 5px;
        min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {tokens.accent};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        width: 0;
        height: 0;
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
    QFrame#midnightEmptyState {{
        background: {tokens.surface_1};
        border: 1px dashed {tokens.border};
        border-radius: {tokens.radius_panel}px;
    }}
    """
