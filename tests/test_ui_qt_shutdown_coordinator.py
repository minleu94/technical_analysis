"""Owner 關閉桌面程式時的合作式背景工作安全契約。"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ui_qt.main as main_module
from ui_qt.views.update_view import UpdateView


class _CloseEvent:
    def __init__(self) -> None:
        self.accepted = False
        self.ignored = False

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class _StatusBar:
    def __init__(self) -> None:
        self.messages: list[tuple[str, int]] = []

    def showMessage(self, message: str, timeout: int) -> None:
        self.messages.append((message, timeout))


class _Window:
    def __init__(self, update_view: object | None = None) -> None:
        self.update_view = update_view
        self._status_bar = _StatusBar()

    def statusBar(self) -> _StatusBar:
        return self._status_bar


def test_main_close_pauses_until_managed_worker_is_safely_finished(
    monkeypatch,
) -> None:
    worker = object()
    monkeypatch.setattr(
        main_module,
        "request_cooperative_task_worker_shutdown",
        lambda: (worker,),
    )
    window = _Window()
    event = _CloseEvent()

    main_module.MainWindow.closeEvent(window, event)

    assert event.ignored is True
    assert event.accepted is False
    assert "1 個合作式取消中的背景工作" in window._status_bar.messages[0][0]


def test_main_close_pauses_for_detached_update_process(monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "request_cooperative_task_worker_shutdown",
        lambda: (),
    )
    update_view = SimpleNamespace(
        has_running_background_process=lambda: True,
    )
    window = _Window(update_view=update_view)
    event = _CloseEvent()

    main_module.MainWindow.closeEvent(window, event)

    assert event.ignored is True
    assert event.accepted is False
    assert "TPEX 背景更新程序" in window._status_bar.messages[0][0]


def test_main_close_accepts_when_no_managed_work_remains(monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "request_cooperative_task_worker_shutdown",
        lambda: (),
    )
    window = _Window()
    event = _CloseEvent()

    main_module.MainWindow.closeEvent(window, event)

    assert event.accepted is True
    assert event.ignored is False
    assert window._status_bar.messages == []


def test_update_view_close_never_uses_terminate_fallback() -> None:
    calls: list[str] = []
    view = SimpleNamespace(
        request_cooperative_shutdown=lambda: False,
        _log=lambda message: calls.append(message),
    )
    event = _CloseEvent()

    UpdateView.closeEvent(view, event)

    assert event.ignored is True
    assert event.accepted is False
    assert calls == ["已送出合作式取消；背景工作結束後才可關閉資料更新頁。"]
