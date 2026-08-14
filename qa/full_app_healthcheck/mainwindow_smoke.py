from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EXPECTED_MAINWINDOW_WORKSPACE_LABELS = (
    "決策工作台",
    "市場探索",
    "推薦分析",
    "策略回測",
    "觀察清單",
    "持倉管理",
    "數據更新",
    "Runtime",
)

# Backwards-compatible public name.  The current MainWindow uses a left-side
# workspace navigator rather than a primary QTabWidget, but downstream report
# consumers still read the historical ``expected_tabs`` field.
EXPECTED_MAINWINDOW_TAB_LABELS = EXPECTED_MAINWINDOW_WORKSPACE_LABELS


@dataclass(frozen=True)
class ViewportSize:
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.width}x{self.height}"


def parse_viewport_spec(spec: str) -> ViewportSize:
    try:
        width_text, height_text = spec.lower().split("x", 1)
        width = int(width_text)
        height = int(height_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid viewport spec: {spec!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid viewport spec: {spec!r}")
    return ViewportSize(width=width, height=height)


def build_mainwindow_smoke_evidence(
    *,
    window_title: str,
    tab_labels: list[str],
    missing_tabs: list[str],
    switched_tabs: list[str],
    screenshots: list[dict[str, Any]] | None = None,
    resize_evidence: list[dict[str, Any]] | None = None,
    dialog_cancel_evidence: list[dict[str, Any]] | None = None,
    forbidden_actions_invoked: list[str] | None = None,
    navigation_mode: str | None = None,
) -> dict[str, Any]:
    return {
        "window_title": window_title,
        "tab_labels": tab_labels,
        "expected_tabs": list(EXPECTED_MAINWINDOW_TAB_LABELS),
        "missing_tabs": missing_tabs,
        "switched_tabs": switched_tabs,
        "screenshots": list(screenshots or []),
        "resize_evidence": list(resize_evidence or []),
        "dialog_cancel_evidence": list(dialog_cancel_evidence or []),
        "forbidden_actions_invoked": list(forbidden_actions_invoked or []),
        "navigation_mode": navigation_mode,
    }


def collect_mainwindow_smoke_evidence(
    window: Any,
    *,
    switch_tabs: bool = False,
) -> dict[str, Any]:
    """收集主視窗唯讀 smoke evidence；呼叫端負責提供已建立的 window。"""
    workspace_navigation = _find_workspace_navigation(window)
    if workspace_navigation is not None:
        tab_labels, workspace_keys = _workspace_labels_and_keys(workspace_navigation)
        select_workspace = getattr(window, "_select_main_workspace", None)
        navigation_mode = "left_workspace_navigation"
    else:
        tab_widget = _find_primary_tab_widget(window)
        tab_labels = [str(tab_widget.tabText(index)) for index in range(tab_widget.count())]
        workspace_keys = []
        select_workspace = None
        navigation_mode = "legacy_tabs"

    missing_tabs = [label for label in EXPECTED_MAINWINDOW_TAB_LABELS if label not in tab_labels]

    switched_tabs: list[str] = []
    if switch_tabs:
        if workspace_navigation is not None:
            for key, label in zip(workspace_keys, tab_labels, strict=True):
                if label not in EXPECTED_MAINWINDOW_TAB_LABELS:
                    continue
                if callable(select_workspace):
                    select_workspace(key)
                else:
                    workspace_navigation.set_current_key(key)
                switched_tabs.append(label)
        else:
            for label in EXPECTED_MAINWINDOW_TAB_LABELS:
                if label not in tab_labels:
                    continue
                index = tab_labels.index(label)
                tab_widget.setCurrentIndex(index)
                switched_tabs.append(label)

    return build_mainwindow_smoke_evidence(
        window_title=_window_title(window),
        tab_labels=tab_labels,
        missing_tabs=missing_tabs,
        switched_tabs=switched_tabs,
        forbidden_actions_invoked=[],
        navigation_mode=navigation_mode,
    )


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


def _find_workspace_navigation(window: Any) -> Any | None:
    navigation = getattr(window, "left_navigation", None)
    if navigation is None:
        return None
    if all(
        callable(getattr(navigation, method_name, None))
        for method_name in ("item_keys", "label_for_key", "set_current_key")
    ):
        return navigation
    return None


def _workspace_labels_and_keys(navigation: Any) -> tuple[list[str], list[str]]:
    keys = [str(key) for key in navigation.item_keys()]
    labels: list[str] = []
    for key in keys:
        label = navigation.label_for_key(key)
        if not isinstance(label, str) or not label:
            raise AssertionError(f"左側工作區導覽缺少有效標籤：{key}")
        labels.append(label)
    return labels, keys


def _looks_like_tab_widget(candidate: Any) -> bool:
    return all(
        callable(getattr(candidate, method_name, None))
        for method_name in ("count", "tabText", "setCurrentIndex")
    )
