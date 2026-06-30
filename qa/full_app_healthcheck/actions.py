from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QPushButton, QTabWidget, QWidget

from qa.full_app_healthcheck.manifest import HealthcheckStep
from qa.full_app_healthcheck.mainwindow_smoke import (
    collect_mainwindow_smoke_evidence as collect_mainwindow_smoke_window_evidence,
)
from qa.full_app_healthcheck.mainwindow_smoke_runner import (
    MainWindowSmokeOptions,
    run_mainwindow_smoke,
)


def switch_tab_by_text(tabs: QTabWidget, tab_text: str) -> None:
    for index in range(tabs.count()):
        if tabs.tabText(index) == tab_text:
            tabs.setCurrentIndex(index)
            return
    raise AssertionError(f"找不到 tab: {tab_text}")


def find_child_button_by_text(parent: QWidget, text: str) -> QPushButton:
    for button in parent.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"找不到按鈕: {text}")


def click_button_by_text(parent: QWidget, text: str) -> None:
    find_child_button_by_text(parent, text).click()


def grab_widget_screenshot(widget: QWidget, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    if pixmap.isNull():
        raise AssertionError("截圖失敗：pixmap is null")
    pixmap.save(str(path))
    return path


# --- Batch D-1 Read-only UI primitives ---

def find_child_by_object_name(root: QWidget, object_name: str) -> QWidget:
    child = root.findChild(QWidget, object_name)
    if child is None:
        raise AssertionError(f"找不到 objectName 為 '{object_name}' 的元件")
    return child


def assert_widget_visible(context: dict[str, Any], step: HealthcheckStep) -> dict[str, Any]:
    widget = context.get("target_widget")
    if widget is None:
        window = context.get("window")
        if window is not None:
            widget = window.findChild(QWidget, step.id)
    if widget is None:
        raise AssertionError(f"找不到要驗證的元件 (step.id: {step.id})")
    if not widget.isVisible():
        raise AssertionError(f"元件 '{step.id}' 目前為不可見狀態")
    return {"visible": True, "widget_class": widget.__class__.__name__}


def assert_tab_exists(context: dict[str, Any], step: HealthcheckStep) -> dict[str, Any]:
    window = context.get("window")
    if window is None:
        raise AssertionError("缺少 window context")
    expected_title = step.expected or step.title
    tabs_list = window.findChildren(QTabWidget)
    if not tabs_list:
        raise AssertionError("找不到任何 QTabWidget 元件")

    found = False
    for tabs in tabs_list:
        for idx in range(tabs.count()):
            if tabs.tabText(idx) == expected_title:
                found = True
                break
        if found:
            break

    if not found:
        raise AssertionError(f"找不到標題為 '{expected_title}' 的分頁 (Tab)")
    return {"found": True, "tab_title": expected_title}


def assert_text_contains(context: dict[str, Any], step: HealthcheckStep) -> dict[str, Any]:
    root = context.get("target_widget") or context.get("window")
    if root is None:
        raise AssertionError("缺少 window 或 target_widget context")

    expected_text = step.expected or step.title
    texts = []
    for child in root.findChildren(QWidget):
        text_attr = getattr(child, "text", None)
        if text_attr and callable(text_attr):
            try:
                val = str(text_attr())
                if val:
                    texts.append(val)
            except Exception:
                continue

    if not any(expected_text in t for t in texts):
        raise AssertionError(f"找不到包含文字 '{expected_text}' 的元件；現有文字: {texts[:10]}")
    return {"contains": True, "matched_text": expected_text}


def assert_viewport_declared(context: dict[str, Any], step: HealthcheckStep) -> dict[str, Any]:
    viewport = context.get("viewport")
    if not viewport:
        raise AssertionError("未宣告 viewport")
    try:
        width_text, height_text = viewport.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except Exception:
        raise AssertionError(f"宣告的 viewport 格式不合法：'{viewport}'")
    return {"viewport": viewport, "width": width, "height": height}


def collect_mainwindow_smoke_evidence(
    context: dict[str, Any],
    step: HealthcheckStep,
) -> dict[str, Any]:
    window = context.get("window")
    if window is None:
        raise AssertionError("缺少 MainWindow context；此 action 只能在明確 opt-in smoke runner 使用")
    switch_tabs = bool(context.get("switch_mainwindow_tabs", False))
    return collect_mainwindow_smoke_window_evidence(window, switch_tabs=switch_tabs)


def run_mainwindow_ui_smoke(
    context: dict[str, Any],
    step: HealthcheckStep,
) -> dict[str, Any]:
    output_dir = Path(context["mainwindow_smoke_output_dir"])
    options = MainWindowSmokeOptions(
        output_dir=output_dir,
        switch_tabs=bool(context.get("ui_smoke_switch_tabs", False)),
        capture_screenshots=bool(context.get("ui_smoke_screenshot", False)),
        resize_viewports=tuple(context.get("ui_smoke_resize") or ()),
        dialog_cancel=bool(context.get("ui_smoke_dialog_cancel", False)),
    )
    return run_mainwindow_smoke(options)
