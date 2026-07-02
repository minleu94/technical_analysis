from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QCalendarWidget, QDateEdit, QFrame, QVBoxLayout


NULL_FILTER_DATE = QDate(1900, 1, 1)


class ControlledCalendarDateEdit(QDateEdit):
    """使用受控日曆 popup，避免內建 popup 落到 sentinel 年份。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._calendar_popup_enabled = True
        self._calendar_popup: QFrame | None = None
        super().setCalendarPopup(False)

    def setCalendarPopup(self, enable: bool) -> None:  # noqa: N802 - Qt API naming
        self._calendar_popup_enabled = enable
        super().setCalendarPopup(False)

    def calendarPopup(self) -> bool:  # noqa: N802 - Qt API naming
        return self._calendar_popup_enabled

    def mousePressEvent(self, event):  # noqa: N802 - Qt API naming
        if self._calendar_popup_enabled and self.isEnabled():
            self._show_calendar_popup()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt API naming
        if (
            self._calendar_popup_enabled
            and event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Down)
            and self.isEnabled()
        ):
            self._show_calendar_popup()
            event.accept()
            return
        super().keyPressEvent(event)

    def _calendar_page_date(self) -> QDate:
        return self.date()

    def _calendar_selected_date(self) -> QDate:
        return self._calendar_page_date()

    def _show_calendar_popup(self) -> None:
        popup = QFrame(None, Qt.Popup)
        popup.setFrameShape(QFrame.StyledPanel)
        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(4, 4, 4, 4)

        calendar = QCalendarWidget(popup)
        page_date = self._calendar_page_date()
        selected_date = self._calendar_selected_date()
        calendar.setGridVisible(True)
        calendar.setMinimumSize(340, 280)
        calendar.setCurrentPage(page_date.year(), page_date.month())
        calendar.setSelectedDate(selected_date)
        calendar.setStyleSheet(self._calendar_popup_stylesheet())
        calendar.clicked.connect(lambda value, frame=popup: self._apply_calendar_date(value, frame))
        popup_layout.addWidget(calendar)

        popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        self._calendar_popup = popup
        popup.show()

    def _apply_calendar_date(self, selected_date: QDate, popup: QFrame) -> None:
        self.setDate(selected_date)
        popup.close()

    def _calendar_popup_stylesheet(self) -> str:
        return """
            QCalendarWidget QToolButton {
                min-width: 44px;
                min-height: 24px;
                padding: 2px 6px;
            }
            QCalendarWidget QAbstractItemView {
                font-size: 12px;
                min-width: 300px;
                min-height: 210px;
                selection-background-color: #2563eb;
                selection-color: white;
            }
        """


class TodayAnchoredDateEdit(ControlledCalendarDateEdit):
    """日期值可維持原狀，但 popup 開啟時定位到今天。"""

    def _calendar_page_date(self) -> QDate:
        return QDate.currentDate()

    def _calendar_selected_date(self) -> QDate:
        return QDate.currentDate()


class OptionalDateFilterEdit(ControlledCalendarDateEdit):
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

    def _calendar_page_date(self) -> QDate:
        if self.date() == NULL_FILTER_DATE:
            return QDate.currentDate()
        return self.date()

    def _calendar_selected_date(self) -> QDate:
        return self._calendar_page_date()


def date_filter_value(date_edit: QDateEdit) -> str | None:
    selected_date = date_edit.date()
    if selected_date == NULL_FILTER_DATE:
        return None
    return selected_date.toString("yyyy-MM-dd")
