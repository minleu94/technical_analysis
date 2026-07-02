from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit


NULL_FILTER_DATE = QDate(1900, 1, 1)


class OptionalDateFilterEdit(QDateEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd")
        self.setMinimumDate(NULL_FILTER_DATE)
        self.setMaximumDate(QDate(2100, 12, 31))
        self.setSpecialValueText("未設定")
        self.setDate(NULL_FILTER_DATE)
        self.setMinimumWidth(122)

    def textFromDate(self, date: QDate) -> str:
        if date == NULL_FILTER_DATE:
            return "未設定"
        return super().textFromDate(date)

    def clear(self) -> None:
        self.setDate(NULL_FILTER_DATE)


def date_filter_value(date_edit: QDateEdit) -> str | None:
    selected_date = date_edit.date()
    if selected_date == NULL_FILTER_DATE:
        return None
    return selected_date.toString("yyyy-MM-dd")
