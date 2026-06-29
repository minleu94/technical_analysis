from __future__ import annotations

from typing import Any


EXPECTED_MAINWINDOW_TAB_LABELS = (
    "數據更新",
    "市場觀察",
    "每日決策",
    "策略回測",
    "推薦分析",
    "觀察清單",
    "持倉管理",
    "Runtime Observatory",
)


def collect_mainwindow_smoke_evidence(
    window: Any,
    *,
    switch_tabs: bool = False,
) -> dict[str, Any]:
    """收集主視窗唯讀 smoke evidence；呼叫端負責提供已建立的 window。"""
    tab_widget = _find_primary_tab_widget(window)
    tab_labels = [str(tab_widget.tabText(index)) for index in range(tab_widget.count())]
    missing_tabs = [label for label in EXPECTED_MAINWINDOW_TAB_LABELS if label not in tab_labels]

    switched_tabs: list[str] = []
    if switch_tabs:
        for label in EXPECTED_MAINWINDOW_TAB_LABELS:
            if label not in tab_labels:
                continue
            index = tab_labels.index(label)
            tab_widget.setCurrentIndex(index)
            switched_tabs.append(label)

    return {
        "window_title": _window_title(window),
        "tab_labels": tab_labels,
        "expected_tabs": list(EXPECTED_MAINWINDOW_TAB_LABELS),
        "missing_tabs": missing_tabs,
        "switched_tabs": switched_tabs,
        "forbidden_actions_invoked": [],
    }


def _window_title(window: Any) -> str:
    title = getattr(window, "windowTitle", None)
    if callable(title):
        return str(title())
    return ""


def _find_primary_tab_widget(window: Any) -> Any:
    direct_tab_widget = getattr(window, "tab_widget", None)
    if direct_tab_widget is not None:
        return direct_tab_widget

    find_children = getattr(window, "findChildren", None)
    if callable(find_children):
        for candidate in find_children(object):
            if _looks_like_tab_widget(candidate):
                return candidate

    raise AssertionError("找不到主視窗分頁容器")


def _looks_like_tab_widget(candidate: Any) -> bool:
    return all(
        callable(getattr(candidate, method_name, None))
        for method_name in ("count", "tabText", "setCurrentIndex")
    )
