from __future__ import annotations

from PySide6.QtWidgets import QLabel

from ui_qt.theme import MIDNIGHT_ANALYST


class EvidenceBoundaryBanner(QLabel):
    def __init__(self, extra_text: str = "", parent=None) -> None:
        text = (
            "這是 research evidence，不是買賣建議。"
            "Close-to-close forward return 不代表可執行實盤績效。"
            "樣本、benchmark、industry、data quality 與人工覆盤狀態都必須人工判讀。"
        )
        if extra_text:
            text = f"{text}{extra_text}"
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.warning}; background: {MIDNIGHT_ANALYST.surface_2}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; border-radius: 6px; padding: 7px;"
        )
